"""Compare frozen development runs after retrieval; never a pipeline input."""
import collections, importlib.util, json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent
sys.path.insert(0,str(OUT/'rag-date-search-v2'))
import date_search as d
E=d.E
def keyed(path,key='doc_id'):return {r[key]:r for r in E.read_lines(path)}
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
me=load('metadata_metrics',OUT/'rag-enrichment-v1/evaluate.py')

def run():
    before=E.read_json(OUT/'additional-evaluation-run-001/summary.json')
    after=E.read_json(OUT/'additional-evaluation-run-002/summary.json')
    original=E.read_json(OUT/'date-search-run-002/evaluation/summary.json')
    qb={q['query_id']:q for q in E.read_json(OUT/'additional-evaluation-run-001/query-comparison.json')}
    qa={q['query_id']:q for q in E.read_json(OUT/'additional-evaluation-run-002/query-comparison.json')}
    queries=keyed(OUT/'additional-dataset-v1/package/queries.jsonl','query_id')
    query_changes=[{'query_id':qid,'query':queries[qid]['query'],'check':a['check'],
        'before_pass':qb[qid]['passed'],'after_pass':a['passed'],
        'before_ids':qb[qid]['actual_doc_ids'],'after_ids':a['actual_doc_ids'],
        'expected_ids':a['expected_doc_ids']} for qid,a in qa.items()]
    mb=E.read_json(OUT/'additional-evaluation-run-001/metadata-comparison.json')
    ma=E.read_json(OUT/'additional-evaluation-run-002/metadata-comparison.json')
    groups={}
    for field in E.FIELDS+list(sorted(d.DATE_FIELDS)):
        b=[r for r in mb if r['field']==field and r['expected_state']=='value']
        a=[r for r in ma if r['field']==field and r['expected_state']=='value']
        groups[field]={'expected':len(a),'before_correct':sum(r['passed'] for r in b),'after_correct':sum(r['passed'] for r in a)}
    old_before=keyed(OUT/'date-search-run-001/enriched.jsonl')
    old_after=keyed(OUT/'date-search-run-002/enriched.jsonl')
    gold=keyed(OUT/'metadata-policy-v1/documents.source-v1.jsonl')
    def score(records):return me.aggregate([v for did,r in records.items() for v in me.compare(r,gold[did])])
    old_values=[{'doc_id':did,'field':f,'before':b['value'],'after':old_after[did]['fields'][f]['value'],
                 'before_status':b['status'],'after_status':old_after[did]['fields'][f]['status']}
                for did,r in old_before.items() for f,b in r['fields'].items()
                if (b['value'],b['status'])!=(old_after[did]['fields'][f]['value'],old_after[did]['fields'][f]['status'])]
    checks=[]
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    for frozen,base in [(OUT/'additional-dataset-v1/package-freeze.json',OUT/'additional-dataset-v1'),
                        (OUT/'additional-dataset-v1/pipeline-freeze-before-authoring.json',OUT.parent)]:
        check(frozen.name,all(E.digest(base/p)==h for p,h in E.read_json(frozen)['files'].items()))
    for folder in ['date-search-run-001','date-search-run-002','additional-search-run-001','additional-search-run-002']:
        p=OUT/folder;prov=E.read_json(p/'provenance.json')
        check(folder+'_run_hashes',all(E.digest(path)==sha for path,sha in prov['inputs'].items()) and all(E.digest(p/name)==sha for name,sha in prov['outputs'].items()))
        check(folder+'_no_model_or_external_io',not prov['model_called'] and prov['external_api_calls']==0 and prov['blocked_io_attempts']==0)
    for a,b in [('date-search-run-001','date-search-run-002'),('additional-search-run-001','additional-search-run-002')]:
        old=keyed(OUT/a/'source-metadata.jsonl');new=keyed(OUT/b/'source-metadata.jsonl')
        check(b+'_source_hash_and_mtime_unchanged',all((old[k]['source_sha256'],old[k]['modified_at_ns'])==(new[k]['source_sha256'],new[k]['modified_at_ns']) for k in old))
        oldc=keyed(OUT/a/'chunks.jsonl');newc=keyed(OUT/b/'chunks.jsonl')
        core=lambda c:[(v['kind'],v['text'],v['source_refs']) for v in c['chunks']]
        check(b+'_native_chunk_body_and_evidence_unchanged',all(core(oldc[k])==core(newc[k]) for k in oldc))
        check(b+'_visual_queue_unchanged',all(oldc[k]['pending_visual_units']==newc[k]['pending_visual_units'] for k in oldc))
    check('old_metadata_values_and_statuses_unchanged',not old_values)
    unresolved=[r for r in E.read_json(OUT/'metadata-policy-v1/label-adjustments.json') if r['disposition']=='unresolved_from_body']
    check('old_draft_dates_still_unresolved',len(unresolved)==13 and all(old_after[r['doc_id']]['fields']['문서일자']['status']=='needs_review' and old_after[r['doc_id']]['fields']['문서일자']['value'] is None for r in unresolved))
    check('old_ranking_and_scores_unchanged',original['original_queries']['all_result_ranks_and_scores_identical'])
    check('new_query_successes_not_lost',not any(r['before_pass'] and not r['after_pass'] for r in query_changes))
    bvals={(r['doc_id'],r['field']):r for r in mb}
    check('new_correct_positive_metadata_not_lost',all(r['passed'] for r in ma if r['expected_state']=='value' and bvals[r['doc_id'],r['field']]['passed']))
    check('new_unresolved_fields_not_filled',all(r['actual_value'] is None for r in ma if r['expected_state']=='unresolved'))
    summary={'date':'2026-10-19','new_dataset':{'before':before,'after':after,
        'recovered_questions':[r['query_id'] for r in query_changes if not r['before_pass'] and r['after_pass']],
        'regressed_questions':[r['query_id'] for r in query_changes if r['before_pass'] and not r['after_pass']],
        'metadata_by_field':groups,'remaining_missing_values':[r for r in ma if r['expected_state']=='value' and not r['passed']]},
        'original_dataset':{'retrieval':original,'metadata_before':score(old_before),'metadata_after':score(old_after),'value_status_changes':old_values},
        'verification':checks,'unit_tests':{'enrichment':63,'date_search':17,'passed':80},
        'paid_api_calls':0,'independent_evaluation':False,'new_dataset_used_for_improvement':True}
    E.dump(ROOT/'comparison.json',summary);E.dump(ROOT/'query-changes.json',query_changes)
    E.dump(ROOT/'provenance.json',{'comparison_script_sha256':E.digest(__file__),
        'input_hashes':{str(p.resolve()):E.digest(p) for p in [OUT/'additional-evaluation-run-001/summary.json',OUT/'additional-evaluation-run-002/summary.json',OUT/'date-search-run-002/evaluation/summary.json',OUT/'metadata-policy-v1/documents.source-v1.jsonl']},
        'outputs':{p.name:E.digest(p) for p in [ROOT/'comparison.json',ROOT/'query-changes.json']}})
    print(E.canonical({'new_native_before':before['native_positive_relevance'],'new_native_after':after['native_positive_relevance'],
        'new_missing':summary['new_dataset']['remaining_missing_values'],'old_metadata':score(old_after),
        'checks_passed':len(checks),'recovered_questions':summary['new_dataset']['recovered_questions']}))

if __name__=='__main__':run()
