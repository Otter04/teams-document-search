"""Score a completed revision against frozen, unchanged v3.1/v2 labels."""
import argparse,collections,csv,hashlib,json,statistics
from pathlib import Path
from score_dataset import score_one,summarize
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'outputs/indexing-v31-001'
OUT=ROOT/'outputs/search-v31-fix-001'
def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);a=ap.parse_args();run=OUT/a.run
 assert (run/'complete.json').exists()
 frozen=read(OUT/'immutable-artifacts.json')
 assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in frozen.items()),'Frozen source/index/labels changed'
 docs=read(BASE/'search-data/documents.json');gold=rows(BASE/'evaluation/gold-v31.jsonl');oldgold=rows(BASE/'evaluation/gold-old125.jsonl')
 rr={r['query_id']:r for r in rows(run/'responses.jsonl')};assert len(rr)==150
 scores=[score_one(q,rr[q['query_id']],docs) for q in gold];olds=[score_one(q,rr[q['query_id']],docs) for q in oldgold];oldids={q['query_id'] for q in oldgold};news=[r for r in scores if r['query_id'] not in oldids]
 first={r['query_id']:r for r in read(BASE/'evaluation/run-001/scores.json')}
 before=rows(ROOT/'outputs/search-boundary-review-001/boundary-review-001/responses.jsonl');prior={r['query_id']:r for r in before}
 v2docs=read(ROOT/'outputs/indexing-v2-001/search-data/documents.json');baseline={q['query_id']:score_one(q,prior[q['query_id']],v2docs) for q in oldgold}
 key='all_required_representatives_found'
 summary={'all150':summarize(scores),'old125_same_gold':summarize(olds),'new25':summarize(news),
 'baseline_old125':summarize(list(baseline.values())),
 'recovered_vs_first':[r['query_id'] for r in scores if r[key] and not first[r['query_id']][key]],
 'regressed_vs_first':[r['query_id'] for r in scores if not r[key] and first[r['query_id']][key]],
 'old_regressions_vs_v2':[r['query_id'] for r in olds if not r[key] and baseline[r['query_id']][key]],
 'old_performance_restored':sum(r[key] for r in olds)>=sum(r[key] for r in baseline.values()),
 'new25_goal_reached':sum(r[key] for r in news)>=23,
 'unchanged_source_index_artifacts':len(frozen)}
 times=sorted(r['seconds'] for r in scores)
 summary['timing']={'mean':statistics.mean(times),'median':statistics.median(times),'p95':times[int(.95*(len(times)-1))], 'max':max(times),'total':sum(times)}
 summary['llm']=dict(collections.Counter(r['query_plan'].get('llm',{}).get('status','rules_only') for r in scores))
 summary['candidate_refill_limit_reached']=sum(bool(stat.get('refill_limit_reached')) for r in rr.values() for stat in r.get('response',{}).get('diagnostics',{}).get('candidate_diversity',{}).values() if isinstance(stat,dict))
 write(run/'scores.json',scores);write(run/'summary.json',summary)
 with (run/'query-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['질문','내용','최초성공','개선후성공','필수대표문서/순위','상위5','초','미달원인'])
  for r in scores:w.writerow([r['query_id'],r['query'],first[r['query_id']][key],r[key],'; '.join(c['representative']+': '+str(c['representative_rank']) for c in r['expected_cards'] if c['priority']=='필수'),'; '.join(c['doc_id']+' '+c['title'] for c in r['top5']),r['seconds'],'; '.join(c['reason'] for c in r['expected_cards'] if c['priority']=='필수' and c['representative_rank'] is None)])
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
