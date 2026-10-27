# 문서 종류·대상 시스템 조건 검색

2026-10-18 · condition-search-1.0.0

[전체 작업 현황·비교 보고서](../condition-search-run-001/README.md) · [입출력/평가 규칙](CONTRACT.md)

기존 rule-search-run-004 색인과 한영 표현·날짜 규칙을 유지하고, 질의에 명시된 문서 종류·대상 시스템을 필터로 더합니다. 후보 제한 뒤 기존 BM25를 계산합니다. 색인 재생성·토큰/가중치 조정·원문 변경·모델 호출은 없습니다.

`TMS 전환 작업 로그` → 문서종류=실행 로그 AND 대상시스템=TMS. `오토스케일링 테스트 로그` → 문서종류=실행 로그. 일반 ‘구성도’는 네트워크/서버 구성도의 합집합입니다. 여러 시스템, 여러 문서 종류, 부정·대안·인용문은 무리하게 단일 조건으로 바꾸지 않습니다. 미등록 단어를 추정하지 않으며 `DB`, `DR`, `tms-db01`을 특정 대상시스템 값으로 바꾸지 않습니다.

대상시스템은 기존 보강 reference-data.json의 12개 명칭을 사용합니다. 메타데이터 status=extracted인 값만 통과시킵니다. `metadata_conditions_checked`는 적용한 필터 값의 일치를 보여주고, `conditions_verified=false`는 질문의 전체 의미 조건과 답변까지 검증한 것이 아님을 뜻합니다. 종류·시스템 인식 범위는 NFC·소문자로 정규화한 질의 기준이며 기존 날짜 범위는 원래 질의 기준입니다.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=work/schema-deps
RAG_PYTHON=/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

"$RAG_PYTHON" outputs/rag-condition-search-v1/condition_search.py \
  --index outputs/rule-search-run-004/index.json \
  --query 'TMS 전환 작업 로그' --as-of 2026-10-18

"$RAG_PYTHON" outputs/rag-condition-search-v1/evaluate.py \
  --baseline outputs/rule-search-run-004 \
  --output outputs/new-condition-search-run \
  --reference outputs/rag-enrichment-v1/reference-data.json --as-of 2026-10-17

"$RAG_PYTHON" -m unittest discover -s outputs/rag-condition-search-v1/tests -v
```

평가 기준일은 이전 실행과 동일한 2026-10-17로 고정합니다. 실제 검색의 기준일은 호출자가 지정합니다. 평가 출력 경로는 새 폴더여야 합니다. 평가 시 기존 순위·점수 동일성, 네 가지 조건 설정, 결과의 필터 위반 여부, 재실행 동일성, 색인 불변을 검사합니다. 검색 중 파일·네트워크·프로세스 접근을 차단하고 결과 고정 후에 정답을 읽습니다.

20개 새 기능 회귀 검사를 통과했습니다. 미확정 메타데이터, 부정/대안/인용, 약어 경계, 복수 종류·시스템, 필터 전 후보 잘림 방지, 날짜 조건 결합, 빈 결과 무완화 등을 검사했습니다. 별도 미공개 사내 데이터 검색 성능을 검증한 것은 아닙니다.
