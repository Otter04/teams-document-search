"""Compare frozen 150-query runs; labels are used only after retrieval."""
import csv,hashlib,json,statistics
from pathlib import Path
from score_dataset import score_one,summarize
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/search-v31-expression-001';BASE=ROOT/'outputs/indexing-v31-001';RUN=OUT/'run-001';PRIOR=ROOT/'outputs/search-v31-fix-001/run-004'
def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(s) for s in p.read_text().splitlines()]
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 assert read(RUN/'complete.json')['completed']==150
 for file,h in read(OUT/'immutable-artifacts.json').items():assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest()==h
 assert hashlib.sha256((PRIOR/'responses.jsonl').read_bytes()).hexdigest()==read(OUT/'baseline.json')['response_sha256']
 docs=read(BASE/'search-data/documents.json');gold=rows(BASE/'evaluation/gold-v31.jsonl');oldgold=rows(BASE/'evaluation/gold-old125.jsonl')
 responses={r['query_id']:r for r in rows(RUN/'responses.jsonl')};prior={r['query_id']:r for r in rows(PRIOR/'responses.jsonl')}
 scores=[score_one(q,responses[q['query_id']],docs) for q in gold];before={q['query_id']:score_one(q,prior[q['query_id']],docs) for q in gold}
 old=[score_one(q,responses[q['query_id']],docs) for q in oldgold];oldids={q['query_id'] for q in oldgold};new=[s for s in scores if s['query_id'] not in oldids];key='all_required_representatives_found'
 changes=[]
 for s in scores:
  q=s['query_id'];a=[d['doc_id'] for d in s['top5']];b=[d['doc_id'] for d in before[q]['top5']]
  if a!=b:changes.append({'query_id':q,'before':b,'after':a})
 times=sorted(s['seconds'] for s in scores)
 summary={'before150':summarize(list(before.values())),'after150':summarize(scores),'old125':summarize(old),'new25':summarize(new),
 'recovered':[s['query_id'] for s in scores if not before[s['query_id']][key] and s[key]],
 'regressed':[s['query_id'] for s in scores if before[s['query_id']][key] and not s[key]],'top5_order_changes':changes,
 'timing':{'mean':statistics.mean(times),'median':statistics.median(times),'p95':times[int(.95*(len(times)-1))],'max':max(times)},
 'llm_attempts':sum(bool(s['query_plan']['llm'].get('attempted')) for s in scores),'llm_accepted':sum(s['query_plan']['used_llm'] for s in scores)}
 write(RUN/'scores.json',scores);write(RUN/'summary.json',summary)
 with (RUN/'query-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['질문ID','질문','기존성공','개선후성공','필수대표문서와순위','기존상위5','현재상위5','시간초'])
  for s in scores:w.writerow([s['query_id'],s['query'],before[s['query_id']][key],s[key],'; '.join(c['representative']+': '+str(c['representative_rank']) for c in s['expected_cards'] if c['priority']=='필수'),'; '.join(d['doc_id'] for d in before[s['query_id']]['top5']),'; '.join(d['doc_id']+' '+d['title'] for d in s['top5']),s['seconds']])
 print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
