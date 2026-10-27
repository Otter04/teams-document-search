import json, importlib.util, hashlib, base64, html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('review',ROOT/'outputs/vision-source-review-001/review.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
M36='qwen3.6-35b-a3b';MV='qwen3-vl-30b-a3b-instruct'
items=[]
def load(model,key):
 p=ROOT/'outputs/vision-comparison-run-001'/model/'units'/key/'response.json';r=json.loads(p.read_text());raw=r['choices'][0]['message']['content']
 try:w=json.loads(raw);complete=True
 except ValueError:w,_,_=h.recover(raw);complete=False
 return p,r,raw,w,complete

def add(n,title,model,key,image,where,meaning,selected,summary):
 p,r,raw,w,complete=load(model,key)
 values=selected(w)
 # Values below are selected fields with their real paths, not invented model output.
 evidence=dict(case=n,title=title,model=model,key=key,original_response=str(p),response_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),image_path=str(ROOT/image),finish_reason=r['choices'][0]['finish_reason'],whole_json_complete=complete,selected_existing_values=values)
 (OUT/f'{n:02d}-excerpt.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
 (OUT/f'{n:02d}-model-content.txt').write_text(raw)
 items.append(dict(n=n,title=title,model=model,key=key,image=image,where=where,meaning=meaning,values=values,summary=summary(w),complete=complete))

add(1,'같은 글자를 서로 다른 칸에 두 번 기록',M36,'D-001-vision-slide2','outputs/parsing-run-003/assets/D-001/slide-2.png',
 '목차의 맨 왼쪽 위 상자: 01 / 사업 이해',
 '원본에는 상자 하나다. 모델은 같은 상자의 글자를 본문용 칸(texts)과 도형의 이름 칸(nodes)에 모두 적었다. 글자를 틀리게 읽었다기보다 같은 대상을 두 종류로 기록한 것이다. 설계에 따라 허용할 수도 있지만, 두 항목을 별도 내용처럼 사용하면 중복 집계될 수 있어 현재는 경고한다. 설명이 원문을 인용하는 모든 경우를 오류로 보지는 않는다.',
 lambda w:{'texts[1].text':w['texts'][1]['text'],'figures[0].nodes[0].label':w['figures'][0]['nodes'][0]['label']},
 lambda w:'원본 상자 1개 → 모델 응답의 서로 다른 두 칸에 같은 글자')
add(2,'표 하나를 통째로 두 번 기록',MV,'D-001-vision-slide7','outputs/parsing-run-003/assets/D-001/slide-7.png',
 '투입 인력 슬라이드의 표 전체. PM / 특급 / 1 / 사업 총괄, 고객 협의 행을 비교한다.',
 '원본에는 제목 아래 표가 하나다. 모델 응답에는 tables[0]과 tables[1], 두 표가 있고 5행×4열의 20개 셀 내용이 각각 반복된다. 아래는 두 표의 같은 PM 행을 발췌한 것이다. 문서에 실제로 표가 두 개 있는 것이 아니다. JSON 문법은 정상이어도 내용은 중복될 수 있다.',
 lambda w:{f'tables[{i}].cells[4:8]':[{k:c[k] for k in ['row','column','text']} for c in w['tables'][i]['cells'][4:8]] for i in [0,1]},
 lambda w:f'원본 표 1개 → 출력 표 {len(w["tables"])}개, 셀 {len(w["tables"][0]["cells"])}개씩. 두 표 전체 동일: {w["tables"][0]==w["tables"][1]}')
add(3,'같은 구성도와 연결선을 계속 다시 기록',MV,'D-001-vision-slide5','outputs/parsing-run-003/assets/D-001/slide-5.png',
 '위쪽 사용자 / 외부망 상자와 중앙 FortiGate 상자를 잇는 세로선',
 '원본은 상자 6개와 연결선 5개로 된 구성도 하나다. 모델은 한 응답 안에서 같은 구성도를 계속 작성했다. node1과 node2는 상자에 붙인 모델 내부 이름이고, from_node/to_node는 어느 상자끼리 연결됐는지를 적는 칸이다. 아래 두 항목은 같은 두 상자 사이 선을 각각 다시 적은 것이다. 그림의 선을 실제로 복사한 것이 아니라 선의 기록을 여러 번 만들었다.',
 lambda w:{f'figures[{i}].relations[0]':w['figures'][i]['relations'][0] for i in [0,1]},
 lambda w:f'원본 구성도 1개 → 상자 6개·선 5개를 갖춘 기록 {sum(len(f.get("nodes",[]))==6 and len(f.get("relations",[]))==5 for f in w["figures"])}개 + 작성 도중인 마지막 기록. 응답은 중간 종료됨.')
add(4,'읽은 문장을 설명 칸에 반복 기록',MV,'D-001-vision-slide4','outputs/parsing-run-003/assets/D-001/slide-4.png',
 '왼쪽 목표 1 상자: 설비 데이터 1초 단위 실시간 수집',
 'claims는 그림에 대한 관찰·해석을 적는 설명 칸이다. 모델은 원문 상자에 한 번 있는 목표 1 문장을 이 설명 칸에 거듭 적었다. 아래 [1]과 [4]는 같은 설명 목록의 서로 다른 두 항목이다. 이 응답에서는 원문을 담아야 할 texts/nodes에 이 문장을 남기지 못한 채 종료했다. 즉 글자가 응답에 전혀 없는 문제와, 읽은 글자가 약속한 칸에 없는 문제는 다르다.',
 lambda w:{'figures[0].claims[1].text':w['figures'][0]['claims'][1]['text'],'figures[0].claims[4].text':w['figures'][0]['claims'][4]['text']},
 lambda w:'원본의 목표 1 문장 1개 → 같은 설명 칸 목록에 반복. 응답 중간 종료.')
add(5,'읽었다는 내용과 못 읽었다는 표시가 함께 있음',M36,'D-044-vision-page2','outputs/parsing-run-003/assets/D-044/page-2.png',
 '계약서 서명란 표 왼쪽: 상호: 의료법인 새봄의료재단',
 '모델은 상호를 실제로 적어 놓고, 같은 셀에는 unreadable(읽지 못함)이라고 표시했다. 동시에 페이지 전체에는 complete(완료)라고 적었다. 문구 자체의 오독과 구분해야 하는 상태 표시의 모순이다. 현재는 글자를 지우지 않고 이 모순을 경고로 남기며 검수 대기로 전달한다.',
 lambda w:{'status':w['status'],'tables[0].cells[2].text':w['tables'][0]['cells'][2]['text'],'tables[0].cells[2].value_status':w['tables'][0]['cells'][2]['value_status']},
 lambda w:'페이지: complete / 셀: unreadable / 셀 글자: 실제 상호가 있음')

esc=html.escape
parts=['''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>비전 파싱 문제 — 실제 원본과 응답</title><style>
body{font-family:system-ui,-apple-system,sans-serif;background:#f4f6fa;color:#152238;line-height:1.8;margin:0}main{max-width:1280px;margin:auto;padding:30px}h1{font-size:30px}h2{font-size:24px}p{max-width:1000px}section{background:white;border:1px solid #dbe2ed;border-radius:16px;padding:26px;margin:28px 0}.row{display:grid;grid-template-columns:1.15fr 1fr;gap:24px}img{width:100%;height:auto;border:1px solid #dbe2ed}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f8;padding:16px;font-size:14px;line-height:1.6}small{color:#53637b}.note{background:#fff3d7;padding:16px;border-radius:8px}.flow{background:#e5eefb;padding:18px;font-weight:650}a{color:#174baf}.summary{font-size:18px;font-weight:700}@media(max-width:850px){.row{grid-template-columns:1fr}main{padding:14px}}
</style><main><h1>반복은 어디서 생겼을까?</h1>
<p>이번 사례의 반복은 <b>비전 모델이 이미지를 읽고 자신의 응답(JSON)을 작성하는 동안</b> 발생했다. 그 뒤 공통 JSON 양식으로 옮기는 Python 변환기가 만들어 낸 반복은 아니다. 이 읽기·구조화·응답 작성은 모두 현재 프로젝트의 <b>파싱 단계</b>에 속한다.</p>
<div class="flow">원본 이미지 → 비전 모델이 읽고 JSON 응답 작성 [아래 문제 발생] → 검증기로 확인 → 변환 코드로 공통 JSON에 옮김 → 이후 문서 보강</div>
<p>JSON은 이름표가 붙은 여러 칸이 있는 양식이라고 생각하면 된다. <b>문법이 맞는 양식에도 같은 내용을 두 번 적거나 잘못된 칸에 적을 수 있다.</b> “파싱 문제”와 “모델이 JSON을 잘못 작성한 문제”가 여기서는 겹친다. 모델이 원래 이미지를 어떻게 이해했는지까지 응답만으로 확정할 수는 없다.</p>
<p>아래 값은 실제 저장된 응답에서 발췌했다. 배열 번호 [0]은 첫 항목, [1]은 두 번째 항목이다. 줄바꿈은 화면에서 \\n으로 보일 수 있다. 원본 이미지 파일은 변경하지 않았다.</p>''']
for a in items:
 b64=base64.b64encode((ROOT/a['image']).read_bytes()).decode()
 parts.append(f'<section id="case{a["n"]}"><h2>{a["n"]}. {esc(a["title"])}</h2><small>{esc(a["model"])} · {esc(a["key"])}</small><p class="summary">{esc(a["summary"])}</p><p>{esc(a["meaning"])}</p><div class="row"><div><b>원본 이미지 — 볼 위치</b><p>{esc(a["where"])}</p><img src="data:image/png;base64,{b64}" alt="{esc(a["where"])}"></div><div><b>모델이 실제로 작성한 값 — 선택 발췌</b><pre>{esc(json.dumps(a["values"],ensure_ascii=False,indent=2))}</pre><p><a href="{a["n"]:02d}-excerpt.json">출처 경로·해시 포함 발췌 JSON</a> · <a href="{a["n"]:02d}-model-content.txt">모델의 전체 응답 텍스트</a></p>')
 if not a['complete']:parts.append('<p class="note">전체 JSON은 중간에 끊겨 정상 자료로 전달하지 않았다. 여기서는 이미 끝까지 작성된 필드만 진단용으로 보여준다. JSON을 고쳐 복구한 결과가 아니다.</p>')
 parts.append('</div></div></section>')
parts.append('''<section><h2>이번에 바꾼 것은 무엇인가?</h2><p>기존에는 중복이 발견되면 페이지 전체의 전달을 막았다. 지금은 구조상 옮길 수 있는 응답은 내용을 그대로 보존하고 경고를 붙여 전달한다. <b>중복을 삭제하거나 모델을 다시 실행한 것은 아니다.</b> 예를 들어 2번의 표 두 개는 경고와 함께 남는다. 3·4번처럼 JSON 자체가 중간에 끊긴 응답은 여전히 차단한다.</p><p>본문과 근거 인용에 같은 글자가 함께 들어가는 것처럼 공통 양식에서 의도한 반복도 있다. 그것을 모두 모델 오류로 세는 것은 아니다. 이 자료는 변환 전 모델 원응답에 이미 있는 반복을 보여준다.</p><small>2026-10-19 · 기존 응답만 사용 · 유료 호출 0건 · 원본과 기존 평가 파일 변경 없음. HTML 화면의 브라우저 렌더링 검증은 수행하지 않았으며, 원본 이미지와 발췌 값은 직접 확인했다.</small></section></main></html>''')
(OUT/'examples.html').write_text(''.join(parts))
# Validate selections and precise counts against existing complete/partial records.
_,_,_,w,_=load(MV,'D-001-vision-slide7');assert len(w['tables'])==2 and w['tables'][0]==w['tables'][1]
_,_,_,w,_=load(MV,'D-001-vision-slide5');assert sum(len(f.get('nodes',[]))==6 and len(f.get('relations',[]))==5 for f in w['figures'])==17
for i in range(1,6):
 ev=json.loads((OUT/f'{i:02d}-excerpt.json').read_text());assert hashlib.sha256(Path(ev['original_response']).read_bytes()).hexdigest()==ev['response_sha256']
print(json.dumps(dict(cases=5,images_embedded=5,source_hashes_verified=5,paid_calls=0,html=str(OUT/'examples.html')),ensure_ascii=False))
