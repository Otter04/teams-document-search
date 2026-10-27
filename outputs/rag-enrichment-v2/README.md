# 메타데이터 기준 정리와 날짜 역할 추출

rules-0.2.1 · schema 1.1.0 · 모델/API 사용 없음. [실제 110문서 비교 결과](../metadata-review-run-002/README.md).

기존 `rag-enrichment-v1`은 그대로 보존하고 그 규칙을 상속하는 새 버전이다. 원문 파싱 JSON을 바꾸지 않고 새 보강 JSON을 만든다. 문서종류·대상시스템·날짜 등 기존 필드에 더해 날짜의 역할·선택 근거를 `date_context`에 기록한다. [기준](CONTRACT.md), [구현](enrich.py), [재실행 및 비교](run.py).

## 현재 날짜 기준

문서일자는 본문의 대표 날짜로 유지하고 파일 최종 수정일은 별도 항목으로 다룬다. 원문 근거 없는 제출일은 추정하지 않으며 필수 필드로 추가하지 않는다. 수정일 수집·최신순 검색은 아직 구현되지 않았다. [단계별 날짜 필드와 실제 D-002 값](../metadata-review-run-002/DATE_FIELDS.md). 기존 실행 당시 계약·평가 결과는 그대로 보존한다.

## 바뀐 동작

- 표지 날짜, 명시적 작성일, 견적일자, 메일 발송일, 로그 시작일, 점검일, 체결부 표기일, 계약기간을 구분한다.
- 초안에 `작성일: 2025-02-07`이 명시되고 체결부에는 `2025-02-19`가 있다면 문서일자는 작성일을 사용하고 체결부 날짜는 별도 관찰값으로 남긴다. 작성일이 없으면 초안 체결부 날짜만으로 문서일자를 확정하지 않는다.
- 잘못된 달력 날짜·같은 역할의 충돌은 보류한다. 구성도의 여러 속성이 한 줄에 있는 머리말은 명시적 작성일로 인식한다.
- 메일 시스템명은 현재 첫 From/Subject 헤더의 원문 근거를 추가한다. 전달 메일 제목과 본문에 나온 시스템을 임의로 수집하지 않는다.
- 새 날짜 역할은 검색 필터에 자동 추가하지 않는다. 기존 확정 필드만 색인한다.

`date_context.observations` 항목은 `role`, `value`, `rule_id`, `evidence`, `assertion`을 가진다. `assertion: source_statement_only`는 원문에 적힌 내용의 관찰이라는 뜻이다. 서명본 파일명이 있어도 실제 서명을 검증했다고 간주하지 않으므로 `actual_signature_verified`는 false다.

JSON 스키마는 [실행 결과의 enrichment.schema.json](../metadata-review-run-002/enrichment.schema.json)에 있다. 기존 1.0.0 소비자는 새 최상위 필드와 규칙 버전을 지원해야 한다. `run.py`는 새 `enrich` 모듈을 먼저 로드해 기존 청킹·검색 모듈에 같은 검증기를 연결한다. 기존 구현 파일을 수정하거나 새 결과를 구버전인 것처럼 저장하지 않는다. 내부적으로 기존 인용·필드 검증을 재사용하고 새 날짜 역할 검증을 추가한다.

## 실행

프로젝트 루트에서 아래 명령을 사용한다. `--dataset`은 실제 예비 데이터셋 폴더 경로로 지정한다. 출력에 기존 `enriched.jsonl`이 있으면 덮어쓰기를 거부한다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-enrichment-v2/run.py \
  --parsed outputs/parsing-run-003/parsed.jsonl \
  --reference outputs/rag-enrichment-v1/reference-data.json \
  --metadata-baseline outputs/enrichment-run-001/enriched.jsonl \
  --search-baseline outputs/field-search-run-002 \
  --dataset '/실제/예비데이터셋/폴더' \
  --output outputs/metadata-review-reproduction-001 \
  --as-of 2026-10-17
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s outputs/rag-enrichment-v2/tests -v
```

추출·검색 중 파일/네트워크/외부 프로세스 접근을 차단한다. 필요한 코드와 데이터는 먼저 읽고 정답은 추출·검색 완료 후 평가 때 읽는다. 생성기는 원인 조사 스크립트에서만 읽으며, 추출 프로그램은 생성기나 문서별 정답값을 사용하지 않는다. 날짜를 하루 더하거나 12일 빼는 데이터셋 전용 보정도 없다.

## 비교의 한계

실제 110문서에서는 기존 평가 필드의 값·상태가 바뀌지 않았다. 따라서 기존 정답표의 정확도나 검색 성능이 상승한 것은 아니다. 50개 필드의 규칙/근거/보류 설명을 정리하고 155개 날짜 관찰의 역할을 추가했다. 개선 동작을 확인한 변형 입력 검사는 합성 검사이며 실제 초안 13건에서 작성일을 새로 발견했다는 뜻이 아니다.

구성도 복합 머리말을 누락한 첫 실행은 `metadata-review-run-001`과 그 폴더의 `implementation/`에 보존했다. 이를 보완한 최종 실행이 `metadata-review-run-002`다. 전체 시각 자료와 운영 품질은 아직 별도 검증 대상이다.
