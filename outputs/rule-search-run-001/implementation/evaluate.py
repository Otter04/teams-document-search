#!/usr/bin/env python3
"""Four-way comparison using frozen questions; labels are read only after searching."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
import search as s
E=s.base.enrich

def metric(ranking,answers):
    ranked=list(dict.fromkeys(ranking))[:10];positions=[i for i,d in enumerate(ranked,1) if d in answers];first=min(positions,default=0)
    return {'first_rank':first,'hit_at_5':int(0<first<=5),'rr_at_10':1/first if first else 0,
            'document_recall_at_5':len(set(ranked[:5])&set(answers))/len(set(answers))}
def aggregate(rows):
    n=len(rows);hits=sum(r['hit_at_5'] for r in rows)
    return {'questions':n,'hits':hits,'hit_at_5':hits/n if n else None,'mrr_at_10':sum(r['rr_at_10'] for r in rows)/n if n else None,
            'mean_document_recall_at_5':sum(r['document_recall_at_5'] for r in rows)/n if n else None,'goal_90pct_passed':hits/n>=.9 if n else False}

def run(args):
    run=Path(args.run);baseline=Path(args.baseline);out=run/'evaluation'
    if out.exists():raise ValueError('new evaluation directory required')
    ix=E.read_json(run/'index.json');old=E.read_json(baseline/'index.json');prov=E.read_json(run/'provenance.json')
    for path,sha in prov['inputs'].items():assert E.digest(path)==sha,path
    assert E.digest(run/'index.json')==prov['outputs']['index.json']
    questions=E.read_lines(baseline/'evaluation/query-inputs.jsonl')
    assert all(set(q)=={'query_id','query'} for q in questions)
    assert len({q['query_id'] for q in questions})==len(questions)
    # No files or network may be accessed in the retrieval/rebuild phase.
    # Warm up Python's lazily loaded calendar parser before blocking file IO.
    s.base.datetime.strptime('2026-10-17','%Y-%m-%d')
    guard={'active':True,'attempts':0}
    def audit(event,args):
        if guard['active'] and event in ('open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):
            guard['attempts']+=1;raise RuntimeError('retrieval attempted external IO: '+event)
    sys.addaudithook(audit)
    assert s.build_index(old,ix['rules'])==ix
    results={};timings={}
    for name,terms,dates in [('baseline',False,False),('terms_only',True,False),('dates_only',False,True),('combined',True,True)]:
        start=time.perf_counter();results[name]=[{'query_id':q['query_id'],'query':q['query'],**s.search(ix if terms else old,q['query'],args.as_of,terms=terms,dates=dates)} for q in questions];timings[name]=time.perf_counter()-start
    # A second invocation must return byte-equivalent JSON structure.
    replay=[{'query_id':q['query_id'],'query':q['query'],**s.search(ix,q['query'],args.as_of)} for q in questions]
    assert replay==results['combined'];guard['active']=False
    # Frozen old labels are read only now, after all search outcomes are fixed.
    labels={r['query_id']:r for r in E.read_json(baseline/'evaluation/query-results.json')}
    old_results=E.read_lines(baseline/'evaluation/search-results.jsonl')
    assert [[r['doc_id'] for r in row['results']] for row in results['baseline']]==[[r['doc_id'] for r in row['results']] for row in old_results]
    native_ids={identity for identity,d in ix['documents'].items() if d['native_chunk_count']}
    summary={'as_of':args.as_of,'timezone':'Asia/Seoul','model_called':False,'queries':len(questions),'documents':len(ix['documents']),
        'entries':ix['entry_count'],'native_chunks_unchanged':True,'modes':{},'conditions_verified':False,'development_set':True,
        'overall_pipeline_complete':False,'evaluation_definition':'Hit@5 means at least one gold document in top 5; native scope requires a native gold document in original top 5.'}
    rows_by_mode={}
    for name,rows in results.items():
        scored=[];native=[]
        for row in rows:
            label=labels[row['query_id']];ranked=[r['doc_id'] for r in row['results']];answers=label['answers']
            scored.append({'query_id':row['query_id'],'query':row['query'],'type':label['type'],'answers':answers,'doc_ids':ranked,**metric(ranked,answers),
                'query_plan':row['query_plan'],'concept_matches':row['concept_matches'],'gold_filters_used':False})
            if set(answers)&native_ids:native.append(metric(ranked,set(answers)&native_ids))
        rows_by_mode[name]=scored
        summary['modes'][name]={'all':aggregate(scored),'native_answer_available':aggregate(native),
            'by_type':{typ:aggregate([r for r in scored if r['type']==typ]) for typ in sorted({r['type'] for r in scored})},
            'queries_with_filters':sum(bool(r['query_plan']['filters']) for r in scored),'queries_with_warnings':sum(bool(r['query_plan']['warnings']) for r in scored),
            'elapsed_seconds':timings[name]}
    before={r['query_id']:r for r in rows_by_mode['baseline']};changes=[]
    for row in rows_by_mode['combined']:
        previous=before[row['query_id']]
        changes.append({'query_id':row['query_id'],'query':row['query'],'before_rank':previous['first_rank'],'after_rank':row['first_rank'],
            'before_hit':previous['hit_at_5'],'after_hit':row['hit_at_5'],'type':row['type']})
    summary['improved_queries']=[r['query_id'] for r in changes if r['before_hit']<r['after_hit']]
    summary['regressed_queries']=[r['query_id'] for r in changes if r['before_hit']>r['after_hit']]
    summary['still_failed_queries']=[r['query_id'] for r in changes if not r['after_hit']]
    summary['all_type_goals_passed']=all(v['goal_90pct_passed'] for v in summary['modes']['combined']['by_type'].values())
    # Verify only postings/length changed, never source text, document metadata, or refs.
    assert old['documents']==ix['documents'];assert old['entries'].keys()==ix['entries'].keys()
    for eid,entry in old['entries'].items():assert {k:v for k,v in entry.items() if k!='length'}=={k:v for k,v in ix['entries'][eid].items() if k!='length'}
    out.mkdir();E.dump(out/'summary.json',summary);E.dump(out/'changes.json',changes);E.save_lines(out/'query-inputs.jsonl',questions)
    for name,rows in results.items():
        E.save_lines(out/(name+'-search-results.jsonl'),rows);E.dump(out/(name+'-query-results.json'),rows_by_mode[name])
    E.dump(out/'failed-queries.json',[r for r in rows_by_mode['combined'] if not r['hit_at_5']])
    E.dump(out/'verification.json',{'baseline_rankings_exact_match':True,'combined_replay_exact_match':True,'index_rebuild_exact_match':True,
        'retrieval_io_guard_enabled':True,'forbidden_io_attempts':guard['attempts'],'query_input_keys':['query_id','query'],
        'gold_read_after_search':True,'gold_filters_used':False,'source_text_refs_metadata_unchanged':True,
        'index_hash_unchanged':E.digest(run/'index.json')==prov['outputs']['index.json'],
        'evaluation_code_sha256':E.digest(__file__),'baseline_labels_sha256':E.digest(baseline/'evaluation/query-results.json'),
        'baseline_chunks_sha256':E.digest(baseline/'chunks.jsonl')})
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('run','baseline','as-of'):parser.add_argument('--'+field,required=True)
    run(parser.parse_args())
