# Elasticsearch·Nori 전환 결과

2026-10-20. 사용자 요청에 따라 **Orin의 현재 색인 저장소를 Elasticsearch 8.19.23 + Nori + BM25 + bge-m3 벡터로 전환했다.** 파싱·문서 보강·청크·임베딩은 기존 결과를 그대로 사용했다. 추가 모델 추론과 유료 API 호출은 0건이다. 인수인계서의 다른 정책은 적용하지 않았다.

저장소 전환은 완료했다. 사용자용 검색·답변 서비스는 만들지 않았다. 아래 검색은 기존 개발 평가를 이용한 연결 검증이며 운영 검색 방식의 확정을 뜻하지 않는다.

## 현재 구조

```text
기존 공통 블록·검수한 비전 결과·규칙/LLM 보강 결과
                    ↓ 기존 청크와 벡터 재사용
Orin / Elasticsearch + Nori
 ├─ rag-documents → rag-documents-v001 : 110문서
 │    문서 원본 정보, 메타데이터, 상태, 날짜 역할, 기존 요약·의미 보강
 └─ rag-chunks → rag-chunks-v001       : 1,089청크
      본문·문맥·근거 위치 + Nori 분석/BM25 + bge-m3 벡터
```

Nori는 원문을 대체하지 않는다. 원문과 근거를 `_source`에 보존하고 한국어 검색용 토큰을 별도로 색인한다. 예를 들어 실제 분석에서 `문서를 검색합니다`는 `문서`, `검색`으로 처리됐다. 계약번호·IP 등은 정확한 문자열을 검색할 `keyword` 필드도 보존했다.

벡터는 1,024차원 FP32, 기존 CLS·L2 정규화 결과다. Elasticsearch의 `dense_vector`에 `flat`·`cosine`을 명시했다. 이 작은 자료집에서는 기존 FAISS와 같이 모든 벡터를 정확하게 비교하기 위해 근사 HNSW나 추가 양자화를 도입하지 않았다. **현재 벡터 색인은 Elasticsearch 내부에 있으며 FAISS를 실행하지 않는다.**

## 검증

| 검증 항목 | 결과 |
|---|---:|
| 문서 / 원문 청크 / 의미 보강 청크 | 110 / 1,072 / 17 |
| 보존한 벡터 | 1,089 × 1,024차원 |
| 전체 저장 항목 다시 읽기 | 1,199개, 내보낸 JSON과 모든 값 동일 |
| Elasticsearch 재시작 후 다시 읽기 | 1,199개 동일 |
| 날짜·거래처·문서 종류·대상 시스템 등의 정확한 필터 | 244건 통과 |
| 수정일 정렬 | 오름차순·내림차순 모두 통과 |
| 날짜 범위·표지일/작성일/파일 수정일 분리 | 통과 |
| 기존 61질문의 메타데이터 필터 대상 대조 | 61건 모두 기존 정책과 일치 |
| Nori 분석 / BM25 계산 / 벡터 실제 요청 | 통과 |
| 클러스터 상태 | green |

근거: [전수 검증](verification.json), [재시작·필터 검증](persistence-and-filters.json), [실제 Nori 토큰](nori-example.json), [BM25 계산 설명](bm25-explanation.json), [벡터 기본 검사](vector-smoke.json), [최종 서버 상태](final-state.json).

첫 검증기의 BM25 확인은 응답에 `BM25`라는 문자열이 있다고 가정해 실패했다. 실제 Lucene 설명에는 `PerFieldSimilarity`와 BM25 수식이 표시됐다. 이를 설정의 BM25 타입·k1=1.2·b=0.75와 실제 계산 설명을 함께 확인하도록 고쳤다. 적재 실패나 데이터 수정이 아니며, 재적재 없이 전체 항목을 다시 검증했다. 설치 중 Docker 빌드 DNS 문제는 설치 작업에만 host 네트워크를 적용해 해결했다.

## 기존 개발용 61질문 비교

| 지표 | 이전 Python BM25 | Elasticsearch Nori·BM25 |
|---|---:|---:|
| 상위 5개에 정답 하나 이상, Hit@5 | 61/61, 100% | **60/61, 98.36%** |
| 질문별 정답 문서 회수율의 평균, mean Recall@5 | 100% | **97.81%** |
| 정답 문서를 모두 상위 5개에서 찾은 질문 | 61/61 | **59/61** |
| 1위에 정답이 있는 질문 | 60/61 | 55/61 |

두 전체 지표는 90%를 넘었다. 다만 이전 100%가 그대로 유지되지는 않았으며, **각 유형별 90%나 새로운 실제 자료에 대한 일반화 성적을 검증한 것은 아니다.**

최종 연결부에 남은 문제:

- **Q-032** `수강신청 몰릴 때 자동으로 서버 늘리는 구성`: D-053 1위, D-054 2위, D-061 **6위**. 정답 3개 중 2개만 상위 5개에 들어갔다.
- **Q-044** `해솔마트 견적 관련 메일`: 정답 D-087 **7위**. 상위 5개에는 정답이 없다.
- Q-020 `TMS 전환 작업 로그`: D-036 **1위 유지**.
- Q-007 `Cheongram Precision 견적 최종본`: D-004 1위, D-003 4위. 기존 거래처 별칭 처리를 복원한 결과다.
- Q-053 부가세 포함 공공기관 견적: D-099 1위, D-100 2위.

첫 연결 검사는 Hit@5 100%, mean Recall@5 98.63%였으나 거래처 영문 별칭의 기존 정규화가 빠져 있었다. 이를 모든 거래처에 공통 적용하고, 이미 포함된 정식 명칭은 중복 추가하지 않도록 보완했다. 최종 점수는 위 표를 기준으로 한다. 별칭 반영이 일부 순위에는 불리하게 작용했다. 과거 성적이 더 높다는 이유로 기존 별칭 기능을 빼거나, 특정 정답에 맞춰 가중치를 조절하지 않았다.

본문 Nori 분석, Lucene BM25 필드 점수, 문서별 최고 청크 집계 방식은 이전의 한국어 2글자 토큰·사용자 정의 필드 점수와 다르다. 기존 필드 중요도·작업 문맥·한영 용어 규칙을 연결했지만 점수 계산이 수학적으로 동일한 것은 아니다. 남은 두 질문은 **검색 설계·순위 조정 과제로 기록하고 이번 전환에서 추가 튜닝하지 않았다.**

**벡터 이전의 동등성:** 동일한 기존 61개 질문 벡터로 Elasticsearch의 벡터 검색을 실행했다. 61개 모두 이전 FAISS와 상위 5개 문서 순서가 같았고, 문서별 코사인 점수 최대 오차는 약 `1.78e-7`이었다. 벡터 단독의 Hit@5 85.25%, mean Recall@5 83.06%도 같았다. 이는 새 검색 방식의 추천 비교가 아니라 벡터 이전이 결과를 바꾸지 않았는지 확인한 검사다. 하이브리드 결합 방식은 이번에 새로 결정하지 않았다.

최종 검사 전체 약 28.98초. 이 중 61개 BM25 요청의 왕복 시간 합계는 약 7.48초, Elasticsearch 보고 처리 시간 합계는 3.37초다. 벡터 요청 왕복 합계는 16.94초, Elasticsearch 보고 처리 시간 합계는 11.26초다. SSH·HTTP 왕복, 캐시 상태, 최초 초기화가 포함되므로 이전 Mac의 인프로세스 실행 시간과 직접적인 속도 비교로 해석하지 않는다. 설치·개발·전수 검증 시간은 별도다.

정답을 점수 계산에 사용하기 전에 순위와 요청을 저장했다. 하지만 기존 개발 세트를 이미 여러 번 사용했고 이번 연결 오류를 결과로 확인했으므로 독립·블라인드 평가가 아니다. [최종 점수](evaluation-final/summary.json), [질문별 결과](evaluation-final/nori_bm25-scores.json), [실제 Elasticsearch 요청](evaluation-final/requests.json), [벡터 동등성](evaluation-final/vector-equivalence.json). 첫 검사와 중간 연결 검사도 별도 폴더에 보존했다.

## Orin에서 삭제한 것과 남긴 것

사용자의 명시적 요청에 따라 전환·재시작 검증 뒤 **66개 파일, 55,179,813바이트(약 52.6MiB)**와 종료 컨테이너 **6개**를 삭제했다. Docker 전체 정리나 다른 프로젝트 폴더 삭제는 하지 않았다.

- 삭제: 기존 `final-index/index.json` Python BM25 색인과 `final-index/vectors.faiss`.
- 삭제: `final-index/` 보존본과 바이트 단위로 동일한 작업용 입력·응답·벡터 등의 중복본 62개.
- 삭제: 새 데이터가 검증된 뒤 불필요해진 임시 Bulk 적재 파일 2개. 동일 내보내기 파일은 Mac의 이 결과 폴더에 보존했다.
- 삭제: 종료된 bge-m3 일회성 컨테이너 2개와 이전 Qwen 설정의 종료 컨테이너 4개. 로그와 설정·볼륨 정보를 먼저 보존했다.
- 보존: Qwen/bge-m3 모델 파일, 공통 블록·원문·검수 결과·메타데이터·원응답·`vectors.npy`·벡터 매핑의 정본, 현재 Qwen 서버, 새 Elasticsearch 데이터.

Mac의 기존 평가·색인 폴더는 비교 재현에 필요한 동결 보존본으로 남겼다. 현재 운영에 FAISS를 계속 쓰기 위해 남긴 것이 아니다. Orin의 옛 작업 폴더에는 `BACKEND_MIGRATED.md`로 현재 위치와 삭제 이유를 기록했다. 과거 `orin-copy-verification.json`은 복사 후 Mac에서 마감된 확인서라 양쪽 해시가 다르며 원상 보존했다. 이 차이를 원문·응답·벡터 손실과 구분해 [최종 상태](final-state.json)에 기록했다.

[삭제 실행 목록](cleanup-result.json) · [종료 컨테이너 기록](retired-container-records/). 표시한 용량은 삭제 파일 합계이며 새 Elasticsearch 이미지·색인의 용량을 뺀 순수 디스크 증가/감소량은 아니다.

## 접속·저장 위치

- 컨테이너: `rag-elasticsearch`, 이미지 `rag-elasticsearch-nori:8.19.23`, ARM64, CPU `runc` 런타임.
- Orin 경로: `/media/sdcard/rag-runtime/elasticsearch-001/`.
- 영구 데이터: 위 폴더의 `data/`, 컨테이너의 `/usr/share/elasticsearch/data`에 연결.
- Orin 주소: `http://127.0.0.1:9200`. 개발 환경으로 인증을 끄고 **호스트 loopback에만 포트를 게시**했다. 사내 공용 접속용 배포가 아니다.
- Mac 확인 통로: 기존 인증 SSH 연결의 `http://127.0.0.1:19200`. SSH 연결이 종료되면 이 통로는 끊기지만 Orin 컨테이너와 데이터는 유지된다.
- 힙 2GiB, 컨테이너 메모리 상한 4GiB, CPU 4개. 점검 중 Elasticsearch 사용량 약 2.6GiB. Qwen 설정·모델·문맥 49,152는 유지했다.
- 자동 재시작 정책 `unless-stopped`. 새 컨테이너는 재시작 검증을 완료했다. 호스트 재부팅 자체를 시험한 것은 아니다.
- `node.store.allow_mmap=false`로 실행해 호스트의 `vm.max_map_count`를 바꾸지 않았다.

코드와 설정: [배포 폴더](../../deploy/elasticsearch/), [백엔드 연결 정보](../../deploy/elasticsearch/backend.json), [문서 매핑](document-mapping.json), [청크 매핑](chunk-mapping.json), [보존한 기존 참조 사전](reference-rules.json).

삭제한 Bulk 파일은 필요할 때 Mac의 `documents.ndjson`, `chunks.ndjson`을 이 Orin 폴더에 다시 복사한 뒤 `postcheck.py`로 재검증할 수 있다. `ingest.py`는 새 색인을 만들 때만 사용하며 기존 색인을 덮어쓰지 않는다. `--verify-existing`은 최초 적재 후 검증이 중단됐고 아직 최종 검증 기록이 없을 때만 사용한다. 평상시 재시작은 `docker start rag-elasticsearch`다. 구버전 생성 작업을 다시 실행하지 않는다.

공식 기능 근거: [Nori 분석기](https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-nori-analyzer), [8.19 dense_vector와 flat 옵션](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/dense-vector.html), [Docker 설치](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/docker.html).
