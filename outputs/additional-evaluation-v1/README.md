# 합성 정답 초안 평가기

기존 `independent-evaluation-prep-v1/holdout.py`의 검색 호출과 채점 계산을 재사용한 별도 실행기다. 기존 프로그램과 동결 기준은 수정하지 않았다.

- `source_origin: synthetic_authored`, `author_id: assistant`, `reviewer_id: null`, `review_status: assistant_source_checked_pending_human`만 허용한다.
- 설정에 합성 초안 범위와 사람 독립 검수 미완료가 명시되어야 한다.
- 결과의 `independent_evaluation`과 `independent_human_review`는 항상 false다.
- 파일 해시·문서군·ID·정답 참조·필드 수·근거 존재를 검사한다. 정답을 query 입력에 넣으면 거부한다.
- 최초 자료 생성 전 파이프라인 해시와 검색 전 패키지 해시를 검사한다. 원문 근거 대조와 의미 검수는 별도 작업이며, 기계적인 입력 검사가 이를 대신하지 않는다.
- 기존 검색 함수에는 질문·limit·검색 인덱스만 전달한다. 결과를 얻은 뒤 정답과 비교한다.

[최초 실행 결과](../additional-evaluation-run-001/README.md). 별도의 사람 검수가 없는 자료를 기존 독립 평가기에서 통과시키기 위해 가짜 검수자나 수집 출처를 만들지 않는다.
