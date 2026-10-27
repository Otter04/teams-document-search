# 작업명·핵심 필드 가중치와 로그 문맥 연결

`field-search-1.0.1` · 모델 및 외부 API 호출 없음. [평가 결과](../field-search-run-002/README.md).

기존 문서 종류·시스템·날짜 필터를 유지하면서 문서 검색 점수에 근거가 있는 필드 일치 점수를 더한다. [첫 실행 전 고정한 실험 규칙](CONTRACT.md), [검색 구현](field_search.py), [평가기](evaluate.py).

## 입출력과 점수

- 입력: 기존 `rule-search-run-004/index.json`, 공통 블록 `parsing-run-003/parsed.jsonl`, `enrichment-run-001/enriched.jsonl`, 시스템 사전. 정답 라벨은 검색 입력에 포함하지 않는다.
- 준비 결과: `features.json`. 문서별 필드의 실제 값과 인용 출처, 로그 청크별 작업명·대상 시스템 문맥을 저장한다. 메타데이터는 `extracted` 값만 사용한다.
- 제목은 파일명·헤딩, 작업명·시스템·거래처·번호는 기존 추출 메타데이터, 표 역할·호스트·IP는 실제 열 제목 아래의 셀을 사용한다. 이미지 내용을 새로 추정하지 않는다.
- 문서 점수 = 해당 문서의 최고 BM25 점수 + 필드별 일치 토큰의 IDF 합 × 가중치. 작업명/표 역할 4, 식별자 3, 제목 0.5, 시스템/거래처 0.25. 같은 필드에서 반복된 값은 중복 가산하지 않는다.
- 로그 문맥은 원문 `text`를 덮어쓰지 않고 `linked_log_context`에 별도로 연결한다. 원래 작업명·시스템의 블록 인용 위치를 보존한다. 실행 로그 468개 네이티브 청크에 적용됐다.
- 표현 규칙: 작업/로그 문맥의 전환 ↔ CUTOVER, 자동으로 서버·인스턴스를 늘림/확장/증설 ↔ 오토스케일링. 임베딩이나 LLM 의미 추론은 아니다.
- `loan-db-dr01`처럼 숫자와 구분자가 포함된 기술 식별자는 필드 가산에서 정확한 식별자로 취급한다. 내부 `db`만 떼어 데이터베이스 작업명에 보너스를 주지 않는다. 명시적으로 적은 별도 `DB` 표현은 기존 개념 연결을 유지한다.
- 조건에 맞는 모든 후보를 점수화한 뒤 정렬한다. 후보를 먼저 몇 개로 자르지 않는다.

검색 결과는 `rank`, `doc_id`, `score`, `lexical_score`, `field_score`, `field_matches`(일치 토큰·가중치·출처), 최대 3개 `evidence`, 원본 경로·메타데이터를 포함한다. 순위 점수는 확률이 아니다. `conditions_verified:false`는 질문의 모든 의미 조건에 대한 최종 근거 검증을 완료한 것은 아니라는 뜻이다. 구조화된 필터 통과 여부와 구분한다.

## 재현

프로젝트 루트에서 현재 설치된 Python을 사용한다. 출력 폴더는 존재하지 않는 새 경로로 지정한다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-field-search-v1/evaluate.py \
  --index outputs/rule-search-run-004/index.json \
  --parsed outputs/parsing-run-003/parsed.jsonl \
  --metadata outputs/enrichment-run-001/enriched.jsonl \
  --reference outputs/rag-enrichment-v1/reference-data.json \
  --baseline outputs/condition-search-run-001 \
  --output outputs/field-search-reproduction-001 \
  --as-of 2026-10-17
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s outputs/rag-field-search-v1/tests -v
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-field-search-v1/field_search.py \
  --index outputs/rule-search-run-004/index.json \
  --bundle outputs/field-search-run-002/features.json \
  --query 'TMS 전환 작업 로그' --as-of 2026-10-17
```

기존/가중치만/문맥만/가중치+문맥/표현만/전체의 6개 설정을 같은 61개 질문에 적용한다. 기존 버전의 점수·순위 일치, 전체 설정 재실행 일치, 검색 도중 외부 입출력 없음, 필터 위반 없음도 검사한다. 원본과 결과의 해시는 각 실행의 `provenance.json`에 저장한다.

## 범위와 한계

첫 시도 `field-search-run-001`의 식별자 과확장 문제와 실행 당시 구현을 보존했다. 위 식별자 처리를 고친 최종 결과가 `field-search-run-002`다. 첫 실행 전 정한 필드 가중치는 변경하지 않았다.

이 규칙은 알려진 예비 데이터와 실패 질문을 보고 개선했다. 독립 평가 세트에서 일반화 성능을 확인한 것은 아니다. 6개 설정의 비교는 모든 가능한 조합의 실험도 아니다. 특히 로그 문맥 단독 적용은 이번 평가에서 성능 향상을 보이지 않았으므로 효과가 검증된 기능이라고 부르지 않는다. 비전 입력 해석·모델 선택·벡터 검색·운영 환경 검증은 이번 작업에 포함하지 않았다.
