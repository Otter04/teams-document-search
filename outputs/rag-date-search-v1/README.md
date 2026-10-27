# 파일 수정일·날짜 역할 검색 v1

2026-10-18 · 로컬 네이티브 파이프라인 · 유료 API/모델 호출 없음.

[실제 110문서 실행과 비교 결과](../date-search-run-001/README.md) · [구현 계약](CONTRACT.md) · [메타데이터 기준 및 29건 처리](../metadata-policy-v1/README.md) · [독립 평가 준비](../independent-evaluation-prep-v1/README.md).

## 저장 구조

기존 공통 블록과 보강 결과를 그대로 유지하고, `doc_id + source_sha256`으로 연결하는 별도 메타데이터 파일을 추가했다.

- `source-metadata.jsonl`: 원본 해시가 파싱 입력과 같은지 확인한 파일 최종 수정시각. UTC 문자열, 나노초 값, 수집시각, 파일 경로와 출처를 저장한다.
- `date-metadata.jsonl`: `fields.표지일`, `fields.작성일`, `fields.파일최종수정일`에 값·상태·역할·근거를 저장한다. 작성일은 explicit_written_date만 사용한다.
- `index.json`: `documents[doc_id].date_metadata`로 같은 정보를 저장해 날짜 필터와 정렬에 사용한다. 본문 토큰·청크·기존 20개 메타데이터는 바꾸지 않는다.
- `enriched.jsonl`, `chunks.jsonl`: 기존 규격을 유지한다. 새 날짜 필드는 문서 색인에서 조회하므로 기존 청크 필터에 중복 삽입하지 않는다.

`not_observed_native`는 네이티브 본문에서 관찰하지 못했다는 뜻이다. 문서 전체에 작성일이 없다는 단정이나 비전 처리 완료를 의미하지 않는다. `needs_review`는 같은 역할의 값이 충돌한 경우다.

## 수집·색인 실행

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-date-search-v1/build.py \
  --parsed outputs/parsing-run-003/parsed.jsonl \
  --files-root /path/to/dataset/files \
  --reference outputs/rag-enrichment-v1/reference-data.json \
  --rules outputs/rag-rule-search-v1/rules.json \
  --output outputs/new-date-run
```

output은 새 경로를 사용한다. 원본 변경이나 파싱 해시 불일치는 수집을 중단하므로 원본이 바뀌면 먼저 다시 파싱해야 한다. 이 구현은 로컬 파일시스템 기준이다. SharePoint 등 원본 저장소의 수정시각 수집과 자동 증분 갱신은 별도 연결 작업이다. 파일 복사·다운로드로 달라진 로컬 수정시각을 업무 작성일로 해석하지 않는다.

## 검색

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-date-search-v1/date_search.py \
  --run outputs/date-search-run-001 \
  --query '청람정밀 가장 최근에 수정된 제안서' \
  --as-of 2026-10-17 --limit 5
```

지원 예시:

- `청람정밀 가장 최근에 수정된 제안서`, `청람정밀 수정일 오름차순 제안서`
- `청람정밀 2025년 1월 14일 수정된 제안서`
- `청람정밀 표지 날짜 2025년 1월 13일 제안서`
- `MES 작성일 2025년 2월 24일 네트워크 구성도`

최신 수정순 검색은 문서종류·시스템·거래처 등 지원하는 조건과 본문 검색 후보를 적용한 뒤 **전체 후보를 정렬하고 마지막에 limit을 적용**한다. 동일 수정시각은 관련성 점수, 문서 ID 순이다. 수정시각이 없는 문서는 미확인 목록으로 분리한다. `최신 제안서`만으로 승인본/최종본을 수정일순으로 해석하지 않는다.

여러 날짜 역할이 섞인 질문, 부정·비교 조건, `최근 3일` 등 아직 지원하지 않는 표현은 `status: needs_clarification`과 경고를 반환한다. `conditions_verified: false`는 지원하는 메타데이터 조건의 확인과 자연어의 모든 의미 조건 충족을 구분하기 위한 값이다. 자유로운 복합 내용 조건까지 모두 검증한 검색기는 아니다.

## 검증

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s outputs/rag-date-search-v1/tests -v
```

새 검사 19개는 날짜 역할, UTC/한국 날짜 경계, 나노초 정밀도, 원본 변경·경로 이탈, 150개 후보의 전역 정렬, 누락 시각, 동률, 독립 평가 입력 검사를 포함한다. 별도로 기존 보강 검사 46개, 실제 개발 질문 61개, 날짜 확장 20개를 확인했다. 날짜 확장 사례는 [고정된 개발 검사](development-date-cases.json)이며 독립 평가가 아니다.
