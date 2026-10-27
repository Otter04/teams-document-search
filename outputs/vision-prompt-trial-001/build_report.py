import base64
import html
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
def load(p):return json.loads(Path(p).read_text())
def main():
    reports=load(OUT/'comparison.json');execution=load(OUT/'execution-summary.json');verification=load(OUT/'verification.json')
    manifest=load(OUT/'manifest.json');items={i['doc_id']+'-'+i['unit_id'].replace(':','-'):i for i in manifest['items']}
    labels={'D-001-vision-slide2':'목차: 본문/도형 중복','D-001-vision-slide4':'목표: 설명 칸 배치','D-001-vision-slide5':'구성도: 연결 반복','D-001-vision-slide7':'투입 인력: 표 반복','D-044-vision-page2':'계약서: 표·읽기 상태','H-020-vision-page1':'견적서: 반복·누락','D-020-vision-slide1':'제안서 표지: 정상 비교'}
    metric=[('중복 검출 이미지','duplicate_images'),('원문이 설명 칸에만 있는 이미지','only_in_claims_images'),('설명 칸에만 있는 기준 항목','only_in_claims'),('원문 칸의 기준 항목 보존','literal_retained'),('설명까지 포함한 기준 항목 보존','anywhere_retained'),('비교할 원문 기준 항목 수','reference_total'),('원문 칸에서 불일치/누락','literal_unmatched'),('어느 칸에서도 원문 일치 없음','anywhere_unmatched'),('완결된 JSON','json_complete'),('공통 JSON 전달 가능','transferred'),('완료/읽기 불가 모순 이미지','complete_with_unreadable_images'),('행·열·내용이 맞는 표 셀','table_cells_correct'),('원본 표 셀 수','table_cells_expected'),('출력된 표 셀 수 — 중복 포함','table_cells_emitted'),('정답과 맞는 구성도 연결','graph_edges_correct'),('원본 구성도 연결 수','graph_edges_expected')]
    lines=['프롬프트만 바꾼 대표 자료 비교 — 2026-10-19','',
      '결론: 이 7장 시험에서 Qwen3-VL은 원문 칸 보존과 JSON 전달이 개선됐다. Qwen3.6은 본문/도형 중복은 줄었지만 정상 표 응답이 중간 종료되어 제목 1개가 새로 누락됐다. 두 모델에 수정 프롬프트를 일괄 적용할 근거로 삼기에는 부족하다.',
      '남은 사례: VL은 목표/구성도에서 본문·도형 중복이 남고 스캔 계약서에서 표를 26번 반복했다. 3.6은 공백 출력 반복과 구성도 좌표 문제가 남았다. 상세한 개선·악화와 원문 대조는 SOURCE_REVIEW.txt에 기록했다.',
      '',
      '대표 7장 × 두 모델을 각 1회 새로 호출하고 같은 자료의 기존 응답과 비교했다. 반복 호출 실험이나 독립 평가가 아닌 개발용 확인이다.',
      '변경: 시스템 프롬프트만 변경. 같은 위치 원문을 어느 칸에 넣을지 먼저 구분, 표/구성도/선의 1회 기록, 원문과 설명의 역할, 읽기 상태의 일치를 명시했다.',
      '유지: 이미지·네이티브 문맥·모델 ID·제공자 DeepInfra FP8·temperature 0·seed 42·출력 한도 16384·JSON 양식·공통 블록 구조·v3 검증 기준.',
      '양식/파이프라인을 새 구조로 바꾼 것이 아니다. 실험용 호출기와 비교 보고서를 추가했으며, 기존 변환기의 실행 이력에는 새 프롬프트 버전만 기록했다.',
      f'응답 {execution["saved_responses"]}/14개 보존. 응답 usage에 보고된 비용 합계 ${execution["reported_cost_usd"]:.8f}. 자동 재호출 0회.',
      '']
    for report in reports:
        b,a=report['before'],report['after'];lines += [report['model'],'항목: 이전 → 수정 후']
        lines += [f'- {label}: {b[key]} → {a[key]}' for label,key in metric]
        lines += ['','자료별: 중복 발생 여부 / 원문 칸 보존 / 설명 포함 보존 / 설명에만 있는 항목 / JSON 종료 여부']
        for r in report['records']:
            def brief(x):return f"중복 {'있음' if x['duplicate_detected'] else '없음'}, 원문 {x['coverage']['compatible']}/{x['coverage']['total']}, 설명포함 {x['coverage_including_claims']['compatible']}/{x['coverage_including_claims']['total']}, 설명에만 {len(x['only_in_claims'])}, JSON {'완결' if x['json_complete'] else '중간종료'}, 전달 {x['assessment']['decision']}"
            lines += [f"- {labels[r['key']]} ({r['key']})",'  이전: '+brief(r['before']),'  이후: '+brief(r['after'])]
            for x in r['newly_missing_anywhere']:lines += ['  새 원문 불일치/누락: '+x['expected'],'  가장 가까운 출력: '+str(x['nearest'])]
            if r['recovered_anywhere']:lines += ['  새로 회수한 기준 항목: '+str(len(r['recovered_anywhere']))]
        lines += ['']
    lines += ['지표를 읽는 방법',
      '- 원문 기준 항목은 문단·셀·상자 글자 단위이며 전체 의미 정확도가 아니다. 공백과 ㈜/(주), ×/x를 동일하게 보고 원문이 해당 칸에 남았는지 확인했다.',
      '- 원문이 설명 칸에만 있는 경우는 원문 칸 누락과 구분해 함께 셌다. 어느 칸에서도 원문과 일치하지 않는 경우도 의역/오독일 수 있으므로 모두 완전한 정보 소실이라고 단정하지 않는다.',
      '- 중간 종료 응답도 끝까지 작성된 필드는 진단에 포함했다. 실패 JSON을 복구하거나 정상 전달한 것은 아니다.',
      '- 중복 이미지는 기존 v3 규칙으로 감지한 이미지 수다. 설명이 원문을 인용하는 모든 경우를 중복으로 세지는 않는다. 세부 이슈 수는 겹칠 수 있다.',
      '- 원문 참조는 기존 AI 검수 초안을 고정해 사용했다. 별도 사람 검수나 새로운 자료에서 얻은 독립 성적이 아니다.',
      '- 같은 조건을 요청했지만 제공자 내부 버전/실행 변동까지 고정한 것은 아니며, 각 모델당 1회이므로 프롬프트의 보편적 효과를 확정하지 않는다.',
      '- 원문 문자·표·연결 점수와 그림 설명의 사실성은 다르다. 의미 설명은 별도 사례 검수 파일을 함께 확인한다.',
      '',f"기존 파일 {verification['previous_files_checked']}개 해시 보존. 기존 기준 점수 재현 확인. 전달된 새 응답 {verification['converted_payload_preserved']}개의 내용/구조 변환 보존 확인.",
      '파일: comparison.json 전체 쌍별 결과 / newly-unmatched-source-items.json 새 원문 불일치 / verification.json 검증 / manifest.json 고정 조건 / 모델별 units의 response.json 원응답.',
      '온라인 추가 실행·전체 132장 재실행·검색 색인 반영은 이번 범위에 포함하지 않았다.']
    (OUT/'REPORT.txt').write_text('\n'.join(lines)+'\n')
    esc=html.escape
    parts=['''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>프롬프트 수정 전후 비교</title><style>
body{font-family:system-ui,sans-serif;background:#f4f6fa;color:#152238;line-height:1.7;margin:0}main{max-width:1400px;margin:auto;padding:28px}section{background:white;padding:24px;border:1px solid #dce3ed;border-radius:12px;margin:24px 0}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #d9dfeb;padding:8px;text-align:left}th{background:#edf3ff}img{max-width:100%;height:auto}.cols{display:grid;grid-template-columns:1fr 1fr;gap:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:500px;overflow:auto;background:#f2f5fa;padding:12px;font-size:13px}a{color:#1751ac}summary{cursor:pointer;font-weight:650}.note{background:#fff1d7;padding:14px}@media(max-width:850px){.cols{grid-template-columns:1fr}}
</style><main><h1>같은 자료, 프롬프트만 바꿔 다시 읽기</h1><p>7장 × 두 모델 · 기존 응답과 새 응답의 비교 · 출력 구조와 평가 기준은 동일</p><p class="note">중복 감소만 보지 않고 원문 누락도 함께 비교한다. 완결된 JSON이어도 원문 정확도가 보장되는 것은 아니다.</p>''']
    parts.append('<p>'+esc(lines[2])+'</p><p>'+esc(lines[3])+'</p>')
    parts.append('<section><h2>전체 결과</h2><table><tr><th>항목</th>'+''.join('<th>'+esc(r['model'])+'<br>이전 → 이후</th>' for r in reports)+'</tr>')
    for label,key in metric:parts.append('<tr><td>'+esc(label)+'</td>'+''.join(f'<td>{r["before"][key]} → {r["after"][key]}</td>' for r in reports)+'</tr>')
    parts.append('</table><details><summary>방법·한계·비용 전체 설명</summary><pre>'+esc('\n'.join(lines))+'</pre></details></section>')
    parts.append('<section><h2>실제 사례에서 좋아진 점과 남은 문제</h2><pre>'+esc((OUT/'SOURCE_REVIEW.txt').read_text())+'</pre></section>')
    for key,item in items.items():
        image=base64.b64encode(Path(item['image_path']).read_bytes()).decode()
        parts.append('<section><h2>'+esc(labels[key])+'</h2><p>'+esc(key)+'</p><details open><summary>같은 원본 이미지</summary><img src="data:image/png;base64,'+image+'"></details>')
        for report in reports:
            r=next(r for r in report['records'] if r['key']==key);parts.append('<h3>'+esc(report['model'])+'</h3><div class="cols">')
            for side,label in [('before','이전 프롬프트'),('after','수정 프롬프트')]:
                v=r[side];content=(OUT/report['model'].split('/')[1]/'units'/key/(side+'-content.txt')).read_text()
                s=f"원문 {v['coverage']['compatible']}/{v['coverage']['total']} · 설명에만 {len(v['only_in_claims'])} · 중복 {'있음' if v['duplicate_detected'] else '없음'} · JSON {'완결' if v['json_complete'] else '중간 종료'}"
                parts.append('<div><b>'+label+'</b><p>'+esc(s)+'</p><pre>'+esc(json.dumps(v['object_counts'],ensure_ascii=False,indent=2))+'</pre><details><summary>실제 모델 응답 전체</summary><pre>'+esc(content)+'</pre></details></div>')
            parts.append('</div>')
        parts.append('</section>')
    parts.append('<p>로컬 HTML에 원본과 응답을 내장했다. 브라우저 렌더링 검증은 수행하지 않았다. 원본과 응답 대조는 별도로 수행했다.</p></main></html>')
    (OUT/'comparison.html').write_text(''.join(parts))
    print('REPORT.txt and comparison.html saved')

if __name__=='__main__':main()
