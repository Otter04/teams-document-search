# 독립 평가 패키지 양식

아래는 **작성 예시이며 실제 평가 자료가 아니다.** JSONL에는 문서 또는 질문 하나를 한 줄에 넣는다. `templates`의 빈 파일을 새 위치에 복사해 작성한다.

manifest.jsonl:

```json
{"doc_id":"H-001","source_sha256":"실제 원본 SHA256 64자리","family_key":"새 문서 계열의 고유키","source_origin":"new_collection","reviewer_id":"검수자 식별자"}
```

queries.jsonl:

```json
{"query_id":"H-Q001","query":"가장 최근 수정된 제안서","category":"modified_order","limit":5}
```

answers.jsonl:

```json
{"query_id":"H-Q001","expected_doc_ids":["H-001"],"check":"ordered","evidence":[{"doc_id":"H-001","location":"원본 저장소의 수정시각","value":"직접 확인한 시각"}],"reviewer_id":"검수자 식별자"}
```

`check`는 `relevance`(정답 포함률), `ordered`(요청한 limit까지의 정답 순서), `no_native_match`(확인된 네이티브 정답 없음), `needs_clarification` 중 하나다. 뒤의 두 경우 expected_doc_ids는 빈 배열이고 근거에는 검토 범위나 모호한 조건을 적는다. `ordered`는 상위 limit개 전체를 기록하되 실제 후보가 적으면 그 후보 전체를 기록한다. 질문의 limit보다 적은 문서만 임의로 정답으로 남기지 않는다.

metadata-labels.jsonl은 문서별 `fields` 객체에 아래 23개 이름을 모두 포함한다. 사업명은 기존 기준처럼 점수에서 제외한다.

`문서종류, 거래처, 문서일자, 대상시스템, 상태, 계약번호, 계약유형, 계약시작일, 계약종료일, 금액, 통화, VAT, 견적번호, 견적유효기간, 사이트, 작업명, 로그시작, 로그종료, 실행결과, 오류코드, 표지일, 작성일, 파일최종수정일`

```json
{"doc_id":"H-001","reviewer_id":"검수자 식별자","fields":{"표지일":{"state":"value","value":"2025-01-13","evidence":[{"page":1,"quote":"2025.01.13"}]},"작성일":{"state":"not_observed_native","value":null,"evidence":[{"scope":"확인한 전체 네이티브 본문"}]}}}
```

위 예시는 두 필드만 보여주는 발췌이며 나머지 필드도 채워야 한다. `state`는 `value`, `not_applicable`, `not_observed_native`, `unresolved`다. 근거가 부족한 날짜는 unresolved로 둔다. `not_observed_native`는 문서 전체에 정보가 없다고 확정한 값이 아니다. `value`에는 날짜·번호·금액을 문자열로 기록한다. 금액은 쉼표 없는 정수, 본문 날짜는 YYYY-MM-DD, 로그 시각은 YYYY-MM-DD HH:MM, 파일 수정일은 UTC의 `YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ`를 사용한다.

기존 필드의 네이티브 미관찰은 출력 상태 `not_found_native`, 새 역할 필드의 미관찰은 `not_observed_native`에 대응한다. 비전 확인이 필요한 필드는 unresolved로 라벨링하여 실제 확인 완료로 세지 않는다. 원본 대표일·표지일·명시적 작성일·파일 수정일을 서로 대신 넣지 않는다.

settings.json:

```json
{"reference_date":"2026-10-17"}
```
