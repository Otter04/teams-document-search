"""Render the completed expression-link evaluation, with its limitations."""
import json
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=R/'outputs/search-v31-expression-001';RUN=O/'run-001'
def read(p):return json.loads(p.read_text())
s=read(RUN/'summary.json');audit=read(RUN/'date-policy-audit.json');complete=read(RUN/'complete.json');prior=read(R/'outputs/search-v31-fix-001/run-004/summary.json');scores={x['query_id']:x for x in read(RUN/'scores.json')};metric='all_required_representatives_found'
def ratio(x):return f"{x[metric]}/{x['questions']} ({100*x[metric]/x['questions']:.1f}%)"
def target(qid,did):return next(c['representative_rank'] for c in scores[qid]['expected_cards'] if c['representative']==did)
text=f'''# Q-130·Q-131 의미 표현 연결 개선 및 150개 회귀 평가

search-1.7.3 → search-1.7.4. 기존 Elasticsearch v003의195문서·3,754청크 및 bge-m3 벡터를 재사용했다. 새 문서 파싱·비전·보강·문서 임베딩은 실행하지 않았다. 질문 분석은 기존 Orin Qwen 모델 ON/2.5초, 필터 B, 순위 조정 R1을 유지했다. 외부 유료API는 사용하지 않았다.

## 실제 결과

성공 기준은 질문에 지정된 **필수 정답 대표 문서가 모두 최종 상위5에 포함**되는 것이다. 생성형 최종 답변 정확도 또는 정답1위 비율이 아니다.

| 범위 | 개선 전 | 개선 후 |
|---|---:|---:|
| 기존125개 | {ratio(prior['old125_same_gold'])} | {ratio(s['old125'])} |
| 신규25개 | {ratio(prior['new25'])} | {ratio(s['new25'])} |
| 전체150개 | {ratio(s['before150'])} | {ratio(s['after150'])} |

복구: {', '.join(s['recovered'])}. 새 필수 정답 실패: {', '.join(s['regressed']) or '없음'}. 상위5 문서 순서가 바뀐 질문: {', '.join(x['query_id'] for x in s['top5_order_changes']) or '없음'}. 나머지 {150-len(s['top5_order_changes'])}개 질문은 상위5 문서와 순서까지 같았다.

## Q-130: 저장장치 처분에 대한 답변

질문: “옛날 장비 저장장치 어떻게 처분하라고 공공기관이 답해 준 문서”

정답 D-178 **OUDC_질의 답변서_250910.docx**: 개선 전 상위5 밖 → **{target('Q-130','D-178')}위**.

원문 표의4번 질의는 “디스크 폐기 확인서”이며 답변은 “폐기 대상 디스크는 공사 직원 입회하에 물리 파쇄하고 파쇄 확인서를 제출할 것”이다. 정보는 기존 공통JSON과 색인에 이미 있었다. 개선 전에는 의미 후보에 들어왔으나 최종 결합에서 장비 목록·계약서·제안 질의서 등에 밀렸다.

질문에서 저장장치·저장매체·디스크·HDD·SSD와 처분·폐기·파쇄 행위가 함께 있을 때에만 두 표현군을 연결한다. “답해 준/답변/회신”까지 명시하면 기존 원문에 답변·회신 근거도 있는 문서를 우선한다. D-176·D-177 질의서는 폐기 방법을 물어보는 내용이고 D-178은 처리 방법을 답한 내용이므로 이를 구분한다. 단순 저장장치 구매나 투자자산 처분에는 이 복합 규칙을 적용하지 않는다.

## Q-131: 품질 쪽 평가 비중

질문: “공공기관이 심사할 때 품질 쪽 비중을 훨씬 크게 잡는다고 알려 온 문서”

정답 D-175 **온새미도시공사_시설관리시스템 노후서버 교체_제안요청서.pdf**: 개선 전 두 후보 목록에 없음 → **{target('Q-131','D-175')}위**.

원문의 “제안서 평가” 항목에는 “기술 평가80점, 가격 평가20점”이 있다. 질문의 품질·비중·심사 표현과 원문의 기술 평가·점수 표현이 달라 정답이 검색 후보에 들어오지 못했다.

품질·기술 표현과 비중·배점·가중치·점수 표현이 함께 있고, 심사·평가 맥락까지 확인될 때만 기술평가·품질평가 및 배점 표현으로 확장한다. 숫자80·20, 기관명, 문서ID 또는 질문ID를 검색 규칙에 넣지 않았다. “품질”이라는 단어만 있다고 기술평가 자료를 우선하지 않는다.

## 바뀐 단계와 보존한 기준

질문 해석의 검색어 확장만 바꿨다. 확장한 표현군은 그룹 안에서는 대안이고, 그룹 사이에서는 함께 나타나야 한다. 원문과 확정 메타데이터를 확인하는 기존 선호 규칙을 통해 후보를 찾고 우선순위를 부여한다. 이것은 답변을 새로 생성하거나 기관을 추측해 강제로 거르는 규칙이 아니다. 문서/질문 임베딩 모델, RRF 계산, R1 가중치, 대표 버전 선택, 긴 로그 후보 보정은 그대로다.

제공 정답은 수정하지 않았다. 실행기에는 질문·기준일만 전달했으며 정답은 응답 저장 후 채점에 사용했다. 이번150개 중 새 복합 규칙이 발동한 질문은 Q-130·Q-131뿐이다. 별도의 표현 변형·부정 적용 사례와 기존 날짜/검색 회귀 검사를 포함한100건의 코드 검사를 통과했다.

## 남은 미달과 시간

남은 필수 정답 미달: {', '.join(s['after150']['failed_required_representative_queries'])}. 기존 Q-068·Q-069는 명시된 기간과 제공 정답의 충돌을 유지한 것이다. 해당 기간에 결과가 없다고 날짜를 자동으로 풀지 않았다.

날짜 검사{audit['date_questions']}개: 조건 고정{audit['locked_ranges']}개, 날짜 자동 완화{audit['date_relaxations']}건. 기간 밖 또는 날짜 미확인 문서 혼입은0건이며 Q-061은 올해 백업 로그3개만 반환했다.

평균 검색 시간 {s['before150']['mean_client_seconds']:.3f}초 → {s['timing']['mean']:.3f}초. 이번 중앙값{s['timing']['median']:.3f}초, P95{s['timing']['p95']:.3f}초, 최대{s['timing']['max']:.3f}초. 전체 실행{complete['elapsed_seconds']:.1f}초, 요청 오류{complete['errors']}건. 질문 분석 LLM 시도{s['llm_attempts']}개, 유효 응답 채택{s['llm_accepted']}개. 시간초과·검증실패 시 기존 규칙으로 돌아가는 정책을 유지한다.

정답 대표가1위인 질문은 {s['before150']['required_representative_top1']}/150 → {s['after150']['required_representative_top1']}/150이다. 신규25개100% 통과는 상위5 기준이며 독립된 새로운 자료의 일반화 성능을 뜻하지 않는다. 기존 선택형 추가 정답 누락과 기타 운영 검증 과제는 이번 두 질문의 수정과 별개다.

## 근거 파일

- `run-001/query-results.csv`: 150개 질문별 이전·현재 성공, 필수 정답 순위, 상위5, 시간
- `run-001/responses.jsonl`: 실제 원시 검색 응답
- `run-001/summary.json`: 직전146/150 결과와 비교 및 모든 순위 변화
- `run-001/date-policy-audit.json`: 날짜 조건 독립 점검
- `source-preservation.json`, `runtime-verification.json`: 원본195개 및 Elasticsearch3,949개 레코드 보존 확인
- `immutable-artifacts.json`, `baseline.json`, `before/`, `code-001/`: 기존 산출물·정답·응답·코드 보존
- `tests.txt`: 회귀 검사100건
'''
(O/'REPORT.md').write_text(text);print(O/'REPORT.md')
