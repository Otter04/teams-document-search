"""Loopback-only, offline cross-encoder. Does not retain requests or change indexes."""
import os
import threading
import torch
from fastapi import FastAPI
from pydantic import BaseModel, Field
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL = '/models/bge-reranker-v2-m3'
torch.set_num_threads(4)
tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
model = AutoModelForSequenceClassification.from_pretrained(MODEL, local_files_only=True,
             torch_dtype=torch.float16).cuda().eval()
lock = threading.Lock()
app = FastAPI(docs_url=None, redoc_url=None)

class Request(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    passages: list[str] = Field(max_length=120)

@app.get('/health')
def health():
    return {'ready': True, 'model': 'bge-reranker-v2-m3', 'max_pair_tokens': 512}

@app.post('/score')
def score(req: Request):
    scores = []
    truncated = 0
    with lock, torch.inference_mode():
        for start in range(0, len(req.passages), 8):
            pairs = [[req.query, p] for p in req.passages[start:start+8]]
            lengths = tokenizer(pairs, truncation=False, padding=False)['input_ids']
            truncated += sum(len(x) > 512 for x in lengths)
            tokens = tokenizer(pairs, padding=True, truncation=True, return_tensors='pt', max_length=512)
            logits = model(**{k: v.cuda() for k, v in tokens.items()}, return_dict=True).logits.view(-1).float()
            scores.extend(logits.cpu().tolist())
    return {**health(), 'scores': scores, 'truncated_pairs': truncated}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8093, access_log=False)
