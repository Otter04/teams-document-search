"""Question/passage cross-encoder. No R1 scoring, truncation, or silent fallback."""
import copy
import hashlib
import json
import math
import os
import threading
import time


class RerankerError(RuntimeError):
    pass


def passage(source):
    # Keep the complete indexed context/body, including source-backed enrichment.
    parts = [source.get('context') or source.get('file_name', '')]
    header = source.get('table_header', '')
    if header and header not in source.get('body', '') and header not in parts[0]:
        parts.append(header)
    parts.append(source['body'])
    return '\n'.join(p for p in parts if p)


def rank_candidates(query, rows, scorer, limit=100):
    if len(rows) > limit:
        raise RerankerError('candidate_limit_exceeded')
    if not rows:
        return [], {'status': 'no_candidates', 'pairs': 0, 'r1_executed': False}
    if scorer is None:
        raise RerankerError('model_unavailable')
    passages = [passage(r['source']) for r in rows]
    try:
        output = scorer(query, passages)
    except RerankerError:
        raise
    except Exception as exc:
        raise RerankerError('model_inference_failed') from exc
    scores = output.get('scores', [])
    if len(scores) != len(rows) or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in scores):
        raise RerankerError('invalid_model_scores')
    ranked = copy.deepcopy(rows)
    for rank, (row, score) in enumerate(zip(ranked, scores), 1):
        row.update(score=float(score), model_score=float(score), rrf_rank=rank,
                   support_eligible=False, verified_condition_match=False)
    ranked.sort(key=lambda r: (-r['score'], r['rrf_rank'], r['chunk_id']))
    return ranked, {k: v for k, v in output.items() if k != 'scores'} | {
        'status': 'applied', 'model': 'bge-reranker-v2-m3', 'pairs': len(rows),
        'r1_executed': False, 'fallback': False,
        'passages_sha256': hashlib.sha256(json.dumps(passages, ensure_ascii=False).encode()).hexdigest()}


class CrossEncoderScorer:
    def __init__(self, modeldir):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        torch.set_num_threads(4)
        self.torch = torch
        self.device = os.environ.get('RAG_DEVICE','cpu')
        self.dtype = torch.float16 if self.device=='mps' else torch.float32
        self.lock = threading.Lock()
        self.batch_size = int(os.environ.get('RERANK_BATCH_SIZE', '4'))
        self.max_tokens = int(os.environ.get('RERANK_MAX_TOKENS', '2048'))
        self.timeout = float(os.environ.get('RERANK_TIMEOUT', '120'))
        self.tokenizer = AutoTokenizer.from_pretrained(modeldir, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            modeldir, local_files_only=True, torch_dtype=self.dtype).to(self.device).eval()
        supported = min(self.tokenizer.model_max_length,
                        self.model.config.max_position_embeddings - self.model.config.pad_token_id - 1)
        if not 1 <= self.max_tokens <= supported or self.batch_size < 1 or self.timeout <= 0:
            raise RerankerError('invalid_model_settings')
        hashes = {}
        for name in ['config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json',
                     'special_tokens_map.json', 'sentencepiece.bpe.model']:
            h = hashlib.sha256()
            with (modeldir / name).open('rb') as stream:
                for b in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    h.update(b)
            hashes[name] = h.hexdigest()
        self.identity = {'name': 'bge-reranker-v2-m3', 'files': hashes, 'supported_pair_tokens': supported,
                         'max_pair_tokens': self.max_tokens, 'batch_size': self.batch_size,
                         'device':self.device, 'dtype': str(self.dtype), 'truncation': False, 'timeout_seconds': self.timeout,
                         'timeout_policy': 'deadline checked before/after each GPU batch; no partial results'}
        self('검색 준비 확인', ['리랭커 모델 준비 확인'])

    def __call__(self, query, passages):
        start = time.perf_counter()
        if not self.lock.acquire(timeout=self.timeout):
            raise RerankerError('model_queue_timeout')
        try:
            pairs = [[query, text] for text in passages]
            encoded = self.tokenizer(pairs, truncation=False, padding=False)
            lengths = [len(x) for x in encoded['input_ids']]
            if any(n > self.max_tokens for n in lengths):
                raise RerankerError('pair_token_limit_exceeded')
            scores = []
            order = sorted(range(len(pairs)), key=lambda i: lengths[i])
            by_index = {}
            with self.torch.inference_mode():
                for start_index in range(0, len(order), self.batch_size):
                    if time.perf_counter() - start > self.timeout:
                        raise RerankerError('model_timeout')
                    ids = order[start_index:start_index + self.batch_size]
                    batch = self.tokenizer.pad(
                        [{k: v[i] for k, v in encoded.items()} for i in ids],
                        padding=True, return_tensors='pt')
                    logits = self.model(**{k: v.to(self.device) for k, v in batch.items()}).logits.view(-1).float()
                    values = logits.cpu().tolist()
                    if len(values) != len(ids) or not all(math.isfinite(v) for v in values):
                        raise RerankerError('invalid_model_output')
                    by_index.update(zip(ids, values))
                    if time.perf_counter() - start > self.timeout:
                        raise RerankerError('model_timeout')
            scores = [by_index[i] for i in range(len(pairs))]
            return {'scores': scores, 'pair_token_counts': lengths, 'max_pair_tokens': max(lengths, default=0),
                    'truncated_pairs': 0, 'model_seconds': time.perf_counter() - start,
                    'batch_size': self.batch_size}
        finally:
            self.lock.release()
