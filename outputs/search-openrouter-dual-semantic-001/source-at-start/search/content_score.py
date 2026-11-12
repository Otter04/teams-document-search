"""Current content-aware evaluation; retains exact-ID metrics and original gold."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'search_reranker'))
from scoring_reference import score_one
VERSION='verified-equivalent-format-1.0'
def score_content(gold,row,docs,equivalence):
    strict=score_one(gold,row,docs)
    response=row.get('response',{});ids=[x['doc_id'] for x in response.get('results',[])]
    expected=[]
    for card in gold['expected_cards']:
        original=card['representative'];accepted=equivalence.accepted(original,gold['query'],response.get('query_plan',{}))
        found=[(i+1,d) for i,d in enumerate(ids) if d in accepted]
        expected.append({'priority':card['priority'],'original_representative':original,'accepted_ids':sorted(accepted),'rank':found[0][0] if found else None,'shown':found[0][1] if found else None})
    required=[c for c in expected if c['priority']=='필수'];assert required
    ranks=[c['rank'] for c in required if c['rank']]
    return {**strict,'evaluation_policy':VERSION,'content_expected_cards':expected,
        'all_required_content_found':all(c['rank'] is not None for c in required),
        'required_content_top1':1 in ranks,'required_content_mrr_at5':1/min(ranks) if ranks else 0}
