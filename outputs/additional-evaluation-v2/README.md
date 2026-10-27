# 추가 합성 자료 개발 재평가기 v2

v1의 정답 입력 검증·채점 계산을 유지하고 검색 구현을 `rag-date-search-v2`로 바꿨다. 원본·질문·정답과 이전 구현의 동결 해시를 계속 확인한다. 새 규칙 자체는 빌드 이력의 해시로 확인한다.

실패를 보고 개선한 자료이므로 결과에 `tuned_on_this_dataset: true`, `independent_evaluation: false`, `scope: development_retest_assistant_authored_synthetic_draft`를 기록한다. 가짜 사람 검수자를 채우거나 정식 독립 평가로 승격하지 않는다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  outputs/additional-evaluation-v2/evaluate_draft.py \
  --package outputs/additional-dataset-v1/package \
  --run outputs/additional-search-run-002 \
  --output outputs/additional-evaluation-run-new
```

[최종 비교 보고서](../generalization-review-001/README.md). 기존 최초 평가와 원본 ZIP은 그대로 보존했다.
