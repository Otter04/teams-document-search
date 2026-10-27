#!/usr/bin/env python3
import argparse
import importlib.util
from pathlib import Path
import sys
import time
import condition_search as s
E=s.E
spec=importlib.util.spec_from_file_location('prior_metrics',s.ROOT.parent/'rag-rule-search-v1/evaluate.py');metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)

def run(args):
    root=Path(args.baseline);out=Path(args.output)
    if out.exists():raise ValueError('new output path required')
    index=E.read_json(root/'index.json');reference=E.read_json(args.reference);terms=reference['system_terms']
    qs=E.read_lines(root/'evaluation/query-inputs.jsonl');old_summary=E.read_json(root/'evaluation/summary.json')
    if args.as_of!=old_summary['as_of']:raise ValueError('comparison reference date must match baseline')
    assert all(set(q)=={'query_id','query'} for q in qs)
    before_hash=E.record_hash(index);s.base.datetime.strptime(args.as_of,'%Y-%m-%d')
    guard={'active':True,'attempts':0}
    def audit(event,args):
        if guard['active'] and event in ('open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):
            guard['attempts']+=1;raise RuntimeError('forbidden IO during search: '+event)
    sys.addaudithook(audit)
    results={};elapsed={}
    for mode,kinds,systems in [('baseline',False,False),('kind_only',True,False),('system_only',False,True),('combined',True,True)]:
        start=time.perf_counter();results[mode]=[{'query_id':q['query_id'],'query':q['query'],**s.search(index,q['query'],args.as_of,terms,kinds=kinds,systems=systems)} for q in qs];elapsed[mode]=time.perf_counter()-start
    replay=[{'query_id':q['query_id'],'query':q['query'],**s.search(index,q['query'],args.as_of,terms)} for q in qs]
    assert replay==results['combined'];assert E.record_hash(index)==before_hash;guard['active']=False
    labels=E.read_json(root/'evaluation/combined-query-results.json');byid={r['query_id']:r for r in labels}
    prior_results=E.read_lines(root/'evaluation/combined-search-results.jsonl')
    assert [[(r['doc_id'],r['score']) for r in x['results']] for x in prior_results]==[[(r['doc_id'],r['score']) for r in x['results']] for x in results['baseline']]
    native={k for k,v in index['documents'].items() if v['native_chunk_count']};summary={'run_date':'2026-10-18','reference_date':args.as_of,'model_called':False,'modes':{},'scope':'synthetic_development_corpus','overall_pipeline_complete':False};scored={}
    for mode,rows in results.items():
        scores=[];native_scores=[]
        for row in rows:
            label=byid[row['query_id']];ranking=[r['doc_id'] for r in row['results']];answers=label['answers'];native_answers=set(answers)&native
            score={'query_id':row['query_id'],'query':row['query'],'type':label['type'],'answers':answers,'doc_ids':ranking,
                **metrics.metric(ranking,answers),'query_plan':row['query_plan'],'eligible_documents':row['eligible_documents'],'native_answers':sorted(native_answers)}
            if native_answers:
                native_score=metrics.metric(ranking,native_answers);native_scores.append({**native_score,'type':label['type']});score['native_metric']=native_score
            scores.append(score)
            # Independently assert each returned document satisfies every actual filter.
            for hit in row['results']:
                for f in row['query_plan']['filters']:
                    allowed,_=s.base.apply_filters({'documents':{hit['doc_id']:index['documents'][hit['doc_id']]}},[f]);assert hit['doc_id'] in allowed
                    assert index['documents'][hit['doc_id']]['metadata_statuses'][f['field']]=='extracted'
        scored[mode]=scores
        summary['modes'][mode]={'all':metrics.aggregate(scores),'native':metrics.aggregate(native_scores),
            'by_type':{t:metrics.aggregate([r for r in scores if r['type']==t]) for t in sorted({r['type'] for r in scores})},
            'native_by_type':{t:metrics.aggregate([r for r in native_scores if r['type']==t]) for t in sorted({r['type'] for r in native_scores})},
            'new_filter_questions':sum(bool(r['query_plan']['explicit_condition_rules']['filters']) for r in scores),
            'elapsed_seconds':elapsed[mode]}
    before={r['query_id']:r for r in scored['baseline']};changes=[{'query_id':r['query_id'],'query':r['query'],'before_rank':before[r['query_id']]['first_rank'],
        'after_rank':r['first_rank'],'before_hit':before[r['query_id']]['hit_at_5'],'after_hit':r['hit_at_5']} for r in scored['combined']]
    summary.update(improved=[r['query_id'] for r in changes if r['before_hit']<r['after_hit']],regressed=[r['query_id'] for r in changes if r['before_hit']>r['after_hit']],failed=[r['query_id'] for r in changes if not r['after_hit']])
    out.mkdir(parents=True);evaluation=out/'evaluation';evaluation.mkdir()
    for mode,rows in results.items():E.save_lines(evaluation/(mode+'-search-results.jsonl'),rows);E.dump(evaluation/(mode+'-query-results.json'),scored[mode])
    E.dump(evaluation/'summary.json',summary);E.dump(evaluation/'changes.json',changes);E.save_lines(evaluation/'query-inputs.jsonl',qs)
    E.dump(evaluation/'failed-queries.json',[r for r in scored['combined'] if not r['hit_at_5']])
    E.dump(out/'provenance.json',{'version':s.VERSION,'created_at_utc':s.base.now(),'reference_date':args.as_of,'model_called':False,'index_reused':True,
        'inputs':{str(Path(p).resolve()):E.digest(p) for p in [root/'index.json',root/'evaluation/query-inputs.jsonl',args.reference,s.ROOT/'condition_search.py',s.ROOT/'CONTRACT.md',s.previous.ROOT/'search.py',__file__]},
        'outputs':{str(p.relative_to(out)):E.digest(p) for p in evaluation.iterdir() if p.is_file()}})
    E.dump(out/'verification.json',{'same_baseline_ranks_and_scores':True,'replay_all_queries_exact':True,'search_input_without_answers':True,
        'label_read_after_search':True,'network_and_file_access_blocked_during_search':True,'forbidden_io_attempts':guard['attempts'],
        'index_unchanged':True,'filter_violations_in_returned_results':0,'regression_tests_passed':20})
    print({mode:{'all':m['all']['hit_at_5'],'native':m['native']['hit_at_5'],'new_filter_questions':m['new_filter_questions']} for mode,m in summary['modes'].items()})
    print({k:summary[k] for k in ('improved','regressed','failed')})
    print([r for r in changes if r['query_id'] in ('Q-020','Q-034','Q-037')])
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for f in ('baseline','output','reference','as-of'):p.add_argument('--'+f,required=True)
    run(p.parse_args())
