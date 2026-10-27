# 2026-10-26 Orin 서버 재개

SSH 인증 확인, Mac18022→Orin8022 터널 복구. 기존 Elasticsearch green 및 v003 문서195/청크3754 확인.

모델과 Elasticsearch를 함께 시작한 첫 시도는 모델 초기 메모리 검사 실패: 가용47.22GiB < 요구49.09GiB(80%). 모델 가중치 로딩 전 실패했다. RAG Elasticsearch만 잠시 멈춘 후 같은 Qwen 컨테이너를 다시 시작하자 초기 검사를 통과하고 기존 모델 로딩 시작. 모델80%, 문맥49152, 캐시8GiB 등 설정 변경 없음. 다른 사내 컨테이너 중지 없음.

현재 모델 로딩 중. 모델 API와 저장소·검색 서버 및 실제 검색 준비 확인 전에는 완료로 보지 않는다.

## 완료

Qwen API 모델 qwen3.6-35b-a3b/문맥49152 응답 정상. 가중치·모델 로딩323.49초, 실행 준비193.68초. 저장소 재시작 후 green. rag-search-v31-validation 시작, bge-m3 준비17.50초. Mac18022 /health ready=true, search-1.7.4,195문서·v003 연결 확인. 화면 HTTP200 및 브라우저에195개 예비문서 검색 화면 표시 확인. Q-130 실제 검색에서 D-178정답1위,3.788초. 질문분석은 기존2.5초에서 시간초과 후 규칙처리. 새 전체평가나 검색규칙 변경 없음.

rag-qwen36, rag-elasticsearch, rag-search-v31-validation 실행 중. 구버전 검색서버2개는 중지 유지. 다른 사내서비스 유지. 복구 확인 자료 health.json/smoke-search.json 보존.
