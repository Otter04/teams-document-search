"""Loopback-only development search service; no query/click/feedback persistence."""
import hashlib,json,os,threading,time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse,StreamingResponse
from pydantic import BaseModel,Field
from typing import Literal
from engine import SearchEngine,CONFIG,http
from streaming import stream_search

ROOT=Path(__file__).resolve().parent;DATA=ROOT/'data';STATE={}
def read(name):return json.loads((DATA/name).read_text())
class Encoder:
    def __init__(self):
        import torch
        from transformers import AutoModel,AutoTokenizer
        modeldir=Path(os.environ.get('BGE_MODEL','/models/bge-m3'));manifest=read('embedding-identity.json')
        for rel,want in manifest['model_hashes'].items():
            h=hashlib.sha256()
            with (modeldir/rel).open('rb') as f:
                for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
            if h.hexdigest()!=want:raise RuntimeError('embedding model hash differs: '+rel)
        self.torch=torch;self.lock=threading.Lock();self.fingerprint=manifest['model_fingerprint']
        self.tokenizer=AutoTokenizer.from_pretrained(modeldir,local_files_only=True)
        self.model=AutoModel.from_pretrained(modeldir,local_files_only=True,torch_dtype=torch.float16,add_pooling_layer=False).cuda().eval()
        self('검색 준비 확인')
    def __call__(self,text):
        with self.lock,self.torch.inference_mode():
            encoded=self.tokenizer(text,return_tensors='pt',truncation=False)
            if encoded['input_ids'].shape[1]>8192:raise ValueError('query exceeds embedding token limit')
            out=self.model(**{k:v.cuda() for k,v in encoded.items()}).last_hidden_state[:,0].float()
            return self.torch.nn.functional.normalize(out,p=2,dim=1)[0].cpu().tolist()

@asynccontextmanager
async def lifespan(app):
    start=time.perf_counter();encoder=Encoder()
    models=http('http://127.0.0.1:8001','/v1/models');model=models['data'][0]['id']
    STATE['engine']=SearchEngine(read('documents.json'),read('blocks.json'),read('reference.json'),encoder,model=model)
    STATE['startup_seconds']=time.perf_counter()-start;STATE['model']=model;STATE['fingerprint']=encoder.fingerprint
    yield

app=FastAPI(title='RAG 문서 검색',lifespan=lifespan,docs_url=None,redoc_url=None)
class Request(BaseModel):
    query:str=Field(min_length=1,max_length=1000)
    filter_mode:Literal['A','B']|None=None
    reranker:Literal['R0','R1']|None=None
    reference_date:str|None=None
    use_llm:bool=True
@app.get('/')
def home():return FileResponse(ROOT/'index.html')
@app.get('/health')
def health():
    if 'engine' not in STATE:raise HTTPException(503,'model loading')
    return {'ready':True,'documents':len(STATE['engine'].docs),'embedding_model':'bge-m3',
      'embedding_fingerprint':STATE['fingerprint'],'query_analysis_model':STATE['model'],
      'startup_seconds':STATE['startup_seconds'],'config':CONFIG,'defaults':defaults()}
def defaults():
    path=ROOT/'selected.json'
    return json.loads(path.read_text()) if path.exists() else {'filter_mode':'B','reranker':'R0'}
@app.post('/search')
def search(req:Request):
    if not req.query.strip():raise HTTPException(422,'검색어를 입력하세요.')
    try:
        selected=defaults()
        return STATE['engine'].search(req.query,req.filter_mode or selected['filter_mode'],req.reranker or selected['reranker'],req.reference_date,req.use_llm)
    except ValueError as e:raise HTTPException(422,str(e))
    except Exception:raise HTTPException(503,'검색 서비스 연결을 확인해 주세요. 이 응답은 검색 결과 0건을 뜻하지 않습니다.')
@app.post('/search/stream')
def search_stream(req:Request):
    if not req.query.strip():raise HTTPException(422,'검색어를 입력하세요.')
    if 'engine' not in STATE:raise HTTPException(503,'검색 서버가 준비 중입니다.')
    selected=defaults()
    return StreamingResponse(stream_search(STATE['engine'],req.query,req.filter_mode or selected['filter_mode'],
      req.reranker or selected['reranker'],req.reference_date,req.use_llm),media_type='application/x-ndjson',
      headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8020,access_log=False,log_level='warning')
