# RAG 시스템 설계·평가 작업 공간

**2026-10-27 전체 토큰 재청킹 비교 완료:** 195문서를 bge-m3 입력 400~600토큰 목표로 재청킹해 별도 v004-rechunk 색인에 저장했다. 원문 청크 3,723→2,991, 기존 의미 보강 31개 유지, 제목 단독 86→0, 입력 600토큰 초과·원문 범위 누락 0. 같은 검색 설정의 150개 실제 평가에서 기존 **148/150→144/150**, 신규25개 **25/25 유지**. Q-023·Q-079는 같은 문서군의 PDF 대신 PPTX 대표 선택, Q-083·Q-097은 상위5 탈락이다. **기본 화면은 v003를 유지하며 자동 전환하지 않았다.** [비교 보고서](outputs/rechunk-v31-001/REPORT.md) · [150질문 전수 비교](outputs/rechunk-v31-001/question-comparison.csv) · [청킹 규칙](deploy/rechunk/README.md).

현재 [v3.1 검색 화면](http://127.0.0.1:18022/)은 **search-1.7.4 / B+R1 코드 기반 순위 조정**을 사용한다. Elasticsearch v003의195문서·3,754청크와 bge-m3 의미 검색을 그대로 쓴다. 후보 문서를 Qwen이 읽고 우선하는 원문 대조는 사용자 요청으로 껐다. 기존 Qwen 질문 분석은 유지한다.

**현재 실제166질문 평가:** 기존150개148/150, 표현 변형16개10/16. 원문 대조 ON으로 시험했을 때는 각각148/150,16/16이었으며, ON의 코드와 응답은 기록으로 보존했다. OFF 전체 평균1.38초, ON 실험 평균3.74초. 이 수치는 개발 질문에 한정된다.

[OFF 상태 비교 보고서](outputs/search-v31-source-review-off-001/REPORT.md) · [ON 실험 보존본](outputs/search-v31-semantic-001/REPORT.md) · [질문별 결과](outputs/search-v31-source-review-off-001/run-001/comparison.csv) · [검색 설계](docs/SEARCH_DESIGN.md) · [재접속](RESUME.md). 실제 SharePoint 수집·권한·Teams 연결 및 독립 운영 검증은 남은 범위다.

## 이전 110문서 구축 기록 — 2026-10-20

**작업 재개 완료:** VPN·SSH 연결을 확인하고 검색 단계별 청크 순위 화면을 반영했다. [최신 순위 표시·검증](outputs/search-rank-trace-001/REPORT.md) · [재접속 절차](RESUME.md).

2026-10-20 현재: **110문서의 Elasticsearch·Nori 색인을 재사용해 검색 API와 개발 확인 화면을 Orin에서 실행했다.** [검색 설계](docs/SEARCH_DESIGN.md) · [첫 검색 구현 결과](outputs/search-service-001/REPORT.md) · [검색 화면](http://127.0.0.1:18020/).

이전110문서 배포는 **search-1.5.0**이다. 명시한 기간은 키워드·벡터 검색 모두에서 필수 조건이며, 결과가 없어도 날짜를 자동으로 풀지 않는다. **99질문 실제 재평가: 기존 61/61, 새 30/30 유지. 원본 정답표 기준은 97/99(97.98%)**다. Q-068·Q-069의 원래 정답은 날짜 완화를 기대했으나 새 요청에 따라 빈 결과를 반환한다. 다른 97개는 성공 유지. Q-061은 올해 백업 로그 D-109·D-072·D-110 **3개만** 표시한다. 날짜가 지정된 11질문에서 최종 카드 29개와 두 검색 분기의 후보, 다른 버전을 대조하여 기간 밖·날짜 미확인 혼입 0건을 확인했다. [최신 보완·비교 보고서](outputs/search-strict-date-fix/REPORT.md). 개발 자료 재평가이며 독립 운영 성능을 보장하지 않는다. 질의 분석 LLM 지연·더 넓은 조건 해석·독립 평가가 남아 있다.

기존 1,072개 원문 청크·17개 의미 보강 청크와 17개 요약·1,089개 벡터는 그대로 유지했다. 이전 Elasticsearch 연결 평가는 **60/61(98.36%)**이며 [이전 전환·검증 기록](outputs/elasticsearch-migration-001/README.md)에 보존했다. 현재는 개발용 검색이고, 실제 SharePoint 수집·권한·Teams 배포는 미구현이다. 검색 중 생성형 답변을 만들거나 운영 검색 기록을 저장하지 않는다.

작성일 최신순과 제안서 내부 구성도 포함 검색도 반영했다. 작성일이 없는 자료는 별도로 표시한다. [보완·기존 61질문 비교](outputs/search-written-content-001/REPORT.md).

확장 평가세트 **99개(기존 61 + 조건 점검 8 + 간접 표현 30)**와 정답은 원본 그대로 유지했다. 재작년·계절 처리, 검색어 확장, 결합 후보 보존, 최초 버전 대표 선택을 보완했다. [보완 전 결과](outputs/search-gold-v2-run-001/REPORT.md) · [99개 질문별 전후 결과](outputs/search-gold-v2-fix/ALL_RESULTS.md) · [날짜 처리 규칙](docs/SEARCH_DESIGN.md).

## 먼저 볼 문서

| 목적 | 문서 |
|---|---|
| 현재 검색 설계·첫 구현 | [검색 설계](docs/SEARCH_DESIGN.md) · [59/61 결과와 미달 기준](outputs/search-service-001/REPORT.md) |
| 이전 Elasticsearch·Nori 저장소 전환 평가 | [전환 완료·61질문 검증·정리 내역](outputs/elasticsearch-migration-001/README.md) |
| 전환 전 평가 보존본 | [61질문 Python BM25·FAISS 비교](outputs/indexing-retrieval-eval-001/README.md) |
| 110문서 중 몇 개가 인덱싱됐는가 | [BM25·벡터 110/110 완료와 의미 보강 17문서](outputs/indexing-110-semantic-vector-001/README.md) |
| LLM 보강 전의 보존본 | [기존 결과 재사용 BM25 색인](outputs/indexing-110-bm25-001/README.md) |
| 어떤 모델을 왜 선택했는가 | [모델 선정 결정서](docs/MODEL_SELECTION.md) |
| Orin에 어떤 모델·설정을 올렸는가 | [실제 서빙 모델: Qwen3.6-35B-A3B-AWQ-4bit](docs/ORIN_ENVIRONMENT.md) |
| 다음에 무엇을 해야 하는가 | [남은 작업](NEXT_TASK.md) |
| Orin 서버 접속·테스트 결과 | [로컬 서빙 검증](outputs/orin-serving-run-001/README.md) |
| Orin 전체 평가·캐시 오류 처리 | [현재 평가](outputs/orin-evaluation-run-001/README.md) |
| 보강 근거 표기 오류 처리·평가 결과 재사용 | [검증 기준 v2와 재사용 범위](docs/ENRICHMENT_DELIVERY_POLICY.md) |
| 기존 110개 중 LLM 필요 범위·예상 시간 | [문서별 분류·재사용·시간 재산정](outputs/indexing-plan-110-001/README.md) |
| OpenRouter 67장 채택·남은 54장 교정 결과 | [121장 원문·구조 재사용 준비 / 필수 재호출 0장](outputs/vision-reuse-review-001/README.md) |
| 자료를 종류별로 찾아보기 | [자료모음](docs/자료모음/README.md) |
| 폴더별 역할과 전체 위치 | [폴더 안내](docs/FOLDER_GUIDE.md) |
| 이번 정리에서 무엇을 바꿨는가 | [정리 기록](docs/ORGANIZATION_LOG.md) |

## 현재 상태

| 영역 | 확인된 결과 | 구분해야 할 범위 |
|---|---|---|
| 공통 블록·네이티브 파싱 | 규격과 예비 자료의 파싱·평가 구현 | 모든 이미지 해석 완료를 뜻하지 않음 |
| 규칙 보강·청킹·검색 | 기존 네이티브 60/60, 추가 자료 47/47 Hit@5; 추가 자료 수정순 6/6 | 개발 자료 재평가이며 독립 운영 성적이 아님 |
| 비전 모델 비교 | 전체 132장, 원문 대조·공통 JSON 전달 평가 완료 | 오독·누락·위치·중복 문제 일부 잔존 |
| 기존 110문서용 비전 결과 재사용 | OpenRouter 기존 67장 + 규칙 교정 49장 + 원본 대조 교정 4장 + 직접 복원 1장 = 121장, 30문서의 BM25 색인에 반영 | 원문·표·노드·연결 관계 범위. 자유 설명 103문장은 사실 색인에서 제외. Orin 비교 점수는 변경하지 않음 |
| 현재 인덱싱 | Orin Elasticsearch 8.19.23·Nori·BM25, 110문서·1,089청크. 저장 내용 전수 대조·재시작 검증 완료 | 원본 색인 보존. 현재 검색 결과는 별도 검색 서비스 평가를 참조 |
| 임베딩 | Orin 기존 bge-m3, 1,089개·1,024차원, 입력 잘림 0건 | 재생성 없이 Elasticsearch dense_vector(flat/cosine)로 이전. 기존 FAISS는 Orin에서 삭제, Mac 평가 보존본만 유지 |
| 문서 보강 비교 | 공통 20문서 × 두 모델, 40응답·요약 대조 완료 | 양 모델 모두 사전 자동 전달 합격 기준 미달 |
| 모델 선택 | **Qwen3.6-35B-A3B 확정** | 선택 완료와 운영 검증 완료는 별개 |
| 로컬 모델 서버 | **Qwen3.6-35B-A3B-AWQ-4bit**, Docker·vLLM 서빙. 기본 요청 검증 후 전체 문맥 49,152·최대 출력 16,384·KV 캐시 8GiB 적용 | 80% 인자보다 직접 지정한 캐시 예산이 우선함. 전체 평가 완료 여부는 평가 기록 참조; 부하·재시작 복구는 미검증 |
| 검색 첫 구현 | Orin API·개발 화면, 기존61/61·새30/30, 원본99 기준97/99(날짜 정책 변경 2건), R1·문서군·직접 근거 | 전체 품질 합격·실제 SharePoint·권한·Teams 연결은 미완료 |
| 운영화 | 검색 설계 기준 Jetson AGX Orin 64GB, Spark 전환 보류 | 실제 수집·권한·독립 검증·동시 부하·Teams 배포 미완료 |

공통 블록은 [규격](outputs/common-block-design/SCHEMA.md), 단계 흐름은 [비전 LLM 반영 그림](outputs/diagrams/rag-pipeline-vision-llm.png)을 참조한다. 그림은 단계 설명용이며 현재 완료 상태는 이 문서를 기준으로 한다.

## 자주 보는 근거

- [비전 원문 대조](outputs/vision-source-review-001/README.md) · [비전 전달 정책 v3](outputs/vision-validation-run-003/README.md)
- [보강 비교 보고서](outputs/enrichment-comparison-run-001/REPORT.txt) · [원문과 두 결과 비교 화면](outputs/enrichment-comparison-run-001/comparison.html)
- [추가 자료와 기존 자료의 검색 비교](outputs/generalization-review-001/README.md)

`docs/자료모음/`은 목적별 폴더와 바로가기로 구성했다. `outputs/`는 실험 원본·코드의 고정 저장 위치, `work/`는 내부 작업·의존성 공간이다. 평소에는 이 README와 자료모음에서 시작하면 된다.

현재 결정을 과거 보고서에 덧붙여 반복 기록하지 않는다. 과거 준비 상태·실험 결과는 [이전 안내문 보관본](docs/archive/README.md)에 보존했다. 기존 평가의 정답·점수·원응답은 바꾸지 않았다.
