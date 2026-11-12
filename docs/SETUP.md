# 실행과 게시 범위

## 저장 결과 재채점

```bash
git clone https://github.com/Otter04/teams-document-search.git
cd teams-document-search
python3 evaluation/replay.py
```

Python 3.10 이상과 표준 라이브러리만 사용합니다. 네트워크·API 키·Elasticsearch·모델 설치가 필요 없습니다. 이 경로가 이번 게시본에서 검증한 실행 방법입니다.

## 새로운 검색 실행과의 차이

최신 전체 실행 원본은 `outputs/search-reranker-only-full-001/run.py`입니다. 과거 고정 입력·색인·해시를 대조하고 완료된 폴더를 덮어쓰지 않도록 설계한 실험 실행기입니다. 새 질문을 받는 배포 서버가 아닙니다. 완료된 실행기를 그대로 재실행하지 마세요. 새 시험은 별도 출력 경로와 실행 기록을 준비해야 합니다.

필요한 외부 자원:

- Elasticsearch와 Nori. `rag-search-context-no-filename-20261104`, `rag-search-chunks-v006-token-nori` 색인. 준비 명세는 `evaluation/runtime-resources.json`을 참조합니다.
- `outputs/search-token-nori-reranker-001/data/`의 `chunks.ndjson`, `documents.json`, `blocks.json`. 이번 업데이트에는 큰 원문·벡터 내보내기를 새로 업로드하지 않습니다. 파일 크기·SHA-256을 자원 명세에 기록합니다.
- 원 실행은 `http://127.0.0.1:19200`의 Elasticsearch를 참조합니다. 새로운 환경은 이를 구성해야 합니다.
- OpenRouter와 SiliconFlow 키 및 사용 가능한 잔액. 공개 예시 파일을 로컬 `.env.local`로 복사해 입력하며 실제 키는 커밋하지 않습니다.
- 실행기·스냅샷·고정 입력의 해시와 경로가 맞아야 합니다. 원 기록에는 원 작업 폴더의 절대 경로가 있으므로 다른 경로에서 새 실험을 구성할 때 새 manifest가 필요합니다. 원 manifest를 고쳐 기존 검증이 통과한 것처럼 만들지 않습니다.

```bash
cp deploy/search_openrouter/.env.example deploy/search_openrouter/.env.local
```

현재 API 기준은 모델 추론을 로컬 Mac이나 Orin에서 실행하지 않습니다. 기존 로컬 모델 클래스가 소스에 남아 있어도 이번 API 실행 경로에서는 로딩하지 않습니다. 질문 재작성·임베딩·리랭커 API는 새로 호출하면 요금이 발생합니다.

## 공개 파일 구성

- README와 `docs/`의 네 안내문: 현재 목적·구조·발전 과정·평가·재현 경계.
- `evaluation/`: 오프라인 재채점기, 원 결과에서 추출한 순위·정답, 게시 파일 해시, 외부 자원 명세.
- 기존 경로의 최신 실행기·고정 검색 코드·API 연결 모듈·설정·프롬프트: 원본 내용과 경로 보존.
- 선택한 비교 보고서: 당시 결과를 보존. 오래된 보고서 안의 다른 링크는 로컬 실험 전체를 요구할 수 있음.

새로운 조건 판정 실험·Jev·다른 세션 작업은 현재 기준에 편입하지 않습니다. 옛 커밋과 Release는 당시 스냅샷이며 최신 실행 환경의 백업이 아닙니다. API 원응답·가상환경·모델 가중치·캐시·인증 파일을 이번 업데이트에 넣지 않습니다. 기존 저장소 이력은 삭제하거나 재작성하지 않습니다.
