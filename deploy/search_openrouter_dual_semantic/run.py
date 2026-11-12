"""Paired two-expression semantic search: OpenRouter Qwen + DeepInfra API bge-m3 + existing ES."""
import argparse,copy,fcntl,hashlib,importlib,json,math,os,platform,shutil,sys,time,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/search-openrouter-dual-semantic-001'
OLD=ROOT/'outputs/search-semantic-tuning-001'
DATA=ROOT/'outputs/search-token-nori-reranker-001/data'
MODEL_DIR=ROOT/'work/local-search/models/bge-m3'
SNAP=OUT/'source-at-start/search'
ES='http://127.0.0.1:19200';INDEX='rag-search-chunks-v006-token-nori'
CHAT='https://openrouter.ai/api/v1/chat/completions';MODEL='qwen/qwen3.6-35b-a3b'
EMBED='https://openrouter.ai/api/v1/embeddings';EMBED_MODEL='baai/bge-m3'
def read(p):return json.loads(p.read_text())
def stamp():return datetime.now(timezone.utc).isoformat()
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def save(p,x,exclusive=True):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x' if exclusive else 'w') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def es(path,body=None):
    assert path.endswith(('/_count','/_mapping','/_settings','/_mget'))
    req=urllib.request.Request(ES+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def index_state():
    count=es('/'+INDEX+'/_count')['count'];assert count==3022
    mapping=es('/'+INDEX+'/_mapping');settings=es('/'+INDEX+'/_settings')
    assert mapping[INDEX]['mappings']['properties']['embedding']['index_options']['type']=='flat'
    def check(batch):
        rows=es('/'+INDEX+'/_mget',{'ids':list(batch)})['docs']
        assert len(rows)==len(batch) and all(r.get('found') and r['_source']==batch[r['_id']] for r in rows)
    with (DATA/'chunks.ndjson').open() as f:
        batch={}
        for line in f:
            batch[json.loads(line)['create']['_id']]=json.loads(next(f))
            if len(batch)==100:check(batch);batch={}
        if batch:check(batch)
    return {'count':count,'mapping':mapping,'settings':settings,'all_sources_vectors_equal':True}
def prepare():
    if (OUT/'manifest.json').exists():return
    first=ROOT/'outputs/search-siliconflow-dual-semantic-001'
    m=read(first/'manifest.json')
    assert (first/'complete.json').exists()
    assert sha(ROOT/'deploy/search_siliconflow_semantic/run.py')==m['runner_sha256']
    assert all(sha(ROOT/p)==h for p,h in m['sources'].items())
    assert all(sha(first/p)==h for p,h in m['snapshots'].items())
    assert all(sha(first/p)==h for p,h in m['frozen'].items())
    state=index_state();assert state==read(first/'index-before.json')
    OUT.mkdir(parents=True,exist_ok=True)
    shutil.copytree(first/'source-at-start',OUT/'source-at-start',ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('inputs.json','labels.json','prompt.json'):shutil.copy2(first/name,OUT/name)
    save(OUT/'index-before.json',state)
    m['created_at']=stamp();m['repeat_of']=str(first.relative_to(ROOT))
    m['original_runner_sha256']=m['runner_sha256'];m['runner_sha256']=sha(Path(__file__))
    m['user_authorized_change']='Record fixed-value schema probe result without requiring it to pass. Main experiment compares request options; no claim of enforced schema. All main payloads, order, ranking and validation rules unchanged.'
    m['first_artifact_hashes']={str(p.relative_to(first)):sha(p) for p in first.rglob('*') if p.is_file() and p.suffix in ('.json','.md','.csv','.py')}
    m['model']=MODEL;m['endpoint']=CHAT
    m['generation']={'temperature':0,'max_tokens':300,'reasoning':{'effort':'none'},'stream':False,'provider':{'require_parameters':True}}
    m['embedding']={'model':EMBED_MODEL,'endpoint':EMBED,'provider':'DeepInfra','allow_fallbacks':False,'batch_size':2,'dimensions':1024,'normalization':'L2','device':'provider-managed API'}
    m['api_call_limit']=330;m['embedding_calls']=165;m['embedding_inputs']=332
    m['user_authorized_change']='User requested both Qwen rewriting and BGE-M3 embeddings via OpenRouter. Qwen routes by supported parameters as in historical OpenRouter experiment; embeddings pinned to DeepInfra. Fixed-value probe observation only, not a gate. Same 82 questions, prompt, 300 tokens, equal mix and semantic search.'
    m['scope_confirmed']='Qwen two expressions via OpenRouter -> DeepInfra bge-m3 API batch -> equal vector mix -> existing semantic ranking; excludes BM25/RRF/reranker'
    m['timing']='single stopwatch before Qwen through final ranking serialization, including both API calls, validation, mixing and ES; evidence writes after stopwatch'
    save(OUT/'manifest.json',m)
def key():
    vals={}
    for l in (ROOT/'deploy/search_openrouter/.env.local').read_text().splitlines():
        if '=' in l and not l.lstrip().startswith('#'):
            k,v=l.split('=',1);vals[k.strip()]=v.strip().strip('\"\'')
    v=os.environ.get('OPENROUTER_API_KEY') or vals.get('OPENROUTER_API_KEY');assert v;return v
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):return None
def payload(q,mode,probe=False):
    fmt={'type':'json_object'}
    if mode=='schema':
        item={'type':'string'}
        if probe:item['enum']=['sf_array_probe_20261104']
        fmt={'type':'json_schema','json_schema':{'name':'semantic_queries','strict':True,'schema':{'type':'object',
            'properties':{'queries':{'type':'array','items':item,'minItems':2,'maxItems':2}},'required':['queries'],'additionalProperties':False}}}
    return {'model':MODEL,'messages':[{'role':'system','content':read(OUT/'prompt.json')['system']},{'role':'user','content':q['query']}],
        **read(OUT/'manifest.json')['generation'],'response_format':fmt}
def request_api(body,token,endpoint=CHAT):
    assert endpoint in (CHAT,EMBED)
    assert body['model']==(MODEL if endpoint==CHAT else EMBED_MODEL)
    record={'endpoint':endpoint,'request':body,'started_at':stamp()};start=time.perf_counter()
    req=urllib.request.Request(endpoint,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=45) as r:record['http_status']=r.status;record['response']=json.load(r)
        if record['response'].get('error'):record['error']='provider_error'
    except urllib.error.HTTPError as e:record.update(error='http_'+str(e.code),http_status=e.code)
    except Exception as e:record['error']=type(e).__name__
    record['seconds']=time.perf_counter()-start
    return record
def load_engine():
    sys.path.insert(0,str(OUT/'source-at-start'));sys.path.insert(0,str(SNAP))
    E=importlib.import_module('engine');C=importlib.import_module('core')
    assert Path(E.__file__).resolve().is_relative_to(SNAP)
    E.es_filters=lambda p:copy.deepcopy(p['_fixed_filters'])
    engine=E.SearchEngine(read(DATA/'documents.json'),read(DATA/'blocks.json'),{},None,es=ES,chunk_index=INDEX)
    assert {k:E.CONFIG[k] for k in ('candidate_per_document','diversity_min_share','candidate_batch','candidate_max_rounds')}=={'candidate_per_document':3,'diversity_min_share':.5,'candidate_batch':150,'candidate_max_rounds':6}
    return engine,C
class Embedder:
    def __init__(self):
        self.token=key();self.folder=OUT/'embedding-compatibility';self.record=None
        self.environment={'model':EMBED_MODEL,'endpoint':EMBED,'requested_provider':'DeepInfra','allow_fallbacks':False,'device':'provider-managed API'}
    def encode(self,texts):
        body={'model':EMBED_MODEL,'input':texts,'encoding_format':'float','provider':{'order':['DeepInfra'],'allow_fallbacks':False}}
        raw=request_api(body,self.token,EMBED);self.record=raw
        try:
            assert not raw.get('error'),'embedding_API_failed'
            response=raw['response'];rows=response['data'];assert len(rows)==len(texts)
            assert sorted(x['index'] for x in rows)==list(range(len(texts)))
            assert not response.get('provider') or response['provider']=='DeepInfra','embedding_provider_changed'
            vectors=[x['embedding'] for x in sorted(rows,key=lambda x:x['index'])]
            assert all(len(v)==1024 and all(type(z) in (int,float) and math.isfinite(z) for z in v) for v in vectors)
            return vectors
        except Exception:
            save(self.folder/'embedding.json',raw)
            save(self.folder/'failure.json',{'stage':'embedding','error':raw.get('error') or 'invalid_embedding_response','no_retry':True})
            raise
def rewrite_texts(q,record,C):
    info={'status':'fallback','texts':[q['query'],q['query']]}
    if record.get('error'):info['reason']=record['error'];return info
    try:
        raw=record['response'];choice=raw['choices'][0];message=choice['message']
        if message.get('reasoning_content') or (raw.get('usage',{}).get('completion_tokens_details') or {}).get('reasoning_tokens'):raise RuntimeError('thinking_observed')
        if choice.get('finish_reason')!='stop':raise ValueError('truncated')
        obj=json.loads(message['content']);info['raw_output']=obj
        if not isinstance(obj,dict) or set(obj)!={'queries'} or not isinstance(obj['queries'],list) or len(obj['queries'])!=2:raise ValueError('invalid_schema')
        info['shape_valid']=all(isinstance(t,str) and bool(t.strip()) for t in obj['queries'])
        texts=[C.validate_expression(q['query'],t) for t in obj['queries']]
        info.update(status='rewritten',texts=texts)
    except (ValueError,KeyError,TypeError,IndexError,AssertionError) as e:info['reason']=str(e) or type(e).__name__
    return info

def run(limit=0):
    m=read(OUT/'manifest.json');inputs=read(OUT/'inputs.json');labels={x['query_id']:x for x in read(OUT/'labels.json')}
    assert sha(Path(__file__))==m['runner_sha256']
    for p,h in m['frozen'].items():assert sha(OUT/p)==h
    for p,h in m['snapshots'].items():assert sha(OUT/p)==h
    if (OUT/'complete.json').exists():print('Already complete; no calls');return
    print('Checking OpenRouter DeepInfra bge-m3 compatibility and existing semantic search',flush=True)
    start=time.perf_counter();embed=Embedder();engine,C=load_engine();token=key()
    try:
        # Four saved query texts, never document re-embedding. Same model fingerprints are mandatory.
        samples=[inputs[i] for i in (0,20,40,60)]
        assert not (embed.folder/'started.json').exists(),'unresolved compatibility call, no retry'
        save(embed.folder/'started.json',{'at':stamp()})
        vectors=embed.encode([q['plan']['semantic'] for q in samples])
        save(embed.folder/'embedding.json',embed.record)
        compatibility=[{'query_id':q['query_id'],'cosine':math.fsum(a*b for a,b in zip(C.unit(v),C.unit(q['vector'])))} for q,v in zip(samples,vectors)]
        assert all(r['cosine']>=.999 for r in compatibility),'existing compatibility criterion not met'
        replay=[]
        for q in inputs:
            hits,_=engine.diverse_branch(q['plan'],q['vector'],'vector',['doc_id','chunk_id'])
            ids=[h['_id'] for h in hits];old=[h['chunk_id'] for h in read(OLD/'rankings/current'/(q['query_id']+'.json'))['hits']]
            assert ids==old,('baseline_rank_changed',q['query_id'])
            replay.append(q['query_id'])
        save(OUT/'runtime.json',{'at':stamp(),'environment':embed.environment,'startup_seconds':time.perf_counter()-start,
            'compatibility':compatibility,'compatibility_threshold':.999,'threshold_origin':'existing search-all-api compatibility check',
            'baseline_exact_reproductions':len(replay),'baseline_success20':70,'baseline_reference_only':True},False)
        print('Model compatible, all82 baseline rankings reproduced',flush=True)
        probe=OUT/'array-schema-probe.json';marker=OUT/'array-schema-probe.started.json'
        if not probe.exists():
            assert not marker.exists(),'unresolved probe, no retry'
            save(marker,{'at':stamp()})
            body=payload(inputs[0],'schema',True);assert 'sf_array_probe_20261104' not in json.dumps(body['messages'])
            raw=request_api(body,token);save(probe,raw)
        raw=read(probe)
        assert not raw.get('error'),'array schema probe failed, inspect without retry'
        obj=json.loads(raw['response']['choices'][0]['message']['content'])
        probe_passed=obj=={'queries':['sf_array_probe_20261104','sf_array_probe_20261104']}
        save(OUT/'probe-observation.json',{'matches_fixed_value':probe_passed,'required_for_main':False,'reason':'User requested comparison of options independent of strict enforcement'},False)
        print('Fixed-value probe observed (not a gate): '+str(probe_passed),flush=True)
        consecutive=0;new=0
        for i,q in enumerate(inputs):
            for mode in (('json_object','schema') if i%2==0 else ('schema','json_object')):
                folder=OUT/'requests'/q['query_id']/mode;result=folder/'result.json';marker=folder/'started.json'
                if result.exists():continue
                if limit and new>=limit:return
                assert not marker.exists(),'unresolved request, no automatic retry'
                assert len(list((OUT/'requests').glob('*/*/started.json')))<164
                body=payload(q,mode);save(marker,{'at':stamp(),'query_id':q['query_id'],'mode':mode})
                embed.folder=folder
                save(folder/'embedding.started.json',{'at':stamp(),'status':'planned after Qwen'})
                started=stamp();start=time.perf_counter()
                api=request_api(body,token)
                if api.get('http_status') in (400,401,402,403,404,422):
                    save(folder/'rewrite.json',api);save(folder/'failure.json',{'error':api['error']});raise RuntimeError('Fatal API response; no retry')
                t=time.perf_counter();rewrite=rewrite_texts(q,api,C);validation_s=time.perf_counter()-t
                t=time.perf_counter();vectors=[C.unit(v) for v in embed.encode(rewrite['texts'])];embed_s=time.perf_counter()-t
                t=time.perf_counter();vector=C.mix(vectors,[.5,.5]);mix_s=time.perf_counter()-t
                t=time.perf_counter();hits,detail=engine.diverse_branch(q['plan'],vector,'vector',['doc_id','chunk_id']);search_s=time.perf_counter()-t
                ranked=[{'chunk_id':h['_id'],'doc_id':h['_source']['doc_id'],'score':h['_score']} for h in hits]
                serialized=json.dumps({'query_id':q['query_id'],'queries':rewrite['texts'],'hits':ranked},ensure_ascii=False);json.loads(serialized)
                total_s=time.perf_counter()-start
                # Gold scoring and evidence disk writes occur after the end-to-end stopwatch.
                measured=C.measure(ranked,labels[q['query_id']])
                row={'query_id':q['query_id'],'query':q['query'],'mode':mode,'started_at':started,'rewrite':rewrite,
                    'timings':{'total_seconds':total_s,'qwen_seconds':api['seconds'],'validation_seconds':validation_s,'embedding_seconds':embed_s,
                        'mix_seconds':mix_s,'search_seconds':search_s},'filters':q['plan']['_fixed_filters'],
                    'vectors':{'A':vectors[0],'B':vectors[1],'mixed':vector},'hits':ranked,'retrieval_stats':detail,'metric':measured,
                    'api_error':api.get('error'),'api_usage':api.get('response',{}).get('usage',{})}
                save(folder/'rewrite.json',api);save(folder/'embedding.json',embed.record);save(result,row);new+=1
                done=len(list((OUT/'requests').glob('*/*/result.json')))
                save(OUT/'progress.json',{'completed':done,'planned':164,'query_id':q['query_id'],'mode':mode,'at':stamp()},False)
                print(json.dumps({'completed':done,'query_id':q['query_id'],'mode':mode,'seconds':round(total_s,3),'rewrite':rewrite['status'],
                    'fallback_reason':rewrite.get('reason'),'success20':measured['at']['20'],'complete_rank':measured['complete_rank']},ensure_ascii=False),flush=True)
                consecutive=consecutive+1 if api.get('error') else 0
                if consecutive>=3:raise RuntimeError('Three consecutive API failures; inspect before continuing')
        after=index_state();assert after==read(OUT/'index-before.json');save(OUT/'index-after.json',after)
        assert all(sha(ROOT/p)==h for p,h in m['sources'].items())
        assert all(sha(OUT/p)==h for p,h in m['snapshots'].items())
        save(OUT/'complete.json',{'at':stamp(),'searches':164,'questions':82,'qwen_calls':165,'embedding_calls':165,'total_model_calls':330,'embedding_device':'DeepInfra API via OpenRouter','index_preserved':True,
            'time_scope':'OpenRouter Qwen + validation + OpenRouter DeepInfra query embedding + mix + semantic retrieval + result serialization',
            'no_keyword_search':True,'no_reranking':True,'only_openrouter':True,'no_document_reembedding':True})
    finally:engine.pool.shutdown()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run']);parser.add_argument('--limit',type=int,default=0);args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);prepare()
        if args.action=='run':run(args.limit)
