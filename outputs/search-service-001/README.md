# 검색 첫 구현 산출물

- [결과·통과 기준·남은 작업](REPORT.md)
- [설계와 사용 기술](../../docs/SEARCH_DESIGN.md)
- [검색 확인 화면](http://127.0.0.1:18020/) — VPN과 SSH 연결 필요, 개발용
- [최종 비교](evaluation/corrected-004/summary.json), [반복](evaluation/repeat-005/summary.json), [순서 동일성](repeat-check.json)
- [소스 보존](source-preservation.json), [문서군 추정 근거](family-review.json), [모델 파일 신원](embedding-identity.json)

현재 기본값은 B+R1. 59/61(96.72%)이며 전체 운영 합격은 아니다. 기존 17개 요약과 1,089개 벡터를 재사용했다. 원래 정답·저장 응답을 수정하지 않았다. 기록된 질의는 고정 평가용이고, 운영 검색 API는 사용자의 검색 기록을 저장하지 않는다.
