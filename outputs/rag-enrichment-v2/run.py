"""Versioned no-model enrichment, unchanged-gold evaluation and retrieval regression."""
import argparse,importlib.util,sys,copy
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import enrich as e
sys.path.insert(0,str(e.ROOT.parent/'rag-field-search-v1'))
import field_search as search
assert search.old.base.enrich is e, 'runner must select the v2 enrichment dependency'
spec=importlib.util.spec_from_file_location('metadata_comparison',e.ROOT.parent/'rag-enrichment-v1/evaluate.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
spec=importlib.util.spec_from_file_location('query_metrics',e.ROOT.parent/'rag-rule-search-v1/evaluate.py')
qm=importlib.util.module_from_spec(spec);spec.loader.exec_module(qm)

def run(args):
 out=Path(args.output);out.mkdir(exist_ok=True)
 if (out/'enriched.jsonl').exists():raise ValueError('enriched output already exists; choose new output')
 parsed=search.old.base.unique_records(args.parsed);reference=e.read_json(args.reference)
 prior_index=e.read_json(Path(args.search_baseline).parent/'rule-search-run-004/index.json')
 query_inputs=e.read_lines(Path(args.search_baseline)/'evaluation/query-inputs.jsonl')
 assert all(set(q)=={'query_id','query'} for q in query_inputs)
 # Warm validation and date modules before the IO guard. No benchmark labels loaded.
 warm=e.extract(next(iter(parsed.values())),reference);assert not e.check_output(warm,next(iter(parsed.values())))
 e.timestamp('2000-01-01 00:00:00')
 search.old.plan('2025년 로그',args.as_of,reference['system_terms'])
 guard={'active':False,'attempts':0}
 def audit(event,details):
  if guard['active'] and event in ('open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'):
   guard['attempts']+=1;raise RuntimeError('External IO forbidden during extraction/retrieval: '+event)
 sys.addaudithook(audit);guard['active']=True
 results={}
 for did,r in parsed.items():
  o=e.extract(r,reference);errors=e.check_output(o,r)
  if errors:raise ValueError((did,errors))
  results[did]=o
 assert results=={d:e.extract(r,reference) for d,r in parsed.items()}
 chunks=[]
 for did,r in parsed.items():
  c=search.old.base.make_chunks(r,results[did]);errors=search.old.base.validate_chunks(c,r,results[did])
  if errors:raise ValueError((did,errors))
  chunks.append(c)
 native_index=search.old.base.build_index(chunks,reference['clients'])
 index=search.old.previous.build_index(native_index,prior_index['rules'])
 bundle=search.prepare(index,parsed,results);view=search.view(index,bundle,context=True,intents=True);stats=search.field_statistics(index,bundle,True)
 def retrieve():return [{'query_id':q['query_id'],'query':q['query'],**search.search(view,bundle,q['query'],args.as_of,reference['system_terms'],intents=True,statistics=stats)} for q in query_inputs]
 searches=retrieve();assert retrieve()==searches;guard['active']=False
 e.save_lines(out/'enriched.jsonl',results.values());e.save_lines(out/'chunks.jsonl',chunks);e.dump(out/'index.json',index);e.dump(out/'features.json',bundle);e.dump(out/'enrichment.schema.json',e.schema())
 e.save_lines(out/'pending-fields.jsonl',[{'doc_id':d,'field':f,**v} for d,r in results.items() for f,v in r['fields'].items() if v['status']!='extracted'])
 # Gold access is confined to this completed-output evaluation stage.
 evaluation.run(SimpleNamespace(parsed=args.parsed,enriched=out/'enriched.jsonl',dataset=args.dataset,output=out/'evaluation'))
 old=search.old.base.unique_records(args.metadata_baseline)
 before_rows=[];after_rows=[];gold=search.old.base.unique_records(Path(args.dataset)/'gold/documents.jsonl')
 for did,r in results.items():before_rows+=evaluation.compare(old[did],gold[did]);after_rows+=evaluation.compare(r,gold[did])
 changes=[{'doc_id':d,'field':f,'before':old[d]['fields'][f],'after':r['fields'][f]} for d,r in results.items() for f in e.ALL_FIELDS if old[d]['fields'][f]!=r['fields'][f]]
 primary_changes=[c for c in changes if any(c['before'][k]!=c['after'][k] for k in ('value','status'))]
 old_queries={r['query_id']:r for r in e.read_json(Path(args.search_baseline)/'evaluation/combined-query-results.json')}
 old_search={r['query_id']:r for r in e.read_lines(Path(args.search_baseline)/'evaluation/combined-search-results.jsonl')}
 native={d for d,x in index['documents'].items() if x['native_chunk_count']};scored=[];native_scored=[]
 regressions=[];rank_changes=[]
 for result in searches:
  prev=old_queries[result['query_id']];ids=[x['doc_id'] for x in result['results']]
  r={k:prev[k] for k in ('query_id','query','type','answers')};r.update(doc_ids=ids,**qm.metric(ids,prev['answers']));r['answer_ranks']={d:ids.index(d)+1 if d in ids else None for d in r['answers']}
  na=set(r['answers'])&native
  if na:r['native_metric']=qm.metric(ids,na);native_scored.append(r['native_metric'])
  scored.append(r)
  for d,a in r['answer_ranks'].items():
   b=prev['answer_ranks'][d]
   if a!=b:rank_changes.append({'query_id':r['query_id'],'doc_id':d,'before':b,'after':a})
   if b is not None and (a is None or a>b):regressions.append(rank_changes[-1])
  for hit in result['results']:
   allowed,_=search.old.base.apply_filters({'documents':{hit['doc_id']:index['documents'][hit['doc_id']]}},result['query_plan']['filters']);assert hit['doc_id'] in allowed
 e.save_lines(out/'evaluation/search-results.jsonl',searches);e.dump(out/'evaluation/query-results.json',scored)
 def aggregate(rs):return {**qm.aggregate(rs),'all_answers_at_5':sum(r['document_recall_at_5']==1 for r in rs),'top1':sum(r['first_rank']==1 for r in rs)}
 summary={'model_called':False,'reference_date':args.as_of,'gold_modified':False,'metadata_before':evaluation.aggregate(before_rows),'metadata_after':evaluation.aggregate(after_rows),
  'primary_value_or_status_changes':primary_changes,'field_evidence_or_rule_changes':len(changes),'date_roles':dict(Counter(o['role'] for r in results.values() for o in r['date_context']['observations'])),
  'search_all':aggregate(scored),'search_native':aggregate(native_scored),'search_answer_rank_changes':rank_changes,'search_answer_rank_regressions':regressions,
  'search_ranks_and_scores_identical':all([(v['doc_id'],v['score']) for v in r['results']]==[(v['doc_id'],v['score']) for v in old_search[r['query_id']]['results']] for r in searches),
  'index_equals_previous':index==prior_index,'blocked_io_attempts':guard['attempts'],'extraction_and_retrieval_replay_equal':True,'schema_evidence_valid_documents':len(results)}
 e.dump(out/'comparison.json',summary);e.dump(out/'field-changes.json',changes)
 examples=out/'examples';examples.mkdir()
 for did in ('D-002','D-005','D-007','D-030'):e.dump(examples/(did+'.json'),results[did])
 paths=[args.parsed,args.reference,args.metadata_baseline,Path(args.dataset)/'gold/documents.jsonl',e.ROOT/'enrich.py',e.ROOT/'CONTRACT.md',Path(__file__),e.ROOT.parent/'rag-enrichment-v1/enrich.py',search.ROOT/'field_search.py',search.old.ROOT/'condition_search.py',search.old.previous.ROOT/'search.py',search.old.base.ROOT/'pipeline.py']
 e.dump(out/'provenance.json',{'version':e.VERSION,'schema_version':'1.1.0','model_called':False,'reference_date':args.as_of,'gold_read_after_extraction_and_search':True,'input_hashes':{str(Path(p).resolve()):e.digest(p) for p in paths},'outputs':{str(p.relative_to(out)):e.digest(p) for p in [out/'enriched.jsonl',out/'chunks.jsonl',out/'index.json',out/'features.json',out/'comparison.json',out/'field-changes.json',*sorted((out/'evaluation').iterdir())] if p.is_file()}})
 print('COMPARISON',e.canonical(summary))

if __name__=='__main__':
 p=argparse.ArgumentParser()
 for name in ('parsed','reference','metadata-baseline','search-baseline','dataset','output','as-of'):p.add_argument('--'+name,required=True)
 run(p.parse_args())
