"""Frozen question inputs and offline scoring; gold never enters indexing/model input."""
import argparse,shutil
from common import *
S=load('v2_gold_scoring',ROOT/'deploy/search/score_dataset.py')
GOLD=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2/search_gold/search_gold.jsonl')
OLD=ROOT/'datasets/search-gold-v2/search_gold.jsonl'
EVAL=OUT/'evaluation'
def prepare():
 assert not (EVAL/'gold-freeze.json').exists(),'Preserve frozen evaluation'
 EVAL.mkdir(exist_ok=True);new=rows(GOLD);old=rows(OLD);byid={q['query_id']:q for q in new}
 assert len(new)==125 and len(byid)==125 and len(old)==99
 assert all(q['query']==byid[q['query_id']]['query'] and q['base_date']==byid[q['query_id']]['base_date'] for q in old)
 for src,name in [(GOLD,'gold-v2.jsonl'),(OLD,'gold-original99.jsonl')]:shutil.copyfile(src,EVAL/name)
 lines(EVAL/'inputs.jsonl',[{k:q[k] for k in ['query_id','query','base_date']} for q in new])
 write(EVAL/'gold-freeze.json',{'files':{n:sha(EVAL/n) for n in ['gold-v2.jsonl','gold-original99.jsonl','inputs.jsonl']},'old_questions':99,'new_questions':26,'scoring':'same required representative top5 criteria; added optional cards separate','labels_sent_to_search':False,'baseline_run':'outputs/search-gold-v2-run-005','strict_date_policy_conflicts':['Q-068','Q-069']})
 print('Prepared 125 question-only requests; original99 and v2 gold separately frozen')
def score():
 freeze=read(EVAL/'gold-freeze.json')
 for n,h in freeze['files'].items():assert sha(EVAL/n)==h
 run=EVAL/'run-001';assert (run/'complete.json').exists()
 responses={r['query_id']:r for r in rows(run/'responses.jsonl')};gold=rows(EVAL/'gold-v2.jsonl');old=rows(EVAL/'gold-original99.jsonl');docs=read(OUT/'search-data/documents.json')
 assert set(responses)=={q['query_id'] for q in gold}
 newscore=[S.score_one(q,responses[q['query_id']],docs) for q in gold]
 oldscore=[S.score_one(q,responses[q['query_id']],docs) for q in old]
 oldids={q['query_id'] for q in old};before={r['query_id']:r for r in read(ROOT/'outputs/search-gold-v2-run-005/scores.json')}
 summary={'all125_original_gold':S.summarize(newscore),'old99_unchanged_gold':S.summarize(oldscore),'new26':S.summarize([r for r in newscore if r['query_id'] not in oldids]),
  'old99_regressed':[r['query_id'] for r in oldscore if before[r['query_id']]['all_required_representatives_found'] and not r['all_required_representatives_found']],
  'old99_improved':[r['query_id'] for r in oldscore if not before[r['query_id']]['all_required_representatives_found'] and r['all_required_representatives_found']],
  'strict_policy_conflicts':{qid:{'returned':[r['doc_id'] for r in responses[qid].get('response',{}).get('results',[])],'request_error':responses[qid].get('error'),'status':responses[qid].get('response',{}).get('status')} for qid in freeze['strict_date_policy_conflicts']}}
 optional=[];oldmap={q['query_id']:q for q in old}
 for q in gold:
  if q['query_id'] not in oldmap:continue
  prev={c['representative'] for c in oldmap[q['query_id']]['expected_cards']}
  added=[c for c in q['expected_cards'] if c['representative'] not in prev]
  if added:
   s=next(x for x in newscore if x['query_id']==q['query_id'])
   optional.append({'query_id':q['query_id'],'cards':[c for c in s['expected_cards'] if c['representative'] not in prev]})
 write(run/'scores.json',newscore);write(run/'scores-original99.json',oldscore);write(run/'summary.json',summary);write(run/'added-optional-cards.json',optional)
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','score']);a=ap.parse_args();prepare() if a.action=='prepare' else score()
