"""Independent date audit against source metadata; never imports search predicates."""
import argparse,collections,json
from datetime import date
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);args=ap.parse_args()
    assert (args.run/'complete.json').exists()
    base=Path(__file__).resolve().parents[2]
    spec=json.loads((base/'datasets/search-gold-v2/strict-date-policy-checks.json').read_text())
    docs=json.loads((base/'outputs/search-service-001/documents.json').read_text())
    responses={r['query_id']:r for r in map(json.loads,(args.run/'responses.jsonl').read_text().splitlines())}
    report=[]
    for case in spec['cases']:
        r=responses[case['query_id']]['response'];field=case['field']
        low=date.fromisoformat(case['start']);high=date.fromisoformat(case['end'])
        def check(did):
            d=docs[did];m=d['metadata'];s=d['metadata_statuses']
            keys=['contract_start','contract_end'] if field=='contract_period' else [field]
            if not all(s.get(k)=='extracted' and m.get(k) for k in keys):return 'unknown'
            if field=='contract_period':
                a=date.fromisoformat(m['contract_start'][:10]);b=date.fromisoformat(m['contract_end'][:10])
                return 'inside' if a<=high and b>=low else 'outside'
            actual=date.fromisoformat(m[field][:10])
            return 'inside' if low<=actual<=high else 'outside'
        cards=r.get('results',[])+r.get('undated_results',[])
        items={name:[{'doc_id':did,'date_check':check(did)} for did in ids] for name,ids in {
            'final':[c['doc_id'] for c in cards],
            'other_versions':[v['doc_id'] for c in cards for v in c.get('other_versions',[])],
            **{branch:[h['doc_id'] for h in r.get('diagnostics',{}).get(branch,[])] for branch in ['bm25','vector']}}.items()}
        expected={ 'gte':case['start'],'lte':case['end'] }
        report.append({**case,'query':responses[case['query_id']]['query'],'status':r['status'],
          'range_locked':r['query_plan'].get('filters',{}).get(field)==expected,
          'relaxed_dates':[x for x in r.get('relaxed_conditions',[]) if x['field'] in ['document_date','log_start','cover_date','written_date','file_modified_at','contract_period']],
          'empty_as_requested':not cards if case['expect_empty'] else None,'items':items})
    totals={branch:dict(collections.Counter(x['date_check'] for c in report for x in c['items'][branch])) for branch in ['final','other_versions','bm25','vector']}
    backup=responses['Q-061']['response']['results'];gold_ids={'D-072','D-109','D-110'}
    result={'date_questions':len(report),'totals':totals,'locked_ranges':sum(x['range_locked'] for x in report),
      'date_relaxations':sum(len(x['relaxed_dates']) for x in report),
      'expected_empty_cases_passed':sum(x['empty_as_requested'] is True for x in report),
      'q061_exact_three':len(backup)==3 and {c['doc_id'] for c in backup}==gold_ids,
      'cases':report}
    (args.run/'date-policy-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
