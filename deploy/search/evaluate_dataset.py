"""Run a versioned, answer-free query file against the current API; no tuning."""
import argparse,datetime,hashlib,json,time,urllib.request,urllib.error
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--inputs',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--base-url',default='http://127.0.0.1:18020')
    ap.add_argument('--no-llm',action='store_true',help='Disable query analysis and source review; keep retrieval and stored enrichments unchanged')
    ap.add_argument('--request-timeout',type=float,default=45)
    args=ap.parse_args();use_llm=not args.no_llm
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'responses.jsonl').exists():raise SystemExit('Refusing to overwrite an existing run')
    raw=args.inputs.read_bytes();inputs=[json.loads(s) for s in raw.decode().splitlines() if s.strip()]
    assert all(set(q)=={'query_id','query','base_date'} for q in inputs),'Only question inputs belong in the runner'
    def request(path,body=None):
        req=urllib.request.Request(args.base_url+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=args.request_timeout) as r:return json.load(r)
    health=request('/health');assert health['ready']
    config={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'health':health,'inputs_sha256':hashlib.sha256(raw).hexdigest(),
      'endpoint':args.base_url+'/search','labels_sent':False,'filter_mode':'B','reranker':'R1','use_llm':use_llm,
      'code_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}}
    (args.output/'freeze.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    start=time.perf_counter();errors=0
    with (args.output/'responses.jsonl').open('w') as f:
        for count,q in enumerate(inputs,1):
            row=dict(q);t=time.perf_counter()
            try:row['response']=request('/search',{'query':q['query'],'reference_date':q['base_date'],'filter_mode':'B','reranker':'R1','use_llm':use_llm})
            except Exception as e:
                errors+=1;row['error']=str(e)
                if isinstance(e,urllib.error.HTTPError):row['error_detail']=e.read().decode()
            row['client_seconds']=time.perf_counter()-t;f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
            progress={'completed':count,'total':len(inputs),'errors':errors,'elapsed_seconds':time.perf_counter()-start}
            (args.output/'progress.json').write_text(json.dumps(progress)+'\n')
            if count%10==0:print(json.dumps(progress),flush=True)
    after=request('/health');assert health['config']==after['config'],'Server configuration changed during evaluation'
    for key in ['indices','documents','embedding_fingerprint']:
        assert health.get(key)==after.get(key),'Server corpus or embedding changed during evaluation: '+key
    (args.output/'complete.json').write_text(json.dumps(progress)+'\n');print(json.dumps(progress),flush=True)

if __name__=='__main__':main()
