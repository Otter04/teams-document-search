"""Read-only 110-document routing and capacity plan; no model requests/index writes."""
import collections
import csv
import hashlib
import importlib.util
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT/'deploy/orin/evaluation'))
import adapter as a
from evaluate_policy_v2 import row as enrichment_assessment


def read(p): return json.loads(Path(p).read_text())
def lines(p): return [json.loads(x) for x in Path(p).read_text().splitlines()]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name, value):
    (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def freeze():
    path = HERE/'snapshot.json'
    if path.exists():
        s = read(path)
        # Dynamic evaluation snapshots are copied once; raw envelopes are immutable.
        assert all(sha(p)==h for p,h in s['fixed_inputs'].items())
        assert all(sha(p)==h for p,h in s['orin_envelopes'].items())
        return s
    fixed = [ROOT/p for p in [
        'outputs/parsing-run-003/parsed.jsonl', 'outputs/parsing-run-003/provenance.json',
        'outputs/date-search-run-002/enriched.jsonl', 'outputs/date-search-run-002/source-metadata.jsonl',
        'outputs/metadata-policy-v1/field-results.jsonl',
        'outputs/vision-comparison-run-001/manifest.json',
        'outputs/vision-validation-run-003/evaluation.json',
        'outputs/vision-source-review-001/evaluation.json',
        'outputs/enrichment-eval-prep-001/private/gold.json']]
    for name in ['vision-evaluation.json', 'progress.json', 'last-sync.json']:
        save('snapshot-'+name, read(a.OUT/name))
    envs = list((a.OUT/'results').glob('*/*/envelope.json'))
    # Capture only units included in the scoring snapshot, to prevent count drift.
    scored = {r['id'] for r in read(HERE/'snapshot-vision-evaluation.json')['records']}
    envs = [p for p in envs if p.parent.parent.name=='enrichment' or p.parent.name in scored]
    s = {'as_of_kst': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
         'fixed_inputs': {str(p):sha(p) for p in fixed},
         'orin_envelopes': {str(p):sha(p) for p in envs},
         'scope': 'original D-001..D-110 only',
         'user_policy': 'search metadata first; LLM summaries only when needed',
         'new_model_calls': 0}
    save('snapshot.json', s)
    return s


def clean_reference(r, decision):
    reasons = []
    if decision != 'candidate': reasons.append('validation_warning_or_reject')
    if not r['json_complete']: reasons.append('incomplete_json')
    if r['coverage']['compatible'] != r['coverage']['total']: reasons.append('source_items_missing_or_wrong')
    tables = r['tables']
    if tables['unmatched_output_cells'] or tables['unmatched_output_tables']: reasons.append('unmatched_table_output')
    for t in tables['tables']:
        if not t['dimensions_correct'] or not t['header_rows_correct']: reasons.append('table_layout_mismatch')
        for kind in ['content', 'structure']:
            x=t[kind]
            if x['correct']!=x['expected'] or x['correct']!=x['observed']: reasons.append('table_'+kind+'_mismatch')
    graph = r.get('graph', r.get('graph_compatible'))
    # A reference with no annotated graph is unscored, not a claim that all
    # visible source boxes are forbidden. Match the existing evaluator's scope.
    if graph['nodes']['expected']:
        for kind in ['nodes','edges']:
            x=graph[kind]
            if x['correct']!=x['expected'] or x['correct']!=x['observed']: reasons.append('graph_'+kind+'_mismatch')
    if r.get('duplicates', r.get('duplicate_source_phrases')): reasons.append('source_duplicates')
    return sorted(set(reasons))


def native_benchmark(parsed):
    """In-memory replay only: no production index, no remote host, no labels."""
    sys.path.insert(0, str(ROOT/'outputs/rag-date-search-v2'))
    import date_search as d
    E=d.E
    reference=read(ROOT/'outputs/rag-enrichment-v1/reference-data.json')
    rules=read(ROOT/'outputs/rag-rule-search-v1/rules.json')
    source_meta={r['doc_id']:r for r in lines(ROOT/'outputs/date-search-run-002/source-metadata.jsonl')}
    E.timestamp('2000-01-01 00:00:00')
    blocked=[]
    def audit(event,args):
        if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
            blocked.append(event); raise RuntimeError('network/process prohibited during offline plan')
    sys.addaudithook(audit)
    start=time.perf_counter();enriched={};dates={};chunks=[]
    for did, record in parsed.items():
        enriched[did]=E.extract(record, reference)
        assert not E.check_output(enriched[did],record)
        dates[did]=d.date_metadata(record,enriched[did],source_meta[did])
        c=d.old.old.base.make_chunks(record,enriched[did])
        assert not d.old.old.base.validate_chunks(c,record,enriched[did])
        chunks.append(c)
    midpoint=time.perf_counter()
    index=d.old.old.previous.build_index(d.old.old.base.build_index(chunks,reference['clients']),rules)
    d.old.prepare(index,parsed,enriched);d.attach_dates(index,dates)
    end=time.perf_counter()
    # Preserve the currently saved artifacts; only report equality and timing.
    saved={r['doc_id']:r for r in lines(ROOT/'outputs/date-search-run-002/enriched.jsonl')}
    assert enriched==saved
    return {'host':'Mac task environment, not Orin', 'documents':len(parsed),
            'rules_validation_chunking_seconds':midpoint-start,'index_build_seconds':end-midpoint,
            'total_seconds':end-start,'native_chunks':sum(len(c['chunks']) for c in chunks),
            'rules_results_equal_saved':True,'model_calls':0,'blocked_network_attempts':blocked,
            'index_written':False,'excludes':['source collection','new image rendering','new vision blocks',
                                           'vector embedding/index','manual review','production integration engineering']}


def main():
    snapshot=freeze()
    parsed={r['doc_id']:r for r in lines(ROOT/'outputs/parsing-run-003/parsed.jsonl')}
    enriched={r['doc_id']:r for r in lines(ROOT/'outputs/date-search-run-002/enriched.jsonl')}
    manifest=read(a.VISION/'manifest.json')
    source_docs={r['doc_id']:r for r in manifest['documents'] if r['corpus']=='original'}
    assert set(parsed)==set(enriched)==set(source_docs) and len(parsed)==110
    # Verify the source bytes, so reuse is not based on just matching filenames.
    verified=[]
    for did, record in parsed.items():
        source=source_docs[did]
        assert sha(source['path'])==record['source']['sha256']==source['sha256']
        assert enriched[did]['source']['sha256']==record['source']['sha256']
        verified.append(did)
    cloud_quality={r['key']:r for r in read(ROOT/'outputs/vision-validation-run-003/evaluation.json')[0]['records']}
    cloud_content={r['key']:r for r in read(ROOT/'outputs/vision-source-review-001/evaluation.json')[0]['records']}
    orin_content={r['id']:r for r in read(HERE/'snapshot-vision-evaluation.json')['records']}
    jobs={j['id']:j for j in read(a.OUT/'manifest.json')['jobs']}
    units=[];timing_envs=[]
    for item in manifest['items']:
        if item['corpus']!='original':continue
        key=a.key(item);assert sha(item['image_path'])==item['image_sha256']
        assert item['source_sha256']==parsed[item['doc_id']]['source']['sha256']
        oldpath=a.VISION/a.MODEL/'units'/key/'response.json'
        old=read(oldpath)
        assert sha(oldpath)==cloud_quality[key]['response_sha256']==cloud_content[key]['response_sha256']
        old_reasons=clean_reference(cloud_content[key],cloud_quality[key]['decision'])
        local=orin_content.get(key);local_reasons=['not_received_in_snapshot'];local_seconds=None
        localpath=a.OUT/'results/vision'/key/'envelope.json'
        if local:
            env=read(localpath);assert str(localpath) in snapshot['orin_envelopes']
            assert env['request_sha256']==jobs[key]['request_sha256']
            assert env['messages_sha256']==jobs[key]['messages_sha256']
            local_reasons=clean_reference(local,local['decision'])
            local_seconds=env['elapsed_ms']/1000;timing_envs.append(env)
        units.append({'id':key,'doc_id':item['doc_id'],'image_sha256':item['image_sha256'],
            'old_source_response_path':str(oldpath),'old_source_response_sha256':sha(oldpath),
            'cloud_reuse_candidate':not old_reasons,'cloud_hold_reasons':old_reasons,
            'orin_received':local is not None,'orin_reuse_candidate':not local_reasons,
            'orin_hold_reasons':local_reasons,'orin_seconds':local_seconds,
            'baseline_output_tokens':old['usage']['completion_tokens'],
            'baseline_finish_reason':old['choices'][0]['finish_reason'],
            'reusable_with_provider_provenance':not old_reasons or not local_reasons,
            'unscored_structure_semantics_may_remain':not bool(cloud_content[key]['graph_compatible']['nodes']['expected']),
            'reuse_is_independent_human_approval':False})
    assert len(units)==121
    gold={g['doc_id']:g for g in read(a.PREP/'private/gold.json')}
    enrichment_reuse={};enrichment_envs=[]
    for p in snapshot['orin_envelopes']:
        env=read(p)
        if env['kind']!='enrichment':continue
        enrichment_envs.append(env)
        if not env['doc_id'].startswith('D-'):continue
        did=env['doc_id'];packet=read(a.PREP/'public/inputs'/f'{did}.json')
        local=enrichment_assessment(env,gold[did],packet)
        old=enrichment_assessment(read(a.BASE_ENRICH/'responses'/a.MODEL/f'{did}.json'),gold[did],packet)
        enrichment_reuse[did]={'orin_after_contract_valid':local['after_contract_valid'],
            'orin_metadata_audited_candidate':local['metadata_audited_candidate'],
            'cloud_after_contract_valid':old['after_contract_valid'],
            'cloud_metadata_audited_candidate':old['metadata_audited_candidate'],
            'orin_errors':local['after_errors'],'cloud_errors':old['after_errors'],
            'summary_review_complete':False,
            'input_is_current_native_record':packet['document']==parsed[did]}
    legacy=lines(ROOT/'outputs/metadata-policy-v1/field-results.jsonl')
    gaps=collections.defaultdict(list)
    for r in legacy:
        if r['gold_present'] and r['verdict']!='match':gaps[r['doc_id']].append(r['field'])
    documents=[]
    for did, en in enriched.items():
        visual=[u for u in units if u['doc_id']==did]
        kind=en['fields']['문서종류']['value']
        missing_type=(kind=='계약서' and en['native_text_present'] and en['fields']['계약유형']['value'] is None)
        if missing_type:
            assert not any('계약유형' in b.get('text','') for b in parsed[did]['blocks'])
        if not en['native_text_present']:
            group='D';reason='스캔 본문 미확보. 비전 결과 검수·연결 후 규칙 재실행; 남는 의미 항목만 LLM 검토.'
        elif visual:
            group='C';reason='네이티브 메타데이터 재사용 가능. 표·그림·구성 관계의 비전 대기는 별도이며 보강 LLM 호출 확정 아님.'
        elif missing_type:
            group='B';reason='규칙값 재사용. 명시적 계약유형 부재는 보류 유지; 제목·업무 설명으로 임의 추정하지 않음.'
        else:
            group='A';reason='현재 검색 필드에 추가 LLM 처리가 필요한 미추출 근거가 확인되지 않음. 규칙 보강 재사용.'
        review_fields=[k for k,v in en['fields'].items() if v['status']=='needs_review']
        documents.append({'doc_id':did,'file_name':en['source']['file_name'],'format':en['source']['format'],
            'relative_path':en['source']['relative_path'],'source_sha256':en['source']['sha256'],
            'group':group,'document_type':kind,'reason':reason,'native_text_present':en['native_text_present'],
            'rules_metadata_reusable':True,'rules_extracted_fields':[k for k,v in en['fields'].items() if v['status']=='extracted'],
            'unresolved_fields':{k:v['status'] for k,v in en['fields'].items() if v['status'] in ['not_found_native','needs_review','pending_vision']},
            'review_fields':review_fields,'contract_type_explicit_label_absent':missing_type,
            'legacy_gold_unresolved_fields':gaps[did],
            'text_llm_required_now':False,'text_llm_route':'after_vision_reassess' if visual else 'no_call_under_metadata_first_policy',
            'summary_route':'not_required_for_current_search; only add with identified need',
            'vision_units':len(visual),'orin_vision_candidates':sum(u['orin_reuse_candidate'] for u in visual),
            'cloud_vision_candidates':sum(u['cloud_reuse_candidate'] for u in visual),
            'either_vision_candidates':sum(u['reusable_with_provider_provenance'] for u in visual),
            'enrichment_test_reuse':enrichment_reuse.get(did)})
    counts=dict(collections.Counter(d['group'] for d in documents));assert counts=={'C':27,'A':56,'B':24,'D':3},counts
    # Current Orin end-to-end output rate includes input processing; no new inference.
    seconds=sum(e['elapsed_ms']/1000 for e in timing_envs)
    tokens=sum(e['response']['usage']['completion_tokens'] for e in timing_envs)
    rate=tokens/seconds
    def estimate(label, remaining):
        proxy=sum(u['baseline_output_tokens'] for u in remaining)
        hours=proxy/rate/3600
        return {'scenario':label,'units_to_resolve':len(remaining),'output_token_proxy':proxy,
                'central_model_hours':hours,'planning_low_hours':hours*0.7,'planning_high_hours':hours*1.5,
                'assumptions':'One pass on every unresolved unit; historical Qwen3.6 FP8 output token counts as a proxy, current Orin observed tokens/second. 0.7x..1.5x is an explicit planning allowance, not measured confidence limits. Some failed historical outputs hit the output cap. No success guarantee.',
                'excludes':'manual review, additional retries, engineering, vector embeddings, other 30-document evaluation jobs'}
    scenarios=[estimate('no_saved_vision_reuse',units),
               estimate('reuse_same_Orin_candidates',[u for u in units if not u['orin_reuse_candidate']]),
               estimate('reuse_Orin_or_reviewed_OpenRouter_candidates_with_provenance',[u for u in units if not u['reusable_with_provider_provenance']])]
    result={'as_of_kst':snapshot['as_of_kst'],'documents':110,'groups':counts,
            'native_metadata_documents':107,'native_complete_coverage_documents':80,
            'visual_documents':30,'visual_units':121,'scanned_documents':['D-044','D-069','D-102'],
            'metadata_llm_calls_confirmed_required_now':0,'summary_calls_planned':0,
            'unsupported_contract_type_documents':sum(d['contract_type_explicit_label_absent'] for d in documents),
            'ambiguous_date_documents':sum(bool(d['review_fields']) for d in documents),
            'old_gold_gaps':42,'old_gold_gaps_native_contract_type':24,'old_gold_gaps_visual':18,
            'original_source_hashes_verified':len(verified),'render_image_hashes_verified':len(units),
            'orin_vision_received':sum(u['orin_received'] for u in units),
            'orin_reuse_candidates':sum(u['orin_reuse_candidate'] for u in units),
            'cloud_reuse_candidates':sum(u['cloud_reuse_candidate'] for u in units),
            'either_reuse_candidates':sum(u['reusable_with_provider_provenance'] for u in units),
            'enrichment_original_saved':len(enrichment_reuse),
            'enrichment_original_orin_reusable_whole':sum(r['orin_metadata_audited_candidate'] for r in enrichment_reuse.values()),
            'enrichment_original_cloud_reusable_whole':sum(r['cloud_metadata_audited_candidate'] for r in enrichment_reuse.values()),
            'observed_orin_vision_timing':{'images':len(timing_envs),'seconds':seconds,'output_tokens':tokens,'output_rate_including_input':rate},
            'enrichment_unit_seconds_median':statistics.median(e['elapsed_ms']/1000 for e in enrichment_envs),
            'scenarios':scenarios,'new_model_calls':0,'production_index_modified':False,
            'full_index_completion_time_known':False,'vector_index_time':'unmeasured; implementation not integrated'}
    benchmark=native_benchmark(parsed);save('native-benchmark.json',benchmark)
    result['native_benchmark']=benchmark
    save('documents.json',documents);save('vision-units.json',units);save('summary.json',result)
    headers=['doc_id','file_name','group','document_type','reason','native_text_present','rules_metadata_reusable',
             'review_fields','contract_type_explicit_label_absent','legacy_gold_unresolved_fields','text_llm_required_now',
             'text_llm_route','vision_units','orin_vision_candidates','cloud_vision_candidates','either_vision_candidates']
    with (HERE/'documents.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=headers);writer.writeheader()
        for d in documents:writer.writerow({k:'; '.join(d[k]) if isinstance(d[k],list) else d[k] for k in headers})
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
