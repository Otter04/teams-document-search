# RAG 시스템 설계·평가 작업 공간

2026-10-20 현재: **110/110문서의 BM25·bge-m3 벡터 색인을 완료했다.** [최신 현황과 결과](outputs/indexing-110-semantic-vector-001/README.md). 기존 원문 1,072청크·규칙값 935개를 보존하고, 17문서에 Orin Qwen3.6 의미 보강·발췌형 요약을 추가했다. 총 1,089개 벡터를 생성했다. 새 보강 호출 17건이며 비전·외부 유료 API 호출은 없다. 검색·답변은 이번 작업에서 구현·실행하지 않았다. 이전의 45응답 비교 작업은 재개하지 않았다.

후속 요청으로 [기존 61질문 오프라인 회귀 평가](outputs/indexing-retrieval-eval-001/README.md)를 실행했다. 최신 BM25는 Hit@5·평균 문서 Recall@5 100%, bge-m3 단독은 85.25%·83.06%, 단순 결합은 100%·99.18%다. 개발 세트 재평가이며 사용자용 검색·답변 서비스는 구현하지 않았다.

## 먼저 볼 문서

| 목적 | 문서 |
|---|---|
| 기존 Q 질문으로 최신 색인을 평가한 결과 | [61질문 BM25·벡터·결합 비교](outputs/indexing-retrieval-eval-001/README.md) |
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
| 현재 인덱싱 | 110/110문서 BM25·벡터 색인. 기존 1,072청크 + 새 의미 청크 17개. 규칙값 935개 보존 | Orin 의미 보강 17문서, 48필드·118구절·발췌형 요약 17개. 어시스턴트 원문 검수이며 검색 성적을 뜻하지 않음 |
| 임베딩 | Orin 기존 bge-m3, 1,089개·1,024차원, 입력 잘림 0건 | FAISS 저장·재로드·벡터 재구성 검증 완료. 검색·답변 구현은 하지 않음 |
| 문서 보강 비교 | 공통 20문서 × 두 모델, 40응답·요약 대조 완료 | 양 모델 모두 사전 자동 전달 합격 기준 미달 |
| 모델 선택 | **Qwen3.6-35B-A3B 확정** | 선택 완료와 운영 검증 완료는 별개 |
| 로컬 모델 서버 | **Qwen3.6-35B-A3B-AWQ-4bit**, Docker·vLLM 서빙. 기본 요청 검증 후 전체 문맥 49,152·최대 출력 16,384·KV 캐시 8GiB 적용 | 80% 인자보다 직접 지정한 캐시 예산이 우선함. 전체 평가 완료 여부는 평가 기록 참조; 부하·재시작 복구는 미검증 |
| 운영화 | 최종 DGX Spark 예정 | 실제 수집·권한·벡터 검색·독립 검증·Spark 구동 미완료 |

공통 블록은 [규격](outputs/common-block-design/SCHEMA.md), 단계 흐름은 [비전 LLM 반영 그림](outputs/diagrams/rag-pipeline-vision-llm.png)을 참조한다. 그림은 단계 설명용이며 현재 완료 상태는 이 문서를 기준으로 한다.

## 자주 보는 근거

- [비전 원문 대조](outputs/vision-source-review-001/README.md) · [비전 전달 정책 v3](outputs/vision-validation-run-003/README.md)
- [보강 비교 보고서](outputs/enrichment-comparison-run-001/REPORT.txt) · [원문과 두 결과 비교 화면](outputs/enrichment-comparison-run-001/comparison.html)
- [추가 자료와 기존 자료의 검색 비교](outputs/generalization-review-001/README.md)

`docs/자료모음/`은 목적별 폴더와 바로가기로 구성했다. `outputs/`는 실험 원본·코드의 고정 저장 위치, `work/`는 내부 작업·의존성 공간이다. 평소에는 이 README와 자료모음에서 시작하면 된다.

현재 결정을 과거 보고서에 덧붙여 반복 기록하지 않는다. 과거 준비 상태·실험 결과는 [이전 안내문 보관본](docs/archive/README.md)에 보존했다. 기존 평가의 정답·점수·원응답은 바꾸지 않았다.
