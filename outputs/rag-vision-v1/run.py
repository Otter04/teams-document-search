#!/usr/bin/env python3
"""Frozen 132-page vision comparison. prepare is offline; execute needs a key.

Model inputs contain source images/native context only. Evaluation is a separate
program. Completed requests are never repeated automatically; ambiguous network
outcomes retain an inflight marker for operator inspection.
"""
import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import urllib.error
import urllib.request

from contract import SCHEMA, PROMPT, check_wire, convert, common

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MODELS = ['qwen/qwen3.6-35b-a3b', 'qwen/qwen3-vl-30b-a3b-instruct']
INPUTS = [('original', ROOT/'outputs/parsing-run-003'), ('additional', ROOT/'outputs/additional-parsing-run-001')]
URL = 'https://openrouter.ai/api/v1/chat/completions'
KEY_FILE = ROOT/'work/credentials/openrouter.key'
DEFAULT_RUN = ROOT/'outputs/vision-comparison-run-001'

def now(): return datetime.now(timezone.utc).isoformat()
def canonical(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def object_hash(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def load(path): return json.loads(Path(path).read_text())
def lines(path): return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
def write(path,x):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    tmp.replace(path)
def write_lines(path,rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(''.join(canonical(x)+'\n' for x in rows));tmp.replace(path)
def task_id(item): return item['doc_id']+'-'+item['unit_id'].replace(':','-')

def key_status():
    return {'environment_present':bool(os.getenv('OPENROUTER_API_KEY')), 'local_file_present':KEY_FILE.is_file()}

def read_key():
    key=os.getenv('OPENROUTER_API_KEY','').strip()
    if not key and KEY_FILE.is_file():
        if KEY_FILE.is_symlink() or KEY_FILE.stat().st_mode & 0o077:
            raise ValueError('key file must be a regular private file (0600)')
        key=KEY_FILE.read_text().strip()
    if not key: raise ValueError('OpenRouter key missing; run setup_key.py in your terminal')
    if not key.startswith('sk-or-') or any(c.isspace() for c in key): raise ValueError('invalid OpenRouter key format')
    return key

def roots():
    original=[p/'files' for p in Path('/Users/kangdongkyoon/Downloads').iterdir()
              if unicodedata.normalize('NFC',p.name)=='RAG_예비데이터셋(클로드)' and (p/'files').is_dir()]
    if len(original)!=1: raise ValueError('original source folder unavailable or ambiguous')
    return {'original':original[0], 'additional':ROOT/'outputs/additional-dataset-v1/files'}

def build_manifest():
    manifest={'version':'vision-1.0.0','models':MODELS,'provider':'deepinfra/fp8','quantization':'fp8',
              'max_tokens':16384,'temperature':0,'seed':42,'reasoning_qwen36':False,
              'prompt':PROMPT,'response_schema':SCHEMA,'inputs':[],'items':[],'documents':[],
              'code_hashes':{p.name:digest(p) for p in [HERE/'contract.py',HERE/'run.py']},
              'common_schema_sha256':digest(HERE.parent/'common-block-design/common-block.schema.json'),
              'common_validator_sha256':digest(HERE.parent/'common-block-design/validate_design.py')}
    source_roots=roots()
    for corpus,run in INPUTS:
        parsed=run/'parsed.jsonl'; queue=run/'vision-pending.jsonl'
        manifest['inputs'].append(dict(corpus=corpus,parsed=str(parsed),parsed_sha256=digest(parsed),
                                       queue=str(queue),queue_sha256=digest(queue)))
        docs={d['doc_id']:d for d in lines(parsed)}
        mapping={unicodedata.normalize('NFC',str(p.relative_to(source_roots[corpus]))):p
                 for p in source_roots[corpus].rglob('*') if p.is_file()}
        for d in docs.values():
            errors=common.check(d)
            if errors: raise ValueError(f'invalid native document: {d["doc_id"]}')
            source=mapping[d['source']['relative_path']]
            if digest(source)!=d['source']['sha256']: raise ValueError('source hash changed')
            manifest['documents'].append(dict(doc_id=d['doc_id'],corpus=corpus,path=str(source),
                sha256=d['source']['sha256'],mtime_ns=source.stat().st_mtime_ns))
        for q in lines(queue):
            d=docs[q['doc_id']]
            a=next(x for x in d['assets'] if x['asset_id']==q['asset_id'])
            path=(run/q['asset_path']).resolve()
            if not path.is_relative_to(run.resolve()): raise ValueError('asset outside source run')
            if digest(path)!=a['sha256'] or q['source_sha256']!=d['source']['sha256']: raise ValueError('input hash mismatch')
            if a['loc']!=q['loc']: raise ValueError('asset locator mismatch')
            ids={b['block_id'] for b in d['blocks']}
            if not set(q['context_block_ids'])<=ids: raise ValueError('invalid context references')
            context=[]
            for b in d['blocks']:
                if b['block_id'] in q['context_block_ids']:
                    context.append({k:b[k] for k in ('block_id','type','text','loc','cells') if k in b})
            manifest['items'].append({**q,'corpus':corpus,'image_path':str(path),'image_sha256':a['sha256'],
                'width':a['width'],'height':a['height'],'native_context':context})
    if len({task_id(x) for x in manifest['items']})!=len(manifest['items']): raise ValueError('duplicate unit')
    return manifest

def prepare(out):
    manifest=build_manifest()
    if (out/'manifest.json').exists():
        if load(out/'manifest.json')!=manifest: raise ValueError('frozen manifest differs; use a new run directory')
    else:
        out.mkdir(parents=True,exist_ok=True)
        write(out/'manifest.json',manifest)
        write(out/'status.json',dict(state='prepared_waiting_for_key',model_calls=0,created_at=now()))
    return manifest

def verify_manifest(manifest):
    if build_manifest()!=manifest: raise ValueError('source, configuration or code changed since preparation')

def make_payload(item,model,manifest):
    image=Path(item['image_path']).read_bytes()
    if hashlib.sha256(image).hexdigest()!=item['image_sha256']: raise ValueError('image changed before call')
    context={'source_location':item['loc'],'native_context':item['native_context']}
    data={'model':model,'stream':False,'temperature':manifest['temperature'],'seed':manifest['seed'],
        'max_tokens':manifest['max_tokens'],
        'provider':{'only':['deepinfra/fp8'],'allow_fallbacks':False,'require_parameters':True,'quantizations':['fp8']},
        'messages':[{'role':'system','content':manifest['prompt']},
                    {'role':'user','content':[{'type':'text','text':canonical(context)},
                     {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image).decode()}}]}],
        'response_format':{'type':'json_schema','json_schema':{'name':'document_vision','strict':True,'schema':manifest['response_schema']}}}
    if model==MODELS[0]: data['reasoning']={'enabled':False}
    return data

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise RuntimeError('unexpected redirect rejected')

def api_call(payload,key):
    request=urllib.request.Request(URL,data=canonical(payload).encode(),headers={
        'Authorization':'Bearer '+key,'Content-Type':'application/json','X-OpenRouter-Title':'RAG vision comparison'},method='POST')
    opener=urllib.request.build_opener(NoRedirect)
    with opener.open(request,timeout=600) as response:
        raw=response.read().decode()
    # Do not persist a credential even if a gateway unexpectedly echoes it.
    return json.loads(raw.replace(key,'[REDACTED]'))

def parse_response(response):
    if response.get('error'): raise ValueError('API response contains error')
    if response.get('provider')!='DeepInfra': raise ValueError('unexpected or unreported provider')
    choices=response.get('choices') or []
    if len(choices)!=1 or choices[0].get('finish_reason')!='stop': raise ValueError('incomplete response (not stop)')
    content=choices[0]['message'].get('content')
    if not isinstance(content,str) or not content.strip(): raise ValueError('empty model content')
    def bad_constant(x): raise ValueError('non-finite JSON number')
    data=json.loads(content,parse_constant=bad_constant)
    errors=check_wire(data)
    if errors: raise ValueError('; '.join(errors[:8]))
    return data

def process_item(out,item,model,manifest,key):
    base=out/model.split('/')[1]/'units'/task_id(item)
    base.mkdir(parents=True,exist_ok=True)
    result_path=base/'result.json'; raw_path=base/'response.json'; inflight=base/'inflight.json'
    if result_path.exists(): return load(result_path)
    if inflight.exists() and not raw_path.exists():
        raise RuntimeError(f'ambiguous previous request: {task_id(item)}; no automatic duplicate request')
    payload=make_payload(item,model,manifest)
    meta=dict(doc_id=item['doc_id'],unit_id=item['unit_id'],corpus=item['corpus'],requested_model=model,
              requested_provider='deepinfra/fp8',requested_quantization='fp8',request_sha256=object_hash(payload),
              image_sha256=item['image_sha256'],started_at=now())
    if not raw_path.exists():
        # Only safe request metadata is written; never headers/key or base64 image copies.
        write(base/'request-info.json',meta)
        with inflight.open('x') as f: f.write(canonical(meta))
        start=time.monotonic()
        try:
            response=api_call(payload,key)
        except urllib.error.HTTPError as e:
            # No raw gateway error body is logged.
            result={**meta,'status':'http_error','http_status':e.code,'elapsed_seconds':time.monotonic()-start,
                    'cost_usd':None,'usage':None,'error':'HTTP request rejected; inspect status before retry'}
            write(result_path,result);inflight.unlink()
            if e.code in (400,401,402,403,404,422,429):
                raise RuntimeError(f'OpenRouter HTTP {e.code}; batch stopped') from None
            return result
        except Exception as e:
            write(base/'network-status.json',dict(status='ambiguous_network_outcome',error_type=type(e).__name__,at=now()))
            raise RuntimeError('network outcome unknown; stopped without automatic retry') from None
        write(raw_path,response)
        write(base/'timing.json',dict(elapsed_seconds=time.monotonic()-start,finished_at=now()))
        inflight.unlink()
    response=load(raw_path)
    meta=load(base/'request-info.json')
    if meta['request_sha256']!=object_hash(payload): raise ValueError('saved response belongs to a different request')
    usage=response.get('usage') or {}
    result={**meta,**(load(base/'timing.json') if (base/'timing.json').exists() else {}),
            'response_id':response.get('id'),'reported_model':response.get('model'),'provider':response.get('provider'),
            'usage':usage,'cost_usd':usage.get('cost'),'status':'invalid','errors':[]}
    try:
        if response.get('model') != model:
            raise ValueError('reported model does not match requested model')
        reasoning=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
        if model==MODELS[0] and reasoning and reasoning>0:
            raise ValueError('reasoning tokens generated despite disabled reasoning; comparison condition differs')
        data=parse_response(response)
        # Conversion verifies the full common-block schema and reference integrity.
        source=next(x for x in manifest['inputs'] if x['corpus']==item['corpus'])
        native=next(d for d in lines(source['parsed']) if d['doc_id']==item['doc_id'])
        converted=convert(native,item,data,model)
        write(base/'extraction.json',data)
        write(base/'common-block-document.json',converted)
        result.update(status='valid',reported_completeness=data['status'],quality_status='needs_source_review')
    except (ValueError,KeyError,TypeError,IndexError) as e:
        result['errors']=[str(e)[:1500]]
    write(result_path,result)
    return result

def summarize(out,manifest):
    summaries=[]
    for model in MODELS:
        mdir=out/model.split('/')[1]
        results=[load(p) for p in sorted((mdir/'units').glob('*/result.json'))]
        byid={(r['doc_id'],r['unit_id']):r for r in results}
        for corpus,source in INPUTS:
            docs={d['doc_id']:d for d in lines(source/'parsed.jsonl')}
            native=copy.deepcopy(docs)
            for item in manifest['items']:
                if item['corpus']!=corpus: continue
                result=byid.get((item['doc_id'],item['unit_id']))
                if result and result['status']=='valid':
                    data=load(mdir/'units'/task_id(item)/'extraction.json')
                    docs[item['doc_id']]=convert(docs[item['doc_id']],item,data,model)
            target=mdir/corpus
            for d in docs.values():
                if [b for b in d['blocks'] if b['run_ref']=='native']!=native[d['doc_id']]['blocks']:
                    raise ValueError('native blocks changed')
                for a in d['assets']:
                    a['path']=os.path.relpath(source/a['path'],target)
                errors=common.check(d)
                if errors: raise ValueError('assembled document invalid: '+str(errors[:3]))
            write_lines(target/'parsed.candidate.jsonl',docs.values())
        costs=[r['cost_usd'] for r in results if isinstance(r.get('cost_usd'),(int,float))]
        summary=dict(model=model,target_units=len(manifest['items']),attempted_units=len(results),
          valid_units=sum(r['status']=='valid' for r in results),
          complete_self_report_units=sum(r.get('reported_completeness')=='complete' for r in results),
          failed_units=sum(r['status']!='valid' for r in results),unattempted_units=len(manifest['items'])-len(results),
          known_cost_usd=sum(costs),unknown_cost_units=sum(r.get('cost_usd') is None for r in results),
          quality_status='not_yet_source_reviewed',native_blocks_preserved=True,
          input_tokens=sum((r.get('usage') or {}).get('prompt_tokens',0) for r in results),
          output_tokens=sum((r.get('usage') or {}).get('completion_tokens',0) for r in results))
        summaries.append(summary)
    write(out/'summary.json',{'models':summaries,'note':'Candidate outputs only; schema validity is not visual accuracy. No production index changed.'})
    return summaries

def execute(out,limit=None):
    manifest=load(out/'manifest.json');verify_manifest(manifest);key=read_key()
    write(out/'status.json',dict(state='running',started_at=now()))
    # Interleave models per image so an interruption does not exhaust only one candidate.
    count=0
    try:
        for item in manifest['items']:
            for model in MODELS:
                existing=out/model.split('/')[1]/'units'/task_id(item)/'result.json'
                if existing.exists(): continue
                if limit is not None and count>=limit: return
                result=process_item(out,item,model,manifest,key);count+=1
                print(canonical({'model':model,'unit':task_id(item),'status':result['status'],'cost_usd':result['cost_usd']}),flush=True)
                if result['status']!='valid':
                    raise RuntimeError('first invalid extraction stopped batch; inspect before spending on remaining pages')
    finally:
        summaries=summarize(out,manifest)
        complete=all(s['valid_units']==s['target_units'] for s in summaries)
        write(out/'status.json',dict(state='api_processing_finished' if complete else 'incomplete',updated_at=now(),
                                   quality_evaluation_complete=False))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','status','execute','assemble'])
    p.add_argument('--output',type=Path,default=DEFAULT_RUN)
    p.add_argument('--limit',type=int,help='Maximum new API calls in this invocation; not a page count')
    args=p.parse_args();out=args.output.resolve()
    if args.action=='status':
        print(canonical({'credentials':key_status(),'run_status':load(out/'status.json') if (out/'status.json').exists() else None}));return
    if args.action=='prepare':
        m=prepare(out)
        print(canonical({'prepared_units':len(m['items']),'affected_documents':len({i['doc_id'] for i in m['items']}),
                         'models':MODELS,'planned_calls':len(m['items'])*len(MODELS),'model_calls':0}));return
    if args.action=='assemble':
        print(canonical(summarize(out,load(out/'manifest.json'))));return
    execute(out,args.limit)

if __name__=='__main__':
    try: main()
    except (ValueError,RuntimeError) as e: raise SystemExit(str(e))
