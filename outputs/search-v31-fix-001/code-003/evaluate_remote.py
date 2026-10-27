"""Fixed development evaluation only. Runtime service has no query logging."""
import argparse,datetime,hashlib,json,time,urllib.request,urllib.error
from pathlib import Path

def request(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:8020'+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
def request_stream(body):
    start=time.perf_counter();events=[];result=None
    req=urllib.request.Request('http://127.0.0.1:8020/search/stream',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=45) as r:
        for line in r:
            if not line.strip():continue
            event=json.loads(line);event['arrival_seconds']=time.perf_counter()-start
            if event['stage']=='error':raise RuntimeError(event['data']['message'])
            if event['stage']=='complete':result=event['data'];events.append({'stage':'complete','arrival_seconds':event['arrival_seconds']})
            else:events.append(event)
    if result is None:raise RuntimeError('stream ended without completion')
    return result,events
def main():
    a=argparse.ArgumentParser();a.add_argument('--run',required=True);a.add_argument('--variants',nargs='+',default=['A-R0','B-R0']);a.add_argument('--stream',action='store_true');args=a.parse_args()
    root=Path(__file__).resolve().parent;out=root/'evaluation'/args.run
    out.mkdir(parents=True,exist_ok=False)
    queries=[json.loads(s) for s in (root/'evaluation-inputs.jsonl').read_text().splitlines()]
    freeze=json.loads((root/'data/search-freeze.json').read_text())
    start=time.perf_counter();health=request('/health')
    (out/'freeze.json').write_text(json.dumps({'implementation':freeze,'health':health,'variants':args.variants,
      'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'query_cache':False,'labels_read':False,'stream':args.stream},ensure_ascii=False,indent=2))
    count=0;errors=0
    with (out/'responses.jsonl').open('w') as f:
        for q in queries:
            for variant in args.variants:
                mode,ranker=variant.split('-');t=time.perf_counter()
                row={'query_id':q['query_id'],'query':q['query'],'variant':variant}
                try:
                    body={'query':q['query'],'filter_mode':mode,'reranker':ranker,'reference_date':'2026-10-14'}
                    if args.stream:row['response'],row['stage_events']=request_stream(body)
                    else:row['response']=request('/search',body)
                except Exception as e:
                    row['error']=str(e);errors+=1
                    if isinstance(e,urllib.error.HTTPError):row['error_detail']=e.read().decode()
                row['client_seconds']=time.perf_counter()-t;f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();count+=1
                progress={'completed':count,'total':len(queries)*len(args.variants),'errors':errors,'elapsed_seconds':time.perf_counter()-start}
                (out/'progress.json').write_text(json.dumps(progress))
            if count%10==0:print(json.dumps(progress),flush=True)
    (out/'complete.json').write_text(json.dumps(progress));print(json.dumps(progress),flush=True)
if __name__=='__main__':main()
