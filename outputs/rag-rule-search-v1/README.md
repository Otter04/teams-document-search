# 모델 없는 한영 표현·날짜 조건 검색

2026-10-17 · rule-search-1.0.3 · operations-vocabulary-1.0.1

기존 청크와 메타데이터를 그대로 사용하고 검색 규칙만 추가했습니다. [실제 비교 보고서](../rule-search-run-004/README.md), [초기 입출력·평가 규칙](CONTRACT.md), [수동 용어 사전](rules.json).

## 구현한 범위

- 22개 운영 개념의 한영 표기를 질의·색인 양쪽에서 공통 토큰으로 연결합니다. 예: 페일오버/failover, 백업/backup. 원문 문자열은 변경하지 않습니다.
- 밑줄로 묶인 식별자의 전체 형태를 보존하면서 구성 단어도 검색합니다. `HAKSA_AUTOSCALE_TEST`에서 AUTOSCALE과 TEST를 찾을 수 있고 버전 `2.3.0`도 보존합니다.
- DG 약어와 일반적인 ‘전환’은 주변 문맥이 맞을 때만 기술 개념으로 연결합니다. 임의의 번역·새로운 사실 생성은 하지 않습니다.
- 절대 연/월/일과 올해·작년·지난해·재작년·내년, 이번 달·지난달·다음 달, 오늘·어제를 달력 구간으로 바꿉니다. 기준일은 호출자가 필수로 제공합니다.
- 일반 로그 날짜는 로그시작, ‘로그 종료’를 명시하면 로그종료, 작성일을 명시하면 문서일자, 계약 시작/종료일을 명시하면 해당 필드에 적용합니다. ‘2025년 유지보수 계약’은 날짜 역할이 모호하므로 보류합니다.
- ‘실패한 로그’처럼 최종 결과가 명시되면 실행결과 필터도 적용합니다. ‘오류 난 로그’는 실패로 단정하지 않습니다.
- 미지원 복수 날짜·분기·월말·부정·비교 표현은 경고와 함께 보류합니다. `Q-2504-02` 같은 번호를 날짜로 해석하지 않습니다. 빈 검색 결과에서 필터를 몰래 완화하지 않습니다.

정규화된 텍스트에 대한 concept_matches, 날짜/조건의 query_plan, 적용 filters, 보류 warnings, 원문 위치가 출력됩니다. concept_matches의 문자 범위는 NFC·소문자 정규화한 텍스트 기준입니다. 날짜 해석 범위는 입력 질의 문자열 기준입니다.

conditions_verified=false는 질문 전체 조건 충족을 판정하지 않았다는 뜻입니다. 명시된 날짜 필터를 통과했더라도 다른 의미 조건이나 답변까지 검증한 것은 아닙니다. 현재 검색은 여전히 단어·음절 기반 BM25입니다.

## 실행

프로젝트 루트에서 기존 환경을 사용합니다. 별도 모델·패키지 설치는 필요하지 않습니다.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=work/schema-deps
RAG_PYTHON=/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

"$RAG_PYTHON" outputs/rag-rule-search-v1/search.py search \
  --index outputs/rule-search-run-004/index.json \
  --query '작년 12월 DB 백업 로그' --as-of 2026-10-17

"$RAG_PYTHON" outputs/rag-rule-search-v1/search.py build \
  --baseline outputs/native-search-run-002/index.json \
  --output outputs/new-rule-search-run

"$RAG_PYTHON" outputs/rag-rule-search-v1/evaluate.py \
  --run outputs/new-rule-search-run \
  --baseline outputs/native-search-run-002 --as-of 2026-10-17

"$RAG_PYTHON" -m unittest discover -s outputs/rag-rule-search-v1/tests -v
```

build/evaluate는 새 출력 경로를 요구합니다. 기본 rules.json 외 사전을 사용하려면 build에 --rules를 전달합니다. 평가 질문·정답은 사전에 넣지 않습니다. 생성된 색인 안에 사용 사전을 함께 저장하므로 검색 시 임의의 새 사전을 읽지 않습니다.

## 평가와 수정 이력

27개 기능 회귀 검사가 통과했습니다. 윤년·연도 경계·기준일 변경·모호한 기간·부정 조건·복수 날짜·번호 오인·문맥 없는 약어·필터 미충족 시 빈 결과·원문/메타데이터 보존을 확인했습니다.

기존 61개 질문으로 기존, 표현만, 날짜/명시 결과 조건만, 둘 다의 네 경우를 비교했습니다. 각 검색 중 파일·네트워크·프로세스 접근을 차단했고, 검색 결과가 고정된 뒤에 정답을 읽었습니다. 단, 사전은 기존 실패 분석을 참고해 만들었으므로 독립적인 미공개 평가가 아닙니다.

- run-001: 첫 비교. ‘전환’을 넓게 switchover로 연결해 순위 악화가 관찰됨.
- run-002: ‘전환’ 연결을 DB 관련 문맥으로 제한. Q-020은 상위 10개 밖에서 6위로 회복했지만 기존 5위보다 낮음.
- run-003: 복수 날짜의 일부만 잘라 적용하지 않도록 보호하고 명시적 로그 종료일 지원.
- run-004: 견적번호 등을 날짜로 오인하는 경계 처리 수정. 최종 사용 결과.

각 이전 실행에는 그 당시 구현·사전 사본과 평가가 보존되어 있습니다. 결과를 맞추기 위한 문서 ID별 가중치, 질문별 정답 필터, 정답 수정은 없습니다. 초기 CONTRACT는 첫 평가 전 기준으로 유지하며, 명시적 로그 종료 시각 지원 등 구현 보완은 이 README에 기록합니다.
