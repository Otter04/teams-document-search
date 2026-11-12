"""One final same-payload transport retry for the remaining finished failed request."""
import run as E
import json,time,urllib.request,urllib.error
if __name__=='__main__':
 E.qs,E.olds,E.labels=E.setup();qid='EX100-I033';d=E.O/'queries'/qid
 if (d/'result.json').exists():raise SystemExit('already complete')
 assert all((d/f'rerank-attempt{i}.json').exists() and E.read(d/f'rerank-attempt{i}.json').get('error') for i in (1,2,3))
 E.op=E.H.key();E.sf=E.S.key();E.engine,E.C=E.H.load_engine();E.chunks={}
 with (E.H.DATA/'chunks.ndjson').open() as f:
  for line in f:E.chunks[json.loads(line)['create']['_id']]=json.loads(next(f))
 original=E.call
 def call(folder,name,body,fn):
  if name!='rerank':return original(folder,name,body,fn)
  out=folder/'rerank-attempt4.json';start=folder/'rerank-attempt4.started.json'
  if out.exists():raw=E.read(out)
  else:
   assert not start.exists(),'unresolved final attempt'
   E.save(start,{'at':E.H.stamp(),'request':body,'transport_timeout_seconds':300});raw={'endpoint':E.URL,'request':body,'started_at':E.H.stamp(),'transport_timeout_seconds':300};t=time.perf_counter()
   req=urllib.request.Request(E.URL,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+E.sf})
   try:
    with urllib.request.build_opener(E.S.NoRedirect).open(req,timeout=300) as r:raw.update(http_status=r.status,response=json.load(r))
    if raw['response'].get('error'):raw['error']='provider_error'
   except urllib.error.HTTPError as e:raw.update(error='http_'+str(e.code),http_status=e.code)
   except Exception as e:raw['error']=type(e).__name__
   raw['seconds']=time.perf_counter()-t;E.save(out,raw)
  if raw.get('error'):raise RuntimeError(raw['error'])
  return raw
 E.call=call
 try:E.one(next(q for q in E.qs if q['query_id']==qid))
 finally:E.engine.pool.shutdown()
