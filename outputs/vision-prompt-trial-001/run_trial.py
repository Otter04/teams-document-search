"""14-call prompt-only trial. Frozen inputs, no retries or provider fallback."""
import argparse
import concurrent.futures
import copy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
import urllib.error

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'outputs/rag-vision-v1'))
spec=importlib.util.spec_from_file_location('frozen_runner',ROOT/'outputs/rag-vision-v1/run.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
spec=importlib.util.spec_from_file_location('quality3',ROOT/'outputs/rag-vision-v3/quality.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
KEYS={
 'D-001-vision-slide2':'text/node repetition',
 'D-001-vision-slide4':'literal placed in claims and repeated',
 'D-001-vision-slide5':'graph/edge repetition and invalid boxes',
 'D-001-vision-slide7':'whole table repeated',
 'D-044-vision-page2':'read status contradiction and table structure',
 'H-020-vision-page1':'repeated cells, omission, truncated JSON',
 'D-020-vision-slide1':'both-model clean-gate control',
}
BASE=ROOT/'outputs/vision-comparison-run-001'
def load(p):return json.loads(Path(p).read_text())

def prepare():
    original=load(BASE/'manifest.json');m=copy.deepcopy(original)
    m['items']=[i for i in m['items'] if old.task_id(i) in KEYS]
    assert len(m['items'])==7
    m['prompt']=(ROOT/'outputs/vision-prompt-proposal-001/proposed-system-prompt.txt').read_text()
    m['version']='vision-prompt-2.0.0'
    m['trial']=dict(type='prompt_only',selection_reasons=KEYS,max_calls=14,automatic_retries=0,
        original_manifest_sha256=old.digest(BASE/'manifest.json'),
        runner_sha256=old.digest(Path(__file__)),quality_code_sha256=old.digest(ROOT/'outputs/rag-vision-v3/quality.py'))
    checks=[]
    for item in m['items']:
        for model in m['models']:
            previous=old.make_payload(item,model,original);new=old.make_payload(item,model,m)
            info=load(BASE/model.split('/')[1]/'units'/old.task_id(item)/'request-info.json')
            assert old.object_hash(previous)==info['request_sha256']
            changed=copy.deepcopy(new);changed['messages'][0]['content']=previous['messages'][0]['content']
            assert changed==previous
            checks.append(dict(model=model,key=old.task_id(item),only_system_prompt_changed=True))
    frozen=set(BASE.rglob('*.json'))|set(BASE.rglob('*.jsonl'))
    for folder in ['rag-vision-v1','rag-vision-v2','rag-vision-v3','vision-source-review-001','vision-validation-run-002','vision-validation-run-003','vision-prompt-proposal-001']:
        frozen.update(p for p in (ROOT/'outputs'/folder).rglob('*') if p.is_file())
    frozen.update(Path(i['image_path']) for i in m['items'])
    frozen.update(Path(i['parsed']) for i in m['inputs'])
    frozen.update(Path(d['path']) for d in original['documents'])
    integrity={str(p):old.digest(p) for p in sorted(frozen)}
    path=OUT/'manifest.json'
    if path.exists():assert load(path)==m,'trial frozen; use a new directory'
    else:
        old.write(path,m);old.write(OUT/'input-verification.json',checks)
        old.write(OUT/'preserved-input-hashes.json',integrity)
    return m

def execute(m):
    key=old.read_key()  # credential read only inside authorized execute; never logged
    stop=threading.Event()
    def worker(model):
        for item in m['items']:
            if stop.is_set():return
            name=old.task_id(item);target=OUT/model.split('/')[1]/'units'/name
            target.mkdir(parents=True,exist_ok=True)
            response_path=target/'response.json';marker=target/'inflight.json'
            if (target/'result.json').exists():continue
            payload=old.make_payload(item,model,m)
            if response_path.exists():
                info=load(target/'request-info.json');assert info['request_sha256']==old.object_hash(payload)
                response=load(response_path)
            else:
                if marker.exists():raise RuntimeError('ambiguous prior call; do not retry '+name)
                info=dict(key=name,requested_model=model,request_sha256=old.object_hash(payload),
                          image_sha256=item['image_sha256'],started_at=old.now(),prompt_version=m['version'])
                old.write(target/'request-info.json',info)
                with marker.open('x') as f:f.write(old.canonical(info))
                started=time.monotonic()
                try:response=old.api_call(payload,key)
                except urllib.error.HTTPError as e:
                    stop.set();old.write(target/'result.json',dict(status='http_error',http_status=e.code,retry=False))
                    marker.unlink();print(model,name,'HTTP',e.code,flush=True);return
                except Exception as e:
                    stop.set();old.write(target/'network-status.json',dict(status='ambiguous',error_type=type(e).__name__,retry=False))
                    print(model,name,'AMBIGUOUS',type(e).__name__,flush=True);return
                old.write(response_path,response)
                old.write(target/'timing.json',dict(elapsed_seconds=time.monotonic()-started,finished_at=old.now()))
                marker.unlink()
            assessment=q.validate_response(response,item,model)
            data=assessment.pop('data')
            if assessment['transfer_allowed']:
                src=next(s for s in m['inputs'] if s['corpus']==item['corpus'])
                native=next(d for d in old.lines(src['parsed']) if d['doc_id']==item['doc_id'])
                converted,_=q.convert_checked(native,item,response,model)
                added=set(next(u for u in converted['coverage']['units'] if u['unit_id']==item['unit_id'])['block_ids'])
                runs={b['run_ref'] for b in converted['blocks'] if b['block_id'] in added}
                for run in converted['runs']:
                    if run['run_id'] in runs:run['prompt_version']=m['version']
                assert not q.base.common.check(converted)
                old.write(target/'extraction.json',data);old.write(target/'common-block-document.json',converted)
            usage=response.get('usage') or {}
            old.write(target/'result.json',dict(**assessment,usage=usage,cost_usd=usage.get('cost'),
                reported_model=response.get('model'),provider=response.get('provider'),response_id=response.get('id')))
            print(model,name,assessment['decision'],'cost',usage.get('cost'),flush=True)
            if response.get('error') or response.get('model')!=model or response.get('provider')!='DeepInfra':
                stop.set();return
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,m) for m in m['models']]
        for f in futures:f.result()
    changed=[p for p,h in load(OUT/'preserved-input-hashes.json').items() if old.digest(p)!=h]
    assert not changed
    responses=list(OUT.glob('*/units/*/response.json'))
    old.write(OUT/'execution-summary.json',dict(saved_responses=len(responses),planned_calls=14,
        inflight_remaining=[str(p) for p in OUT.glob('*/units/*/inflight.json')],
        changed_previous_files=changed,stopped=stop.is_set(),
        reported_cost_usd=sum((load(p).get('usage') or {}).get('cost',0) or 0 for p in responses)))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','execute']);args=parser.parse_args()
    manifest=prepare()
    if args.mode=='execute':execute(manifest)
    else:print('Prepared 7 images x 2 models; only system prompt differs; no API calls.')
