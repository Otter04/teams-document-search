"""Extra fixed fixtures suggested by the design; not added to the original 61 gold queries."""
import argparse,json
from pathlib import Path
from evaluate_remote import request

parser=argparse.ArgumentParser();parser.add_argument('--run',default='fixtures-001.json');args=parser.parse_args()
path=Path(__file__).resolve().parent/'evaluation'/args.run
assert not path.exists()
cases=[
 {'id':'older-quote','query':'견적번호 Q-2501-03','expected_representative':'D-003'},
 {'id':'draft-status','query':'청람정밀 MES 고도화 계약서 초안','expected_representative':'D-005'},
 {'id':'relax-daon','query':'다온로지스 2023년 견적서','relaxed_field':'document_date','client':'다온로지스'},
 {'id':'relax-haesol','query':'해솔유통 2024년 계약서','relaxed_field':'document_date','client':'해솔유통'},
 {'id':'cover-date','query':'청람정밀 표지일 2025년 1월 13일 제안서','filter_field':'cover_date'},
 {'id':'modified-order','query':'청람정밀 최근 수정된 문서','sort_field':'file_modified_at'},
 {'id':'negation','query':'청람정밀 말고 계약서','status':'needs_clarification'},
 {'id':'ambiguous-date','query':'지난 분기 견적서','status':'needs_clarification'},
]
out=[]
for case in cases:
    r=request('/search',{'query':case['query'],'filter_mode':'A','reranker':'R1','reference_date':'2026-10-14','use_llm':False})
    checks={}
    if 'expected_representative' in case:checks['representative']=bool(r['results']) and r['results'][0]['doc_id']==case['expected_representative']
    if 'relaxed_field' in case:
        checks['relaxation']=any(x['field']==case['relaxed_field'] for x in r['relaxed_conditions'])
        checks['client_preserved']=bool(r['results']) and all(x['metadata']['client']==case['client'] for x in r['results'])
    if 'filter_field' in case:checks['date_role']=case['filter_field'] in r['query_plan']['filters'] and not r['relaxed_conditions']
    if 'sort_field' in case:
        times=[c['metadata']['file_modified_at'] for c in r['results']]
        checks['order']=bool(times) and times==sorted(times,reverse=True)
    if 'status' in case:checks['status']=r['status']==case['status']
    out.append({'case':case,'checks':checks,'passed':all(checks.values()),'response':r})
path.write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps([{'id':r['case']['id'],'passed':r['passed'],'checks':r['checks']} for r in out],ensure_ascii=False))
