"""Offline bge-m3 dense vectors. Runs in an existing local image on Orin."""
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
import transformers
from transformers import AutoTokenizer,AutoModel

OUT=Path(sys.argv[1]);MODEL=Path(sys.argv[2])
INPUT_KIND=sys.argv[3] if len(sys.argv)>3 else 'documents'
assert INPUT_KIND in ('documents','queries')
def read(p):return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,ensure_ascii=False,indent=2));tmp.replace(p)
def main():
    lock=(OUT/'embedding.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    start=time.monotonic()
    def state(status,**kw):write(OUT/'embedding-progress.json',{'status':status,'elapsed_seconds':round(time.monotonic()-start,2),**kw})
    state('checking_model_files')
    rows=[json.loads(x) for x in (OUT/'embedding-inputs.jsonl').read_text().splitlines()]
    assert len({r['chunk_id'] for r in rows})==len(rows)
    pooling=read(MODEL/'1_Pooling/config.json');assert pooling['pooling_mode_cls_token'] and not pooling['pooling_mode_mean_tokens']
    files=['config.json','tokenizer.json','tokenizer_config.json','sentencepiece.bpe.model','pytorch_model.bin','1_Pooling/config.json']
    hashes={f:sha(MODEL/f) for f in files}
    fingerprint=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    tokenizer=AutoTokenizer.from_pretrained(str(MODEL),local_files_only=True)
    token_counts=[len(tokenizer(r['text'],truncation=False)['input_ids']) for r in rows]
    assert all(0<n<=8192 for n in token_counts),'No input truncation allowed'
    write(OUT/'token-budget.json',{'counts':token_counts,'max_tokens':max(token_counts),'model_limit':8192,'truncated_inputs':0,'input_file_sha256':sha(OUT/'embedding-inputs.jsonl')})
    state('loading_model',planned=len(rows))
    torch.set_num_threads(4)
    assert torch.cuda.is_available(),'Expected Orin CUDA'
    model,loading=AutoModel.from_pretrained(str(MODEL),local_files_only=True,torch_dtype=torch.float16,add_pooling_layer=False,output_loading_info=True)
    assert not loading['missing_keys'] and not loading.get('mismatched_keys'),loading
    model=model.to('cuda').eval()
    cache=OUT/'embedding-cache';cache.mkdir(exist_ok=True)
    vectors=np.empty((len(rows),1024),dtype=np.float32);pending=[];hits=0
    keys=[]
    for i,r in enumerate(rows):
        key=hashlib.sha256((fingerprint+'\ncls-l2-fp16-v1\n'+r['text']).encode()).hexdigest();keys.append(key)
        p=cache/(key+'.npy')
        if p.exists():vectors[i]=np.load(p,allow_pickle=False);hits+=1
        else:pending.append(i)
    pending.sort(key=lambda i:token_counts[i]);done=hits;batch_size=4
    def encode(indices):
        data=tokenizer([rows[i]['text'] for i in indices],padding=True,truncation=False,return_tensors='pt').to('cuda')
        with torch.inference_mode():
            output=model(**data).last_hidden_state[:,0].float()
            return torch.nn.functional.normalize(output,p=2,dim=1).cpu().numpy()
    try:
        for pos in range(0,len(pending),batch_size):
            ids=pending[pos:pos+batch_size];out=encode(ids)
            assert np.isfinite(out).all() and out.shape==(len(ids),1024)
            for i,v in zip(ids,out):
                vectors[i]=v;p=cache/(keys[i]+'.npy')
                with p.with_suffix('.tmp').open('wb') as f:np.save(f,v,allow_pickle=False)
                p.with_suffix('.tmp').replace(p)
            done+=len(ids);state('embedding',completed=done,planned=len(rows),cache_hits=hits)
            if pos%80==0:print('Embedded',done,'/',len(rows),flush=True)
        norms=np.linalg.norm(vectors,axis=1)
        assert np.isfinite(vectors).all() and np.allclose(norms,1,atol=1e-5)
        # Repeat the first real input to check deterministic representation, not retrieval.
        repeated=encode([0])[0];repeat_cos=float(vectors[0]@repeated);assert repeat_cos>.999
        with (OUT/'vectors.npy.tmp').open('wb') as f:np.save(f,vectors,allow_pickle=False)
        (OUT/'vectors.npy.tmp').replace(OUT/'vectors.npy')
        write(OUT/'embedding-manifest.json',{'model':'bge-m3','source_model_directory':'/media/sdcard/models/bge-m3','model_hashes':hashes,'model_fingerprint':fingerprint,'device':torch.cuda.get_device_name(0),'torch':torch.__version__,'transformers':transformers.__version__,'dtype':'float16 model / float32 normalized vectors','pooling':'CLS','normalization':'L2','dimension':1024,'vectors':len(rows),'token_max':max(token_counts),'token_limit':8192,'truncated_inputs':0,'batch_size':batch_size,'input_sha256':sha(OUT/'embedding-inputs.jsonl'),'vectors_sha256':sha(OUT/'vectors.npy'),'cache_hits':hits,'loading_info':loading,'repeat_cosine':repeat_cos,'elapsed_seconds':time.monotonic()-start,'input_kind':INPUT_KIND,'query_embeddings_generated':len(rows) if INPUT_KIND=='queries' else 0,'new_model_downloads':0})
        state('complete',completed=len(rows),planned=len(rows),cache_hits=hits)
    except BaseException as e:
        state('stopped_error',completed=done,planned=len(rows),error=str(e));raise
if __name__=='__main__':main()
