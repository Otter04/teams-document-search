# 비전 응답 검증기 v2

네트워크나 API 키를 사용하지 않는 검사·변환 코드다. 기존 rag-vision-v1/contract.py의 응답 스키마와 공통 블록 변환 코드를 재사용하고 그 앞에 품질 검사를 추가했다. 동결 v1 파일은 수정하지 않았다.

`validate_response(response, item, expected_model)`은 candidate/review/reject와 근거 경로를 반환한다. `candidate`는 규칙 통과 후보일 뿐 의미 정확도 합격이 아니다. `convert_checked(record, item, response, model)`은 candidate만 공통 블록으로 변환한다. review/reject는 예외를 발생시켜 전달을 차단한다. 입력은 수정하지 않는다.

`item.native_context`는 기존 네이티브 파서가 추출한 같은 페이지/슬라이드의 문맥이다. 정답 라벨이나 검수 주석을 넣으면 안 된다. 스캔처럼 문맥이 없으면 원문 문구 대조에 기반한 필드 배치·출현 횟수 검사는 수행할 수 없다.

중간 종료 응답의 접두 복원은 evaluate.py의 진단용이다. convert_checked에서는 완결된 JSON과 finish_reason=stop을 요구하며, 접두 진단 결과를 변환하지 않는다. evaluate.py만 별도의 원문 평가 결과를 읽어 잔여 작업 목록을 만든다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s outputs/rag-vision-v2 -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/rag-vision-v2/evaluate.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/rag-vision-v2/build_report.py
```

[기존 응답 재평가 결과](../vision-validation-run-002/README.md). 온라인 호출기를 새로 연결하거나 API를 재호출하지 않았다. 기존 유료 실행기 v1을 다시 실행하면 자동으로 v2가 적용되는 구조는 아니므로, 향후 새 온라인 실행을 만들 때 convert_checked를 통합해야 한다.
