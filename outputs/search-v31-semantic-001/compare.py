"""Score saved responses only. Labels are never sent to search/model services."""
import collections,csv,hashlib,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'deploy/search'))
from score_dataset import score_one,summarize
P=Path(__file__).resolve().parent
run=P/(sys.argv[1] if len(sys.argv)>1 else 'run-001')
assert (run/'complete.json').exists()
def read(path):return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]
def mapped(path):return {r['query_id']:r for r in read(path)}
docs=json.loads((ROOT/'outputs/indexing-v31-001/search-data/documents.json').read_text())
blocks=json.loads((ROOT/'outputs/indexing-v31-001/search-data/blocks.json').read_text())
gold=read(ROOT/'outputs/indexing-v31-001/evaluation/gold-v31.jsonl')
before=mapped(ROOT/'outputs/search-v31-expression-001/run-001/responses.jsonl')
variant_before=mapped(ROOT/'outputs/search-v31-paraphrase-001/run-001/responses.jsonl')
after=mapped(run/'responses.jsonl');assert len(after)==166
old=[score_one(g,before[g['query_id']],docs) for g in gold]
new=[score_one(g,after[g['query_id']],docs) for g in gold]
cases=[c for c in json.loads((ROOT/'outputs/search-v31-paraphrase-001/cases.json').read_text()) if c['category']!='원문 대조']
variant=[]
for c in cases:
    qid=c['query_id'];target=c['expected_doc_id']
    def ranks(r):
        ids=[x['doc_id'] for x in r.get('response',{}).get('results',[])][:5]
        return ids.index(target)+1 if target in ids else None
    variant.append({**c,'before_rank':ranks(variant_before[qid]),'after_rank':ranks(after[qid]),
      'before_seconds':variant_before[qid]['client_seconds'],'after_seconds':after[qid]['client_seconds'],
      'source_review':after[qid].get('response',{}).get('query_plan',{}).get('source_review')})
def variant_summary(rs):
    return {'questions':len(rs),'before_top5':sum(r['before_rank'] is not None for r in rs),
      'after_top5':sum(r['after_rank'] is not None for r in rs),
      'before_top1':sum(r['before_rank']==1 for r in rs),'after_top1':sum(r['after_rank']==1 for r in rs)}
def timing(rows):
    xs=sorted(r['client_seconds'] for r in rows)
    return {'mean':statistics.mean(xs),'median':statistics.median(xs),'p95':xs[min(len(xs)-1,int(.95*(len(xs)-1)))],'max':max(xs)}
quotes=[]
for qid,r in after.items():
    review=r.get('response',{}).get('query_plan',{}).get('source_review',{})
    if review.get('status')=='accepted':
        text='\n'.join(b.get('text','') for b in blocks.get(review['doc_id'],{}).values())
        quotes.append({'query_id':qid,**review,'verified_against_source_blocks':review['quote'] in text})
allbefore={**before,**{q:variant_before[q] for q in after if q not in before}}
summary={'before150':summarize(old),'after150':summarize(new),
 'before125':summarize(old[:125]),'after125':summarize(new[:125]),
 'before_new25':summarize(old[125:]),'after_new25':summarize(new[125:]),
 'regressions150':[b['query_id'] for a,b in zip(old,new) if a['all_required_representatives_found'] and not b['all_required_representatives_found']],
 'recovered150':[b['query_id'] for a,b in zip(old,new) if not a['all_required_representatives_found'] and b['all_required_representatives_found']],
 'changed_top5':[b['query_id'] for a,b in zip(old,new) if [x['doc_id'] for x in a['top5']]!=[x['doc_id'] for x in b['top5']]],
 'variants':variant_summary(variant),
 'by_variant_category':{c:variant_summary([r for r in variant if r['category']==c]) for c in sorted({r['category'] for r in variant})},
 'recovered_variants':[r['query_id'] for r in variant if r['before_rank'] is None and r['after_rank'] is not None],
 'regressed_variants':[r['query_id'] for r in variant if r['before_rank'] is not None and r['after_rank'] is None],
 'time_before166':timing(list(allbefore.values())),'time_after166':timing(list(after.values())),
 'time_before150':timing(list(before.values())),'time_after150':timing([after[g['query_id']] for g in gold]),
 'time_before16':timing([variant_before[c['query_id']] for c in cases]),'time_after16':timing([after[c['query_id']] for c in cases]),
 'errors':[qid for qid,r in after.items() if 'error' in r],
 'review_statuses':dict(collections.Counter(r.get('response',{}).get('query_plan',{}).get('source_review',{}).get('status','not_used') for r in after.values())),
 'unverified_quotes':[q['query_id'] for q in quotes if not q['verified_against_source_blocks']],
 'frozen_files_unchanged':all(hashlib.sha256(Path(f).read_bytes()).hexdigest()==h for f,h in json.loads((P/'freeze.json').read_text()).items())}
for name,value in [('summary.json',summary),('scores.json',new),('variants.json',variant),('quote-audit.json',quotes)]:
    (run/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
with (run/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['질문ID','질문','이전 상위5 성공','현재 상위5 성공','이전 정답 순위','현재 정답 순위','현재 상위5 문서','현재 초'])
    for a,b in zip(old,new):
        ranks=lambda x:[(c['representative'],c['representative_rank']) for c in x['expected_cards'] if c['priority']=='필수']
        w.writerow([b['query_id'],b['query'],a['all_required_representatives_found'],b['all_required_representatives_found'],ranks(a),ranks(b),[x['doc_id'] for x in b['top5']],b['seconds']])
    for r in variant:
        qid=r['query_id'];w.writerow([qid,r['query'],r['before_rank'] is not None,r['after_rank'] is not None,r['before_rank'],r['after_rank'],[x['doc_id'] for x in after[qid].get('response',{}).get('results',[])],r['after_seconds']])
print(json.dumps({k:v for k,v in summary.items() if k not in ['before150','after150','before125','after125','before_new25','after_new25']},ensure_ascii=False,indent=2))
print('150 top5',summary['before150']['all_required_representatives_found'],summary['after150']['all_required_representatives_found'])
