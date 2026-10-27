# 날짜 검색 v2와 보강 v3 통합 실행

2026-10-19. 기존 [날짜·수정시각 계약](CONTRACT.md)을 유지하고 보강 의존성을 v3로 바꿨다. 수정순 요청의 `상위/최대/첫 N개·건`을 내용 조건에서 분리하고, 전체 후보를 정렬한 뒤 요청 개수와 호출자의 limit 중 작은 값으로 제한한다. 잘못된 개수·상충한 개수는 확인 질문으로 돌린다. 일반 내용 수량이나 지원하지 않는 날짜 역할을 삭제하지 않는다.

원본 파일의 해시와 수정시각을 다시 확인하고 보강·청크·BM25 색인을 재생성한다. 기존 파싱 JSON과 원문을 재사용하며 모델·유료 API·정답 입력은 없다. [전후 비교](../generalization-review-001/README.md).

프로젝트 루트에서 새 출력 경로를 지정한다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-date-search-v2/build.py \
  --parsed outputs/additional-parsing-run-001/parsed.jsonl \
  --files-root outputs/additional-dataset-v1/files \
  --reference outputs/additional-dataset-v1/reference-data.json \
  --rules outputs/rag-rule-search-v1/rules.json \
  --output outputs/additional-search-run-new
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/rag-date-search-v2/date_search.py \
  --run outputs/additional-search-run-002 \
  --query '가장 최근에 수정된 제안서 상위 3개' \
  --as-of 2026-10-18 --limit 10
```

`evaluate.py`는 보존된 이전 날짜 검색 결과와 기존 61질문·20날짜 검사를 비교한다. 새 자료는 별도의 초안 평가기로 평가한다. 날짜·정렬 테스트는 `python3 -m unittest discover -s outputs/rag-date-search-v2/tests`로 실행하며 17개 통과했다.
