"""Re-score the published frozen rankings without models, network, or ES."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('keyword', 'semantic', 'rrf', 'reranker')


def complete_rank(hits, groups):
    positions = {h['chunk_id']:i for i,h in enumerate(hits, 1)}
    ranks = [min((positions[c] for c in group if c in positions), default=None)
             for group in groups]
    assert ranks, 'empty required evidence groups'
    return max(ranks) if all(r is not None for r in ranks) else None


def main():
    manifest = json.loads((ROOT/'evaluation/publication-manifest.json').read_text())
    for item in manifest['files']:
        path = (ROOT/item['path']).resolve()
        assert path.is_relative_to(ROOT), 'manifest path outside repository'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], item['path']
    rows = [json.loads(line) for line in (ROOT/'evaluation/baseline-20261111/rankings.jsonl').read_text().splitlines()]
    assert len(rows) == 82 and len({r['id'] for r in rows}) == 82
    assert sum(r['clarification_diagnostic'] for r in rows) == 8
    counts = {s:{str(n):0 for n in (10,20,50)} for s in STAGES}
    missing = {s:[] for s in STAGES}
    for row in rows:
        for stage in STAGES:
            hits = row[stage]
            assert len(hits) <= 50 and len({h['chunk_id'] for h in hits}) == len(hits)
            assert all(math.isfinite(h['score']) for h in hits)
            rank = complete_rank(hits, row['required_evidence_groups'])
            for n in (10,20,50):
                counts[stage][str(n)] += rank is not None and rank <= n
            if rank is None:
                missing[stage].append(row['id'])
        # Independently recalculate the historical RRF and exact deterministic tie order.
        combined = {}
        for stage, weight in [('keyword',1), ('semantic',2)]:
            for rank, hit in enumerate(row[stage],1):
                key = hit['chunk_id']
                item = combined.setdefault(key, {'chunk_id':key, 'score':0.0})
                item['score'] += weight/(60+rank)
        expected = sorted(combined.values(), key=lambda h:(-h['score'],h['chunk_id']))[:50]
        assert [h['chunk_id'] for h in expected] == [h['chunk_id'] for h in row['rrf']], row['id']
        assert all(math.isclose(a['score'], b['score'], abs_tol=1e-12)
                   for a,b in zip(expected,row['rrf']))
        assert {h['chunk_id'] for h in row['rrf']} == {h['chunk_id'] for h in row['reranker']}
        assert all(a['score'] >= b['score'] for a,b in zip(row['reranker'],row['reranker'][1:]))
    reference = json.loads((ROOT/'evaluation/baseline-20261111/expected.json').read_text())
    assert counts == reference['at'], (counts,reference)
    assert missing == reference['missing50']
    print('82 questions verified; no model, API or search calls.')
    print('stage        @10  @20  @50  missing50')
    for s in STAGES:
        print(f'{s:12} {counts[s]["10"]:3}  {counts[s]["20"]:3}  {counts[s]["50"]:3}  {len(missing[s]):3}')
    print('Source hashes, RRF scores/order and reranker candidate preservation: PASS')


if __name__ == '__main__':
    main()
