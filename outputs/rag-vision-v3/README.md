# 비전 검증기 v3

v2의 검출 규칙을 그대로 호출하고, 손실 없이 표현 가능한 문제는 경고로 낮춰 공통 블록을 전달한다. v1/v2는 비교 기록으로 보존한다. API·네트워크·키를 사용하지 않는다.

- `validate_response`: `candidate`, `candidate_with_warnings`, `reject`를 반환한다. 처음 두 경우만 `transfer_allowed=true`. 원문 정확도 승인은 하지 않는다.
- `convert_checked`: 전달 가능한 응답만 공통 블록으로 변환한다. 경고는 문서·블록에 저장하고 해당 coverage 단위를 `pending`으로 남긴다. 내용은 보존하며 중복 제거·필드 이동·값 수정은 하지 않는다.
- 셀 앵커 충돌, 잘린 JSON, 잘못된 좌표/연결 참조 등 v1 구조 오류는 차단한다. 미분류 새 이슈도 자동 완화하지 않는다.
- `native_context`는 같은 페이지의 실제 네이티브 파싱 문맥만 사용한다. 정답 라벨은 검증기에 넣지 않는다. 원문 평가 참조는 평가 후 잔여 작업 목록에만 사용한다.
- `evaluate.py`는 저장된 264응답을 재사용한다. v2 이슈 검출 보존, 내용 왕복 보존, 경고·차단 단위 상태, 스키마 및 이전 결과 해시를 검사한다. CLI 실행은 네트워크 소켓을 차단한다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s outputs/rag-vision-v3 -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/rag-vision-v3/evaluate.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/rag-vision-v3/build_report.py
```

[재평가 결과](../vision-validation-run-003/README.md). 현재 오프라인 검증·변환 경로만 적용했다. 유료 호출용 기존 v1 실행기를 재실행하면 자동으로 v3가 적용되지는 않는다. 향후 새 호출 경로에 이 모듈의 `convert_checked`를 연결해야 한다.
