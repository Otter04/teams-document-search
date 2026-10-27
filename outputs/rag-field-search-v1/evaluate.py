#!/usr/bin/env python3
import argparse,importlib.util,sys,time
from pathlib import Path
import field_search as s
E=s.E
spec=importlib.util.spec_from_file_location('prior_metrics',s.ROOT.parent/'rag-rule-search-v1/evaluate.py');metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)
MODES={'baseline':(False,False,False),'weights_only':(True,False,False),'context_only':(False,True,False),'weights_context':(True,True,False),'intent_only':(False,False,True),'combined':(True,True,True)}
def aggregate(rows):
 return {**metrics.aggregate(rows),'hit_at_1':sum(r['first_rank']==1 for r in rows)/len(rows),'all_answers_at_5':sum(r['document_recall_at_5']==1 for r in rows),'all_answers_at_5_rate':sum(r['document_recall_at_5']==1 for r in rows)/len(rows)}
def run(args):
 out=Path(args.output)
 if out.exists():raise ValueError('new output required')
 ix=E.read_json(args.index);parsed=s.old.base.unique_records(args.parsed);meta=s.old.base.unique_records(args.metadata);terms=E.read_json(args.reference)['system_terms']
 prior=Path(args.baseline);summary0=E.read_json(prior/'evaluation/summary.json');assert args.as_of==summary0['reference_date']
 qs=E.read_lines(prior/'evaluation/query-inputs.jsonl');assert all(set(q)=={'query_id','query'} for q in qs)
 bundle=s.prepare(ix,parsed,meta);views={(c,i):s.view(ix,bundle,context=c,intents=i) for c in (False,True) for i in (False,True)}
 stats={i:s.field_statistics(ix,bundle,i) for i in (False,True)};original_hash=E.record_hash(ix)
 s.old.base.datetime.strptime(args.as_of,'%Y-%m-%d');guard={'active':True,'attempts':0}
 def audit(event,args):
  if guard['active'] and event in ('open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):guard['attempts']+=1;raise RuntimeError('external IO during retrieval')
 sys.addaudithook(audit)
 results={};times={}
 for name,(weights,context,intents) in MODES.items():
  start=time.perf_counter();results[name]=[{'query_id':q['query_id'],'query':q['query'],**s.search(views[(context,intents)],bundle,q['query'],args.as_of,terms,weights=weights,intents=intents,statistics=stats[intents])} for q in qs];times[name]=time.perf_counter()-start
 replay=[{'query_id':q['query_id'],'query':q['query'],**s.search(views[(True,True)],bundle,q['query'],args.as_of,terms,intents=True,statistics=stats[True])} for q in qs];assert replay==results['combined'];guard['active']=False
 assert E.record_hash(ix)==original_hash
 labels={r['query_id']:r for r in E.read_json(prior/'evaluation/combined-query-results.json')};old=E.read_lines(prior/'evaluation/combined-search-results.jsonl')
 assert [[(r['doc_id'],r['score']) for r in row['results']] for row in old]==[[(r['doc_id'],r['score']) for r in row['results']] for row in results['baseline']]
 native={d for d,x in ix['documents'].items() if x['native_chunk_count']};scored={};summary={'reference_date':args.as_of,'model_called':False,'development_set':True,'modes':{},'weights':s.WEIGHTS,'log_context_chunks':len(bundle['log_contexts']),'overall_pipeline_complete':False}
 for name,rows in results.items():
  scored[name]=[];native_scores=[]
  for r in rows:
   label=labels[r['query_id']];ranking=[v['doc_id'] for v in r['results']];answers=label['answers'];na=set(answers)&native
   row={'query_id':r['query_id'],'query':r['query'],'type':label['type'],'answers':answers,'doc_ids':ranking,**metrics.metric(ranking,answers),'answer_ranks':{d:ranking.index(d)+1 if d in ranking else None for d in answers}}
   if na:
    n=metrics.metric(ranking,na);row['native_metric']=n;native_scores.append(n)
   scored[name].append(row)
   for hit in r['results']:
    allowed,_=s.old.base.apply_filters({'documents':{hit['doc_id']:ix['documents'][hit['doc_id']]}},r['query_plan']['filters']);assert hit['doc_id'] in allowed
  summary['modes'][name]={'all':aggregate(scored[name]),'native':aggregate(native_scores),'by_type':{t:aggregate([r for r in scored[name] if r['type']==t]) for t in sorted({r['type'] for r in scored[name]})},'elapsed_seconds':times[name]}
 before={r['query_id']:r for r in scored['baseline']};changes=[{'query_id':r['query_id'],'query':r['query'],'before_rank':before[r['query_id']]['first_rank'],'after_rank':r['first_rank'],'before_hit':before[r['query_id']]['hit_at_5'],'after_hit':r['hit_at_5'],'before_recall':before[r['query_id']]['document_recall_at_5'],'after_recall':r['document_recall_at_5']} for r in scored['combined']]
 summary['hit5_regressions']=[r['query_id'] for r in changes if r['before_hit']>r['after_hit']];summary['recall_regressions']=[r['query_id'] for r in changes if r['before_recall']>r['after_recall']]
 summary['rank_regressions']=[r['query_id'] for r in changes if r['before_rank'] and (r['after_rank']==0 or r['after_rank']>r['before_rank'])]
 summary['targets']={name:[r for r in rows if r['query_id'] in ('Q-020','Q-032')] for name,rows in scored.items()}
 out.mkdir(parents=True);ev=out/'evaluation';ev.mkdir();E.dump(out/'features.json',bundle)
 for name,rows in results.items():E.save_lines(ev/(name+'-search-results.jsonl'),rows);E.dump(ev/(name+'-query-results.json'),scored[name])
 E.dump(ev/'summary.json',summary);E.dump(ev/'changes.json',changes);E.save_lines(ev/'query-inputs.jsonl',qs)
 E.dump(out/'provenance.json',{'version':s.VERSION,'model_called':False,'reference_date':args.as_of,'inputs':{str(Path(p).resolve()):E.digest(p) for p in [args.index,args.parsed,args.metadata,args.reference,s.ROOT/'field_search.py',s.ROOT/'CONTRACT.md',__file__,s.old.ROOT/'condition_search.py',s.old.previous.ROOT/'search.py']},'outputs':{str(p.relative_to(out)):E.digest(p) for p in [out/'features.json',*ev.iterdir()] if p.is_file()}})
 E.dump(out/'verification.json',{'baseline_ranks_scores_exact':True,'full_search_replay_equal':True,'original_index_unchanged':True,'query_input_keys':['query_id','query'],'gold_read_after_search':True,'retrieval_io_guard':True,'blocked_io_attempts':guard['attempts'],'filter_violations':0})
 for name,m in summary['modes'].items():print(name,m['all'])
 print('TARGETS', {name:[(r['query_id'],r['answer_ranks']) for r in rows] for name,rows in summary['targets'].items()})
 print('REGRESSIONS',{k:summary[k] for k in ('hit5_regressions','recall_regressions','rank_regressions')})
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for f in ('index','parsed','metadata','reference','baseline','output','as-of'):p.add_argument('--'+f,required=True)
 run(p.parse_args())
