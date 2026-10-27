"""Send frozen enrichment requests once. No retries, repair, or fallback."""
import concurrent.futures
import hashlib
import json
import os
import sys
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREP = ROOT / 'outputs/enrichment-eval-prep-001'
MODELS = ['qwen/qwen3.6-35b-a3b', 'qwen/qwen3-vl-30b-a3b-instruct']
STOP = threading.Event()

def read(p): return json.loads(p.read_text())
def canonical(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def write(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(p)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RuntimeError('redirect rejected')

def main():
    frozen = read(PREP / 'freeze.json')
    for name, h in frozen['files'].items():
        assert hashlib.sha256((PREP / name).read_bytes()).hexdigest() == h, name
    for name, h in frozen['external_dependencies'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == h, name
    rows = read(PREP / 'requests/index.json')['requests']
    assert len(rows) == 40
    for r in rows: assert digest(read(PREP / r['path'])) == r['request_sha256']
    opener = urllib.request.build_opener(NoRedirect)
    # Public, non-billable capability checks before accessing the credential.
    endpoints = {}
    for model in MODELS:
        with opener.open('https://openrouter.ai/api/v1/models/' + model + '/endpoints', timeout=60) as response:
            data = json.load(response)
        endpoints[model] = data
        matches = [e for e in data['data']['endpoints'] if e.get('tag') == 'deepinfra/fp8']
        assert matches, 'Frozen FP8 endpoint unavailable: ' + model
        e = matches[0]
        body = read(PREP / next(r['path'] for r in rows if r['model'] == model))
        params = set(e.get('supported_parameters', []))
        needed = set(body) - {'model', 'messages', 'provider'}
        assert needed <= params, 'Unsupported frozen parameters: ' + str(needed - params)
        assert e['context_length'] >= 32768
        if e.get('max_completion_tokens') is not None: assert e['max_completion_tokens'] >= 16384
    write(HERE / 'endpoint-preflight.json', endpoints)
    print('Public endpoint capabilities verified for both frozen requests', flush=True)
    key = os.getenv('OPENROUTER_API_KEY', '').strip()
    if not key:
        p = ROOT / 'work/credentials/openrouter.key'
        assert not p.is_symlink() and p.is_file() and not (p.stat().st_mode & 0o077)
        key = p.read_text().strip()
    assert key.startswith('sk-or-') and not any(c.isspace() for c in key)

    def worker(model, assigned=None):
        for r in (assigned if assigned is not None else [r for r in rows if r['model'] == model]):
            if STOP.is_set(): break
            slug = model.split('/')[-1]
            out = HERE / 'responses' / slug / (r['doc_id'] + '.json')
            marker = HERE / 'attempts' / slug / (r['doc_id'] + '.json')
            if out.exists():
                assert read(out)['request_sha256'] == r['request_sha256']
                continue
            marker.parent.mkdir(parents=True, exist_ok=True)
            # Any existing attempt, including an ambiguous timeout, prohibits resend.
            with marker.open('x') as f:
                json.dump({'model': model, 'doc_id': r['doc_id'], 'request_sha256': r['request_sha256'], 'started_unix': time.time()}, f)
            body = read(PREP / r['path'])
            start = time.monotonic()
            try:
                req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',
                    data=canonical(body).encode(), headers={'Authorization': 'Bearer ' + key,
                    'Content-Type': 'application/json', 'X-OpenRouter-Title': 'RAG enrichment comparison'}, method='POST')
                with opener.open(req, timeout=600) as response:
                    raw = response.read().decode().replace(key, '[REDACTED]')
                result = json.loads(raw)
                elapsed = round((time.monotonic() - start) * 1000)
                write(out, {'model': model, 'doc_id': r['doc_id'], 'request_sha256': r['request_sha256'], 'response': result, 'elapsed_ms': elapsed})
                assert not result.get('error'), 'API response error'
                assert result.get('model') == model, 'Reported model mismatch'
                assert result.get('provider') == 'DeepInfra', 'Reported provider mismatch'
                print(json.dumps({'model': slug, 'doc_id': r['doc_id'], 'elapsed_ms': elapsed, 'finish_reason': result.get('choices', [{}])[0].get('finish_reason'), 'cost': result.get('usage', {}).get('cost')}, ensure_ascii=False), flush=True)
            except Exception as exc:
                STOP.set()
                detail = {'exception_type': type(exc).__name__, 'http_status': getattr(exc, 'code', None), 'automatic_retry': False}
                if isinstance(exc, urllib.error.HTTPError):
                    detail['response_body'] = exc.read().decode(errors='replace').replace(key, '[REDACTED]')
                write(HERE / 'errors' / slug / (r['doc_id'] + '.json'), detail)
                print(json.dumps({'stopped': True, 'doc_id': r['doc_id'], **{k:v for k,v in detail.items() if k!='response_body'}}), flush=True)
                break
    if '--tail-vl' in sys.argv:
        # Independent late documents only; the original serial worker will reuse
        # their saved envelopes. Exclusive attempt files prevent duplicate sends.
        tail = [r for r in rows if r['model'] == MODELS[1]][7:]
        assert all(not (HERE/'attempts'/MODELS[1].split('/')[-1]/(r['doc_id']+'.json')).exists() for r in tail)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for f in [pool.submit(worker, MODELS[1], [r]) for r in tail]: f.result()
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for f in [pool.submit(worker, m) for m in MODELS]: f.result()
    print(json.dumps({'responses_saved': len(list((HERE / 'responses').rglob('*.json'))), 'stopped_on_error': STOP.is_set()}), flush=True)

if __name__ == '__main__': main()
