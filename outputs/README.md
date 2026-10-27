# 실험·구현 원본 저장소

현재 색인 저장소는 **Orin Elasticsearch·Nori**다. [전환·최종 평가·삭제 기록](elasticsearch-migration-001/README.md)을 먼저 확인한다. 이전 `indexing-110-semantic-vector-001`과 `indexing-retrieval-eval-001`은 원문·모델 결과 및 전환 전 평가를 재현하기 위한 Mac 보존본이며 현재 FAISS 운영 저장소가 아니다.

현재 모델은 **Qwen3.6-35B-A3B로 선정 확정**했다. [결정과 근거](../docs/MODEL_SELECTION.md)를 따른다.

자료는 [목적별 자료모음](../docs/자료모음/README.md) 또는 [전체 위치 안내](../docs/FOLDER_GUIDE.md)에서 찾는다. 이 폴더의 실제 경로는 코드 참조·평가 동결·재현을 위해 유지한다.

- `rag-*`: 단계별 구현 코드. 버전이 낮아도 다른 코드가 가져다 쓸 수 있다.
- `*-run-*`, `*-review-*`, `*-trial-*`: 해당 시점의 실행 결과·검수·실험 기록.
- `*-design`, `*-policy-*`, `*-prep-*`: 규격·정책·평가 입력. 준비 이후 실행이 완료됐어도 동결 입력으로 필요하다.
- 데이터셋과 ZIP: 당시 원본·정답·배포 묶음.

과거 보고서의 상태·계획은 당시 기록이다. 현재 작업 상태는 [프로젝트 README](../README.md), 남은 일은 [NEXT_TASK](../NEXT_TASK.md)에서 확인한다. 역사적 점수·프롬프트·모델 응답은 최신 결정에 맞춰 덮어쓰지 않는다.
