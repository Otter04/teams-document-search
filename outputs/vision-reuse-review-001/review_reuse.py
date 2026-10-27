"""Offline derivative preparation. Never edit raw responses, gold, or validators.

No request execution and no network. Distinguishes model output, deterministic
normalization, assistant image correction, and reconstruction of missing prose.
"""
import collections
import copy
import csv
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'deploy/orin/evaluation'))
import adapter as a
from manual_review import apply as manual_apply, reconstruct_d102_page2

def offline(event,args):
    if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
        raise RuntimeError('Offline review prohibits network/process execution')
sys.addaudithook(offline)

def save(name,obj): a.write(HERE/name,obj)
def norm(s): return a.review.norm(s,True)

def repair_geometry(w,item,log):
    # Only connector rectangles: sort existing endpoints and give thin lines a
    # one-pixel margin. Text/table/figure regions never receive blind padding.
    for fi,f in enumerate(w['figures']):
        for ri,r in enumerate(f['relations']):
            b=r['bbox'];x0,y0,x1,y1=b
            if x0<x1 and y0<y1: continue
            x0,x1=sorted((x0,x1));y0,y1=sorted((y0,y1))
            if x0==x1: x0,x1=max(0,x0-1/item['width']),min(1,x1+1/item['width'])
            if y0==y1: y0,y1=max(0,y0-1/item['height']),min(1,y1+1/item['height'])
            r['bbox']=[x0,y0,x1,y1]
            log.append(dict(path=f'figures[{fi}].relations[{ri}].bbox',before=b,after=r['bbox'],
                            method='deterministic_geometry',reason='Existing endpoints sorted; zero-width/height line enclosed with one image-pixel margin; endpoints/direction/labels unchanged'))

def deduplicate(w,ref,log):
    literals=a.review.text_items(w)
    # Never delete a cell/node/edge or a merely similar/contained phrase.
    keep=[]
    for i,t in enumerate(w['texts']):
        matches=[x for x in literals if x['kind'] in ('node','cell') and
                 norm(x['text'])==norm(t['text']) and
                 a.quality.v2.same_region(x['bbox'],t['bbox'])]
        if matches:
            other=matches[0]
            log.append(dict(path=f'texts[{i}]',before=copy.deepcopy(t),after=None,
                            retained_path=other['path'],retained_literal=other['text'],
                            method='deterministic_exact_duplicate',
                            reason='동일 위치의 동일 문구가 구조 필드에 그대로 남음; 표 셀·노드·관계 삭제 없음'))
        else: keep.append(t)
    w['texts']=keep
    # A claim that is exactly a node label (allow colon used as a line-break)
    # contributes no visual interpretation. Preserve actual explanatory claims.
    for fi,f in enumerate(w['figures']):
        kept=[]
        for ci,c in enumerate(f['claims']):
            ns=[n for n in f['nodes'] if norm(c['text']).replace(':','')==norm(n['label']).replace(':','') and a.quality.v2.same_region(c['bbox'],n['bbox'])]
            if ns:
                log.append(dict(path=f'figures[{fi}].claims[{ci}]',before=copy.deepcopy(c),after=None,
                                retained_node=ns[0]['id'],retained_literal=ns[0]['label'],
                                method='deterministic_exact_label_claim',reason='원문 라벨만 되풀이한 설명; 해당 노드에 원문 유지'))
            else: kept.append(c)
        f['claims']=kept
    return w

def metrics(w,item,ref):
    errs=a.quality.base.check_wire(w)
    issues=a.quality.check_quality(w,item.get('native_context',[])) if not errs else []
    cov=a.review.coverage(ref,a.review.text_items(w));tab=a.review.table_scores(ref,w)
    graph=a.review.graph_scores(ref,w,True);dups=a.review.duplicates(ref,w)
    reasons=list(errs)+[x['code'] for x in issues]
    if cov['compatible']!=cov['total']:reasons.append('missing_or_wrong_source_literal')
    if tab['unmatched_output_tables'] or tab['unmatched_output_cells']:reasons.append('extra_table_output')
    for t in tab['tables']:
        if not t['dimensions_correct'] or not t['header_rows_correct']:reasons.append('table_layout')
        for k in ('content','structure'):
            p=t[k]
            if p['correct']!=p['expected'] or p['correct']!=p['observed']:reasons.append('table_'+k)
    if ref['nodes']:
        for k,p in graph.items():
            if p['correct']!=p['expected'] or p['correct']!=p['observed']:reasons.append('graph_'+k)
    if dups:reasons.append('source_duplicate')
    return dict(reusable=not reasons,remaining_reasons=sorted(set(reasons)),
                schema_errors=errs,quality_issues=issues,coverage=cov,tables=tab,
                graph=graph,graph_scored=bool(ref['nodes']),duplicates=dups)

def main():
    plan=a.read(ROOT/'outputs/indexing-plan-110-001/vision-units.json')
    manifest=a.read(a.VISION/'manifest.json')
    items={a.key(i):i for i in manifest['items']}
    refs=a.read(ROOT/'outputs/vision-source-review-001/source-references.json')
    old={r['key']:r for r in a.read(ROOT/'outputs/vision-validation-run-003/evaluation.json')[0]['records']}
    source_eval={r['key']:r for r in a.read(ROOT/'outputs/vision-source-review-001/evaluation.json')[0]['records']}
    parsed={d['doc_id']:d for d in [json.loads(l) for l in (ROOT/'outputs/parsing-run-003/parsed.jsonl').read_text().splitlines()]}
    originals=[Path(r['old_source_response_path']) for r in plan]
    originals += [ROOT/'outputs/parsing-run-003/parsed.jsonl',ROOT/'outputs/vision-source-review-001/source-references.json',ROOT/'outputs/vision-source-review-001/evaluation.json',ROOT/'outputs/vision-validation-run-003/evaluation.json',a.VISION/'manifest.json',ROOT/'outputs/indexing-plan-110-001/vision-units.json']
    originals += [Path(items[r['id']]['image_path']) for r in plan]
    source_paths={Path(refs[r['id']]['source_path']) for r in plan}
    originals += sorted(source_paths)
    frozen={str(p):a.filehash(p) for p in originals}
    records=[];assembled={};changes_count=collections.Counter()
    for r in plan:
        key=r['id'];item=items[key];ref=refs[key]
        assert a.filehash(item['image_path'])==item['image_sha256']==ref['image_sha256']
        assert a.filehash(ref['source_path'])==item['source_sha256']==ref['source_sha256']
        path=Path(r['old_source_response_path']);response=a.read(path)
        assert a.filehash(path)==old[key]['response_sha256']==source_eval[key]['response_sha256']
        raw=response['choices'][0]['message']['content']
        original_wire,complete,closed=a.review.recover(raw)
        w=copy.deepcopy(original_wire);log=[]
        if r['cloud_reuse_candidate']:
            assert complete and response['choices'][0]['finish_reason']=='stop'
            category='adopted_unchanged'
        else:
            if not complete:
                assert key=='D-102-vision-page2'
                w=reconstruct_d102_page2(w,log)
                category='assistant_source_reconstruction'
            else:
                assert response['choices'][0]['finish_reason']=='stop'
                w=manual_apply(key,w,log)
                repair_geometry(w,item,log)
                w=deduplicate(w,ref,log)
                category='assistant_image_corrected' if any(x['method']=='assistant_image_review' for x in log) else 'deterministic_repair'
        audit=metrics(w,item,ref)
        base=Path('units')/key
        save(base/'wire.json',w)
        save(base/'changes.json',log)
        changes_count.update(x['method'] for x in log)
        # Explicitly test that deterministic operations cannot remove any unique
        # literal, cell grid, node or graph relation, even outside reference gold.
        if category=='deterministic_repair':
            assert {norm(x['text']) for x in a.review.text_items(w)}=={norm(x['text']) for x in a.review.text_items(original_wire)}
            assert w['tables']==original_wire['tables']
            assert [[n for n in f['nodes']] for f in w['figures']]==[[n for n in f['nodes']] for f in original_wire['figures']]
            def rels(x):return [[{k:v for k,v in e.items() if k!='bbox'} for e in f['relations']] for f in x['figures']]
            assert rels(w)==rels(original_wire)
        common_valid=False;roundtrip=False
        if audit['reusable']:
            did=item['doc_id'];doc=assembled.get(did,parsed[did])
            converted=a.quality.base.convert(doc,item,w,a.OLD_MODEL,provider=response.get('provider','DeepInfra'),quantization='fp8')
            run_id='vision-'+item['unit_id'].split(':',1)[1]
            run=next(x for x in converted['runs'] if x['run_id']==run_id)
            run['implementation']='rag-vision-1.0.0' if category=='adopted_unchanged' else 'rag-vision-1.0.0+offline-reuse-review-1.0.0'
            unit=next(x for x in converted['coverage']['units'] if x['unit_id']==item['unit_id'])
            unit['reason']='Reused OpenRouter extraction; '+category+'; source/changes in vision-reuse-review-001/units/'+key+'/provenance.json'
            if category.startswith('assistant_'):
                # The existing run-result schema permits only native_parser or
                # vision_llm. Keep the ORIGINAL extraction identity, identify the
                # subsequent correction pipeline, and attach explicit warnings
                # plus field-level sidecars. Never impersonate a new model run.
                run['implementation']='original-vision-extraction+assistant-source-correction-2026-10-20'
                for b in converted['blocks']:
                    if b['block_id'] in unit['block_ids']:
                        b['warnings']=['assistant_source_review_not_independent_human_gold',
                                       'not_unmodified_model_output_see_field_level_provenance',
                                       category]
            for b in converted['blocks']:
                if b['block_id'] in unit['block_ids'] and b.get('claims'):
                    b['warnings'].append('claims_not_cleared_for_factual_index_see_ingestion_policy')
            conversion_errors=a.quality.base.common.check(converted)
            assert not conversion_errors, (key,conversion_errors)
            common_valid=True
            roundtrip=a.review.wire_payload(w)==a.review.common_payload(converted,item)
            assert roundtrip
            assembled[did]=converted
            save(base/'common-block-document.json',converted)
        provenance=dict(key=key,category=category,original_response_path=str(path),
            original_response_sha256=a.filehash(path),source_path=ref['source_path'],
            source_sha256=item['source_sha256'],image_path=item['image_path'],image_sha256=item['image_sha256'],
            original_model=response['model'],original_provider=response.get('provider'),original_quantization='fp8',
            original_json_complete=complete,original_finish_reason=response['choices'][0]['finish_reason'],
            derivative_path=str(HERE/base/'wire.json'),derivative_sha256=a.filehash(HERE/base/'wire.json'),
            changes_path=str(HERE/base/'changes.json'),change_count=len(log),
            review_type='assistant_image_review' if category.startswith('assistant_') else 'existing_source_reference_and_structural_checks',
            original_model_success_changed=False,independent_human_review=False,
            semantic_claims_fully_reviewed=False,pixel_accurate_bbox_verified=False,new_model_calls=0)
        save(base/'provenance.json',provenance)
        records.append(dict(id=key,doc_id=item['doc_id'],unit_id=item['unit_id'],category=category,
            prior_candidate=r['cloud_reuse_candidate'],before_decision=old[key]['decision'],
            before_source_coverage=source_eval[key]['coverage'],before_json_complete=complete,
            after=audit,common_json_valid=common_valid,wire_common_roundtrip=roundtrip,
            changes=len(log),provenance_path=str(HERE/base/'provenance.json')))
    assert len(records)==121 and sum(r['prior_candidate'] for r in records)==67
    # Staging only. Do not overwrite native records or publish a live index.
    for did,doc in assembled.items():
        assert doc['source']==parsed[did]['source']
        assert all(b in doc['blocks'] for b in parsed[did]['blocks'])
        assert not a.quality.base.common.check(doc)
    with (HERE/'parsed.reuse-staging.jsonl').open('w') as f:
        for did in sorted(assembled):f.write(json.dumps(assembled[did],ensure_ascii=False)+'\n')
    save('records.json',records)
    retry=[dict(id=r['id'],reasons=r['after']['remaining_reasons']) for r in records if not r['after']['reusable']]
    save('retry-required.json',dict(new_calls_authorized=False,units=retry,
        scope='original 110 documents / 121 vision units',
        reuse_scope='source literals, table cells/layout, nodes and source-annotated relations; free-form claims retained separately',
        caveat='No mandatory rerun for the known extraction/delivery failures under assisted correction policy. Free-form claims are not cleared for factual indexing; this does not certify independent semantic accuracy or AWQ equivalence.'))
    save('adopted-67.json',[r['id'] for r in records if r['prior_candidate']])
    save('reviewed-54.json',[r for r in records if not r['prior_candidate']])
    claims=[]
    for r in records:
        wire=a.read(HERE/'units'/r['id']/'wire.json')
        for fi,f in enumerate(wire['figures']):
            for ci,c in enumerate(f['claims']):
                claims.append(dict(id=r['id'],path=f'figures[{fi}].claims[{ci}]',
                    **c,review_status='not_cleared_for_factual_index'))
    save('semantic-review-pending.json',dict(claims=claims,scope='Free-form claims are preserved, not silently discarded or scored.',
        known_concerns=[
            {'id':'D-026-vision-slide1','phrase':'4계층 구조','reason':'서버 4대의 병렬 연결과 4계층은 다름. 구조 필드 재사용과 별도로 설명 문구 검수 필요.'},
            {'id':'D-025-vision-slide1','phrase':'외부망에 직접 접근','reason':'연결선만으로 실제 접근 허용·통신 가능 여부를 확정할 수 없음.'}],
        new_model_call_required=False))
    save('ingestion-policy.json',dict(scope='original corpus vision reuse staging',
        selected_source='OpenRouter Qwen3.6 FP8 with versioned offline corrections',
        accepted_literal_structural_units=[r['id'] for r in records if r['after']['reusable']],
        factual_index_fields=['texts.text','tables.cells.text','figures.nodes.label','figures.relations checked against annotated source edges'],
        excluded_from_factual_index=['figures.claims'],
        claims_preserved_in='semantic-review-pending.json',
        explanatory_claims_require_separate_review=True,
        live_index_updated=False,model_benchmark_updated=False,
        automatic_cache_equivalent_to_orin_awq=False,new_model_calls=0))
    changed=[p for p,h in frozen.items() if a.filehash(p)!=h]
    assert not changed
    save('integrity.json',dict(checked_files=len(frozen),hashes=frozen,changed_files=changed,
        new_model_calls=0,network_calls=0,source_documents=len(source_paths),images=121,
        native_blocks_preserved=True,assembled_documents=len(assembled)))
    summary=dict(scope_images=121,original_reusable=67,reviewed=54,
        categories=dict(collections.Counter(r['category'] for r in records)),
        reusable_after=sum(r['after']['reusable'] for r in records),retry_required=len(retry),
        common_json_valid=sum(r['common_json_valid'] for r in records),
        wire_common_roundtrip=sum(r['wire_common_roundtrip'] for r in records),
        coverage_before={k:sum(r['before_source_coverage'][k] for r in records) for k in ('total','compatible')},
        coverage_after={k:sum(r['after']['coverage'][k] for r in records) for k in ('total','compatible')},
        warning_pages_before=sum(r['before_decision']=='candidate_with_warnings' for r in records),
        rejected_pages_before=sum(r['before_decision']=='reject' for r in records),
        after_quality_issues=sum(len(r['after']['quality_issues']) for r in records),
        change_types=dict(changes_count),new_model_calls=0,staging_only=True,
        repaired_result_is_not_model_benchmark=True,
        free_form_claims_pending=len(claims),free_form_claim_units=len({c['id'] for c in claims}))
    save('summary.json',summary)
    with (HERE/'reviewed-54.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f);wr.writerow(['자료','처리 유형','기존 판정','재사용 가능','수정 수','미해결','감사 기록'])
        for r in records:
            if not r['prior_candidate']:wr.writerow([r['id'],r['category'],r['before_decision'],r['after']['reusable'],r['changes'],';'.join(r['after']['remaining_reasons']),r['provenance_path']])
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    for r in records:
        if not r['after']['reusable']:print(r['id'],r['after']['remaining_reasons'])

if __name__=='__main__':main()
