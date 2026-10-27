# 두 후보 비전 처리 실행기

2026-10-19 사용자 요청으로 Qwen3.6-35B-A3B와 Qwen3-VL-30B-A3B-Instruct의 유료 OpenRouter 비전 비교를 진행한다. 이전 유료 호출 보류는 **이번 비전 처리 범위에 한해 해제**됐다. 새 키 인증과 재개 후 264개 응답 처리를 완료했다. [비교 결과](../vision-comparison-run-001/README.md)를 확인한다. 형식 통과는 Qwen3.6 104/132, Qwen3-VL 65/132이며 전체 정확도 합격이 아니다.

- 기존 110문서 중 30문서의 121장 + 추가 30문서 중 6문서의 11장 = **36문서, 132장**.
- 모델당 같은 132장, 합계 **264회**. 모델별·페이지별 응답, 비용, 실패를 별도 보존한다.
- DeepInfra FP8 엔드포인트를 고정하고 제공업체 자동 대체를 끈다. Qwen3.6 reasoning 비활성화, temperature 0, seed 42, 출력 한도 16,384토큰으로 양쪽을 비교한다. 출력 잘림을 줄이기 위한 한도이며 실제 청구는 사용량 기준이다. 앞선 비용 견적의 평균 출력 가정과 실제 사용량은 다를 수 있다.
- 입력은 원본 렌더링 이미지와 해당 장의 네이티브 문맥뿐이다. 정답·평가 주석은 실행기에서 읽지 않는다. `evaluate.py`만 평가 자료를 읽는다.
- 텍스트 전사, 표의 행·열/병합, 구성도 노드·연결, 그림의 관찰·추론을 분리한다. 문서 보강 LLM·임베딩·운영 검색 색인 갱신은 이번 실행 범위에 포함하지 않는다.

## 키 준비

1. https://openrouter.ai/settings/keys 에 로그인해 키를 만든다.
2. https://openrouter.ai/settings/credits 에서 크레딧을 충전한다.
3. 사용자의 터미널에서 다음 명령을 실행하고 숨김 입력에 키를 붙여넣는다.

```bash
python3 "/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/rag-vision-v1/setup_key.py"
```

키는 `work/credentials/openrouter.key`에 0600 권한으로 저장되고 상위 폴더는 0700이다. `.gitignore`에 제외했다. 키를 채팅·소스·로그에 쓰지 않는다. 이미 실행 환경에 `OPENROUTER_API_KEY`가 있으면 그 값을 먼저 사용한다. 별도 터미널에서 단순 `export`한 값은 실행 중인 데스크톱 앱에 전달되지 않으므로 위 파일 설정을 제공했다. 키 파일을 이미 만들어 둔 경우 기본 실행은 덮어쓰지 않으며, 사용자가 `--replace`로 실행하면 숨김 입력으로 새 키를 받아 교체한다.

2026-10-19 최초 키는 HTTP 401 인증 실패였다. 사용자가 교체한 키는 인증에 성공했다. 이후 사용자 요청으로 중지했다가 명시적인 재개 요청으로 전체 비교를 완료했다. 과거 인증 실패·중단 기록과 재개 이력은 실행 폴더에 보존한다. 키를 다시 설정하거나 승인을 반복 요청할 필요는 없다.

## 실행

프로젝트 루트에서 다음 Python을 사용한다. 아래 환경 변수는 비밀이 아니다.

```bash
RAG_PYTHON="/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
export PYTHONPATH=work/schema-deps
export PYTHONDONTWRITEBYTECODE=1
"$RAG_PYTHON" outputs/rag-vision-v1/run.py prepare
"$RAG_PYTHON" outputs/rag-vision-v1/run.py status
```

`prepare`는 140개 원본·파싱 JSON·132개 이미지의 해시와 원본 수정시각, 프롬프트·스키마·코드를 고정한다. API 호출은 없다.

키가 준비되면 처음 두 요청으로 연결/조건/출력 형태를 확인하고 이어서 전체를 처리한다. 첫 두 요청도 실제 평가 결과에 포함되며 재호출하지 않는다.

```bash
"$RAG_PYTHON" outputs/rag-vision-v1/run.py execute --limit 2
"$RAG_PYTHON" outputs/rag-vision-v1/run.py execute
"$RAG_PYTHON" outputs/rag-vision-v1/evaluate.py
```

완료된 요청을 자동 반복하지 않는다. `run.py execute`는 첫 실패에서 멈춘다. 전체 비교에서는 첫 실패 원인을 확인한 뒤 `batch.py`와 `dispatch_remaining.py`로 나머지 대상도 처리하며, 모델 출력의 형식 실패는 재시도 없이 실패로 기록하고 다음 대상으로 진행한다. API·전송 오류는 새 요청 배정을 중지한다. 타임아웃처럼 과금 여부를 알 수 없는 경우 `inflight.json`을 유지하고 자동 재시도를 막는다. 변경된 코드·입력은 새 실행 폴더에서 다른 실험으로 기록한다. 키/크레딧/네트워크 오류가 생기면 실행을 완료했다고 표시하지 않는다.

## 산출물과 판정 범위

기본 산출물: `outputs/vision-comparison-run-001/`.

- `manifest.json`: 두 모델에 공통인 고정 입력과 실행 조건.
- `<model>/units/<doc-unit>/response.json`: API 원응답(인증 헤더 제외).
- `extraction.json`: 검증을 통과한 모델의 구조화 출력.
- `common-block-document.json`: 해당 장의 비전 블록을 기존 공통 블록 1.0.0에 연결한 문서.
- `<model>/<corpus>/parsed.candidate.jsonl`: 해당 모델의 비전 결과를 연결한 후보 문서 전체. 네이티브 블록은 그대로 유지한다. 동일 원문을 네이티브/비전이 각각 추출했을 수 있으므로 **이 파일을 그대로 운영 색인에 넣지 않는다**. 원문 대조 후 중복·충돌 처리와 검색 재평가를 별도로 진행한다.
- `summary.json`: 시도/성공/실패/미실행 수, 토큰, 알려진 실제 비용과 비용 미보고 건수.
- `evaluation-comparison.json`: 스캔 필수 문자열, D-044 표 셀, D-069 구성도 노드·연결의 기존 초안 기준 검사.
- `evaluation/source-review-queue.json`: 132장 전체의 원본 대조 대기 항목. 추가 H-020을 포함한다.

모델이 `complete`라고 답하고 스키마 검사를 통과한 것은 추출 작업 완료의 자기보고이지 정확도 합격이 아니다. `partial`은 공통 블록에서도 대기로 유지한다. 기존 주석은 독립 검수 전 초안이며 사진/그림 해석의 환각·근거 위치·전체 누락 여부는 원본 대조가 더 필요하다. 근거 위치는 모델이 제시한 근사값이다. API 공급자가 표시한 FP8을 사내 Spark의 동일 실행 결과라고 단정하지 않는다.

## 오프라인 검증

```bash
"$RAG_PYTHON" -m unittest discover -s outputs/rag-vision-v1/tests -v
```

네이티브 보존과 공통 스키마 변환, 병합·빈 셀, 표 셀 누락·겹침, 잘못된 연결선 참조·좌표, 부분 추출 대기, 잘린 JSON/제공업체 오류 거절, 완료 요청 재과금 방지, 네트워크 결과 불명 요청 재시도 방지를 검사한다. 이 테스트는 모델 성능 점수가 아니다.

[비교 지표와 판정 범위](COMPARISON_METRICS.md)에 자동 측정, 원문 대조 대기, 별도 후속 평가를 구분했다.
