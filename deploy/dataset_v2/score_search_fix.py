"""Compare frozen gold against immutable search-only improvement trials."""
import sys,collections
from common import *
S=load('fix_score',ROOT/'deploy/search/score_dataset.py')
DEST=ROOT/'outputs/search-v2-fix-001'
def main(runname):
 p=DEST/runname;assert (p/'complete.json').exists()
 for rel,h in read(DEST/'preservation.json').items():assert sha(ROOT/rel)==h,rel
 rs={r['query_id']:r for r in rows(p/'responses.jsonl')};assert len(rs)==125
 gold=rows(OUT/'evaluation/gold-v2.jsonl');old=rows(OUT/'evaluation/gold-original99.jsonl');docs=read(OUT/'search-data/documents.json');oldids={q['query_id'] for q in old}
 scored=[S.score_one(q,rs[q['query_id']],docs) for q in gold];oldscore=[S.score_one(q,rs[q['query_id']],docs) for q in old]
 before={r['query_id']:r for r in read(OUT/'evaluation/run-001/scores-original99.json')}
 historic={r['query_id']:r for r in read(ROOT/'outputs/search-gold-v2-run-005/scores.json')}
 llm=collections.Counter(r.get('response',{}).get('query_plan',{}).get('llm',{}).get('status','not_attempted') for r in rs.values())
 result={'all125':S.summarize(scored),'old99':S.summarize(oldscore),'new26':S.summarize([r for r in scored if r['query_id'] not in oldids]),
 'regressions_vs_previous110':[r['query_id'] for r in oldscore if historic[r['query_id']]['all_required_representatives_found'] and not r['all_required_representatives_found']],
 'recovered_vs_v2_before':[r['query_id'] for r in oldscore if not before[r['query_id']]['all_required_representatives_found'] and r['all_required_representatives_found']],
 'llm_statuses':dict(llm),'complete':read(p/'complete.json'),'config':read(p/'freeze.json')['health']['config']}
 write(p/'scores.json',scored);write(p/'scores-original99.json',oldscore);write(p/'summary.json',result)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main(sys.argv[1])
