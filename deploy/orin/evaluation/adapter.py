"""Local transport adapter; frozen inputs, gold, validators and responses stay intact."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'outputs/orin-evaluation-run-001'
VISION = ROOT / 'outputs/vision-comparison-run-001'
PREP = ROOT / 'outputs/enrichment-eval-prep-001'
BASE_ENRICH = ROOT / 'outputs/enrichment-comparison-run-001'
MODEL = 'qwen3.6-35b-a3b'
OLD_MODEL = 'qwen/qwen3.6-35b-a3b'

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

quality = module('orin_quality3', ROOT / 'outputs/rag-vision-v3/quality.py')
saved_contract = sys.modules.get('contract')
sys.modules['contract'] = quality.base
vision_runner = module('orin_original_vision_runner', ROOT / 'outputs/rag-vision-v1/run.py')
if saved_contract is None:
    del sys.modules['contract']
else:
    sys.modules['contract'] = saved_contract
ec = module('orin_enrichment_contract', PREP / 'contract.py')
review = module('orin_source_review', ROOT / 'outputs/vision-source-review-001/review.py')

def read(path): return json.loads(Path(path).read_text())
def canonical(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def filehash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, x):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)
def key(item): return vision_runner.task_id(item)

def local_request(original):
    body = copy.deepcopy(original)
    body.pop('provider', None)
    reasoning = body.pop('reasoning', None)
    if reasoning is not None and reasoning != {'enabled': False}:
        raise ValueError('Unexpected reasoning setting')
    body['model'] = MODEL
    body['chat_template_kwargs'] = {'enable_thinking': False}
    # Sampling, prompt, schema and output budget are unchanged.
    return body

def assess_vision(response, item, model=MODEL, provider='local-vllm'):
    errors = []; data = None
    if response.get('model') != model: errors.append('unexpected model')
    if provider == 'local-vllm':
        if response.get('provider') not in (None, 'local-vllm'): errors.append('unexpected provider')
    elif response.get('provider') != provider: errors.append('unexpected provider')
    if response.get('error'): errors.append('response contains error')
    reasoning = ((response.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens')
    if isinstance(reasoning, (int, float)) and reasoning > 0:
        errors.append('reasoning tokens generated despite frozen disabled reasoning')
    choices = response.get('choices') or []
    if len(choices) != 1: errors.append('expected one choice')
    else:
        if choices[0].get('finish_reason') != 'stop': errors.append('incomplete response (not stop)')
        try: data = ec.loads(choices[0].get('message', {}).get('content'))
        except (ValueError, TypeError) as e: errors.append('invalid JSON: ' + str(e)[:200])
    if data is None: errors.append('missing or null extraction object')
    schema_errors = list(quality.base.VALIDATOR.iter_errors(data)) if data is not None else []
    if data is not None: errors += quality.base.check_wire(data)
    issues = quality.check_quality(data, item.get('native_context', [])) if data is not None and not schema_errors else []
    blocked = bool(errors) or any(i['blocks_transfer'] for i in issues)
    decision = 'reject' if blocked else 'candidate_with_warnings' if issues else 'candidate'
    return {'decision': decision, 'transfer_allowed': not blocked, 'baseline_errors': errors, 'issues': issues,
            'review_required': bool(issues), 'meaning_accuracy_verified': False, 'data': data}

def convert_vision(doc, item, response):
    result = assess_vision(response, item)
    if not result['transfer_allowed']: raise ValueError('Rejected vision response')
    converted = quality.base.convert(doc, item, result['data'], MODEL, provider='local-vllm', quantization='awq-4bit')
    if result['issues']:
        unit = next(u for u in converted['coverage']['units'] if u['unit_id'] == item['unit_id'])
        codes = sorted({i['code'] for i in result['issues']})
        unit.update(status='pending', reason=quality.VERSION + ': transferred with warnings; source review required: ' + ', '.join(codes))
        tags = [quality.VERSION + ':' + c for c in codes]
        for block in converted['blocks']:
            if block['block_id'] in unit['block_ids']: block['warnings'].extend(tags)
        converted['warnings'].extend(item['unit_id'] + ': ' + t for t in tags)
    assert not quality.base.common.check(converted)
    assert review.wire_payload(result['data']) == review.common_payload(converted, item)
    return converted, result

def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT/'manifest.json').exists(): return read(OUT/'manifest.json')
    frozen = read(PREP/'freeze.json')
    for name, h in frozen['files'].items(): assert filehash(PREP/name) == h, name
    for name, h in frozen['external_dependencies'].items(): assert filehash(name) == h, name
    m = read(VISION/'manifest.json'); jobs = []
    for item in m['items']:
        name = key(item)
        original = vision_runner.make_payload(item, OLD_MODEL, m)
        info = read(VISION/MODEL/'units'/name/'request-info.json')
        assert digest(original) == info['request_sha256'], name
        body = local_request(original)
        path = Path('requests/vision')/(name+'.json')
        write(OUT/path, body)
        jobs.append({'kind':'vision','id':name,'doc_id':item['doc_id'],'path':str(path),
                     'request_sha256':digest(body),'baseline_request_sha256':digest(original),'messages_sha256':digest(body['messages'])})
    for row in read(PREP/'requests/index.json')['requests']:
        if row['model'] != OLD_MODEL: continue
        original = read(PREP/row['path']); assert digest(original) == row['request_sha256']
        body = local_request(original); path = Path('requests/enrichment')/(row['doc_id']+'.json')
        write(OUT/path, body)
        jobs.append({'kind':'enrichment','id':row['doc_id'],'doc_id':row['doc_id'],'path':str(path),
                     'request_sha256':digest(body),'baseline_request_sha256':digest(original),'messages_sha256':digest(body['messages'])})
    # Initial cases cover scan, diagram and native context; order does not alter inputs.
    first = ['D-044-vision-page2','D-069-vision-page1','D-001-vision-slide1','D-001-vision-slide7','H-020-vision-page1','H-021','H-006']
    jobs.sort(key=lambda j: (first.index(j['id']) if j['id'] in first else len(first), j['kind'], j['id']))
    preserve = set()
    for folder in [VISION, PREP, BASE_ENRICH, ROOT/'outputs/vision-source-review-001', ROOT/'outputs/vision-validation-run-003', ROOT/'outputs/rag-vision-v1', ROOT/'outputs/rag-vision-v2', ROOT/'outputs/rag-vision-v3']:
        preserve.update(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    preserve.update(Path(i['image_path']) for i in m['items'])
    preserve.update(Path(i['parsed']) for i in m['inputs'])
    write(OUT/'preserved-hashes.json', {str(p):filehash(p) for p in sorted(preserve)})
    manifest = {'model':MODEL,'endpoint':'http://127.0.0.1:18001','provider':'local-vllm','quantization':'awq-4bit',
                'planned':{'vision':132,'enrichment':20},'jobs':jobs,
                'same_messages_and_schema':True,'original_max_tokens':16384,'automatic_retries':0,
                'changes':['model API alias','provider routing removed','reasoning=false translated to chat_template_kwargs.enable_thinking=false','FP8 cloud to local AWQ4'],
                'note':'Existing original full-set vision prompt retained; revised seven-case trial is not mixed in. Enrichment uses the same reviewed common inputs, not new vision outputs, to isolate enrichment capability.'}
    write(OUT/'manifest.json',manifest)
    return manifest

def parity_check():
    manifest = read(VISION/'manifest.json'); count=0
    for item in manifest['items']:
        response = read(VISION/MODEL/'units'/key(item)/'response.json')
        old = quality.validate_response(response,item,OLD_MODEL)
        new = assess_vision(response,item,OLD_MODEL,'DeepInfra')
        assert old['decision'] == new['decision'], key(item)
        assert old['issues'] == new['issues'], key(item)
        assert bool(old['baseline_errors']) == bool(new['baseline_errors']), key(item)
        count += 1
    write(OUT/'adapter-parity.json',{'saved_openrouter_responses':count,'v3_decisions_and_issues_identical':True,'new_model_calls':0})
    print('Adapter parity passed:',count,flush=True)

if __name__ == '__main__':
    print('Prepared jobs:',len(prepare()['jobs']),flush=True)
    parity_check()
