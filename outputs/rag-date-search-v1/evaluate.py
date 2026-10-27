"""Frozen original-query regression plus separately reported date development cases."""
import argparse, importlib.util, sys
from pathlib import Path
import date_search as d
E=d.E

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
qm=load_module('date_query_metrics',d.ROOT.parent/'rag-rule-search-v1/evaluate.py')

def passes(result,label):
    ids=[r['doc_id'] for r in result['results']]
    if label['check']=='needs_clarification':return result.get('status')=='needs_clarification' and not ids
    if result.get('status')=='needs_clarification':return False
    return ids==label['expected_doc_ids'] if label['check']=='ordered' else set(ids)==set(label['expected_doc_ids'])

def evaluate(run,baseline,output,as_of='2026-10-17'):
    run=Path(run);baseline=Path(baseline);out=Path(output)
    if out.exists():raise ValueError('new evaluation path required')
    prov=E.read_json(run/'provenance.json')
    for p,h in prov['inputs'].items():assert E.digest(p)==h,p
    for p,h in prov['outputs'].items():assert E.digest(run/p)==h,p
    freeze=E.read_json(d.ROOT/'evaluation-freeze.json');assert E.digest(d.ROOT/'development-date-cases.json')==freeze['date_cases_sha256']
    ix=E.read_json(run/'index.json');bundle=E.read_json(run/'features.json');view=d.old.view(ix,bundle,context=True,intents=True);stats=d.old.field_statistics(view,bundle,True)
    oldix=E.read_json(baseline/'index.json');oldbundle=E.read_json(baseline/'features.json');oldview=d.old.view(oldix,oldbundle,context=True,intents=True);oldstats=d.old.field_statistics(oldview,oldbundle,True)
    inputs=E.read_lines(d.ROOT.parent/'field-search-run-002/evaluation/query-inputs.jsonl')
    extra=E.read_lines(d.ROOT/'development-date-inputs.jsonl')
    assert all(set(q)=={'query_id','query'} for q in inputs)
    assert all(set(q)=={'query_id','query','limit'} for q in extra)
    d.plan('2025년 수정된 문서',as_of,ix['system_terms'],ix['clients']);E.timestamp('2000-01-01 00:00:00')
    guard={'active':True,'blocked_attempts':0}
    def audit(event,args):
        if guard['active'] and event in {'open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
            guard['blocked_attempts']+=1;raise RuntimeError('IO forbidden during retrieval: '+event)
    sys.addaudithook(audit)
    def retrieve(qs):return [{'query_id':q['query_id'],'query':q['query'],**d.search(view,bundle,q['query'],as_of,ix['system_terms'],limit=q.get('limit',10),statistics=stats)} for q in qs]
    results=retrieve(inputs);date_results=retrieve(extra)
    old_date_results=[{'query_id':q['query_id'],'query':q['query'],**d.old.search(oldview,oldbundle,q['query'],as_of,ix['system_terms'],intents=True,limit=q['limit'],statistics=oldstats)} for q in extra]
    assert retrieve(inputs)==results and retrieve(extra)==date_results
    guard['active']=False
    out.mkdir(parents=True);E.save_lines(out/'search-results.jsonl',results);E.save_lines(out/'date-search-results.jsonl',date_results);E.save_lines(out/'baseline-date-search-results.jsonl',old_date_results)
    # Evaluation-only labels are loaded after output is fixed.
    labels={r['query_id']:r for r in E.read_json(baseline/'evaluation/query-results.json')}
    before={r['query_id']:r for r in E.read_lines(baseline/'evaluation/search-results.jsonl')}
    date_labels={r['query_id']:r for r in E.read_json(d.ROOT/'development-date-cases.json')}
    native={did for did,v in ix['documents'].items() if v['native_chunk_count']};scored=[];natives=[];changes=[]
    for r in results:
        label=labels[r['query_id']];ids=[h['doc_id'] for h in r['results']]
        row={'query_id':r['query_id'],'query':r['query'],'answers':label['answers'],'doc_ids':ids,**qm.metric(ids,label['answers'])}
        row['answer_ranks']={a:ids.index(a)+1 if a in ids else None for a in label['answers']};scored.append(row)
        if set(label['answers'])&native:natives.append(qm.metric(ids,set(label['answers'])&native))
        for a,v in row['answer_ranks'].items():
            if v!=label['answer_ranks'][a]:changes.append({'query_id':r['query_id'],'doc_id':a,'before':label['answer_ranks'][a],'after':v})
    detail=[]
    for a,b in zip(old_date_results,date_results):
        label=date_labels[b['query_id']]
        detail.append({**label,'before_pass':passes(a,label),'after_pass':passes(b,label),'before_ids':[x['doc_id'] for x in a['results']],
          'after_ids':[x['doc_id'] for x in b['results']],'query_plan':b['query_plan'],'unresolved_documents':b['unresolved_filter_documents']})
    for r in results+date_results:
        for hit in r['results']:
            allowed,_=d.apply_filters({'documents':{hit['doc_id']:ix['documents'][hit['doc_id']]}},r['query_plan']['filters']);assert hit['doc_id'] in allowed
    def agg(rows):return {**qm.aggregate(rows),'top1':sum(r['first_rank']==1 for r in rows),'all_answers_at_5':sum(r['document_recall_at_5']==1 for r in rows)}
    summary={'original_queries':{'before':agg(list(labels.values())),'after':agg(scored),'native_after':agg(natives),'rank_changes':changes,
      'all_result_ranks_and_scores_identical':all([(h['doc_id'],h['score']) for h in r['results']]==[(h['doc_id'],h['score']) for h in before[r['query_id']]['results']] for r in results)},
      'date_development_checks':{'total':len(detail),'before_pass':sum(r['before_pass'] for r in detail),'after_pass':sum(r['after_pass'] for r in detail),'failures':[r['query_id'] for r in detail if not r['after_pass']],
        'not_independent':True,'positive_cases':sum(bool(r['expected_doc_ids']) for r in detail),'no_confirmed_native_match_cases':sum(not r['expected_doc_ids'] and r['check']=='set' for r in detail),'clarification_cases':sum(r['check']=='needs_clarification' for r in detail)},
      'enriched_byte_identical':E.digest(run/'enriched.jsonl')==E.digest(baseline/'enriched.jsonl'),
      'chunks_byte_identical':E.digest(run/'chunks.jsonl')==E.digest(baseline/'chunks.jsonl'),
      'blocked_io_attempts':guard['blocked_attempts'],'repeat_results_identical':True,'paid_api_calls':0,'independent_evaluation_performed':False}
    E.dump(out/'query-results.json',scored);E.dump(out/'date-case-comparison.json',detail);E.dump(out/'summary.json',summary)
    E.dump(out/'provenance.json',{'code_sha256':E.digest(Path(__file__)),'date_cases_sha256':freeze['date_cases_sha256'],'reference_date':as_of,'labels_loaded_after_retrieval':True,
        'outputs':{p.name:E.digest(p) for p in out.iterdir() if p.is_file()}})
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('run','baseline','output'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(E.canonical(evaluate(a.run,a.baseline,a.output)))
