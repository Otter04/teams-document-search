from pathlib import Path
import json,statistics
P=Path(__file__).resolve().parent;R=P/'run-003'
s=json.loads((R/'summary.json').read_text());v=json.loads((R/'variants.json').read_text());date=json.loads((R/'date-policy-audit.json').read_text())
rows=[json.loads(l) for l in (R/'responses.jsonl').read_text().splitlines()]
reviewed=[r for r in rows if r['response']['query_plan'].get('source_review',{}).get('attempted')]
accepted=[r for r in reviewed if r['response']['query_plan']['source_review']['status']=='accepted']
a=s['after150'];b=s['before150'];failed=[r for r in v if r['before_rank'] is None]
report=f'''# 의미 표현 검색 개선 및 166질문 재평가

2026-10-26 · search-1.8.4 · 결과 기준 run-003. 사용자 화면 배포 여부는 DEPLOYMENT.json을 별도로 확인한다.

기존 단어 규칙을 추가하지 않고, 키워드 후보가 없는 간접 질문에 기존 Orin Qwen3.6의 원문 대조를 연결했다. 인덱싱된195문서·3,754청크를 그대로 사용했다. 기존150개 필수 정답 상위5 성적은 **{b['all_required_representatives_found']}/150 → {a['all_required_representatives_found']}/150**, 변형16개는 **10/16 → {s['variants']['after_top5']}/16**이다. 기존 성공 회귀: {s['regressions150'] or '없음'}.

## 성능 비교

상위5 성공은 질문별 필수 대표 정답 전부 포함을 뜻한다. 변형 질문은 지정된 목표 문서의 포함 여부다. 정답1위는 별도 지표다.

| 평가 범위 | 이전 상위5 성공 | 개선 후 상위5 성공 | 이전 정답1위 | 개선 후 정답1위 |
|---|---:|---:|---:|---:|
| 기존150 | 148/150 | {a['all_required_representatives_found']}/150 | {b['required_representative_top1']}/150 | {a['required_representative_top1']}/150 |
| 그중 기존125 | 123/125 | {s['after125']['all_required_representatives_found']}/125 | {s['before125']['required_representative_top1']}/125 | {s['after125']['required_representative_top1']}/125 |
| v3.1 신규25 | 25/25 | {s['after_new25']['all_required_representatives_found']}/25 | 16/25 | {s['after_new25']['required_representative_top1']}/25 |
| 변형16 | 10/16 | {s['variants']['after_top5']}/16 | 7/16 | {s['variants']['after_top1']}/16 |
| 가까운 표현8 | 8/8 | {s['by_variant_category']['가까운 표현']['after_top5']}/8 | 7/8 | {s['by_variant_category']['가까운 표현']['after_top1']}/8 |
| 간접 표현8 | 2/8 | {s['by_variant_category']['간접 표현']['after_top5']}/8 | 0/8 | {s['by_variant_category']['간접 표현']['after_top1']}/8 |

## 실패했던6개

| 질문 | 실제 표현 | 이전 | 개선 후 | 정답 |
|---|---|---:|---:|---|
'''
for r in failed:
 report+=f"| {r['query_id']} | {r['query']} | 상위5 밖 | {str(r['after_rank'])+'위' if r['after_rank'] else '상위5 밖'} | {r['expected_doc_id']} |\n"
report+='''
Q-130 계열은 `OUDC_질의 답변서_250910.docx`(D-178)의 표에서 “폐기 대상 디스크는 공사 직원 입회하에 물리 파쇄하고 파쇄 확인서를 제출할 것”을 근거로 선택했다. 질문만 적힌 질의서와 실제 지침이 적힌 답변서를 구분하는 판단이다.

Q-131 계열은 `온새미도시공사_시설관리시스템 노후서버 교체_제안요청서.pdf`(D-175) 1페이지의 “기술 평가 80 점, 가격 평가 20 점.”을 근거로 선택했다. “금액보다 수행 수준에 많은 몫”이라는 표현을 기술과 가격의 실제 배점 관계로 읽는 판단이다.

## 무엇이 달라졌나

검색 조건과 한영·동의어 규칙(query.py)은 이전 파일과 바이트가 같다. 질문 ID별 분기나 정답 ID 가산을 넣지 않았다. 검색 결과에서 모델이 고른 ID를 런타임에 우선하는 것이며 정답 목록을 모델에 보내는 방식이 아니다.

BM25 후보가 없고 기존 명시 조건·개념 확장으로 해결하지 않는 질문에 한해 의미 후보를 최대150청크로 넓힌다. 최대60문서의 제한된 본문을 Qwen이 읽고 가장 적합한 한 문서와 연속 인용문을 반환한다. 숫자가 직접 포함된 질문은 수치 조건 검증을 지원할 때까지 원문 대조로 순위를 바꾸지 않고 기존 결과를 유지한다. 전체 후보에 새 점수를 붙이는 전용 리랭커와는 다른 조건부 LLM 문서 선택 방식이다. 기존 RRF·R1 조정은 유지한다.

인용은 모델에 제공한 텍스트와 실제 공통 블록 양쪽에 있어야 한다. 모델 출력이 잘리거나 형식·근거가 틀리면 원래50청크 기반 결과를 유지한다. 같은 문서군의 다른 검색 후보에도 동일한 근거가 확인되면 기존 버전 선택 규칙을 따른다. 따라서 초안에 해당 문장이 있다는 이유만으로 근거가 같은 서명본을 밀어내지 않는다.

화면은 키워드·의미·결합된 청크 순위를 유지하고, 추가 원문 대조가 적용된 경우 그 상태와 근거를 표시한다. 최종 답변을 생성하는 단계는 추가하지 않았다.

## 시간과 모델 사용

시간은 요청 시작부터 최종 문서 결과 수신까지다. 첫 정답을 발견한 시점이나 답변 생성 시간은 아니다. 같은 Orin의 실측 비교이며 시점별 캐시·부하 영향을 완전히 통제한 성능 시험은 아니다.

| 범위 | 이전 평균 | 개선 후 평균 | 개선 후 중앙값 | 개선 후95백분위 |
|---|---:|---:|---:|---:|
'''
for key,label in [('150','기존150'),('16','변형16'),('166','전체166')]:
 old=s['time_before'+key];new=s['time_after'+key]
 report+=f"| {label} | {old['mean']:.2f}초 | {new['mean']:.2f}초 | {new['median']:.2f}초 | {new['p95']:.2f}초 |\n"
report+=f'''
- 전체166개 원문 대조 시도 {len(reviewed)}건, 채택 {len(accepted)}건. 상태별: {json.dumps(s['review_statuses'],ensure_ascii=False)}.
- 원문 대조를 시도한 질문의 평균 전체 응답 {statistics.mean(r['client_seconds'] for r in reviewed):.2f}초. 정확도를 얻는 대신 시간이 늘어나는 방식이며 기존3초 목표를 달성했다고 설명하지 않는다.
- 질문 분석의 기존2.5초 제한과 원문 대조의90초 상한은 서로 다른 단계다. 실제90초를 항상 기다리는 것은 아니다.
- 전용 bge-reranker-v2-m3 실험은 기존 성공 일부를 떨어뜨려 채택하지 않았다. 해당 컨테이너는 중지 상태다. 현재 방식은 기존 Qwen을 사용하며 새 모델 설치·유료 API 호출은 없다.

## 검증과 보존

- 전체 요청 오류: {len(s['errors'])}건. 실제 공통 블록에 없는 채택 인용: {len(s['unverified_quotes'])}건.
- 원본195파일 해시 일치, Elasticsearch 원문195문서+3,754청크 전체 일치. 구v001/v002 보존.
- 기존 정답·응답·입력 보존: {s['frozen_files_unchanged']}. 109개 자동검사 통과.
- 날짜 질문{date['date_questions']}개 조건 잠금 {date['locked_ranges']}개, 날짜 완화{date['date_relaxations']}건. Q-061 올해 백업 로그 정확히3개: {date['q061_exact_three']}.
- 기간 밖 포함: {json.dumps({k:x.get('outside',0) for k,x in date['totals'].items()},ensure_ascii=False)}.

최초 전체실험 run-001은 변형16/16이지만 기존146/150이어서 채택하지 않았다. Q-070/080의 대표 버전 회귀와 Q-074의 요약 전용 인용 문제를 보완한 뒤 run-002를 새로 실행했다. run-002에서는 Q-083이 금액만 비슷한 다른 사업 계약서를 선택해 기존147/150이었다. 숫자로 명시된 조건의 별도 검증 없이 모델이 순위를 바꾸지 못하도록 보호한 뒤 run-003을 전체 실행했다. 최초 응답들은 그대로 보존했다. 초기 실험의 자세한 범위는 PROTOCOL.md에 있다.

## 해석의 한계

남은 기존 실패는 {a['failed_required_representative_queries']}이다. Q-068/069는 정해진 날짜 정책과 과거 정답의 충돌이며, 이번에도 기간 조건을 풀어 점수를 올리지 않았다.

150개는 개발용 평가이고 변형16개도 이미 확인한 실패를 개선하는 데 사용했다. 따라서 이번 성적은 이166개에 대한 회귀 검사이며 새로운 모든 표현에서 같은 정확도를 보장하지 않는다. 원문 대조는 일부 후보·제한된 본문만 읽으며, 인용 문자열의 존재가 모델의 의미 판단까지 보장하지는 않는다. 동시 이용자 부하와 별도 미사용 질문의 성능은 이번에 평가하지 않았다.

## 결과 파일

- run-003/summary.json: 총점·회귀·시간
- run-003/comparison.csv: 166개 질문별 이전/이후 비교
- run-003/variants.json: 변형16개 순위·실제 모델 근거
- run-003/responses.jsonl: 실제 검색 결과
- run-003/quote-audit.json, date-policy-audit.json: 근거·날짜 검사
- index-preservation.json, source-preservation.json, freeze.json: 보존 기록
- final-code/: 평가한 코드, before/: 이전 코드
'''
(P/'REPORT.md').write_text(report)
print('REPORT.md written')
