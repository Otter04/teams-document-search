"""Write a local report from completed evaluation snapshots; no model calls."""
from run import DEFAULT_RUN, MODELS, load, now

def main(out=DEFAULT_RUN):
    scores=load(out/'evaluation-comparison.json')
    audits=load(out/'response-audit-comparison.json')
    for e,a in zip(scores,audits):
        if e['model']!=a['model'] or e['execution']['attempted_units']!=a['responses']:
            raise ValueError('Evaluation snapshots differ; assemble and evaluate again first')
    done=all(e['execution']['unattempted_units']==0 for e in scores)
    names=['Qwen3.6-35B-A3B','Qwen3-VL-30B-A3B-Instruct']
    rows=[]
    def row(label,values):rows.append('| '+label+' | '+' | '.join(str(v) for v in values)+' |')
    row('응답 기록 / 대상',[f"{a['responses']}/132" for a in audits])
    row('완결 응답의 JSON 스키마 일치(좌표 순서 검사 전)',[f"{a['raw_schema_valid_before_geometry_checks']}/132" for a in audits])
    row('공통 블록 형식·참조 검사 통과',[f"{a['schema_and_reference_valid']}/132 ({a['schema_and_reference_valid']/132:.2%})" for a in audits])
    row('변환 거절·실패',[e['execution']['failed_units'] for e in scores])
    row('좌표 형식 오류로 거절',[sum(any('bbox' in msg for msg in f.get('errors') or []) for f in a['failure_cases']) for a in audits])
    row('출력 한도 도달',[a['finish_reasons'].get('length',0) for a in audits])
    row('전체 장이 형식 검사를 통과한 문서',[f"{a['all_units_valid_documents']}/36" for a in audits])
    row('입력 / 출력 토큰',[f"{e['execution']['input_tokens']:,} / {e['execution']['output_tokens']:,}" for e in scores])
    row('저장된 응답의 비용 합계',[f"${a['cost_usd_known_returned_responses']:.8f}" for a in audits])
    row('요청 경과 시간 중앙값 / 최대',[f"{a['latency_seconds']['median']:.1f}초 / {a['latency_seconds']['max']:.1f}초" for a in audits])
    row('완료 보고와 읽기 불가 셀이 함께 있는 응답',[len(a['complete_with_unreadable_cells']) for a in audits])
    row('같은 텍스트 블록 반복 의심 응답',[len(a['exact_text_repetition_flags_need_source_review']) for a in audits])
    metrics=[]
    for e,a in zip(scores,audits):
        raw=a['raw_diagnostics_not_admitted_to_common_blocks']
        metrics.append([
            f"{e['scan_required_strings']['correct']}/12",f"{raw['scan_strings']['correct']}/12",
            f"{e['D044_table_anchor_content']['correct']}/8",f"{raw['D044_table_anchor_content']['correct']}/8",
            f"{e['D069_nodes_exact_label']['correct']}/8",f"{raw['D069_exact_graph']['nodes']['correct']}/8",
            f"{e['D069_edges_exact_label_direction']['correct']}/7",f"{raw['D069_exact_graph']['edges']['correct']}/7"])
    labels=['필수 문자열 — 채택된 출력','필수 문자열 — 원응답 진단','D-044 표 셀 — 채택된 출력','D-044 표 셀 — 원응답 진단',
            'D-069 노드 — 채택된 출력','D-069 노드 — 원응답 진단','D-069 연결 — 채택된 출력','D-069 연결 — 원응답 진단']
    metric_table='\n'.join('| '+label+' | '+metrics[0][i]+' | '+metrics[1][i]+' |' for i,label in enumerate(labels))
    state='전체 264개 대상의 응답 처리·비교 집계 완료. 실패 출력과 원문 검수 대기는 남아 있다.' if done else '실행 중인 중간 집계. 미실행 항목의 점수는 모델 성능으로 해석하지 않는다.'
    doc=f'''# 두 후보 비전 처리 비교

집계 시각(UTC): {now()}

**{state}**

동일한 36문서·132장에 두 모델을 적용했다. JSON 변환 통과는 내용 정확도 합격이 아니다. 실패는 삭제하거나 성공 분모에서 제외하지 않았다. 기존 네이티브 원본·블록과 운영 검색 색인을 보존했다.

## 실행 결과

| 지표 | {names[0]} | {names[1]} |
|---|---:|---:|
{chr(10).join(rows)}

시간은 OpenRouter 요청의 관찰값이다. 실행 중 모델별 대기열과 동시 요청 수가 달랐으므로 동일 부하 처리량 비교나 DGX Spark 성능으로 해석하지 않는다. 요청 내용·제공업체·출력 조건은 동결했다.

반복 의심은 읽을 수 있는 JSON에서 같은 텍스트 블록이 여러 번 나온 자동 탐지 수다. 원본 자체의 반복 여부를 대조하기 전에는 전부 오류로 확정하지 않는다. 잘린 JSON은 이 탐지에 포함하지 않는다.

비용은 응답에 보고된 cost의 합계다. 사용자 중단 당시 원응답을 확보하지 못한 4개 요청은 별도 이력을 남기고 재개했으며, 그 이전 요청의 개별 과금 여부는 불명확하다. 따라서 위 합계를 모든 중단 이력까지 포함한 총 결제액으로 표현하지 않는다. 크레딧 충전 수수료·환율도 포함하지 않는다.

[실제 비용 대조](BILLING.md)에 키 사용액 조회와 응답 비용 합계를 기록했다. 재개 후 사용액 증가분은 재개 후 저장 응답의 비용과 일치한다.

## 정답 초안 검사

| 항목 | {names[0]} | {names[1]} |
|---|---:|---:|
{metric_table}

채택된 출력은 공통 블록 검사를 통과한 결과만 평가한다. 원응답 진단은 좌표 검사 등에서 거절돼도 읽을 수 있는 JSON의 내용을 별도로 검사한다. 원응답 진단 점수가 높아도 공통 블록 실패가 취소되지 않는다.

표 셀 점수는 내용·행열 인덱스·병합 범위를 비교한다. `value_status`와 실제 좌표 정확도까지 포함한 점수는 아니다. D-044의 상태 표시 모순은 아래에 별도로 기록했다.

위 정답은 기존 보조자 작성 초안이다. 전체 132장의 의미 정확도나 독립 검수 성적이 아니다. 노드 라벨은 공백 정규화 후 완전 일치로 검사하므로 `×`와 `x` 같은 표기 차이도 노드·연결 점수에 영향을 준다. 구체적인 해석은 [원본 대조 사례](SOURCE_REVIEW_CASES.md)를 함께 확인한다.

## 확인한 문제와 판정

- Qwen3.6은 일부 구성도 연결선의 폭·높이 0 또는 역순 좌표 때문에 공통 블록 변환에 실패했다. D-069의 연결 관계 자체는 원본 대조에서 확인했다.
- Qwen3-VL도 D-069에서 8개 라벨·7개 연결을 읽었지만 모든 좌표가 `[1,0,1,1]`이어서 실패했다. 주변 제목·작성일·범례도 누락됐다.
- Qwen3.6의 D-044 표는 8개 셀의 내용·행열 위치가 일치했지만 모두 `unreadable`로 표시했다. 실제 표 위치와 다른 좌표도 형식 검사를 통과했다. 형식 검사만으로 의미·근거 정확성을 보증할 수 없다.
- 두 모델 모두 출력 한도 도달 사례가 있다. Qwen3-VL의 일부 응답에는 내용 반복, Qwen3.6의 두 응답 후반에는 공백 반복이 관찰됐다.

현재 조건의 비전 파싱 후보 비교가 완료되더라도 최종 운영 모델은 아직 확정하지 않는다. 문서 보강 LLM 역할, 검색 효과, Spark 실행은 별도 평가다. 기존 검색 목표 90%와 위 JSON 통과율은 서로 다른 지표다.

공식 권장·평가 재현 설정과 현재 baseline의 차이는 [생성 설정 검토](GENERATION_SETTINGS_REVIEW.md)에 기록했다. 두 공식 자료의 temperature 0.7 설정과 이번 temperature 0은 다르다. 이것만으로 반복의 원인을 확정하지 않으며, 현재 결과를 모든 설정에서의 모델 순위로 일반화하지 않는다.

## 후속 작업

1. 원문 대조 결과를 기준으로 좌표·읽기 상태 모순·중복을 처리할 규격과 검증기를 보완한다. 이 실행의 원응답과 첫 점수는 보존하고 후속 실험을 별도 버전으로 만든다.
2. 실패·스캔·표·구성도 사례에서 수정한 설정을 두 모델에 동일하게 적용해 확인한다. `temperature=0`, strict JSON schema 등 현재 조건에서 나온 결과를 모델의 모든 설정에 일반화하지 않는다.
3. 검수한 비전 블록의 네이티브 중복을 정리한 뒤 문서 보강·청킹·검색에 연결하고 기존 및 비전 질문을 재평가한다.
4. 두 역할을 맡을 모델을 고르려면 메타데이터 추출의 값·근거·날짜 역할·근거 없는 추정도 비교한다. 최종 후보는 DGX Spark에서 별도 실행 검증한다.

## 파일

- [비교 지표 정의](../rag-vision-v1/COMPARISON_METRICS.md), [실행기](../rag-vision-v1/README.md)
- [고정 입력·프롬프트·스키마](manifest.json), [집계](summary.json)
- [채택 결과 평가](evaluation-comparison.json), [원응답 진단](response-audit-comparison.json)
- [원본·후보 JSON·요청 해시 무결성 확인](integrity-verification.json). 구현용 오프라인 테스트 9개도 통과했으며, 이 테스트는 모델 성능 점수가 아니다.
- 모델별 `units/`의 `response.json`은 원응답, `result.json`은 검증 결과다. 검증 통과 건에만 `extraction.json`과 공통 블록 문서가 있다.
- 모델별 `original/parsed.candidate.jsonl`, `additional/parsed.candidate.jsonl`은 110개·30개 문서를 포함한 후보 결과다. 그대로 운영 색인에 투입하지 않는다.
- 모델별 `evaluation/source-review-queue.json`은 132장 전체의 원본 대조 대기 목록이다. 일부 사례를 여기서 대조했지만 전체 사람 검수 상태를 완료로 바꾸지 않았다.
'''
    (out/'README.md').write_text(doc)
    print('Report written; all responses accounted for:',done)

if __name__=='__main__':main()
