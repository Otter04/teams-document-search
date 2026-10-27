"""Score frozen paraphrases from saved responses; never calls the model or search API."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cases = json.loads((ROOT / 'cases.json').read_text())
responses = [json.loads(s) for s in (ROOT / 'run-001/responses.jsonl').read_text().splitlines()]
assert len(cases) == len(responses) == 18
rows = []
for c, r in zip(cases, responses):
    assert c['query_id'] == r['query_id'] and c['query'] == r['query']
    resp = r.get('response', {})
    plan = resp.get('query_plan', {})
    diag = resp.get('diagnostics', {})
    target = c['expected_doc_id']
    ids = [x['doc_id'] for x in resp.get('results', [])][:5]
    rank = ids.index(target) + 1 if target in ids else None
    branches = {}
    for branch in ['bm25', 'vector', 'rrf_top30', 'rerank_candidates']:
        hits = diag.get(branch, [])
        branches[branch + '_first_chunk_rank'] = next((i for i, x in enumerate(hits, 1) if x.get('doc_id') == target), None)
    if r.get('error'):
        reason = 'HTTP/실행 오류'
    elif rank:
        reason = '상위5 성공'
    elif not branches['bm25_first_chunk_rank'] and not branches['vector_first_chunk_rank']:
        reason = '두 검색 후보에서 정답 누락'
    elif not branches['rerank_candidates_first_chunk_rank']:
        reason = '검색 후보에는 있으나 순위 조정 후보에서 누락'
    else:
        reason = '검색·순위 조정 후보에는 있으나 최종 상위5 탈락'
    rows.append({**c, 'rank': rank, 'top1': rank == 1, 'top5': rank is not None,
                 'top5_doc_ids': ids, 'top5_titles': [x.get('title') for x in resp.get('results', [])][:5],
                 **branches, 'expansions': plan.get('lexical_expansions', []),
                 'preferred_doc_ids': plan.get('preferred_doc_ids', []),
                 'used_llm': plan.get('used_llm', False), 'llm': plan.get('llm', {}),
                 'conditions': plan.get('conditions'), 'filters': plan.get('filters'),
                 'seconds': r['client_seconds'], 'diagnosis': reason})

def score(rs):
    return {'n': len(rs), 'top1': sum(x['top1'] for x in rs), 'top5': sum(x['top5'] for x in rs)}

variants = [r for r in rows if r['category'] != '원문 대조']
summary = {'all_paraphrases': score(variants), 'controls': score([r for r in rows if r['category'] == '원문 대조']),
           'by_question': {q: score([r for r in variants if r['source_question'] == q]) for q in ['Q-130', 'Q-131']},
           'by_category': {c: score([r for r in variants if r['category'] == c]) for c in ['가까운 표현', '간접 표현']},
           'llm_attempted': sum(r['llm'].get('attempted', False) for r in rows),
           'llm_used': sum(r['used_llm'] for r in rows),
           'mean_seconds': sum(r['seconds'] for r in rows) / len(rows)}
protocol = json.loads((ROOT / 'protocol.json').read_text())
summary['frozen_files_unchanged'] = {f: hashlib.sha256(Path(f).read_bytes()).hexdigest() == h for f, h in protocol['sha256'].items()}
assert all(summary['frozen_files_unchanged'].values())
(ROOT / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
(ROOT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
with (ROOT / 'results.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()} for r in rows)
print(json.dumps(summary, ensure_ascii=False, indent=2))
for r in rows:
    print(r['query_id'], r['rank'], r['diagnosis'], 'expansions=', len(r['expansions']), 'lex=', r['bm25_first_chunk_rank'], 'vec=', r['vector_first_chunk_rank'], r['top5_doc_ids'])
