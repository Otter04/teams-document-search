# 모델 없이 실행하는 청킹·키워드 검색

버전 native-search-0.1.1 · 2026-10-17

실제 네이티브 공통 블록과 규칙 메타데이터를 받아 검색용 청크와 로컬 BM25 색인을 생성합니다. 모델·외부 API·추가 패키지를 설치하거나 호출하지 않았습니다. 입력 검증에는 기존 jsonschema 환경을 사용합니다.

- [실제 실행 결과와 예시](../native-search-run-002/README.md)
- [입출력 규칙과 평가 기준](CONTRACT.md)
- [구현](pipeline.py), [평가기](evaluate.py), [재현 검증](verify.py)

## 입력과 출력

| 파일 | 단위와 역할 |
|---|---|
| 입력 parsed.jsonl | 문서별 공통 블록, 원문 위치, 비전 대기 |
| 입력 enriched.jsonl | 문서별 규칙 메타데이터, 근거, 값의 상태 |
| 입력 reference-data.json | 제공된 거래처 이름·별칭 사전 |
| 출력 chunks.jsonl | 한 줄에 문서 하나. 내부 chunks 배열이 검색 조각 |
| 출력 index.json | 문서 메타데이터 항목 + 청크 항목 + BM25 역색인 |
| 출력 provenance.json | 입력·코드·출력 해시와 실행 설정 |
| 평가 evaluation/ | 원문 보존, 필수 문자열, 61개 질문의 순위·근거 |

청크 text는 원문입니다. context_header는 파일명·확정 메타데이터·제목·위치를 조합한 문맥이며 원문과 구분됩니다. source_refs에는 block_id, start, end, loc가 있고 문자 끝 end는 포함하지 않습니다. 표 머리말의 원문 위치는 context_refs로 반복 연결합니다. token_count는 null입니다.

문서마다 스캔 등 pending_visual_units를 보존합니다. 스캔만 있는 문서는 chunks=[]이지만 문서 메타데이터 항목은 색인에 남습니다. 이 파일 색인은 데이터베이스 서버나 운영 검색 서비스가 아닙니다. 원본 링크 web_url은 예비 자료에서 null이며, 현재 결과는 상대 경로와 원문 위치로 추적합니다.

## 실행 예시

프로젝트 루트에서 기존 Python 환경을 사용합니다. 새 실행 폴더 이름을 지정해야 하며 기존 결과를 덮어쓰지 않습니다.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=work/schema-deps
RAG_PYTHON=/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

"$RAG_PYTHON" outputs/rag-native-search-v1/pipeline.py build \
  --parsed outputs/parsing-run-003/parsed.jsonl \
  --metadata outputs/enrichment-run-001/enriched.jsonl \
  --reference outputs/rag-enrichment-v1/reference-data.json \
  --output outputs/new-native-search-run

"$RAG_PYTHON" outputs/rag-native-search-v1/pipeline.py search \
  --index outputs/native-search-run-002/index.json \
  --query 'ORA-01555' --limit 5

"$RAG_PYTHON" outputs/rag-native-search-v1/pipeline.py search \
  --index outputs/native-search-run-002/index.json \
  --query 'MES' \
  --filters '[{"field":"문서일자","op":"gte","value":"2025-09-01"},{"field":"문서일자","op":"lte","value":"2025-09-30"},{"field":"실행결과","op":"eq","value":"실패"}]'

"$RAG_PYTHON" -m unittest discover -s outputs/rag-native-search-v1/tests -v
```

평가는 evaluate.py에 --run, --parsed, --metadata, --dataset을 전달합니다. --dataset은 files/와 gold/가 있는 실제 예비 데이터셋 폴더입니다. verify.py도 같은 인자를 받아 정답·네트워크 접근을 차단한 재현 검사와 원본 파일 해시 비교를 수행합니다. 평가에는 기존 openpyxl 환경도 사용합니다.

필터는 호출자가 명시한 JSON만 적용합니다. eq/in을 지원하며 날짜·시각·금액은 gte/lte도 지원합니다. 날짜는 YYYY-MM-DD, 로그 시각은 YYYY-MM-DD HH:MM, 금액 범위는 숫자 문자열입니다. 보류된 값은 필터를 충족했다고 취급하지 않습니다. 자연어에서 필터를 만드는 기능은 아직 없습니다.

## 검증 범위

21개 회귀 검사를 통과했습니다. 표 머리말·원문 참조·긴 블록·슬라이드 경계·미확정 메타데이터·필터 입력·삭제 후 스냅샷·순위 집계·평가 계산을 확인했습니다. 실제 110문서와 61질의 재현 결과는 [검증 기록](../native-search-run-002/verification.json)에 있습니다.

한국어 어절·음절 2-gram 검색은 형태소 분석이나 의미 검색과 다릅니다. 모든 청크를 채점한 뒤 문서별 최고 점수로 묶으며, 상위 3개 근거는 묶은 뒤 선택합니다. conditions_verified=false는 결과가 질문의 모든 조건을 검증하지 않았다는 표시입니다.

[첫 실행](../native-search-run-001/evaluation/report.md)을 보존했습니다. 이후 검색 결과에 반복 표 헤더의 원문 참조 전달, 날짜 필터 형식 검증, 검색 토큰 순회 순서 고정만 보완했습니다. 문서별 정답 보정이나 벤치마크 질의별 가중치를 추가하지 않았고 두 실행의 성적은 같습니다.
