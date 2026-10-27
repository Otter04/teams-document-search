"""Optional source-based cross-encoder ranking for queries without precise anchors.

No synonym dictionaries, question IDs, gold labels or document IDs are used here.
Explicit filters and date/version selection remain the engine's responsibility.
"""
import collections
import json
import math
import time
import urllib.request


def eligible(plan):
    return not (plan.get('requires_clarification') or plan.get('filters')
                or plan.get('identifiers') or plan.get('sort')
                or plan.get('requested_version') or plan.get('requested_version_order')
                or plan.get('content_requirement') or plan.get('concepts')
                or plan.get('boost')
                or set(plan.get('conditions', {})) - {'document_type'})


def select_rows(rows, per_document=2, limit=120):
    """One passage per document first, then a second; long logs cannot fill the pool."""
    counts = collections.Counter()
    rounds = [[] for _ in range(per_document)]
    for row in rows:
        did = row['source']['doc_id']
        n = counts[did]
        if n < per_document:
            rounds[n].append(row)
            counts[did] += 1
    return [r for group in rounds for r in group][:limit]


class SemanticClient:
    def __init__(self, url='http://127.0.0.1:8093', timeout=90, blocks=None):
        self.url = url
        self.timeout = timeout
        self.blocks = blocks or {}

    def __call__(self, query, rows):
        selected = select_rows(rows)
        if not selected:
            return [], {'status': 'empty', 'pairs': 0}
        passages = []
        for r in selected:
            s = r['source']
            source = '\n'.join(b.get('text','') for b in self.blocks.get(s['doc_id'],{}).values())
            # Small source documents can be read whole: a table row's question
            # and answer must not be mistaken for a document that only asks it.
            body = source if source.strip() and len(source)<=1500 else s['body']
            r['semantic_scope']='whole_short_document' if body==source else 'indexed_passage'
            passages.append(s['file_name'] + '\n' + s.get('table_header', '') + '\n' + body)
        start = time.perf_counter()
        req = urllib.request.Request(self.url + '/score',
              data=json.dumps({'query': query, 'passages': passages}).encode(),
              headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            result = json.load(response)
        scores = result['scores']
        if len(scores) != len(selected) or any(not isinstance(s, (int, float)) or not math.isfinite(s) for s in scores):
            raise ValueError('invalid_semantic_scores')
        for r, score in zip(selected, scores):
            r['previous_score'] = r.get('score')
            r['score'] = score
            r['semantic_score'] = score
            r['verified_condition_match'] = False
            r['support_eligible'] = False
        selected.sort(key=lambda r: (-r['score'], r['chunk_id']))
        return selected, {'status': 'applied', 'model': result['model'], 'pairs': len(scores),
                          'seconds': time.perf_counter() - start,
                          'truncated_pairs': result.get('truncated_pairs', 0),
                          'max_pair_tokens': result.get('max_pair_tokens')}
