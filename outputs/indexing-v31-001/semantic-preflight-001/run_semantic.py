"""Resumable local-only serial generation on Orin; no implicit retries."""
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
from datetime import datetime,timezone

OUT=Path(sys.argv[1])
def read(p):return json.loads(p.read_text())
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(x,ensure_ascii=False,indent=2));temp.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k):raise RuntimeError('Redirect refused')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def call(path,body=None):
    req=urllib.request.Request('http://127.0.0.1:8001'+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=1800) as r:return json.loads(r.read())
def main():
    lock=(OUT/'semantic.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    manifest=read(OUT/'manifest.json');start=time.monotonic();models=call('/v1/models')
    assert any(x['id']==manifest['model'] for x in models['data'])
    write(OUT/'server-models.json',models)
    def state(status,current=None):write(OUT/'semantic-progress.json',{'status':status,'saved':len(list((OUT/'responses').glob('*.json'))),'planned':len(manifest['jobs']),'current':current,'elapsed_seconds':round(time.monotonic()-start,2),'checked_at':datetime.now(timezone.utc).isoformat()})
    try:
        for j in manifest['jobs']:
            did=j['doc_id'];dest=OUT/'responses'/f'{did}.json';attempt=OUT/'attempts'/f'{did}.json'
            if dest.exists():
                assert read(dest)['request_sha256']==j['request_sha256'];continue
            if attempt.exists():raise RuntimeError('Unfinished attempt requires inspection: '+did)
            p=OUT/j['request'];assert sha(p)==j['request_sha256'];body=read(p)
            tok=call('/tokenize',{'model':body['model'],'messages':body['messages'],'add_generation_prompt':True,'chat_template_kwargs':body['chat_template_kwargs']})
            assert tok['count']+body['max_tokens']<=49152
            write(attempt,{'started_at':datetime.now(timezone.utc).isoformat(),'request_sha256':sha(p),'input_tokens':tok['count']})
            state('generating',did);t=time.monotonic();response=call('/v1/chat/completions',body)
            write(dest,{'doc_id':did,'response':response,'request_sha256':sha(p),'elapsed_seconds':time.monotonic()-t,'provider':'Orin local vLLM','quantization':'AWQ-4bit','http_status':200})
            print(did, response.get('usage'), 'seconds',round(time.monotonic()-t,2),flush=True)
            assert response['choices'][0]['finish_reason']=='stop',did+' incomplete'
            state('running')
        state('responses_complete')
    except BaseException as e:
        state('stopped_error',str(e));raise
if __name__=='__main__':main()
