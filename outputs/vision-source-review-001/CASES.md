# 원본 이미지 대조 사례

검색 성능은 포함하지 않았다. 아래는 원본 이미지와 저장 응답에서 확인한 사례다. 전체 수치는 README.md를 참고한다.

## D-102-vision-page1 — 오독·원문 변경

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-102/page-1.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업2팀/Shared Documents/OUDC/2025_시설관리시스템 노후 서버 교체/계약/시설관리시스템 노후 서버 교체_계약서(서명본).pdf>)

- 원본: 온새미시 도시공사 / 선금 / 무상으로 / 서면 시정 요구를 받은
- Qwen3.6: 은새미시 도시공사 / 선급 / 무료로 / 서면 시정을 받은
- Qwen3-VL: 위 원문을 보존. 이 페이지의 23개 기준 항목 모두 일치.
- 판정: 3.6은 거래처명을 오독했고, 일부 문구를 바꾸거나 생략했다. 무료로는 뜻이 비슷하지만 원문 전사 기준에서는 변경이다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-102-vision-page1/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-102-vision-page1/response.json>)

## D-044-vision-page1 — 오독·원문 보정

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-044/page-1.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업2팀/Shared Documents/새봄병원/2025_PACS 스토리지 증설/계약/PACS 스토리지 증설_계약서(서명본).pdf>)

- 원본: 양 당사자는 / …한다)은
- Qwen3.6: 당 당사자는 / …한다)는
- Qwen3-VL: 양 당사자는 / …한다)는
- 판정: 3.6은 양→당 오독. 두 모델 모두 원문의 어색한 조사 은을 는으로 바꿨다. 파싱 단계에서는 원문을 보존해야 한다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-044-vision-page1/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-044-vision-page1/response.json>)

## D-044-vision-page2 — 표 구조·좌표·상태

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-044/page-2.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업2팀/Shared Documents/새봄병원/2025_PACS 스토리지 증설/계약/PACS 스토리지 증설_계약서(서명본).pdf>)

- 원본: 4행×2열, 셀 8개. 표는 이미지 높이 약 23~31% 구간.
- Qwen3.6: 8개 셀과 행·열은 정확. 그러나 모두 unreadable, 페이지는 complete. 표 좌표 y=0.42~0.62로 원본과 불일치.
- Qwen3-VL: 완료된 셀 문자열 2개에 갑/을 각 열의 4행을 합침. 원래 8개 문구는 남아 있지만 셀 구조는 0/8. JSON 중간 종료, bbox=[1,1,1,1].
- 판정: 읽기·셀 구조·전달은 별개다. 3.6도 형식 검사 통과만으로 정확하다고 볼 수 없다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-044-vision-page2/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-044-vision-page2/response.json>)

## D-102-vision-page2 — 누락·표 구조

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-102/page-2.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업2팀/Shared Documents/OUDC/2025_시설관리시스템 노후 서버 교체/계약/시설관리시스템 노후 서버 교체_계약서(서명본).pdf>)

- 원본: 분쟁 해결 제목·2문단·2025년 10월 24일과 4×2 표.
- Qwen3.6: 표 8개 셀 내용·주소는 남음. 행 개수 등 뒤쪽 필드와 본문·날짜를 내보내기 전에 종료.
- Qwen3-VL: 표를 1×2로 합쳤고 본문·날짜는 빠짐. 좌표도 모두 한 점.
- 판정: 표 속 문구 보존 8/8과 표 구조 보존은 다르다. 두 출력 모두 공통 JSON 채택 실패.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-102-vision-page2/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-102-vision-page2/response.json>)

## D-069-vision-page1 — 구성도·누락·좌표

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-069/page-1.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/기술지원팀/Shared Documents/도담캐피탈/구성도/DDC_네트워크구성도_검토본_스캔.pdf>)

- 원본: 노드 8개, 화살촉 없는 연결선 7개, 제목·작성일·범례.
- Qwen3.6: 노드/연결은 모두 보존(×→x 허용 시). 범례의 =를 ≈로 변경. 선 좌표 폭 또는 높이 0으로 거절.
- Qwen3-VL: 노드 라벨·연결 8/8, 7/7. 제목·작성일·범례 누락. bbox=[1,0,1,1], 빈 chart도 추가.
- 판정: 이전 엄격 문자 비교에서 3.6의 연결선이 0/7로 보인 것은 ×/x가 포함된 노드 라벨 일치 문제였다. 실제 연결 구조가 전부 틀렸다는 뜻이 아니다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-069-vision-page1/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-069-vision-page1/response.json>)

## H-020-vision-page1 — 출력 반복·누락

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/additional-parsing-run-001/assets/H-020/page-1.png) · [원본 문서](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/additional-dataset-v1/files/푸른리테일/온라인몰 반품분류 견적서_최종.pdf>)

- 원본: 3×3 표 9셀과 견적번호 QT-26-PR-88, 작성일·유효기간·견적금액 등 표 밖 10항목.
- Qwen3.6: 9셀은 정확하게 기록. 표 밖 10항목을 내보내기 전에 JSON 종료.
- Qwen3-VL: 9셀 문구를 찾을 수 있으나 완료된 셀 text 필드가 211개까지 반복. 표 밖 10항목 누락, JSON 종료.
- 판정: 중단된 응답에서 완성된 필드만 읽은 진단이다. 복구된 정상 JSON으로 취급하지 않았다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/H-020-vision-page1/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/H-020-vision-page1/response.json>)

## D-001-vision-slide1 — 중복

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-001/slide-1.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업1팀/Shared Documents/청람정밀/2025_2025 MES 고도화 구축/제안/㈜청람정밀_2025 MES 고도화 구축_제안서.pptx>)

- 원본: 거래처·날짜 문단은 각각 한 번만 표시.
- Qwen3.6: 본문 한 번씩 기록.
- Qwen3-VL: 거래처·날짜 문단을 반복. ㈜와 (주) 표기 차이를 허용해도 원문 대비 중복.
- 판정: 공통 블록의 근거 인용이나 행 요약에서 생기는 의도된 반복은 이 집계에서 제외했다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-001-vision-slide1/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-001-vision-slide1/response.json>)

## D-001-vision-slide4 — 필드 배치·중복

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-001/slide-4.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업1팀/Shared Documents/청람정밀/2025_2025 MES 고도화 구축/제안/㈜청람정밀_2025 MES 고도화 구축_제안서.pptx>)

- 원본: 제안 목표 제목과 목표 1~3 상자.
- Qwen3.6: 원문을 texts와 노드에 중복 기록.
- Qwen3-VL: 읽은 원문을 claims에 반복 기록하다 종료. 원문 필드 texts/cells/nodes에는 전달하지 못함.
- 판정: 읽지 못한 경우와 읽었지만 잘못된 필드에만 넣은 경우를 분리한다. VL 전체 66개 기준 항목이 claims에서만 발견됐다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-001-vision-slide4/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-001-vision-slide4/response.json>)

## D-001-vision-slide5 — 구성도 반복

[원본 이미지](/Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-001/slide-5.png) · [원본 문서](</Users/kangdongkyoon/Downloads/RAG_예비데이터셋(클로드)/files/sites/영업1팀/Shared Documents/청람정밀/2025_2025 MES 고도화 구축/제안/㈜청람정밀_2025 MES 고도화 구축_제안서.pptx>)

- 원본: 노드 6개와 연결선 5개인 구성도 하나.
- Qwen3.6: 노드 6개·연결 5개를 한 번씩 기록.
- Qwen3-VL: 완성된 구성도 17개와 중간 구성도 1개를 반복. 원래 관계를 회수할 수 있어도 중복으로 정밀도가 하락.
- 판정: 반복을 제거한 회수율만 보면 문제를 숨기므로 중복을 포함한 정밀도도 함께 보고한다.

[qwen3.6-35b-a3b 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-001-vision-slide5/response.json>)
[qwen3-vl-30b-a3b-instruct 원응답](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/vision-comparison-run-001/qwen3-vl-30b-a3b-instruct/units/D-001-vision-slide5/response.json>)
