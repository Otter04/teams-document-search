# v2 증분 인덱싱 실행 기록

**2026-10-24 완료 업데이트:**40개 비전 원본 대조 및44단위 반영,155문서·1,244벡터의 v002 적재와125질문 평가 완료. 결과 기존93/99·신규21/26으로 품질 목표는 미달. 기존 서비스는 유지한다. 아래 실행 순서는 재현/점검용이며 완료 작업을 중복 실행하지 않는다. [최종 보고서](../../outputs/indexing-v2-001/REPORT.md).

2026-10-23 사용자 승인으로 실행 중. 원본155개, 이전110개 산출물, 원본 정답/응답을 보존한다. 원본 아래 바이너리·압축파일3개는 제외한다. 외부 유료 API는 호출하지 않는다.

## 현재 실행과 연결 중단

- Orin 작업 폴더: `/media/sdcard/rag-runtime/indexing-v2-001`
- 비전 실행기: `vision_batch.py`, `nohup` 실행. 40개 고유 이미지 요청이며 동일 픽셀4개는 재사용한다. Mac/VPN/SSH 종료와 독립적으로 계속된다.
- 현재 실행 PID는514714였지만 재개 시 반드시 실제 프로세스·명령줄을 확인한다. `vision-progress.json`, `vision-dispatch.log`, 저장된 `response.json`을 함께 확인한다.
- 실행 중인 비전 작업을 중복 실행하지 않는다. `attempt.json`만 있고 응답이 없으면 먼저 기존 요청·서버·오류를 조사한다. 자동 재시도하지 않는다.
- 사용자가 나중에 중단을 요청하면 새 단계 실행을 멈추고 완료 응답을 보존한다. 중단 중이던 요청은 별도 미완료로 기록한다. 현재 실행기는 즉시 반영되는 일시정지 기능이 없으므로 완료 건수·활성 요청을 확인하고 조치한다. Docker 전체나 VPN을 임의로 끄지 않는다.
- 비전 외의 검수·조립·색인·검색 평가는 자동 연쇄 실행되지 않는다. 소스 검수가 끝난 자료만 다음 단계로 전달한다.

## 준비된 순서

로컬 Python은 `/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`다. cwd는 프로젝트 루트.

1. `prepare_native.py`, `reuse.py`: 이미 완료. 기존110개 재사용과 변경26개 계약구분, 신규45개 네이티브 자료를 준비했다. 완료 파일이 있으면 재실행하지 않는다.
2. SSH로 `vision-responses`, `vision-progress.json`의 tar 스냅샷을 가져온 뒤 `import_responses.py <tar>` 실행. 저장 원본이 다르면 덮어쓰지 않고 오류 처리한다.
3. `review.py`: HTTP/종료 사유/JSON/필드 구조 검증. 별도의 `vision-review/`에서 원본 이미지와 대조한 승인을 기록한다. 수정본은 `vision-reviewed-wire/`, 원본 응답은 그대로 보존한다. 파일 경로 역슬래시·중복 항목 등도 원본을 본 경우에만 수정한다.
4. `assemble.py --partial`: 준비·검사 전용. `prepared-partial/`은 배포 금지. `assemble.py`의 최종 실행은 모든44개 이미지 단위가 검수되기 전 차단된다. 기존17개 보강·요약 근거를 다시 확인한다.
5. 완료된 문서53개에서 변경·신규112개 청크는 `embedding-stable-001/`에서 먼저 임베딩했다. Orin 컨테이너 `rag-v2-embedding-stable`은 exit0으로 종료됐으며 결과를 로컬로 회수했다. 이 캐시는 최종 조립에서 동일 입력에 재사용한다.
6. 최종 `prepared/`의 `embedding-inputs.jsonl`과 `embedding-cache/`를 Orin 별도 디렉터리에 전달한다. 기존 `deploy/indexing/embed_bge.py`를 동일 모델파일/CLS/L2/fp16 방식으로 실행한다. 이전1,063개 벡터와 이번112개 중 입력이 일치하는 항목은 캐시 재사용한다. 입력·벡터 해시/모델지문/1024차원/정규화/잘림0 검사를 확인하고 결과를 보존하여 회수한다.
7. `export_index.py`는 완성된 `prepared/`와 실제 벡터만 허용한다. 새로운 `rag-search-documents-v002`, `rag-search-chunks-v002`용 파일을 `search-data/`에 생성한다. 기존 검색 규칙·Nori 사전·RRF/R1 방식은 그대로다.
8. Orin에서 `load_index.py <data-directory>` 실행. v002만 생성하며 기존 문서를 덮어쓰지 않는다. 중간 종료 시 기존 v002 문서가 완전히 같은 경우에만 나머지를 채운다. 전체 `_source` 일치와 Nori 동작, 기존 v001 건수 보존을 검증한다.
9. 별도 폴더에 `deploy/search/`의 현재 service/engine/query/content/streaming/index.html/selected.json과 v2 `data/`, `start_candidate.sh`를 배치한다. `rag-search-v2-validation`은8021에서 v002만 사용한다. 기존8020·Mac18020 화면은 유지한다. 실제 메모리 상태를 다시 확인한 뒤 실행한다.
10. 준비한 질문 전용 `evaluation/inputs.jsonl`을 Orin에 전달한다. `evaluate_dataset.py --inputs <inputs> --output <run-001> --base-url http://127.0.0.1:8021`로125개를 실행한다. 비전 작업 종료 후 실행하여 GPU 경합을 피한다. 원본 정답은 이 요청/모델에 전달하지 않는다.
11. 응답을 회수하고 `evaluation.py score`로 기존99개/추가26개/추가 보조정답8건을 분리한다. `audit_date_policy.py --run <run> --documents <v2 documents.json>`으로 기존 명시 날짜11질문의 기간 혼입을 확인한다. 새 질문의 날짜 조건도 원문·실제 계획과 대조한다.
12. Q-068·Q-069는 기존 정답과 명시기간 유지 정책이 충돌한다. 원본 정답 점수를 유지하고 정책별 빈 결과 확인을 별도로 적는다. 새 데이터에서 회귀가 드러나면 점수와 원인을 공개하며 정답·원본 응답을 고치지 않는다.

## 검증과 아직 하지 않은 일

- `test_preparation.py`: 기존 산출물/원본 해시, 계약구분26건만 변경, 잘린 응답 차단, 이미지·응답 해시 승인 연결, 벡터 동일성, 정답 없는 요청, 잘못된 위치 거부. 7개 통과.
- `deploy/search/test_search.py`: 기존37개와 후보 색인 분리1개, 총38개 통과.
- 이 검사는 실제125질문의 검색 정확도 결과가 아니다. 최종 색인 적재·후보 서비스·125질문 평가는 아직 실행 전이다.
- `prepared-partial/`에 일부 청크가 존재한다는 것을155문서의 Elasticsearch 색인 완료로 표현하지 않는다.
- 기존 파일의 관측 수정시각은 v2 파일시스템에서 재수집한다. 원문 작성일·표지일·납품/설치일과 구분하며 근거 없는 제출일을 만들지 않는다.
