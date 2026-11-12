"""SiliconFlow Qwen3-Reranker-8B on immutable AB semantic candidates."""
import fcntl,hashlib,json,math,os,sys,time,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timezone
R=Path(__file__).resolve().parents[2];O=R/'outputs/search-rerank-ab-001'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def stamp():return datetime.now(timezone.utc).isoformat()
def key():
 d={}
 for l in (R/'deploy/search_openrouter/.env.local').read_text().splitlines():
  if '=' in l and not l.lstrip().startswith('#'):k,v=l.split('=',1);d[k.strip()]=v.strip().strip('\"\'')
 k=os.environ.get('SILICONFLOW_API_KEY') or d.get('SILICONFLOW_API_KEY');assert k;return k
def measure(hits,label):
 ranks={h['chunk_id']:i for i,h in enumerate(hits,1)};ar=[min([ranks[c] for c in g if c in ranks],default=None) for card in label['cards'] for g in card['anchor_groups']]
 last=max(ar) if all(x is not None for x in ar) else None
 return {'anchor_ranks':ar,'complete_rank':last,'at':{str(k):last is not None and last<=k for k in [5,10,20,40,50]}}
def validate(raw,n):
 assert isinstance(raw,dict) and not raw.get('error'),'provider_error'
 rows=raw.get('results');assert isinstance(rows,list) and len(rows)==n,'missing_candidate_scores'
 out=[None]*n
 for x in rows:
  i=x['index'];s=x['relevance_score'];assert type(i)==int and 0<=i<n and out[i] is None,'invalid_index'
  assert type(s) in (int,float) and math.isfinite(s),'invalid_score';out[i]=s
 return out
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**k):return None

def main():
 m=read(O/'siliconflow-manifest.json');assert m['endpoint']=='https://api.siliconflow.com/v1/rerank' and m['model']=='Qwen/Qwen3-Reranker-8B';assert sha(Path(__file__))==m['runner_sha256'];assert sha(O/'inputs.json')==m['inputs_sha256'];assert sha(O/'labels.json')==m['labels_sha256']
 for p,h in m['source_hashes'].items():assert sha(R/p)==h,p
 assert not (O/'complete.json').exists(),'Already complete'
 labels={x['query_id']:x for x in read(O/'labels.json')};token=key();inputs=read(O/'inputs.json')
 for q in inputs:
  folder=O/'requests'/q['query_id']
  if (folder/'result.json').exists():continue
  assert not (folder/'started.json').exists(),'Unresolved request: inspect, no automatic retry'
  body={'model':m['model'],'query':q['query'],'documents':[h['passage'] for h in q['candidates']],'top_n':50,'return_documents':False}
  save(folder/'request.json',body);save(folder/'started.json',{'at':stamp()})
  raw={'endpoint':m['endpoint'],'started_at':stamp()};t=time.perf_counter()
  req=urllib.request.Request(m['endpoint'],data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
  try:
   with urllib.request.build_opener(NoRedirect).open(req,timeout=120) as res:raw['status']=res.status;raw['response']=json.load(res)
  except urllib.error.HTTPError as e:
   raw.update(status=e.code,error='http_'+str(e.code))
   # Keep only the structured provider error, never headers or credentials.
   try:raw['provider_error']=json.loads(e.read().decode()).get('error')
   except Exception:pass
  except Exception as e:raw['error']=type(e).__name__
  api_s=time.perf_counter()-t;raw['api_seconds']=api_s
  if raw.get('error'):
   save(folder/'response.json',raw);save(O/'blocked.json',{'query_id':q['query_id'],'error':raw['error'],'finished_questions':len(list((O/'requests').glob('*/result.json'))),'no_retry':True});print(json.dumps({'blocked':q['query_id'],'error':raw['error']},ensure_ascii=False),flush=True);return
  try:
   scores=validate(raw['response'],50)
   reranked=sorted([{'chunk_id':c['chunk_id'],'doc_id':c['doc_id'],'score':scores[i],'original_rank':i+1} for i,c in enumerate(q['candidates'])],key=lambda x:(-x['score'],x['original_rank'],x['chunk_id']))
   json.loads(json.dumps(reranked));total=time.perf_counter()-t
   before=measure(q['candidates'],labels[q['query_id']]);after=measure(reranked,labels[q['query_id']]);assert before['at']['50']==after['at']['50'];assert {x['chunk_id'] for x in reranked}=={x['chunk_id'] for x in q['candidates']}
   row={'query_id':q['query_id'],'query':q['query'],'before':before,'after':after,'hits':reranked,'api_seconds':api_s,'total_seconds':total,'provider':raw['response'].get('provider'),'usage':raw['response'].get('usage')}
  except Exception as e:save(folder/'response.json',raw);raise
  save(folder/'response.json',raw);save(folder/'result.json',row)
  print(json.dumps({'completed':len(list((O/'requests').glob('*/result.json'))),'id':q['query_id'],'before':before['complete_rank'],'after':after['complete_rank'],'seconds':round(total,3)},ensure_ascii=False),flush=True)
 for p,h in m['source_hashes'].items():assert sha(R/p)==h,p
 save(O/'complete.json',{'questions':82,'rerank_calls':82,'chat_calls':0,'embedding_calls':0,'search_calls':0,'model':m['model'],'candidate_sets_preserved':True,'at':stamp()})
if __name__=='__main__':
 with (O/'run.lock').open('a') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
