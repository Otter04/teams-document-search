"""Serial, resumable local-only evaluation dispatch. No secrets or paid APIs."""
import argparse
from datetime import datetime, timezone
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from transport_common import OUT, MODEL, read, write, canonical, digest

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('Redirect refused: local-only transport')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int);ap.add_argument('--base-url');ap.add_argument('--server-container');args=ap.parse_args()
    manifest=read(OUT/'manifest.json');url=args.base_url or manifest['endpoint']
    assert urllib.parse.urlsplit(url).hostname == '127.0.0.1'
    write(OUT/'dispatch-location.json',{'base_url':url,'execution_host':'Orin' if args.base_url else 'Mac','transport':'loopback' if args.base_url else 'SSH tunnel','automatic_retries':0})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def state(status, **extra):
        done=list((OUT/'results').glob('*/*/envelope.json'))
        record={'status':status,'checked_at':datetime.now(timezone.utc).isoformat(),
                'saved':len(done),'planned':len(manifest['jobs']),
                'counts':{k:sum(p.parent.parent.name==k for p in done) for k in ['vision','enrichment']},**extra}
        write(OUT/'run-status.json',record);write(OUT/'progress.json',record)
    state('waiting_for_server')
    def call(path, body=None, timeout=7200):
        req=urllib.request.Request(url+path,data=canonical(body).encode() if body is not None else None,
                                   headers={'Content-Type':'application/json'})
        with opener.open(req,timeout=timeout) as res:return res.status,json.loads(res.read().decode())
    # Readiness check does not invoke model generation.
    for attempt in range(120):
        if args.server_container:
            server=json.loads(subprocess.check_output(['docker','inspect',args.server_container]))[0]['State']
            if not server['Running']:
                state('blocked_server_initialization',server_state=server)
                raise RuntimeError('Server exited before readiness')
        try:
            status,models=call('/v1/models',timeout=10)
            entry=next(x for x in models['data'] if x['id']==MODEL)
            assert entry['max_model_len']==49152, entry
            write(OUT/'server-models.json',models)
            state('ready')
            break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt==119:raise
            time.sleep(10)
    completed=0
    for job in manifest['jobs']:
        kind,name=job['kind'],job['id'];folder=OUT/'results'/kind/name
        response_path=folder/'envelope.json';marker=folder/'attempt.json'
        if response_path.exists():
            assert read(response_path)['request_sha256']==job['request_sha256']
            continue
        if marker.exists():raise RuntimeError('Ambiguous prior attempt; inspect before resend: '+name)
        body=read(OUT/job['path']);assert digest(body)==job['request_sha256']
        token_body={'model':MODEL,'messages':body['messages'],'add_generation_prompt':True,'chat_template_kwargs':body['chat_template_kwargs']}
        _,tok=call('/tokenize',token_body,timeout=180)
        write(folder/'token-count.json',{'input_tokens':tok['count'],'max_tokens':body['max_tokens'],'context':entry['max_model_len']})
        if tok['count']+body['max_tokens']>entry['max_model_len']:
            write(folder/'preflight-error.json',{'error':'context_budget_exceeded','input':tok['count']})
            raise RuntimeError('Input not truncated; context too small: '+name)
        with marker.open('x') as f:
            json.dump({'started_at':datetime.now(timezone.utc).isoformat(),'request_sha256':job['request_sha256'],'automatic_retry':False},f)
        print(json.dumps({'started':name,'kind':kind,'input_tokens':tok['count']},ensure_ascii=False),flush=True)
        state('generating',current={'id':name,'kind':kind,'started_at':datetime.now(timezone.utc).isoformat()})
        start=time.monotonic()
        try:
            status,response=call('/v1/chat/completions',body)
        except urllib.error.HTTPError as e:
            status=e.code
            raw=e.read().decode(errors='replace')
            try:response=json.loads(raw)
            except ValueError:response={'error':raw}
        except Exception as e:
            write(folder/'ambiguous-error.json',{'error':str(e),'type':type(e).__name__,'elapsed_seconds':time.monotonic()-start})
            raise
        elapsed_ms=round((time.monotonic()-start)*1000)
        env={'model':MODEL,'provider':'local-vllm','quantization':'awq-4bit','kind':kind,'doc_id':job['doc_id'],
             'id':name,'request_sha256':job['request_sha256'],'baseline_request_sha256':job['baseline_request_sha256'],
             'messages_sha256':job['messages_sha256'],'response':response,'http_status':status,'elapsed_ms':elapsed_ms}
        write(response_path,env)
        write(folder/'completed.json',{'finished_at':datetime.now(timezone.utc).isoformat(),'response_sha256':digest(env)})
        usage=response.get('usage') or {};choice=(response.get('choices') or [{}])[0]
        summary={'completed':name,'kind':kind,'http':status,'elapsed_seconds':elapsed_ms/1000,
                 'output_tokens':usage.get('completion_tokens'),'finish_reason':choice.get('finish_reason')}
        print(json.dumps(summary,ensure_ascii=False),flush=True)
        state('running',latest=summary)
        if status>=500:raise RuntimeError('Server error; stopping dispatch')
        if status==200 and response.get('model')!=MODEL:raise RuntimeError('Unexpected model')
        completed+=1
        if args.limit and completed>=args.limit:break
    print('Dispatch finished',flush=True)
    state('responses_collected' if len(list((OUT/'results').glob('*/*/envelope.json')))==len(manifest['jobs']) else 'limited_run_finished')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        current=read(OUT/'run-status.json') if (OUT/'run-status.json').exists() else {}
        if current.get('status')!='blocked_server_initialization':current['status']='blocked_dispatch_error'
        current.update(error=str(exc),error_type=type(exc).__name__,automatic_retry=False)
        write(OUT/'run-status.json',current);write(OUT/'progress.json',current)
        raise
