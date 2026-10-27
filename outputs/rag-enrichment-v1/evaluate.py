#!/usr/bin/env python3
"""State-aware evaluation: pending is never silently converted to confirmed N/A."""
import argparse
from collections import Counter
import csv
import importlib.util
import json
from pathlib import Path
from enrich import ROOT,FIELDS,read_lines,read_json,digest,dump,check_output,save_lines

spec=importlib.util.spec_from_file_location('legacy_metadata_comparison',ROOT.parent/'rag-evaluator/evaluate.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
CRITICAL={'계약번호','계약시작일','계약종료일','금액','통화','VAT','견적번호','견적유효기간','로그시작','로그종료','실행결과','오류코드'}
def ratio(a,b):return a/b if b else None
def percent(v):return '미측정' if v is None else f'{v:.2%}'

def compare(output,gold):
    rows=[]
    for field in FIELDS:
        prediction=output['fields'][field];raw=gold.get(field)
        labelled=raw is not None and str(raw).strip()!=''
        target=legacy.normalize(field,raw) if labelled else None
        actual=legacy.normalize(field,prediction['value']) if prediction['status']=='extracted' else None
        present=labelled and target!='N/A';filled=actual is not None
        match=bool(filled and present and legacy.excel_text(actual)==legacy.excel_text(target))
        verdict=('excluded_unlabelled' if not labelled else 'match' if match else
                 'wrong_value' if filled and present else 'filled_against_NA' if filled else
                 'unresolved_present' if present else 'unresolved_absence')
        rows.append({'doc_id':output['doc_id'],'format':output['source']['format'],'field':field,
            'gold':target,'prediction':actual,'status':prediction['status'],'verdict':verdict,'labelled':labelled,
            'gold_present':bool(present),'native_text_present':output['native_text_present'],
            'visual_pending':bool(output['pending_visual_units']),'critical':field in CRITICAL,
            'rule_id':prediction['rule_id'],'evidence':prediction['evidence'],'reason':prediction['reason']})
    return rows

def aggregate(rows):
    evaluated=[r for r in rows if r['labelled']]
    filled=[r for r in evaluated if r['prediction'] is not None]
    positive=[r for r in evaluated if r['gold_present']]
    empty=[r for r in evaluated if not r['gold_present']]
    correct=sum(r['verdict']=='match' for r in rows)
    false_na=sum(r['verdict']=='filled_against_NA' for r in rows)
    return {'slots':len(rows),'labelled_slots':len(evaluated),'filled':len(filled),'correct':correct,
        'wrong_values':sum(r['verdict']=='wrong_value' for r in rows),'filled_against_NA':false_na,
        'filled_value_precision':ratio(correct,len(filled)),'gold_present':len(positive),
        'gold_value_recall':ratio(correct,len(positive)),'gold_NA':len(empty),
        'false_fill_rate_on_NA':ratio(false_na,len(empty)),
        'critical_errors':sum(r['critical'] and r['verdict'] in ('wrong_value','filled_against_NA') for r in rows),
        'status_counts':dict(Counter(r['status'] for r in rows))}

def run(args):
    out=Path(args.output)
    if out.exists():raise ValueError('evaluation output must be new')
    records=read_lines(args.parsed);outputs=read_lines(args.enriched)
    goldrows=read_lines(Path(args.dataset)/'gold/documents.jsonl')
    def keyed(rows):
        d={r['doc_id']:r for r in rows}
        if len(d)!=len(rows):raise ValueError('duplicate document IDs')
        return d
    sources=keyed(records);pred=keyed(outputs);gold=keyed(goldrows)
    if sources.keys()!=pred.keys() or sources.keys()!=gold.keys():raise ValueError('full input/output/gold document inventory must match')
    checks=[];rows=[]
    for identity,r in pred.items():
        errors=check_output(r,sources[identity]);checks.append({'doc_id':identity,'errors':errors})
        if errors:raise ValueError(identity+': '+'; '.join(errors))
        rows.extend(compare(r,gold[identity]))
    groups={
        'all':aggregate(rows),
        'native_text_documents':aggregate([r for r in rows if r['native_text_present']]),
        'no_native_text_documents':aggregate([r for r in rows if not r['native_text_present']]),
        'with_visual_pending':aggregate([r for r in rows if r['visual_pending']]),
        'without_visual_pending':aggregate([r for r in rows if not r['visual_pending']])}
    overall=groups['all'];fields={f:aggregate([r for r in rows if r['field']==f]) for f in FIELDS}
    gates={
        'schema_evidence_and_inventory':{'passed':not any(c['errors'] for c in checks),'measured':len(checks),'required':len(sources)},
        'filled_value_precision':{'passed':overall['filled_value_precision'] is not None and overall['filled_value_precision']>=.95,'measured':overall['filled_value_precision'],'threshold':.95},
        'critical_value_errors':{'passed':overall['critical_errors']==0,'measured':overall['critical_errors'],'threshold':0},
        'false_fill_rate_on_NA':{'passed':overall['false_fill_rate_on_NA'] is not None and overall['false_fill_rate_on_NA']<=.02,'measured':overall['false_fill_rate_on_NA'],'threshold':.02}}
    # Full-population measures: unresolved values remain misses, as in the original handoff.
    handoff={f:fields[f]['gold_value_recall'] for f in ('문서종류','거래처')}
    handoff['날짜·금액·번호']=aggregate([r for r in rows if r['field'] in legacy.EXACT])['gold_value_recall']
    summary={'scope':'native_text_and_source_metadata_rules_only','overall_status':'partial',
        'quality_gate_passed':all(g['passed'] for g in gates.values()),'model_called':False,
        'documents':len(outputs),'schema_and_evidence_valid':len(checks),'groups':groups,'fields':fields,
        'by_format':{fmt:aggregate([r for r in rows if r['format']==fmt]) for fmt in sorted({r['format'] for r in rows})},
        'gates':gates,'handoff_full_population_accuracy':handoff,
        'handoff_threshold':.95,'documents_with_visual_pending':sum(bool(r['pending_visual_units']) for r in outputs),
        'visual_pending_units':sum(len(r['pending_visual_units']) for r in outputs),
        'not_evaluated':['vision','semantic summary','family grouping','latest version','chunking','retrieval','independent holdout'],
        'limitations':['Synthetic development corpus, not independent held-out accuracy.',
            'Evidence citation validation confirms source linkage, not semantic truth.',
            'N/A disagreement is a label disagreement; inspect source before calling it a hallucination.',
            'Pending/unknown fields are not confirmed absent and do not count as true negatives.']}
    out.mkdir(parents=True)
    dump(out/'summary.json',summary);save_lines(out/'field-results.jsonl',rows)
    dump(out/'mismatches.json',[r for r in rows if r['verdict'] in ('wrong_value','filled_against_NA')])
    dump(out/'validation.json',{'checks':checks,'inputs':{str(p):digest(p) for p in [Path(args.parsed),Path(args.enriched),Path(args.dataset)/'gold/documents.jsonl',Path(__file__),ROOT/'enrich.py',ROOT/'CONTRACT.md']}})
    with (out/'field-metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['필드','채운 값','일치','오답','N/A 오기입','채운 값 정확도','정답 값 수','정답 값 회수율','비전 대기','검토 대기','네이티브 미발견','적용 대상 아님'])
        for name,m in fields.items():writer.writerow([name,m['filled'],m['correct'],m['wrong_values'],m['filled_against_NA'],m['filled_value_precision'],m['gold_present'],m['gold_value_recall'],m['status_counts'].get('pending_vision',0),m['status_counts'].get('needs_review',0),m['status_counts'].get('not_found_native',0),m['status_counts'].get('not_applicable',0)])
    lines=['# 규칙 기반 문서 보강 실제 평가','', '범위: 네이티브 원문과 파일명·경로. 모델/API 호출 없음. 전체 보강 상태: **부분 완료**.','',
        f"문서 {len(outputs)}개, 채점 슬롯 {len(rows)}개. 스키마·근거 인용 검사 {len(checks)}/{len(checks)} 통과.",
        f"채운 값 {overall['filled']}개 중 {overall['correct']}개 정답 일치: **{percent(overall['filled_value_precision'])}**.",
        f"정답에 값이 있는 {overall['gold_present']}개 중 {overall['correct']}개 회수: **{percent(overall['gold_value_recall'])}**. 미추출·대기는 분모에 남겼습니다.",
        f"정답 N/A 오기입 {overall['filled_against_NA']}/{overall['gold_NA']}, 중대한 필드 오답 {overall['critical_errors']}건.",
        '', '## 필드별 결과','', '| 필드 | 채움 | 일치 | 채운 값 정확도 | 정답 값 회수 | 비전 대기 | 검토 대기 | 네이티브 미발견 | 적용 제외 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,m in fields.items():
        s=m['status_counts'];lines.append(f"| {name} | {m['filled']} | {m['correct']} | {percent(m['filled_value_precision'])} | {m['correct']}/{m['gold_present']} | {s.get('pending_vision',0)} | {s.get('needs_review',0)} | {s.get('not_found_native',0)} | {s.get('not_applicable',0)} |")
    lines+=['','## 범위별 결과','','| 범위 | 채운 값 정확도 | 정답 값 회수율 |','|---|---:|---:|']
    for title,key in [('전체','all'),('네이티브 글자가 있는 문서','native_text_documents'),('네이티브 글자가 없는 스캔','no_native_text_documents')]:
        m=groups[key];lines.append(f"| {title} | {m['correct']}/{m['filled']} ({percent(m['filled_value_precision'])}) | {m['correct']}/{m['gold_present']} ({percent(m['gold_value_recall'])}) |")
    lines+=['','## 판정과 제한','',f"제한된 규칙 출력의 품질 기준: {'통과' if summary['quality_gate_passed'] else '미달 항목 있음'}. 전체 문서 보강의 통과 판정은 아닙니다.",
        f"비전 처리 대기: {summary['documents_with_visual_pending']}문서, {summary['visual_pending_units']}개 원본 단위.",
        '미발견·보류를 N/A로 변환하지 않았습니다. 표의 빈 정답 수는 정답 라벨이며, 이번 실행이 정보 부재를 확인했다는 뜻이 아닙니다.',
        '거래처 사전을 입력으로 사용했습니다. 문서별 gold 라벨은 평가에서만 읽었습니다. 원문 양식을 보고 개발한 규칙이므로 독립 검증 세트 성적이 아닙니다.',
        '3줄 요약·계약유형의 의미 추론·사본 묶기·최신본·비전 의미·청킹·검색은 별도 작업입니다.',
        '원본 정답 라벨과 충돌할 경우 원문 근거를 함께 검토하며, 정답이나 출력값을 채점에 맞춰 고치지 않습니다. [오답 목록](mismatches.json)',
        '상세 상태·근거는 [필드별 결과](field-results.jsonl), 입력 해시는 [검증 기록](validation.json)에 있습니다.','']
    (out/'report.md').write_text('\n'.join(lines))
    print(json.dumps({'documents':len(outputs),'metrics':overall,'gates':gates},ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('parsed','enriched','dataset','output'):p.add_argument('--'+key,required=True)
    run(p.parse_args())
