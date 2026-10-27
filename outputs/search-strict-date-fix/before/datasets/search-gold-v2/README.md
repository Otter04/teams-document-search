# 확장 검색 평가세트 v2

2026-10-20 사용자 제공 `search_gold.jsonl`을 원본 그대로 등록했다.

- 기존 Q-001~Q-061: 61개. 질문 문구 변경 없음.
- 추가 Q-062~Q-069: 버전·날짜·완화 관련 8개.
- 새 간접 표현 Q-070~Q-099: 30개.
- 기준일: 2026-10-14. 현재 시스템은 B+R1, search-1.2.0에서 최초 평가.

`search_gold.jsonl`은 채점용이며 검색 입력으로 넣지 않는다. `query-inputs.jsonl`은 전체 99개, `new-30-query-inputs.jsonl`은 새 30개의 질문과 기준일만 담는다. `manifest.json`에 원본 경로·해시를 기록했다. 기존 61개 평가와 원본 정답은 보존한다.

실행기는 `deploy/search/evaluate_dataset.py --inputs datasets/search-gold-v2/query-inputs.jsonl --output outputs/<새 실행 폴더>`를 사용한다. 기존 폴더 응답은 덮어쓰지 않는다. 완료 후 `deploy/search/score_dataset.py --gold datasets/search-gold-v2/search_gold.jsonl --run outputs/<실행 폴더>`로 별도 채점한다.

[최초 결과: 새 30개 문서군 26/30, 필수 대표 문서 25/30](../../outputs/search-gold-v2-run-001/REPORT.md)
