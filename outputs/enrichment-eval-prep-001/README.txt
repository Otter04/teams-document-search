문서 보강 모델 비교 - 오프라인 준비 패키지
2026-10-19 / 추가 튜닝 없음 / 유료 호출 0 / 실제 두 모델의 보강 성적 없음

완료 범위
선정한 20문서를 공통 입력으로 고정했다. 스캔 3문서 5페이지는 원본 렌더 이미지 전체를 대조했고, 문단과 3개 표의 25셀을 공통 블록으로 구성했다. 메타데이터 23필드×20문서=460칸과 요약 핵심 사실 61개를 근거에 연결했다. 모델 입력용 40개 요청 JSON은 로컬에 준비했으며 전송하지 않았다.

검수 주체는 현재 대화의 AI assistant다. 별도 사람 검수 완료 또는 독립 평가 세트로 표시하지 않았다. 이미 개발에 사용한 합성 자료의 선정 평가용 패키지다. DOCX/PPTX XML, XLSX 셀, PDF 저장 텍스트, TXT/LOG 원문을 읽어 네이티브 입력을 대조했다. 텍스트 PDF는 추출 순서가 다를 수 있어 일부 문구는 원문 구성 조각의 존재를 확인했으며, 전체 시각 레이아웃 검증을 뜻하지 않는다. 스캔 5페이지는 실제 이미지를 직접 확인했다.

주요 파일
- public/inputs/*.json: 두 모델에 같은 내용으로 주는 20문서 입력. 파싱 근거·표 구조·출처·수집 수정시각·미처리 범위 포함.
- public/system-prompt.txt: 공통 문서 보강 지시. 문서 종류/필드 적용 범위, 날짜 역할, 보류, 근거, 요약 기준.
- public/response.schema.json: 실험 응답 JSON 형식. 21개 기존 업무 필드와 표지일·작성일을 fields 안의 23항목으로 평탄화했다. 기존 운영 date_context나 규칙 전용 스키마를 변경한 것이 아니다.
- public/reference-data.json: 두 자료의 거래처·시스템 사전만 병합. 문서별 정답 없음.
- private/gold.json: 460필드 정답/보류 상태, 허용 별칭·근거, 61요약 사실. 모델에 전달하지 않는다.
- private/REVIEW.txt: 사람이 읽기 쉬운 문서별 값·상태·요약 사실 목록.
- private/label-adjustments.json: 이전 라벨과 달라진 판단 및 근거 범위.
- scan-review.json: 이번에 원본과 다시 대조한 스캔 전사와 표. 기존 원응답을 수정한 파일이 아니다.
- private/source-checks.json: 원본 20개 해시·수정시각·원문 대조 범위.
- private/rules-baseline.json: 동일 입력에 기존 규칙을 적용한 비교 기준. 모델 응답이 아니다.
- requests/index.json 및 requests/모델명/*.json: 40개 로컬 요청 본문, 요청/공통 메시지 해시. API 키 없음. prepared_not_sent 상태.
- run.py: 외부 통신 기능이 없는 평가 실행기. 검증, 요청 준비, 동결, 저장 응답 채점, 의미 검수 양식 생성.
- contract.py, test_evaluator.py: 스키마·정규화·근거 검사와 실패 사례 테스트.
- freeze.json: 최초 모델 호출 전에 고정한 입력·정답·지시·스키마·코드·요청과 외부 의존 파일의 해시.
- reports/: 준비 검증, 테스트 기록, 규칙 기준선, 미실행 상태 확인.

이번 원문 대조에서 정리한 라벨 12개
1) D-005, D-044, D-102 계약유형 3개: 과거 생성기 라벨은 용역/구매지만 명시적 계약유형 표기는 없다. 현재 명시적 추출 기준에서는 not_found_in_input으로 남긴다. 실제 계약의 법적 성격을 판정한 것이 아니다.
2) H-020의 문서일자·작성일·금액·통화·VAT·견적번호·유효기간 7개: 기존 네이티브 입력에는 없었으나 검수한 스캔 입력에 생겼으므로 평가 가능한 값으로 전환했다. 값은 2026-09-18 / 7,000,000 KRW / VAT 별도 / QT-26-PR-88 / 2026-10-18이다.
3) D-002, D-007 사업명 2개: 기존 평가에서 채점 제외였던 제목 기반 사업명이다. 이번 23필드 평가는 명시적 사업명 라벨 또는 본 사업 구절을 요구하므로 제목만으로 확정하지 않는다. 미처리 시각 영역이 있어 pending_vision 또는 not_found_in_input을 허용한다. 이를 모델 실수로 과거 성적에 소급하지 않는다.
기존 라벨·원본·파싱·비전 원응답·색인은 변경하지 않았다.

스캔 입력의 출처
기존 양 모델 응답의 한쪽을 정답으로 고르지 않았다. 원본 5페이지와 과거 원문 전사 초안을 다시 대조해 새 공통 사본을 만들었다. D-044/D-102 서명란은 각각 4×2 표, H-020은 3×3 표다. H-020의 훼손, 본문 날짜/번호/금액, 하단 합성 자료 문구까지 보존했다. 문단의 공백/줄바꿈은 정규화했고 위치는 페이지 수준으로 기록했다. 검수하지 않은 세밀한 bbox를 만들어 넣지 않았다.

기존 공통 블록 계약은 manual_design을 run_result로 가장하는 것을 금지한다. 따라서 스캔 사본은 design_example/manual_design, coverage.scope=excerpt라는 기존 허용 표현을 사용하고 외부 input_review에 전체 원본 페이지를 검수한 평가 사본임을 명시했다. 5페이지 내용이 모두 있어도 자동 비전 파서의 생산 실행 성과로 표시하지 않는다. 운영 파서에는 재주입하지 않았다.

규칙 기준선의 의미
규칙 전용 추출기의 문서 내용 처리 로직은 변경하지 않았다. 평가 어댑터만 위 3개의 검수 사본을 허용하며 출력은 별도 평가 후보로 저장한다. 같은 검수 입력 위에서 규칙이 회수할 수 있는 값을 확인하는 비교 기준이다. 원래 네이티브만으로 스캔을 읽었다는 뜻이 아니다. 요약은 규칙에 없으므로 메타데이터만 기준선으로 보고한다.

평가 방법
- 모든 20문서와 460필드를 분모에 유지한다. 응답 누락·JSON 중간 종료·스키마 실패를 조용히 제외하지 않는다.
- 정답 값이 있는 190칸은 회수율 대상이다. 채운 값 정확도와 회수율을 함께 보고, 미확정 날짜에 무근거 값을 채운 경우 별도 오류로 센다.
- 입력에 없는 값/적용 제외/비전 대기/의미 미확정을 구분한다. 별칭만 허용하고 숫자·번호·날짜 오류는 고쳐서 정답 처리하지 않는다.
- 인용의 실제 존재와 의미상 지지를 구분한다. 고정한 허용 근거 위치·값 표기를 만족한 항목을 자동 집계한다. 다른 위치의 타당한 근거는 오답 확정 대신 검수 대기다.
- 요약은 정답 문장을 그대로 복사할 필요가 없다. 뜻이 같은 바꿔쓰기를 허용하되 숫자·부정·조건·제안/관찰 시점을 보존해야 한다. 요약 문장을 원자적 사실로 나누어 근거·의미를 검수한 기록이 있어야 사실성 점수가 나온다. 인용 ID만 있다고 의미 정확도 100%로 표시하지 않는다.
- 빈 요약은 핵심 사실 회수 0이다. 누락/미검수 결과를 만점으로 만들지 않는다.
- 규칙 대비 새로 맞춘 값, 기존 올바른 값과 충돌한 값, 병합 검토 대기를 따로 보고한다. 병합은 오프라인 시뮬레이션이며 운영 값을 덮어쓰지 않는다. 실제 결과를 봐야 하는 요약 검수와 최종 모델 선정은 아직 없다.

오프라인 실행 방법 (프로젝트 루트에서)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/enrichment-eval-prep-001/run.py check

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s outputs/enrichment-eval-prep-001 -p 'test_*.py' -v

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/enrichment-eval-prep-001/run.py baseline --out outputs/enrichment-eval-prep-001/reports/rules-baseline

실제 응답이 생긴 뒤 실행할 평가 명령 (현재 응답 폴더는 비어 있음):
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=work/schema-deps /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/enrichment-eval-prep-001/run.py evaluate --responses outputs/enrichment-eval-prep-001/responses --out outputs/enrichment-eval-prep-001/reports/model-evaluation

저장 응답 형식
각 JSON 파일은 model, doc_id, request_sha256, response, elapsed_ms를 가진다. request_sha256은 requests/index.json의 해당 요청 해시다. response는 choices/message/content/finish_reason 및 usage를 포함하는 원래 OpenRouter 응답 객체다. elapsed_ms는 실제 관찰 시간이며 없으면 null이다. 같은 모델·문서의 중복 파일, 다른 요청 해시, 잘못된 JSON은 거부한다. 원응답 content를 사후 고쳐 저장하지 않는다. 가격을 추정해 실제 비용으로 쓰지 않고 응답에 보고된 usage.cost만 집계한다.

의미 검수 흐름
evaluate가 semantic-review.template.json을 생성한다. reviewer_id, reviewer_kind(human/assistant), 응답 해시와 원문 근거를 기록한다. 각 요약 문장을 atomic_claims로 나누고 text, verdict(supported/unsupported/uncertain), reason, evidence(kind/ref/quote), covered_gold_fact_ids를 적는다. 매칭한 핵심 사실의 조건을 일부만 충족하면 회수로 세지 않는다. metadata_evidence_reviews는 대체 인용 위치의 의미 확인에만 사용하며 잘못된 값을 정답으로 바꾸는 기능이 아니다. 검수 완료 후 status=completed로 저장하고 evaluate에 --review 검수파일경로를 추가한다. 파일명이나 모델 순서로 편향되지 않도록 검수 시 A/B 표시를 사용하고, 원본 모델 연결은 실행기에서 보존한다.

실행 경계
run.py에는 온라인 전송 기능이 없으며 키를 읽지 않는다. 사용자 승인 없이 모델을 실행할 수 없다. 이번 준비에는 이미 승인된 자료를 가공하는 오프라인 작업만 포함한다. 나중에 유료 호출을 승인하면 준비된 요청을 보내는 전송 단계에서 현재 제공자 지원·입력 한도를 확인하고 응답 원본을 이 형식으로 보존하면 된다. 이번에는 실제 OpenRouter 접속 수락이나 모델 품질을 테스트하지 않았다.

동결 후 입력/정답/지시/코드를 바꾸면 check/evaluate가 실패한다. 다음 실험으로 바꾸려면 별도 버전을 만든다. 현재 모델당 1회·문서당 1회라는 계획을 유지하고 응답이 나쁘다는 이유로 자동 재호출하지 않는다.
