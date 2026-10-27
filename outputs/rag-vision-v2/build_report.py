"""Describe quality-gate replay separately from extraction accuracy."""
import collections
from evaluate import OUT,ROOT,load,write

def main():
    reports=load(OUT/'evaluation.json');queue=load(OUT/'remediation-queue.json');integrity=load(OUT/'integrity.json')
    table=['| 항목 | Qwen3.6-35B-A3B | Qwen3-VL-30B-A3B-Instruct |','|---|---:|---:|']
    def add(label,fn):table.append('| '+label+' | '+' | '.join(str(fn(m)) for m in reports)+' |')
    add('기존 형식 검사 통과',lambda m:f"{m['summary']['previous_valid']}/132")
    add('새 규칙 통과 후보 — 의미 정확도 합격 아님',lambda m:f"{m['summary']['decisions'].get('candidate',0)}/132")
    add('차단 reject — 기존 실패 포함',lambda m:m['summary']['decisions'].get('reject',0))
    add('추가 확인 review — 자동 전달 보류',lambda m:m['summary']['decisions'].get('review',0))
    add('기존 통과 중 새로 차단·보류',lambda m:m['summary']['newly_held_from_previous_valid'])
    add('이전 원문 대조의 중복 표시 사례 재검출',lambda m:f"{m['summary']['prior_duplicate_flag_detected']}/{m['summary']['prior_duplicate_flagged_images']}")
    add('원문이 claims에만 있는 페이지',lambda m:m['summary']['issues_by_image'].get('SOURCE_LITERAL_ONLY_IN_CLAIMS',0))
    add('complete + unreadable 모순 페이지',lambda m:m['summary']['issues_by_image'].get('COMPLETE_WITH_UNREADABLE_CELL',0))
    add('기존 140문서 네이티브 블록·source 보존',lambda m:m['summary']['native_documents_preserved'])
    report='''# 비전 검증기 v2 — 기존 응답 오프라인 재평가

2026-10-19. 36문서·132장 × 두 모델의 기존 응답 264개를 재검사했다. **추가 유료 호출, 모델 재호출, 검색 평가는 0건**이다. 모델의 원문 추출 내용이나 이전 결과를 수정하지 않았다.

## 변환기와 검증기의 의미

```text
이미지 → 비전 LLM → 모델 JSON → 검증기 v2 → 통과 후보만 공통 블록 변환 코드 → 공통 JSON
                                     └→ 문제 발견 시 차단/검수 대기
네이티브 문서 → 네이티브 파서 ─────────────────────────────→ 공통 JSON
                                                               ↓
                                                이후 문서 보강(메타데이터 추출 등)
```

변환기는 LLM이 아니라 Python 코드다. 예를 들어 모델의 tables[].cells[]를 공통 블록의 table/table_row/cells로 옮기고, 이미지 ID·페이지 위치·근거·모델 이력을 붙인다. 원문을 다시 이해하거나 오독을 고치는 역할은 없다. 문서 보강에서 쓰려는 LLM과도 별개다.

모델 가중치는 이번에 바꾸지 않았다. 같은 모델이라도 프롬프트·이미지 해상도·한 번에 요구하는 출력량·생성 설정에 따라 응답은 달라질 수 있으나, 개선 효과는 별도 실험이 필요하다. **이번 작업은 모델 성능 향상이 아니라 오류 검출과 다음 단계 전달 통제의 개선**이다.

## 결과

'''+ '\n'.join(table)+'''

통과가 줄어든 이유는 기준이 더 엄격해졌기 때문이다. 원문 내용 보존율이나 모델 읽기 정확도가 개선됐다는 뜻이 아니다. 규칙별 발견 수는 한 응답에 겹칠 수 있어 합산하면 안 된다. 중간 종료 응답의 완성된 필드에서도 진단은 수행했지만, 그런 응답을 정상 JSON으로 복구하거나 승격하지 않았다.

Qwen3-VL의 review 5장은 같은 원문 구절을 다른 좌표에 반복 기록한 사례다. 문맥의 출현 횟수와 비교해 보류했으며, 위치·분할 방식에 대한 검수가 필요하므로 확정 삭제 대상으로 간주하지 않았다.

이전 원문 대조에서 중복을 표시했던 13장/98장을 모두 다시 검출했다. 이는 **같은 개발 자료의 알려진 사례 회귀 확인**이며, 새로운 독립 정답에 대한 검출 정밀도/재현율 인증은 아니다. 새 규칙은 6~7자 목차 문구의 texts/nodes 반복처럼 이전 8자 이상 구절 검사에서 빠진 사례도 잡는다.

## 추가한 규칙

| 검사 | 동작 | 정상 사례와의 구분 |
|---|---|---|
| 같은 위치의 문장·노드 반복, texts↔nodes/cells 중복 | 차단 | 다른 위치의 같은 문구는 원문 횟수 근거 없이는 차단하지 않음 |
| 같은 표와 셀 앵커, 같은 관계, 같은 설명 반복 | 차단 | 다른 셀에 동일한 숫자/값이 있는 것은 허용. 관계는 끝점·방향·라벨·영역을 함께 봄 |
| 원문 문맥보다 같은 구절이 많이 나옴 | 검수 대기 | 잘못된 좌표 때문에 반복 검사가 빠지는 경우 보완. 자동 삭제하지 않음 |
| 제공된 네이티브 원문이 claims에만 있고 원문 필드에 없음 | 검수 대기 | 이미지 설명이 원문 필드를 인용하는 정상 경우는 허용. 네이티브 문맥 없는 스캔에 자동 추정 적용하지 않음 |
| complete인데 unreadable 셀이 있음 | 차단 | 부분 판독은 partial + 경고로 표현할 수 있음 |
| known인데 셀 내용이 비어 있음 | 차단 | blank/unreadable을 구분하도록 요구 |
| unreadable인데 일부 글자가 있음 | 검수 대기 | 일부만 읽은 정상 상황일 수도 있어 내용 삭제나 known 전환을 하지 않음 |
| 잘린 JSON·중복 객체 키·기존 스키마/좌표/참조 오류 | 차단 | 괄호 추가, 값 추측, 실패 결과 정상 승격 없음 |

새 검증기는 정답 라벨을 읽지 않는다. 응답 자체와 호출 시 이미 제공한 native_context만 사용한다. 원문 검수 초안은 별도의 평가/잔여 작업 목록을 만드는 데만 썼다. 문서 ID나 특정 모델에 맞춘 예외 규칙은 없다.

## 확인된 대표 사례

- **D-001 slide2 / Qwen3.6:** 목차 항목 `01 사업 이해` 등을 texts와 nodes에 동시에 기록한 응답을 추가 차단했다.
- **D-044 page2 / Qwen3.6:** 기존 형식 검사에서는 통과했으나, 8개 셀의 unreadable과 페이지 complete가 모순되어 추가 차단했다. 셀 문구는 변경하지 않았다.
- **D-001 slide4 / Qwen3-VL:** 원문이 그림 설명 claims에만 들어간 점을 검출했다. 이미 JSON 중간 종료로 실패했던 응답에 실패 원인을 추가로 분류한 것이며 신규 실패로 중복 집계하지 않았다.
- **D-040 page1 / Qwen3-VL:** 같은 날짜·회사 문구가 반복되는데 좌표가 달라 위치 기반 검사만으로는 놓쳤다. 네이티브 문맥의 실제 출현 횟수로 검수 대기 처리했다.
- **H-020 / 두 모델:** JSON 중간 종료는 계속 차단했다. VL의 셀 반복 및 두 모델의 complete/unreadable 모순은 완성된 접두 필드에서 진단했다. 접두 필드는 ingestion에 사용하지 않았다.

## 원문 재확인이 필요한 문제

**Qwen3.6의 D-044 page1은 새 규칙을 통과해도 원문 오독이 남는다.** `양 당사자→당 당사자`처럼 내부 형식에 모순이 없는 오독을 검증기만으로 알아낼 수 없기 때문이다. 통과 후보는 의미상 승인된 자료가 아니며 model_output_needs_source_review 표시를 유지한다.

별도 [원문 재확인·재추출 목록](REEXTRACTION_REVIEW.md)에 3.6의 스캔 불일치 23항목, VL의 21항목을 남겼다. 이는 잘못된 문서 수가 아니라 이전 원문 대조에서 정의한 문단·셀·라벨 단위다. 숫자·날짜·거래처명을 검증기가 임의로 채우지 않는다.

- 3.6: 스캔 본문의 오독/표현 변경 후보 9항목, 누락/불일치 14항목.
- VL: 오독/표현 변경 후보 1항목, 누락/불일치 20항목.
- 여기에는 H-020의 표 밖 10항목, D-102 page2의 본문·날짜 4항목처럼 기존 응답에 없는 정보가 포함된다. 사람의 원문 기반 수정이나 향후 모델 재추출이 필요하며, 새 호출 성공을 보장하지 않는다.
- VL의 **claims에 남아 있는 66항목**과 **네이티브 원문에서 복구할 수 있는 5항목**은 별도로 구분했다. 이들은 바로 유료 재호출이 필요한 것으로 묶지 않았다. 필드 이동·복원도 원문/위치 검수 후 별도 이력으로 수행해야 한다.
- 계약서 표를 4×2에서 긴 두 셀로 합친 문제, 잘못된 bbox는 원문 구조/위치 확인이 필요하다. 문자열이 남아 있는 경우 수동·규칙 재구성 가능성을 검토할 수 있지만 이번에는 자동 수정하지 않았다.

## 산출물과 실행 경계

- [전체 검사 결과](evaluation.json): 264응답의 결정, 기존 실패, 새 이슈, 접두 진단을 분리.
- [잔여 작업 JSON](remediation-queue.json): 기존 응답 필드 검수 / 네이티브 복구 검수 / 원문 재확인·재추출의 세 경로.
- 모델별 original/additional/parsed.quality-candidate.jsonl: 새 규칙 통과한 비전 단위만 반영한 **검토용 문서 후보**. 차단·보류 단위는 pending. 각 모델의 140개 문서와 기존 네이티브 블록은 유지했다. 기존 검색 색인에는 반영하지 않았다.
- [보존 증거](integrity.json): 이전 응답·평가 결과·원본·네이티브 자료·동결 v1 코드를 해시로 비교.
- [최종 확인](verification.json): 경계·회귀 테스트 27개 통과, 후보 문서 280개 스키마 검사, 규칙 통과 88개 비전 단위의 원응답→조립 JSON 내용·구조 보존, 나머지 176개 단위 pending 유지. 마지막 재평가는 소켓 생성을 차단한 상태에서 실행했다.
- [검증기 코드](../rag-vision-v2/quality.py)의 convert_checked가 새 검사 후 변환하는 진입점이다. [재평가기](../rag-vision-v2/evaluate.py)가 이 진입점을 실제 사용했다. 기존 유료 호출용 v1은 동결 기록으로 보존했다. 향후 새로운 호출 경로도 이 진입점을 거치도록 연결해야 하며, 이번에는 온라인 실행 경로를 새로 만들거나 호출하지 않았다.

실제 적용한 것은 로컬 오프라인 검증·변환 경로다. 모델 입력 프롬프트, 출력 토큰 한도, API 설정, 모델 가중치, 공통 블록 스키마는 변경하지 않았다. 자동 중복 제거·필드 이동·원문 수정·누락 채우기도 수행하지 않았다.

## 한계

원문 없는 내부 검사만으로 문장 뜻의 정확성, 모든 누락, 모든 bbox 위치 오류를 증명할 수 없다. 필드 배치 검사는 네이티브 문맥이 있는 범위에 한정된다. 짧은 문자열, 문구를 바꾼 반복, 다른 위치의 반복은 일부 빠지거나 검수가 필요할 수 있다. 이 자료에서 발견된 오류를 보고 만든 규칙이므로 독립 자료에서 오탐/미탐을 추가 확인해야 한다. 원문 참조는 이전 AI 검수 초안이며 사람의 독립 검수 성적이 아니다.
'''
    (OUT/'README.md').write_text(report)
    remaining=['# 원문 재확인·재추출 목록','', '추가 호출은 실행하지 않았다. 아래 항목은 검증기만으로 정답을 만들 수 없다. 사람의 원본 대조 수정 또는 향후 모델 재추출이 필요하다. 재호출이 유일한 방법이거나 성공이 보장된다는 뜻은 아니다.','',
      '구절 단위는 이전 AI 검수 초안을 유지했다. possible_misread_or_rewrite / missing_or_unmatched는 근접 문자열 유사도 0.7 기준의 분류 보조이며, 최종 원인 확정은 원문 대조가 필요하다. 기존 검수에서 확인한 오독 예시는 README에 적었다.','']
    for m in reports:
        name=m['summary']['model'];qs=[q for q in queue if q['model']==name];remaining += ['## '+name,'']
        for action,title in [('source_reinspection_or_model_recall','원문 재확인 또는 향후 재추출'),('existing_response_field_review','기존 응답 claims에서 필드 배치 검수 가능'),('native_source_recovery_review','네이티브 원문 복구 검수 가능')]:
            rows=[q for q in qs if q['action']==action];remaining += [f'### {title}: {len(rows)}항목','']
            for key in dict.fromkeys(q['key'] for q in rows):
                group=[q for q in rows if q['key']==key];remaining += [f'#### {key}', '',f"[원본 이미지](<{group[0]['image_path']}>) · 새 검증 결과: {group[0]['new_gate_decision']}",'']
                for q in group:
                    remaining += [f"- 원문 기준: {q['expected']}",f"  - 가까운 출력: {q['nearest'] or '없음'}",f"  - 분류 보조: {q['kind']}"]
                remaining.append('')
    (OUT/'REEXTRACTION_REVIEW.md').write_text('\n'.join(remaining))
    print('reports saved',integrity['files_checked'],'frozen files preserved')

if __name__=='__main__':main()
