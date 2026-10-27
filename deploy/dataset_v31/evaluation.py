"""Frozen first-pass 150-question evaluation; no automatic retrieval tuning."""
import shutil,csv
from common import *
S=load('v31_scoring',ROOT/'deploy/search/score_dataset.py')
EVAL=OUT/'evaluation';GOLD=FILES.parent/'search_gold/search_gold.jsonl';OLD=ROOT/'outputs/indexing-v2-001/evaluation/gold-v2.jsonl'
def prepare():
 EVAL.mkdir(exist_ok=True);assert not (EVAL/'gold-freeze.json').exists()
 gold=rows(GOLD);old=rows(OLD);assert len(gold)==150 and len(old)==125
 byid={q['query_id']:q for q in gold};assert len(byid)==150
 assert all(q['query']==byid[q['query_id']]['query'] and q['base_date']==byid[q['query_id']]['base_date'] for q in old)
 for src,n in [(GOLD,'gold-v31.jsonl'),(OLD,'gold-old125.jsonl')]:shutil.copyfile(src,EVAL/n)
 lines(EVAL/'inputs.jsonl',[{k:q[k] for k in ['query_id','query','base_date']} for q in gold])
 write(EVAL/'gold-freeze.json',{'files':{n:sha(EVAL/n) for n in ['gold-v31.jsonl','gold-old125.jsonl','inputs.jsonl']},'search_version':'search-1.6.1','use_llm':True,'llm_budget_seconds':2.5,'first_results_before_any_retrieval_changes':True,'baseline':'outputs/search-boundary-review-001/boundary-review-001','labels_sent_to_search':False})
def score():
 freeze=read(EVAL/'gold-freeze.json')
 for n,h in freeze['files'].items():assert sha(EVAL/n)==h
 run=EVAL/'run-001';assert (run/'complete.json').exists();responses={r['query_id']:r for r in rows(run/'responses.jsonl')};gold=rows(EVAL/'gold-v31.jsonl');old=rows(EVAL/'gold-old125.jsonl');docs=read(OUT/'search-data/documents.json')
 allscores=[S.score_one(q,responses[q['query_id']],docs) for q in gold];oldscores=[S.score_one(q,responses[q['query_id']],docs) for q in old];oldids={q['query_id'] for q in old};newscores=[r for r in allscores if r['query_id'] not in oldids]
 priorrows={r['query_id']:r for r in rows(ROOT/freeze['baseline']/'responses.jsonl')};old_docs=read(ROOT/'outputs/indexing-v2-001/search-data/documents.json');before={q['query_id']:S.score_one(q,priorrows[q['query_id']],old_docs) for q in old}
 summary={'all150':S.summarize(allscores),'old125_same_gold':S.summarize(oldscores),'new25':S.summarize(newscores),'baseline_old125':S.summarize(list(before.values())),
 'regressed':[r['query_id'] for r in oldscores if before[r['query_id']]['all_required_representatives_found'] and not r['all_required_representatives_found']],
 'improved':[r['query_id'] for r in oldscores if not before[r['query_id']]['all_required_representatives_found'] and r['all_required_representatives_found']],
 'new25_goal_reached':sum(r['all_required_representatives_found'] for r in newscores)/25>=.9,'frozen_first_run':True,'retrieval_tuned_after_scores':False}
 write(run/'scores.json',allscores);write(run/'scores-old125.json',oldscores);write(run/'summary.json',summary)
 with (run/'query-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['질문ID','질문','필수정답/순위','실제상위5','필수정답전체포함','시간초','실패분류'])
  for r in allscores:w.writerow([r['query_id'],r['query'],'; '.join(c['representative']+': '+str(c['representative_rank']) for c in r['expected_cards'] if c['priority']=='필수'),'; '.join(c['doc_id']+' '+c['title'] for c in r['top5']),r['all_required_representatives_found'],r['seconds'],'; '.join(c['reason'] for c in r['expected_cards'] if c['priority']=='필수' and c['representative_rank'] is None)])
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':prepare() if sys.argv[1]=='prepare' else score()
