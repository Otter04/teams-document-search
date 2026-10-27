# 네이티브 보강 규칙 v3

2026-10-19. `enrich.py`의 날짜 역할·근거 검증과 `native_rules.py`의 규칙 추출을 사용한다. v1/v2 파일은 수정하지 않았다. 출력 공통 규격 1.1.0은 유지하고 `rules_version`은 `rules-0.3.0`이다.

변경 사항은 거래처 라벨·폴더 별칭, TXT 제목의 메모/메일 종류, 단독 표지 날짜, 체결부 인쇄 날짜, 한글 로그 시작·종료·작업명, 오류 문맥의 코드, 명시적 번호와 표의 라벨·값 행 처리다. 원문 날짜를 수정일로 보충하거나 제출일로 추정하지 않는다. 후보가 충돌하면 검토 대기로 남긴다.

실제 파싱 블록과 사전에 선언한 거래처·시스템 목록만 입력으로 받는다. 문서 ID·정답 ID·질문별 예외나 합성 자료 생성기에는 의존하지 않는다. 이미지 본문은 만들어 넣지 않는다.

실행은 [날짜 검색 v2 빌더](../rag-date-search-v2/README.md)를 통해 한다. [비교 결과](../generalization-review-001/README.md).

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps \
  /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest discover -s outputs/rag-enrichment-v3/tests
```

63개 테스트 통과. 라벨 없는 본문 오류코드 등 모든 자연어 표현을 지원하는 추출기는 아니며, 새 자료의 H-021 오류코드 1개가 미추출로 남는다.
