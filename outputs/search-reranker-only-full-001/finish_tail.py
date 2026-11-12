"""Finish untouched tail and bounded retry of fully finished transport failures."""
import run as E
import concurrent.futures as F,json,time
if __name__=='__main__':
 E.qs,E.olds,E.labels=E.setup();E.op=E.H.key();E.sf=E.S.key();E.engine,E.C=E.H.load_engine();E.chunks={}
 with (E.H.DATA/'chunks.ndjson').open() as f:
  for line in f:E.chunks[json.loads(line)['create']['_id']]=json.loads(next(f))
 untouched=[q for q in E.qs if not (E.O/'queries'/q['query_id']/'question.started.json').exists()]
 failed=[]
 for q in E.qs:
  d=E.O/'queries'/q['query_id']
  if (d/'result.json').exists():continue
  if all((d/f'rerank-attempt{i}.json').exists() and E.read(d/f'rerank-attempt{i}.json').get('error') for i in (1,2)):failed.append(q)
 selected=failed+untouched[-18:]
 E.save(E.O/'tail-execution.json',{'questions':[q['query_id'] for q in selected],'completed_transport_failures':[q['query_id'] for q in failed],'extra_workers':2,'max_combined_workers':5,'reason':'User requested quickest completion without delay analysis; all request settings unchanged. Existing exclusive per-stage request markers prevent duplicate calls.'})
 original=E.call
 def call(d,name,body,fn):
  if name=='rerank' and all((d/f'rerank-attempt{i}.json').exists() and E.read(d/f'rerank-attempt{i}.json').get('error') for i in (1,2)):
   out=d/'rerank-attempt3.json';start=d/'rerank-attempt3.started.json'
   if out.exists():raw=E.read(out)
   else:
    assert not start.exists(),'unresolved third attempt';E.save(start,{'at':E.H.stamp(),'request':body});raw=fn();E.save(out,raw)
   if raw.get('error'):raise RuntimeError((d.name,name,raw['error']))
   return raw
  return original(d,name,body,fn)
 E.call=call
 try:
  with F.ThreadPoolExecutor(max_workers=2) as executor:
   jobs={executor.submit(E.one,q):q['query_id'] for q in selected}
   for job in F.as_completed(jobs):
    try:job.result()
    except Exception as e:print('TAIL_FAILED',jobs[job],str(e),flush=True)
 finally:E.engine.pool.shutdown()
