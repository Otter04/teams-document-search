# 폴더 안내

2026-10-20 현재 색인: [Elasticsearch·Nori 배포 코드](../deploy/elasticsearch/), [전환·평가·삭제 보고서](../outputs/elasticsearch-migration-001/README.md). Orin의 현재 폴더는 `/media/sdcard/rag-runtime/elasticsearch-001/`이며, 이전 생성 결과의 정본은 `/media/sdcard/rag-runtime/indexing-110-semantic-vector-001/final-index/`에 남겼다. 이전 BM25·FAISS 실행 색인과 중복·임시 파일은 검증 뒤 삭제했다. Mac의 동결 보존본은 평가 재현 때문에 유지한다.

## 일상적으로 여는 곳

```text
rag/
├── README.md                  현재 상태와 주요 문서
├── NEXT_TASK.md               미완료 작업만 기록
├── docs/
│   ├── MODEL_SELECTION.md     Qwen3.6 선정 확정과 근거
│   ├── FOLDER_GUIDE.md        이 안내
│   ├── ORGANIZATION_LOG.md    이번 정리 범위와 검증
│   ├── 자료모음/              목적별 폴더와 원본 바로가기
│   ├── archive/               이전 안내문 보관본
│   └── maintenance/           정리 전후 해시·목록·확인 결과
├── outputs/                   코드·데이터·실험 결과의 고정 경로
└── work/                      내부 작업·의존성·개발 흔적
```

`outputs`의 많은 폴더는 평가 입력·코드·절대 경로·동결 해시에 연결되어 있다. 실험 재현을 보존하기 위해 실제 위치를 유지하고, `docs/자료모음`에 목적별 바로가기를 배치했다. 바로가기를 삭제해도 원본은 남지만, 바로가기를 통해 원본 파일을 수정하면 실제 파일이 변경된다.

과거 보고서는 당시 조건과 결과의 근거다. ‘후보’, ‘준비 완료’, ‘미선정’ 같은 당시 상태를 최신 지시로 해석하지 않는다. 현재 결정은 [MODEL_SELECTION.md](MODEL_SELECTION.md), 남은 작업은 [NEXT_TASK](../NEXT_TASK.md)를 따른다.

## 전체 자료 위치

### 01_설계와기준

파이프라인·공통 블록·원문 기준 메타데이터 정책.

- [common-block-design](../outputs/common-block-design)
- [metadata-policy-v1](../outputs/metadata-policy-v1)
- [diagrams](../outputs/diagrams)

### 02_데이터셋과평가준비

원본/정답 패키지 및 동결 평가 입력. 보강 준비 패키지는 후속 실행 완료 후에도 재현 입력으로 유지한다.

- [additional-dataset-v1](../outputs/additional-dataset-v1)
- [independent-evaluation-prep-v1](../outputs/independent-evaluation-prep-v1)
- [enrichment-eval-prep-001](../outputs/enrichment-eval-prep-001)

### 03_현재코드

현재 버전의 진입점. 이전 버전 코드를 내부 의존성으로 불러올 수 있다.

- [rag-parser-v3](../outputs/rag-parser-v3)
- [rag-enrichment-v3](../outputs/rag-enrichment-v3)
- [rag-date-search-v2](../outputs/rag-date-search-v2)
- [rag-vision-v3](../outputs/rag-vision-v3)
- [rag-evaluator](../outputs/rag-evaluator)
- [additional-evaluation-v2](../outputs/additional-evaluation-v2)

### 04_현재파싱과검색결과

각 범위의 최신 확인 결과. 서로 다른 분모와 평가 범위를 구분한다.

- [parsing-run-003](../outputs/parsing-run-003)
- [additional-parsing-run-001](../outputs/additional-parsing-run-001)
- [generalization-review-001](../outputs/generalization-review-001)
- [date-search-run-002](../outputs/date-search-run-002)
- [additional-evaluation-run-002](../outputs/additional-evaluation-run-002)
- [additional-search-run-002](../outputs/additional-search-run-002)
- [metadata-review-run-002](../outputs/metadata-review-run-002)

### 05_모델선정근거

선정에 사용한 실제 실험·원문 대조 기록. 당시 미확정 문구보다 현재 MODEL_SELECTION.md 결정이 우선한다.

- [vision-comparison-run-001](../outputs/vision-comparison-run-001)
- [vision-source-review-001](../outputs/vision-source-review-001)
- [vision-validation-run-003](../outputs/vision-validation-run-003)
- [vision-prompt-trial-001](../outputs/vision-prompt-trial-001)
- [enrichment-comparison-run-001](../outputs/enrichment-comparison-run-001)

### 06_설명과실제예시

설명용 발췌·비교 자료. 평가 원본은 해당 실행 폴더에 별도 보존한다.

- [vision-explained-001](../outputs/vision-explained-001)
- [enrichment-explained-001](../outputs/enrichment-explained-001)

### 90_선행코드와이전실험

이전 결과·실험 계획·선행 구현이다. 현재 코드가 의존할 수 있어 불필요하다고 일괄 삭제하지 않는다. 현재 사용 지시는 아니다.

- [additional-evaluation-run-001](../outputs/additional-evaluation-run-001)
- [additional-evaluation-v1](../outputs/additional-evaluation-v1)
- [additional-search-run-001](../outputs/additional-search-run-001)
- [condition-search-run-001](../outputs/condition-search-run-001)
- [date-search-run-001](../outputs/date-search-run-001)
- [enrichment-run-001](../outputs/enrichment-run-001)
- [field-search-run-001](../outputs/field-search-run-001)
- [field-search-run-002](../outputs/field-search-run-002)
- [metadata-review-run-001](../outputs/metadata-review-run-001)
- [model-selection-review-001](../outputs/model-selection-review-001)
- [native-search-run-001](../outputs/native-search-run-001)
- [native-search-run-002](../outputs/native-search-run-002)
- [parsing-run-001](../outputs/parsing-run-001)
- [parsing-run-002](../outputs/parsing-run-002)
- [rag-condition-search-v1](../outputs/rag-condition-search-v1)
- [rag-date-search-v1](../outputs/rag-date-search-v1)
- [rag-enrichment-v1](../outputs/rag-enrichment-v1)
- [rag-enrichment-v2](../outputs/rag-enrichment-v2)
- [rag-field-search-v1](../outputs/rag-field-search-v1)
- [rag-native-search-v1](../outputs/rag-native-search-v1)
- [rag-parser](../outputs/rag-parser)
- [rag-parser-v2](../outputs/rag-parser-v2)
- [rag-rule-search-v1](../outputs/rag-rule-search-v1)
- [rag-vision-v1](../outputs/rag-vision-v1)
- [rag-vision-v2](../outputs/rag-vision-v2)
- [rule-search-run-001](../outputs/rule-search-run-001)
- [rule-search-run-002](../outputs/rule-search-run-002)
- [rule-search-run-003](../outputs/rule-search-run-003)
- [rule-search-run-004](../outputs/rule-search-run-004)
- [vision-prompt-proposal-001](../outputs/vision-prompt-proposal-001)
- [vision-validation-run-002](../outputs/vision-validation-run-002)

### 91_배포시점ZIP

각 제작 시점의 배포 스냅샷. 최신 재평가 결과를 포함한다고 가정하지 않는다.

- [additional-evaluation-package-v1.zip](../outputs/additional-evaluation-package-v1.zip)
- [common-block-design-v1.zip](../outputs/common-block-design-v1.zip)

## 내부 작업 공간

`work/credentials/`는 로컬 자격 증명 보관 위치로 열람 자료모음에 포함하지 않았다. `schema-deps`, `node_modules`, 글꼴·렌더 도구는 재현 의존성이다. OCR 실험과 예전 렌더/파싱 실행 흔적은 과거 보관 자료이며 현재 선택한 비전 LLM 방향의 사용 지시가 아니다. 자세한 구분은 [work 안내](../work/README.md)를 참조한다.
