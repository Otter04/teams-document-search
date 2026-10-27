"""Render an offline, escaped source/result comparison report."""
import html
import json
from pathlib import Path
from review_tools import HERE,PREP,evaluator

def esc(x):return html.escape(str(x))
def main():
    diag=evaluator.read(HERE/'diagnostics.json')['models']
    rv={r['candidate_id']:r for r in evaluator.read(HERE/'semantic-review.completed.json')}
    out=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>문서 보강 모델 비교</title>',
    '<style>body{font:16px/1.65 system-ui,sans-serif;background:#f4f6fa;color:#172439;margin:36px auto;max-width:1400px;padding:0 24px}h1{font-size:28px}h2{font-size:23px}h3{font-size:19px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border:1px solid #d9dfea;text-align:left}details{background:white;border:1px solid #d9dfea;border-radius:12px;padding:14px;margin:16px 0}summary{cursor:pointer;font-weight:700}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:#fff;border:1px solid #dae0e9;padding:18px;border-radius:12px;min-width:0}pre{white-space:pre-wrap;word-break:break-word;font-size:13px}.bad{color:#af2734}.muted{color:#5b6575}.source{background:#eef2f6;padding:12px}.pill{background:#dce8fe;padding:6px 12px;border-radius:12px}@media(max-width:850px){.pair{grid-template-columns:1fr}}</style>',
    '<h1>문서 보강 비교 · 같은 20문서, 두 모델</h1><p class="pill">추천 후보: Qwen3.6-35B-A3B · 자동 운영 합격 모델: 없음</p>',
    '<p>검색 성능 및 이미지 판독 재평가가 아닙니다. 공통 텍스트에서 메타데이터·요약을 만드는 능력을 비교했습니다. 원응답을 고치지 않았으며, 아래 내용 진단은 전달 실패 응답도 포함합니다. AI 원문 검수이며 독립 사람 검수 성적은 아닙니다.</p>',
    '<table><tr><th>지표</th><th>Qwen3.6</th><th>Qwen3-VL</th></tr>']
    for label,values in [
      ('필요한 메타데이터 값 일치 / 190',[f"{m['value_only']['matches']}/190" for m in diag]),
      ('완결되고 엄격하게 읽을 수 있는 JSON / 20',[f"{m['strict_json_documents']}/20" for m in diag]),
      ('전체 근거·상태·참조 검사 통과 / 20',[f"{m['frozen_valid_documents']}/20" for m in diag]),
      ('요약 핵심 사실 포함 / 61',[f"{m['summary_content_diagnostic']['covered']}/61" for m in diag]),
      ('요약 사실의 원문 지지',[f"{m['summary_content_diagnostic']['supported']}/{m['summary_content_diagnostic']['claims']}" for m in diag]),
      ('응답에 보고된 비용',[f"${m['usage']['reported_cost_sum']:.8f}" for m in diag])]:
        out.append('<tr><th>'+esc(label)+'</th>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    out.append('</table><p>값 일치는 인용·상태 규칙을 제외한 진단값입니다. 보강의 정식 합격 점수가 아닙니다. 핵심 사실은 요약 본문에 조건·수치가 포함되어야 하며 인용에만 있으면 회수로 세지 않습니다. VL의 제어문자 오류 1건은 내용만 확인하고 JSON 실패로 유지했습니다.</p>')
    for item in evaluator.manifest()['documents']:
        did=item['doc_id'];p=evaluator.read(PREP/item['input_path']);d=p['document']
        out.append(f'<details><summary>{esc(did)} · {esc(d["source"]["file_name"])}</summary>')
        out.append('<details><summary>공통 입력 원문 보기</summary><div class="source">')
        for b in d['blocks']:
            if b.get('text','').strip():out.append('<small>'+esc(b['block_id'])+'</small><pre>'+esc(b['text'])+'</pre>')
        out.append('</div></details><div class="pair">')
        for m in diag:
            row=next(x for x in m['documents'] if x['doc_id']==did)
            r=rv.get(evaluator.blind_id(m['model'],did))
            out.append('<div class="card"><h3>'+esc(m['model'].split('/')[-1])+'</h3>')
            out.append(f'<p>값 일치 {row["value_matches"]}/{row["needed"]} · 핵심 사실 {len(row["core_facts_covered"])}/{len(row["core_facts_expected"])}</p>')
            if r:
                for s in r['sentences']:
                    out.append('<p>'+esc(s['source_text'])+'</p>')
                    out.append('<details><summary>이 문장의 모델 인용과 검수 근거</summary><pre>'+esc(json.dumps({'model_evidence':s['candidate_evidence'],'review':s['atomic_claims']},ensure_ascii=False,indent=2))+'</pre></details>')
            if row['wrong_values']:out.append('<p class="bad">값 또는 필드 의미 문제</p><pre>'+esc(json.dumps(row['wrong_values'],ensure_ascii=False,indent=2))+'</pre>')
            if row['missing_needed']:out.append('<p class="bad">누락: '+esc(', '.join(row['missing_needed']))+'</p>')
            for issue in row['summary_issues']:out.append('<p class="bad">'+esc(issue['text'])+' — '+esc(issue['reason'])+'</p>')
            out.append('<details><summary>전체 전달 검증 오류 '+str(len(row['delivery_errors']))+'개</summary><pre>'+esc('\n'.join(row['delivery_errors']))+'</pre></details></div>')
        out.append('</div></details>')
    out.append('</html>');(HERE/'comparison.html').write_text('\n'.join(out))

if __name__=='__main__':main()
