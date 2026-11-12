from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'outputs/search-openrouter-rerank40-001'
def main():
    c=json.loads((OUT/'comparison.json').read_text());a='baseline100';b='candidate40';qa=c['question_analysis'];m=c['metrics']
    lines=['# Qwen ON: RRF 전체 최대100청크와 상위40청크 비교','',
    '2026-10-29. Mac MPS/FP16에서 기존195문서·3022청크·1024차원 문서 벡터를 재사용했다. 양쪽 질문 분석은 OpenRouter Qwen 재작성 ON이고, BM25는 원문50청크·벡터 검색은 재작성 문장50청크다. Qwen 출력과 질문 벡터·검색 후보·필터·RRF 전체 순위는 질문당1회 실행해 공유했다. 리랭커에는 원문 질문을 전달한다. 코드 R1은 사용하지 않는다.','',
    '**변경 변수:** 리랭커에 전달하는 RRF 후보 상한100/40만 변경했다. 중복 제거 후100개 미만이면 비교군은 실제 후보 전체를 사용한다. 재작성 실패 시 원문 복귀는 양쪽에 동일하게 적용하고 별도 집계했다.','',
    '## 판단','',
    '이번 개발용 166개 질문에서는 40개 제한이 기존 성공을 잃지 않으면서 평균 전체 단계 시간을 23.6% 줄였다. 새 성공 1개는 낮은 RRF 순위의 경쟁 문서가 제외되어 정답 문서가 5위에 진입한 사례다. 정확도가 일반적으로 더 좋아진다는 증거로 확대하지 않는다. 40개를 다음 검증의 유력한 후보로 유지하되, 기준 구조를 자동 변경하지 않는다.',
    '다만 Q-075의 정답 후보는 RRF 44위에서 제외됐다. 두 방식 모두 최종 검색에는 실패했으므로 이번 성공률에는 새 손실이 없지만, 40개 제한이 정답 후보를 잃을 수 있다는 사실은 확인됐다.','',
    '## 검색 성공','',
    '필수 정답 대표 문서가 모두 최종 상위5문서에 포함되어야 성공이다. 다른 버전·다른 형식만 있으면 대표 문서 성공과 구분한다.','',
    '| 범위 | 최대100 | 최대40 | 변화 |','|---|---:|---:|---:|']
    for label,key in [('기존125','old125'),('추가25','new25'),('원래150','original150'),('변형16','variants16'),('전체166','all166'),('재작성 검증 통과만','rewritten_only'),('재작성 원문 복귀만','fallback_only')]:
        x=c['summary'][a][key];y=c['summary'][b][key]
        if not x:continue
        n=x['questions'];u=x['all_required_representatives_found'];v=y['all_required_representatives_found']
        lines.append(f'| {label} | {u}/{n} ({u/n:.1%}) | {v}/{n} ({v/n:.1%}) | {v-u:+d} |')
    lines+=['',f"새 성공 {len(c['improvements'])}개: {', '.join(c['improvements']) or '없음'}.",f"기존 성공에서 새 실패 {len(c['regressions'])}개: {', '.join(c['regressions']) or '없음'}.",
      f"최종 상위5문서 목록·순서가 달라진 질문: {c['changed_top5_questions']}/166.",'',
      '| 전체166 보조 지표 | 최대100 | 최대40 |','|---|---:|---:|']
    for label,key in [('필수 문서군 모두 포함','all_required_families_found'),('필수 대표 문서가1위','required_representative_top1')]:
        lines.append(f"| {label} | {c['summary'][a]['all166'][key]}/166 | {c['summary'][b]['all166'][key]}/166 |")
    lines.append(f"| 정답 문서 MRR@5 (기존 정답표의 허용 문서 기준) | {c['summary'][a]['all166']['mrr_at5']:.4f} | {c['summary'][b]['all166']['mrr_at5']:.4f} |")
    lines+=['','## 후보 보존·모델 입력량','',f"40개 제한이 실제로 후보를 줄인 질문은 {c['cap_affected_questions']}개다. 아래 후보 지표는 실제 리랭커 적용 질문만 대상으로 한다.",'',
       '| 지표 | 최대100 | 최대40 |','|---|---:|---:|']
    for label,fun in [('모델 적용 질문',lambda x:str(x['applied_requests'])),('평균 입력 청크',lambda x:f"{x['actual_pairs']['mean']:.2f}"),('입력 청크 총합',lambda x:str(x['total_model_pairs'])),('평균 고유 후보 문서',lambda x:f"{x['unique_candidate_documents']['mean']:.2f}"),('한 문서가 차지하는 최대 청크 비중의 평균',lambda x:f"{x['largest_document_chunk_share']['mean']:.1%}"),('필수 정답 대표 문서 후보 보존',lambda x:f"{x['required_candidates']['present']}/{x['required_candidates']['required_documents']} ({x['required_candidates']['recall']:.1%})"),('모든 필수 정답 후보가 남은 질문',lambda x:f"{x['required_candidates']['all_required_present']}/{x['required_candidates']['queries']}")]:
        lines.append('| '+label+' | '+fun(m[a])+' | '+fun(m[b])+' |')
    lines+=['','## 시간','',
      '**측정 방법:** 첫 실행 방식을 질문마다 번갈아 배치했다. Qwen·임베딩·검색은 한 번 실행하고,100/40은 각각 모델 추론과 문서 묶기를 실행했다. 전체 단계 합은 공통 전처리 실측+각 경로 실측이다. 독립된 두 HTTP 요청 지연이나 동시부하 성적으로 해석하지 않는다. Qwen 비용 없는 워밍업은 제외했다.','',
      '| 시간 지표 | 최대100 | 최대40 |','|---|---:|---:|']
    for label,section,key in [('리랭킹 평균','rerank_applied','mean'),('리랭킹 중앙값','rerank_applied','median'),('리랭킹 P95','rerank_applied','p95'),('전체 단계 합 평균','equivalent_total','mean'),('전체 단계 합 중앙값','equivalent_total','median'),('전체 단계 합 P95','equivalent_total','p95')]:
        lines.append(f"| {label} | {m[a][section][key]:.3f}초 | {m[b][section][key]:.3f}초 |")
    rt=(1-m[b]['rerank_applied']['mean']/m[a]['rerank_applied']['mean'])*100
    total=(1-m[b]['equivalent_total']['mean']/m[a]['equivalent_total']['mean'])*100
    pairs=(1-m[b]['total_model_pairs']/m[a]['total_model_pairs'])*100
    lines+=['',f'평균 리랭킹 시간 변화: {rt:.1f}% 감소. 전체 단계 합 평균 변화: {total:.1f}% 감소. 모델 평가 쌍 수 변화: {pairs:.1f}% 감소.',
       f"공통 전처리 평균 {m[a]['common']['mean']:.3f}초, 그중 Qwen 호출 평균 {qa['seconds']['mean']:.3f}초. paired HTTP 전체 요청 시간도 원자료에 별도 저장했다.",'',
       '## Qwen·비용','',
       f"실제 상태: `{qa['statuses']}`. 원문 복귀 사유: `{qa['errors']}`. 공급자: `{qa['providers']}`.",
       f"API 응답 비용 합계 **USD {qa['api_reported_cost_usd']:.8f}**. 입력 {qa['prompt_tokens']}토큰·출력 {qa['completion_tokens']}토큰. 비용 미기록 {qa['missing_cost_records']}건. 비용은 질문당1회만 합산하며 양쪽에 중복 합산하지 않았다. 이전 연결 확인1회 비용 USD0.000045는 이 비교 비용에서 제외한다.",
       '재작성 검증 통과는 의미가 완전히 보존됐다는 보증이 아니다. 본 실험은 동일한 재작성·후보에 대한 입력 상한 비교이며 Qwen ON/OFF 품질 비교가 아니다.','',
       '## 검증·한계','',
       f"- 요청/실행 오류 {len(c['errors'])}건: {', '.join(c['errors']) or '없음'}.",
       f"- 공유 후보·계획·필터·40개 선택·R1/잘림 정책 불일치 {len(c['invariant_violations'])}건.",
       f"- 두 경로 원문 발췌 {c['literal_checks']}개 문자 범위·위치 대조, 불일치 {len(c['literal_errors'])}건.",
       '- 날짜순·추가 확인 요청은 리랭커 상한의 영향을 받지 않는 별도 경로로 구분했다.',
       f"- 동일 청크를 다른 배치에서 각각 추론한 점수 차이 최대 {c['common_score_absolute_delta'].get('max',0):.6f}. MPS FP16 연산과 배치 구성에 따른 미세 수치 차이가 있을 수 있다.",
       '- 개발에 사용된166질문 평가다. 신규 검증40질문·수만 문서 규모·동시부하·GPU 피크 메모리 비교는 이번 범위에 포함하지 않았다. Mac 실측을 과거 Orin 실측과 직접 비교하지 않는다.','']
    for name in [a,b]:
        path=OUT/name/'date-policy-audit.json'
        if path.exists():
            d=json.loads(path.read_text());lines.append(f"- {name} 날짜 검수: 고정 {d['locked_ranges']}/{d['date_questions']}, 완화 {d['date_relaxations']}, 범위 검사 `{d['totals']}`, Q-061 정확히3건 여부 `{d['q061_exact_three']}`.")
    lines+=['','### 공통으로 남은 조건 처리 문제','',
      '날짜 범위 11/11 고정·날짜 범위 밖 결과 0건과 검색 조건 전체 충족은 다르다. 결과가 없어야 하는 2개 검사 중 양쪽 모두 Q-068만 통과했다. Q-069(해솔유통 2024년 계약서)는 날짜 조건은 지켰지만 다른 업체·문서 종류를 반환했다. 실제 적용 필터에 업체와 문서 종류의 강제 조건이 없었다. Q-061(올해 돌린 백업 로그)은 정답 백업 로그 3개 외에 점검 문서도 반환하여 정확히 3개 결과 검사에 실패했다. 이는 두 방식에 공통으로 남은 문제이며 이번 입력 상한 비교에서 수정하지 않았다.',
      'Q-140의 성공 변화는 정답 문서 최고 점수 변화 때문이 아니다. 정답 D-174의 최고 점수는 두 방식 모두 -7.18359375다. RRF 46위의 경쟁 문서 D-192가 40개 제한에서 제외되면서 D-174가 최종 5위에 진입했다.','',
      '## 변경 질문 상세','']
    for d in c['details']:
        if d['query_id'] not in c['regressions']+c['improvements'] and not d['lost_required_candidates']:continue
        lines += [f"### {d['query_id']} — {d['query']}",'',f"- 재작성: {d['rewritten']} ({d['llm_status']})",f"- 성공:100 `{d['baseline_success']}` /40 `{d['candidate_success']}`.",
          f"- 최종100: {', '.join(d['top100'])}",f"- 최종40: {', '.join(d['top40'])}",f"- 잘린 필수 정답 후보: {', '.join(d['lost_required_candidates']) or '없음'}"]
        for r in d['required']:lines.append(f"- {r['doc_id']} {r['title']}: RRF {r['rrf_rank']}, 최종100 {r['final100_rank']}, 최종40 {r['final40_rank']}.")
        lines.append('')
    lines+=['## 파일','', '[질문별 CSV](question-comparison.csv) · [비교 지표 JSON](comparison.json) · [실제 paired 응답](pairs.jsonl) · [고정 설정·해시](freeze.json) · [실험 계획](PROTOCOL.md)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    print('REPORT.md saved')
if __name__=='__main__':main()
