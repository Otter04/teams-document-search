# 현재 구조와 코드 진입점

게시 기준: 2026-11-12. README의 평가 환경 표를 공통 데이터 기준으로 사용합니다.

## 인덱싱

원본 → 형식별 파싱·공통 블록 JSON → 규칙 메타데이터·필요한 비전/LLM 보강 → 토큰 청킹 → bge-m3 문서 임베딩 → Elasticsearch 텍스트·벡터 색인. 이번 검색 평가에서는 기존 청크와 벡터를 재사용했습니다.

## 검색 단계

1. 질문 원문과 고정된 날짜·필터 계획을 입력합니다. 이번 실험은 기준일 2026-10-14와 저장된 검색 요청을 사용했습니다. 날짜 처리 자체를 새로 검증한 실험은 아닙니다.
2. Qwen이 원래 의도를 유지하는 A·B 표현을 생성합니다. JSON 형태·잘림·일부 식별자 보존 등을 검사합니다. 이 검사는 모든 의미 누락을 검출하는 검사가 아닙니다. 실패하면 원문을 두 입력으로 사용합니다.
3. A·B 각각 bge-m3 임베딩 → 개별 L2 정규화 → 50:50 합산 → 재정규화합니다.
4. 키워드는 원문 → 명사·숫자·영문 중심 Nori → 전체 필드 최소일치 20%. BM25 k1=1.2, b=0.75, 파일명/본문/표 머리글 가중치 1, 문맥 2. 키워드용 문맥에서 파일명 중복을 제거했습니다. 임베딩용 내용은 그대로입니다.
5. 키워드와 의미 검색은 각각 최대 50청크를 반환합니다. 의미 후보 한 문서 독점이 과반이면 문서당 3개 제한·150개 보충·최대 6회라는 기존 다양성 정책을 사용합니다.
6. RRF는 청크 ID를 기준으로 결합합니다. 상수 60, 키워드:의미 1:2. 결합 상위 50개를 남깁니다.
7. 원문 질문과 후보 본문·문맥을 SiliconFlow Qwen3-Reranker-8B에 전달합니다. 반환 인덱스·점수·누락을 검사하고 내림차순 정렬합니다. 후보 집합은 그대로입니다.

## 실제 실행 경로

| 역할 | 파일 |
|---|---|
| 최신 전체 실험 시작점 | [run.py](../outputs/search-reranker-only-full-001/run.py) |
| Qwen 요청·검사·임베딩·검색 엔진 로딩 | [dual semantic/run.py](../deploy/search_openrouter_dual_semantic/run.py) |
| 당시 고정된 검색 엔진 | [고정 engine.py](../outputs/search-openrouter-dual-semantic-001/source-at-start/search/engine.py) |
| 벡터 결합·표현 검사 | [고정 core.py](../outputs/search-openrouter-dual-semantic-001/source-at-start/core.py) |
| RRF 함수 | [fusion_normalized.py](../deploy/search_pos_eval/fusion_normalized.py) |
| 리랭커 응답 검사·근거 채점 | [run_siliconflow.py](../deploy/search_rerank_ab/run_siliconflow.py) |
| 리랭커 입력 구성 | [model_ranker.py](../deploy/search_openrouter/model_ranker.py) |
| 실제 프롬프트 | [prompt.json](../outputs/search-openrouter-dual-semantic-001/prompt.json) |

공통 파일에 예전 방식이나 로컬 모델 클래스가 남아 있어도 이번 실행이 그것을 사용했다는 뜻은 아닙니다. 최신 실행기는 `fuse(..., 'rrf')`와 API 호출 경로를 선택합니다. 검색 엔진의 예전 기본 리랭킹 설정 대신 실행기가 별도 RRF·8B API 경로를 수행합니다. 설치된 로컬 모델을 로딩하지 않습니다.

## 결과 범위

문서·버전 묶기와 원문 위치 연결의 기존 구현은 별도 작업입니다. 최신 평가 표는 문서 묶기 전 청크 순위입니다. 새로운 요구사항 추출·충족 판정, 2차 Qwen, Jev, 최종 생성 답변은 이번 기준 경로에 없습니다.
