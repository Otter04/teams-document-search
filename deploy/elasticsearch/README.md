# Orin Elasticsearch·Nori 색인

현재 실행 결과는 [보고서](../../outputs/elasticsearch-migration-001/README.md), 현재 연결 정보는 [backend.json](backend.json)을 기준으로 한다. 원문·LLM 응답·정답을 바꾸지 않는 저장소 전환이다. 검색 서비스와 답변 생성 코드는 포함하지 않는다.

## 실행 중인 구성

- Elasticsearch 8.19.23 ARM64, 동일 버전 `analysis-nori` 플러그인.
- 컨테이너 `rag-elasticsearch`, CPU runc, 4GiB 메모리 상한·2GiB JVM heap·CPU 4개.
- Orin의 `/media/sdcard/rag-runtime/elasticsearch-001/data` 영구 볼륨.
- `rag-documents` → `rag-documents-v001`, `rag-chunks` → `rag-chunks-v001`.
- Nori `mixed` 분해, 품사 필터·읽기형·소문자 처리, BM25 k1=1.2 b=0.75.
- bge-m3 1024차원 float32 `flat`·cosine. 기존 벡터 재사용.
- 9200 포트는 Orin의 127.0.0.1에만 바인딩. 개발 모드 인증 비활성. 외부 공개 전 보안·인증 설계 필요.
- `node.store.allow_mmap=false`. 호스트 커널 설정 변경 없음.

## 운영 확인

Orin에서 실행:

```bash
docker ps --filter name=rag-elasticsearch
curl http://127.0.0.1:9200/_cluster/health
curl http://127.0.0.1:9200/rag-documents/_count
curl http://127.0.0.1:9200/rag-chunks/_count
```

예상 결과는 green, 110, 1089다. 수량만으로 원문/벡터 품질을 확정하지 않는다. 이 전환에서는 전수 내용 대조와 재시작 검증까지 수행했다.

Mac의 기존 인증 SSH 세션을 이용한 평가용 터널:

```bash
ssh -S /Users/kangdongkyoon/.ssh/rag-orin.sock -O forward \
  -L 127.0.0.1:19200:127.0.0.1:9200 ubuntu@192.168.60.40
```

현재 이미 열려 있으므로 중복 실행하지 않는다. SSH 세션이 종료되면 다시 인증 후 연결한다. 모델 추론용 8001과 다른 포트다.

## 코드 역할과 보존

| 파일 | 역할 |
|---|---|
| export.py | 기존 문서·청크·벡터를 불변 입력으로 읽어 mapping/Bulk 파일 생성 |
| Dockerfile / start.sh | 공식 이미지 + Nori 설치, 영구 데이터 연결·실행 |
| ingest.py | 새 이름으로만 색인 생성, create 전용 적재, 전체 내용 대조, 별칭 연결 |
| postcheck.py | 컨테이너 재시작 후 전수 내용·244필터·수정일 정렬 검증 |
| evaluate.py | 기존 61질문·질문 벡터로 오프라인 회귀 평가; 결과 저장 후 정답 평가 |
| cleanup.py | 검증된 구색인·동일 중복본·임시 파일과 이름이 명시된 종료 컨테이너만 정리 |
| final_state.py | 정리 후 정본 해시·서버·모델 상태 확인 |

Mac의 Python은 기존 bundled runtime과 `work/vector-deps`, `work/schema-deps`를 쓴다. Orin의 적재/검증/정리는 표준 Python만 사용한다. 이전 규칙의 거래처 별칭·기술 용어와 날짜 해석은 평가 어댑터가 재사용하지만, 실제 토큰 분석·BM25 계산·벡터 검색·메타데이터 필터는 Elasticsearch에서 실행한다. 검색용 UI나 애플리케이션 API가 생긴 것은 아니다.

동결된 출력에 대한 재실행은 차단한다. 새 실험은 별도 결과 폴더와 새 인덱스 버전을 지정하고 점수·정답·응답 원본을 덮어쓰지 않는다. 현재 ingest 검증 결과가 있으므로 `ingest.py`는 다시 실행하지 않는다. `--verify-existing`은 최초 적재 후 검증이 중단된 경우에만 사용한다.

정리 후 Orin의 Bulk 임시 파일은 삭제됐다. 재시작 검사를 다시 할 때는 Mac의 `outputs/elasticsearch-migration-001/documents.ndjson`, `chunks.ndjson`을 Orin 배포 폴더에 복사하고 `postcheck.py`를 실행한다. 두 파일 해시는 `manifest.json`에 있다. 정상 재시작에 내보내기 파일은 필요하지 않으며 `docker start rag-elasticsearch`만으로 기존 data를 사용한다. 컨테이너만 삭제할 경우 볼륨 경로는 반드시 보존한다.

과거 실패/종료 Qwen 컨테이너는 제거됐지만 현재 `rag-qwen36`과 모델 가중치는 그대로다. `cleanup.py`는 1회 실행 결과를 보존하며 재실행할 작업이 아니다.
