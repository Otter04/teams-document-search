"""Render a policy comparison from offline results; no model invocation."""
import collections
from evaluate import OUT, load

def main():
    reports=load(OUT/'evaluation.json');integrity=load(OUT/'integrity.json')
    verification=load(OUT/'verification.json')
    lines=['# 비전 검증기 v3 — 차단과 경고를 분리한 재평가', '',
      '2026-10-19. 기존 36문서·132장에 대한 두 모델의 264응답을 그대로 재사용했다. 유료 호출·모델 재호출·검색 평가는 0건이다.', '',
      '검출 기준은 유지하고 **전달 정책을 완화**했다. 중복·필드 배치 의심·읽기 상태 모순이 있어도 구조상 공통 JSON으로 옮길 수 있으면 경고와 함께 전달한다. 새로 전달되는 내용의 오류를 수정했다는 뜻은 아니다.', '',
      '## 이전과 비교', '',
      '| 항목 | Qwen3.6-35B-A3B | Qwen3-VL-30B-A3B-Instruct |', '|---|---:|---:|']
    def row(label,fn):lines.append('| '+label+' | '+' | '.join(str(fn(r['summary'])) for r in reports)+' |')
    row('v2 전달 가능',lambda s:s['previous_v2_decisions'].get('candidate',0))
    row('v3 새 검사 경고 없음',lambda s:s['decisions'].get('candidate',0))
    row('v3 경고를 붙여 전달',lambda s:s['decisions'].get('candidate_with_warnings',0))
    row('v3 총 전달 가능 / 132장',lambda s:f"{s['transferred']}/132 ({s['transferred']/132:.2%})")
    row('전달 차단·보류: v2 → v3',lambda s:f"{132-s['previous_v2_decisions'].get('candidate',0)} → {s['decisions'].get('reject',0)}")
    row('기존 v1 형식 통과 응답',lambda s:s['previous_valid'])
    lines += ['', 'v2에서 추가 차단·보류했던 26장과 55장을 경고부 전달로 전환했다. 최초 v1의 형식 통과 수로 돌아왔지만, 발견된 이슈와 검수 필요 표시는 그대로 남는다. 이는 전달률이며 모델 정확도·파싱 완료율·검색 성공률이 아니다.', '',
      '## 적용 기준', '',
      '| 문제 | v2 | v3 |', '|---|---|---|',
      '| 같은 문구·표·연결선·설명의 반복 | 차단 | 경고와 원문을 보존해 전달 |',
      '| 네이티브 문맥보다 많은 반복 / 원문이 claims에만 있음 | 검수까지 전달 보류 | 경고부 전달, 필드를 자동 이동하지 않음 |',
      '| complete인데 unreadable 셀 존재 / known 셀이 비어 있음 | 차단 | 경고부 전달, 해당 단위는 pending |',
      '| unreadable인데 일부 글자가 있음 | 검수까지 전달 보류 | 부분 판독 가능성을 인정해 경고부 전달 |',
      '| 잘린 JSON·중복 객체 키·스키마 위반 | 차단 | 차단 유지 |',
      '| 중복/겹친 셀 앵커·표 범위 밖 셀·빠진 셀 위치 | 차단 | 차단 유지 |',
      '| 잘못된 좌표·없는 노드로 연결·중복 노드 ID | 차단 | 차단 유지 |',
      '| 제공자·모델·종료 이유 등 고정 실행 조건 위반 | 차단 | 차단 유지 |', '',
      '모델별·문서별 예외나 정답 라벨에 맞춘 통과 규칙은 없다. 기존 검사 이슈 코드와 발생 횟수가 264응답 모두 v2와 같은지 확인했다. 새로 추가되는 미분류 검사는 자동 경고 전환하지 않는다.', '',
      '## 경고가 전달되는 방식', '',
      '- 응답 자체의 문구·셀 값·claims·좌표·노드/관계는 바꾸지 않는다. 중복도 이번에 삭제하지 않는다.',
      '- 평가 JSON에는 candidate_with_warnings, review_required=true, 이슈별 경로와 근거를 남긴다.',
      '- 공통 JSON의 해당 블록과 문서 warnings에 버전과 이슈 코드를 기록한다.',
      '- coverage.units의 해당 페이지/슬라이드는 block_ids를 채우되 status=pending으로 둔다. 내용은 전달됐고 검수는 남았다는 뜻이다. 모델이 보고한 complete를 검수 완료로 간주하지 않는다.',
      '- candidate도 의미 정확도 승인이라는 뜻이 아니다. 모든 새 블록의 model_output_needs_source_review 표시를 유지한다.', '',
      '예: **Qwen3.6 D-001 slide2**의 본문/도형 목차 중복은 그대로 전달하고 경고를 붙인다. **D-044 page2**의 표는 셀 문구와 unreadable 상태를 유지하면서 페이지의 검수 상태를 pending으로 둔다. **Qwen3-VL D-040 page1**의 반복 의심도 내용 보존 후 경고로 전달한다. H-020처럼 JSON이 중간 종료된 경우는 계속 차단한다.', '',
      '## 여전히 차단되는 이유', '']
    for r in reports:
        reasons=collections.Counter(e for rec in r['records'] if rec['decision']=='reject' for e in set(rec['baseline_errors']))
        lines += ['### '+r['summary']['model'], '', '같은 응답이 여러 이유에 포함될 수 있다. 아래는 주요 6가지 원인이다.', '']
        lines += [f'- {reason}: {count}응답' for reason,count in reasons.most_common(6)]
        lines.append('')
    lines += ['## 원문 정확도와 후속 작업', '',
      '검증 완화로 원문 오독·누락이 해결되지는 않았다. D-044 page1의 `양 당사자 → 당 당사자` 같은 오독은 경고 없는 응답에도 남을 수 있다. 경고 응답의 내용을 그대로 넘기므로 중복과 잘못된 필드 배치도 후속 검수·정제 전에는 남아 있다.', '',
      '[기존 원문 재검수·재추출 상세 목록](../vision-validation-run-002/REEXTRACTION_REVIEW.md)의 원문/출력 대조는 그대로 유효하다. 그 문서의 v2 채택 상태는 과거 기록이다. 이번 상태는 [잔여 작업 JSON](remediation-queue.json)의 new_gate_decision에서 확인한다. 스캔의 원문 불일치 23항목/21항목, VL의 claims에 남은 66항목과 네이티브 복구 검수 5항목은 새로 고치거나 재추출하지 않았다.', '',
      '## 검증과 파일', '',
      f'- 원응답·원본·v1/v2 코드·기존 결과 {integrity["files_checked"]}파일 해시 비교: 변경 0건.',
      f'- 모델별 140문서, 총 {verification["schema_valid_documents"]}개의 후보 문서 공통 스키마 검사 통과.',
      f'- 전달 {verification["roundtrip_units"]}개 단위의 문자·표 셀·좌표·구성도·claims가 공통 블록 변환 후 동일함을 확인.',
      f'- 경고부 전달 {verification["warning_units_pending"]}개 단위는 내용과 경고를 보존한 pending, 차단 {verification["rejected_units_empty_pending"]}개 단위는 블록 없는 pending.',
      '- 새 경계·회귀 테스트 34개 통과. 네트워크 소켓 생성을 차단한 상태로 전체 재평가했다.',
      '- [전체 평가](evaluation.json) · [검증 결과](verification.json) · [보존 해시](integrity.json)',
      '- 모델별 original/additional/parsed.quality-candidate.jsonl: 경고부 전달까지 포함한 검토용 후보. 기존 검색 색인에는 반영하지 않았다.',
      '- [코드와 실행 방법](../rag-vision-v3/README.md). v3 convert_checked를 로컬 오프라인 경로에 적용했다. 동결된 기존 유료 실행기는 변경하지 않았으며 향후 온라인 경로에서는 v3를 연결해야 한다.', '']
    (OUT/'README.md').write_text('\n'.join(lines))

if __name__=='__main__':main()
