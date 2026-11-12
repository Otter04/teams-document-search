"""Fresh 82-query full retrieval, API models only; no second Qwen or Min-max."""
from datetime import datetime,timezone
import concurrent.futures as F,csv,fcntl,hashlib,importlib.util,json,math,statistics,sys,time,urllib.request,urllib.error
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
sys.path.insert(0,str(R/'deploy/search_pos_eval'))
from fusion_normalized import fuse

def mod(name,path):
 s=importlib.util.spec_from_file_location(name,R/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
H=mod('full_rewrite_helpers','deploy/search_openrouter_dual_semantic/run.py')
S=mod('full_sf_helpers','deploy/search_rerank_ab/run_siliconflow.py')
M=mod('full_passages','deploy/search_openrouter/model_ranker.py')
KEYIDX='rag-search-context-no-filename-20261104';URL='https://api.siliconflow.com/v1/rerank';RM='Qwen/Qwen3-Reranker-8B'
read=H.read

def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(x,f,ensure_ascii=False,allow_nan=False,indent=1)
def es(path,body=None):
 req=urllib.request.Request(H.ES+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=40) as r:return json.load(r)
def hits(res):
 assert not res.get('timed_out') and not res.get('_shards',{}).get('failed')
 return [dict(chunk_id=h['_id'],doc_id=h['_source']['doc_id'],score=h['_score']) for h in res['hits']['hits']]
def sf_call(body,key):
 t=time.perf_counter();req=urllib.request.Request(URL,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
 raw={'endpoint':URL,'request':body,'started_at':H.stamp()}
 try:
  with urllib.request.build_opener(S.NoRedirect).open(req,timeout=120) as r:raw.update(http_status=r.status,response=json.load(r))
  if raw['response'].get('error'):raw['error']='provider_error'
 except urllib.error.HTTPError as e:raw.update(error='http_'+str(e.code),http_status=e.code)
 except Exception as e:raw['error']=type(e).__name__
 raw['seconds']=time.perf_counter()-t;return raw

def call(d,name,body,fn):
 """At most two transport attempts; preserve failures, never reissue unresolved calls."""
 for attempt in (1,2):
  prefix=d/(name+'-attempt'+str(attempt));out=prefix.with_suffix('.json');start=prefix.with_suffix('.started.json')
  if out.exists():raw=read(out)
  else:
   assert not start.exists(),('unresolved_request',d.name,name,attempt)
   save(start,{'at':H.stamp(),'request':body});raw=fn();save(out,raw)
  if not raw.get('error'):return raw
  retry=raw.get('http_status') in (429,500,502,503,504) or raw.get('error') in ('TimeoutError','timeout','URLError','RemoteDisconnected','ConnectionResetError')
  if not retry or attempt==2:raise RuntimeError((d.name,name,raw['error']))
  time.sleep(1)

def setup():
 qs=read(H.OUT/'inputs.json');labels=read(H.OUT/'labels.json');assert len(qs)==82
 paths=[H.OUT/'inputs.json',H.OUT/'labels.json',H.OUT/'prompt.json',H.OUT/'manifest.json',H.DATA/'chunks.ndjson',H.DATA/'documents.json',H.DATA/'blocks.json',Path(__file__),Path(H.__file__),Path(S.__file__),Path(M.__file__),R/'deploy/search_pos_eval/fusion_normalized.py']
 paths+=sorted(H.SNAP.glob('*.py'))
 olds={q['query_id']:read(R/'outputs/search-physical-merge-001/rankings'/q['query_id']/'split.json') for q in qs}
 for q in qs:
  x=olds[q['query_id']];assert x['query']==q['query'];assert x['keyword_request']['query']['bool']['must'][0]['multi_match']['query']==q['query']
  paths.append(R/'outputs/search-physical-merge-001/rankings'/q['query_id']/'split.json')
 if not (O/'manifest.json').exists():
  before=H.index_state();assert es('/'+KEYIDX+'/_count')['count']==3022
  save(O/'index-before.json',before)
  save(O/'keyword-settings-before.json',es('/'+KEYIDX+'/_settings'))
  save(O/'inputs.json',qs);save(O/'labels.json',labels)
  save(O/'manifest.json',{'created_at':H.stamp(),'questions':82,'models':{'rewrite':H.MODEL,'embedding':H.EMBED_MODEL,'reranker':RM},'endpoints':{'rewrite':H.CHAT,'embedding':H.EMBED,'reranker':URL},'second_qwen':False,'minmax':False,'new_calls_per_question':3,'max_attempts_per_stage':2,'query_concurrency':3,'branch_cap':50,'rrf_constant':60,'weights':[1,2],'reranker_cap':50,'rewrite_payload':H.payload(qs[0],'schema'),'embedding_mix':[.5,.5],'embedding_provider':'DeepInfra','keyword_settings':{'minimum_should_match':'20% across fields','weights':{'file_name':1,'context':2,'table_header':1,'body':1},'context_filename':False},'source_hashes':{str(p):H.sha(p) for p in paths},'labels_policy':'same as rrf50-paired-api-20261110; no alternative gold changes','metric':'all required evidence groups represented within topN; not document hit','timing':'per-question wall-clock from fresh Qwen start through serialized reranker order, includes requests, validation, ES and intermediate artifacts; excludes initialization, queue before worker, gold evaluation and final doc grouping; retry waiting included','service_blocked8':'diagnostic ranking executed on all82, separately report74+8; not automatic service answer'})
 for p,h in read(O/'manifest.json')['source_hashes'].items():assert H.sha(Path(p))==h,p
 return qs,olds,{x['query_id']:x for x in labels}

def one(q):
 qid=q['query_id'];d=O/'queries'/qid
 if (d/'result.json').exists():return
 resumed=(d/'question.started.json').exists()
 if not resumed:save(d/'question.started.json',{'at':H.stamp()})
 start=time.perf_counter();o=olds[qid]
 t=time.perf_counter();body=H.payload(q,'schema');raw=call(d,'rewrite',body,lambda:H.request_api(body,op));rw=H.rewrite_texts(q,raw,C);rewrite_s=time.perf_counter()-t
 t=time.perf_counter();eb={'model':H.EMBED_MODEL,'input':rw['texts'],'encoding_format':'float','provider':{'order':['DeepInfra'],'allow_fallbacks':False}}
 er=call(d,'embedding',eb,lambda:H.request_api(eb,op,H.EMBED));data=er['response'];assert not data.get('provider') or data['provider']=='DeepInfra'
 vr=sorted(data['data'],key=lambda x:x['index']);assert [x['index'] for x in vr]==[0,1]
 assert all(len(x['embedding'])==1024 and all(type(z) in (float,int) and math.isfinite(z) for z in x['embedding']) for x in vr)
 v=C.mix([C.unit(x['embedding']) for x in vr],[.5,.5]);embedding_s=time.perf_counter()-t
 t=time.perf_counter();kh=hits(es('/'+KEYIDX+'/_search',o['keyword_request']));keyword_s=time.perf_counter()-t
 t=time.perf_counter();plan=dict(q['plan'],_fixed_filters=o['filters']);rr,_=engine.diverse_branch(plan,v,'vector',['doc_id','chunk_id']);sh=[dict(chunk_id=h['_id'],doc_id=h['_source']['doc_id'],score=h['_score']) for h in rr];semantic_s=time.perf_counter()-t
 t=time.perf_counter();union,_=fuse(kh,sh,'rrf');pool=union[:50];assert len(pool)==len({x['chunk_id'] for x in pool})==50;fusion_s=time.perf_counter()-t
 # Persist search ranks before the potentially slower final API call.
 retrieved={'query':q['query'],'rewrite':rw,'keyword':kh,'semantic':sh,'rrf_union':union,'rrf':pool,'filters':o['filters']}
 if (d/'retrieval.json').exists():assert read(d/'retrieval.json')==retrieved
 else:save(d/'retrieval.json',retrieved)
 t=time.perf_counter();sb={'model':RM,'query':q['query'],'documents':[M.passage(chunks[h['chunk_id']]) for h in pool],'top_n':50,'return_documents':False};sr=call(d,'rerank',sb,lambda:sf_call(sb,sf));scores=S.validate(sr['response'],50)
 ranked=sorted([dict(chunk_id=h['chunk_id'],doc_id=h['doc_id'],original_rank=i+1,score=scores[i]) for i,h in enumerate(pool)],key=lambda h:(-h['score'],h['original_rank'],h['chunk_id']));json.dumps(ranked);reranker_s=time.perf_counter()-t;total=time.perf_counter()-start
 if resumed:total=(datetime.now(timezone.utc)-datetime.fromisoformat(read(d/'question.started.json')['at'])).total_seconds()
 orders={'keyword':kh,'semantic':sh,'rrf':pool,'reranker':ranked};metrics={k:S.measure(h,labels[qid]) for k,h in orders.items()}
 assert {h['chunk_id'] for h in pool}=={h['chunk_id'] for h in ranked};assert metrics['rrf']['at']['50']==metrics['reranker']['at']['50']
 save(d/'result.json',{'id':qid,'query':q['query'],'blocked_in_service':q['blocked_in_service'],'resumed_after_interruption':resumed,'rewrite':rw,**orders,'metrics':metrics,'timings':{'rewrite':rewrite_s,'embedding':embedding_s,'keyword':keyword_s,'semantic':semantic_s,'fusion':fusion_s,'reranker':reranker_s,'total':total},'api_seconds':{'rewrite':raw['seconds'],'embedding':er['seconds'],'reranker':sr['seconds']}})
 print(json.dumps({'done':len(list((O/'queries').glob('*/result.json'))),'id':qid,'ranks':{k:m['complete_rank'] for k,m in metrics.items()},'seconds':round(total,2)},ensure_ascii=False),flush=True)

def report():
 rows=[read(O/'queries'/q['query_id']/'result.json') for q in qs];assert len(rows)==82
 agg={}
 for group,rr in [('all82',rows),('normal74',[r for r in rows if not r['blocked_in_service']]),('clarify8',[r for r in rows if r['blocked_in_service']])]:
  agg[group]={'n':len(rr),'stages':{k:{'at':{str(c):sum(r['metrics'][k]['at'][str(c)] for r in rr) for c in (10,20,50)},'missing50':sum(r['metrics'][k]['complete_rank'] is None for r in rr)} for k in ('keyword','semantic','rrf','reranker')}}
 times={k:{'mean':statistics.mean(r['timings'][k] for r in rows),'max':max(r['timings'][k] for r in rows),'p95':sorted(r['timings'][k] for r in rows)[math.ceil(.95*len(rows))-1]} for k in rows[0]['timings']}
 calls={n:[read(p) for p in (O/'queries').glob('*/'+n+'-attempt[12].json')] for n in ('rewrite','embedding','rerank')}
 statuses={n:{'attempts':len(rs),'successful':sum(not r.get('error') for r in rs),'failed':sum(bool(r.get('error')) for r in rs)} for n,rs in calls.items()}
 save(O/'summary.json',{'metrics':agg,'seconds':times,'api_calls':statuses,'rewrite_fallbacks':[{'id':r['id'],'reason':r['rewrite'].get('reason')} for r in rows if r['rewrite']['status']!='rewritten']})
 with (O/'questions.csv').open('x',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['id','question','clarification_diagnostic','keyword_rank','semantic_rank','rrf_rank','reranker_rank','total_seconds'])
  for r in rows:w.writerow([r['id'],r['query'],r['blocked_in_service']]+[r['metrics'][k]['complete_rank'] for k in ('keyword','semantic','rrf','reranker')]+[r['timings']['total']])
 after=H.index_state();assert after==read(O/'index-before.json');assert es('/'+KEYIDX+'/_settings')==read(O/'keyword-settings-before.json')
 for p,h in read(O/'manifest.json')['source_hashes'].items():assert H.sha(Path(p))==h,p
 save(O/'complete.json',{'questions':82,'model_calls':statuses,'sources_vectors_preserved':True,'completed_at':H.stamp(),'second_qwen_calls':0})
 print(json.dumps(read(O/'summary.json'),ensure_ascii=False),flush=True)

if __name__=='__main__':
 lock=(O/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 qs,olds,labels=setup()
 if sys.argv[-1]=='preflight':print('READY:82 questions;3022 unchanged chunks;fresh API calls not yet started');sys.exit()
 assert not (O/'complete.json').exists(),'already complete'
 op=H.key();sf=S.key();engine,C=H.load_engine();chunks={}
 with (H.DATA/'chunks.ndjson').open() as f:
  for line in f:chunks[json.loads(line)['create']['_id']]=json.loads(next(f))
 try:
  pending=[q for q in qs if not (O/'queries'/q['query_id']/'result.json').exists()]
  with F.ThreadPoolExecutor(max_workers=3) as executor:
   jobs={executor.submit(one,q):q['query_id'] for q in pending};errors=[]
   for job in F.as_completed(jobs):
    try:job.result()
    except Exception as e:errors.append({'id':jobs[job],'error':str(e)});print('FAILED',jobs[job],str(e),flush=True)
   if errors:
    save(O/('errors-'+str(time.time_ns())+'.json'),errors);raise RuntimeError('Incomplete questions preserved; other questions processed')
  report()
 finally:engine.pool.shutdown()
