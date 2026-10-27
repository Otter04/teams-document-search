"""Generate an offline, self-contained inspection viewer and Korean report."""
import base64
import io
import json
import os
from pathlib import Path
from urllib.parse import quote
from PIL import Image
from review import OUT, ROOT, RUN, MODELS, load, write, recover

DETAILED=['D-044-vision-page1','D-044-vision-page2','D-102-vision-page1','D-102-vision-page2','D-069-vision-page1','H-020-vision-page1','D-022-vision-page1',
 'D-001-vision-slide1','D-001-vision-slide4','D-001-vision-slide5','D-001-vision-slide6',
 'D-002-vision-page5','D-040-vision-page5','D-054-vision-page5','D-075-vision-page5','D-076-vision-page5']
CASES=[
 dict(key='D-102-vision-page1',category='오독·원문 변경',source='온새미시 도시공사 / 선금 / 무상으로 / 서면 시정 요구를 받은',q36='은새미시 도시공사 / 선급 / 무료로 / 서면 시정을 받은',vl='위 원문을 보존. 이 페이지의 23개 기준 항목 모두 일치.',judgment='3.6은 거래처명을 오독했고, 일부 문구를 바꾸거나 생략했다. 무료로는 뜻이 비슷하지만 원문 전사 기준에서는 변경이다.'),
 dict(key='D-044-vision-page1',category='오독·원문 보정',source='양 당사자는 / …한다)은',q36='당 당사자는 / …한다)는',vl='양 당사자는 / …한다)는',judgment='3.6은 양→당 오독. 두 모델 모두 원문의 어색한 조사 은을 는으로 바꿨다. 파싱 단계에서는 원문을 보존해야 한다.'),
 dict(key='D-044-vision-page2',category='표 구조·좌표·상태',source='4행×2열, 셀 8개. 표는 이미지 높이 약 23~31% 구간.',q36='8개 셀과 행·열은 정확. 그러나 모두 unreadable, 페이지는 complete. 표 좌표 y=0.42~0.62로 원본과 불일치.',vl='완료된 셀 문자열 2개에 갑/을 각 열의 4행을 합침. 원래 8개 문구는 남아 있지만 셀 구조는 0/8. JSON 중간 종료, bbox=[1,1,1,1].',judgment='읽기·셀 구조·전달은 별개다. 3.6도 형식 검사 통과만으로 정확하다고 볼 수 없다.'),
 dict(key='D-102-vision-page2',category='누락·표 구조',source='분쟁 해결 제목·2문단·2025년 10월 24일과 4×2 표.',q36='표 8개 셀 내용·주소는 남음. 행 개수 등 뒤쪽 필드와 본문·날짜를 내보내기 전에 종료.',vl='표를 1×2로 합쳤고 본문·날짜는 빠짐. 좌표도 모두 한 점.',judgment='표 속 문구 보존 8/8과 표 구조 보존은 다르다. 두 출력 모두 공통 JSON 채택 실패.'),
 dict(key='D-069-vision-page1',category='구성도·누락·좌표',source='노드 8개, 화살촉 없는 연결선 7개, 제목·작성일·범례.',q36='노드/연결은 모두 보존(×→x 허용 시). 범례의 =를 ≈로 변경. 선 좌표 폭 또는 높이 0으로 거절.',vl='노드 라벨·연결 8/8, 7/7. 제목·작성일·범례 누락. bbox=[1,0,1,1], 빈 chart도 추가.',judgment='이전 엄격 문자 비교에서 3.6의 연결선이 0/7로 보인 것은 ×/x가 포함된 노드 라벨 일치 문제였다. 실제 연결 구조가 전부 틀렸다는 뜻이 아니다.'),
 dict(key='H-020-vision-page1',category='출력 반복·누락',source='3×3 표 9셀과 견적번호 QT-26-PR-88, 작성일·유효기간·견적금액 등 표 밖 10항목.',q36='9셀은 정확하게 기록. 표 밖 10항목을 내보내기 전에 JSON 종료.',vl='9셀 문구를 찾을 수 있으나 완료된 셀 text 필드가 211개까지 반복. 표 밖 10항목 누락, JSON 종료.',judgment='중단된 응답에서 완성된 필드만 읽은 진단이다. 복구된 정상 JSON으로 취급하지 않았다.'),
 dict(key='D-001-vision-slide1',category='중복',source='거래처·날짜 문단은 각각 한 번만 표시.',q36='본문 한 번씩 기록.',vl='거래처·날짜 문단을 반복. ㈜와 (주) 표기 차이를 허용해도 원문 대비 중복.',judgment='공통 블록의 근거 인용이나 행 요약에서 생기는 의도된 반복은 이 집계에서 제외했다.'),
 dict(key='D-001-vision-slide4',category='필드 배치·중복',source='제안 목표 제목과 목표 1~3 상자.',q36='원문을 texts와 노드에 중복 기록.',vl='읽은 원문을 claims에 반복 기록하다 종료. 원문 필드 texts/cells/nodes에는 전달하지 못함.',judgment='읽지 못한 경우와 읽었지만 잘못된 필드에만 넣은 경우를 분리한다. VL 전체 66개 기준 항목이 claims에서만 발견됐다.'),
 dict(key='D-001-vision-slide5',category='구성도 반복',source='노드 6개와 연결선 5개인 구성도 하나.',q36='노드 6개·연결 5개를 한 번씩 기록.',vl='완성된 구성도 17개와 중간 구성도 1개를 반복. 원래 관계를 회수할 수 있어도 중복으로 정밀도가 하락.',judgment='반복을 제거한 회수율만 보면 문제를 숨기므로 중복을 포함한 정밀도도 함께 보고한다.')]

def ratio(n,d):return f'{n}/{d} ({n/d*100:.2f}%)' if d else '해당 없음'
def pct(x):return f'{100*x:.2f}%'
def main():
    reports=load(OUT/'evaluation.json');refs=load(OUT/'source-references.json');ss=[r['summary'] for r in reports]
    rows=[]
    def row(label,fn):rows.append('| '+label+' | '+' | '.join(fn(s) for s in ss)+' |')
    row('원문 필드 내 기준 항목 보존 — 전체',lambda s:ratio(s['coverage']['all']['compatible'],s['coverage']['all']['total']))
    row('네이티브 문맥 제공 126장 — 기준 항목 보존',lambda s:ratio(s['coverage']['native']['compatible'],s['coverage']['native']['total']))
    row('문맥 없는 스캔 6장 — 기준 항목 보존',lambda s:ratio(s['coverage']['scan']['compatible'],100))
    row('표 셀 내용+행·열·병합 일치 회수',lambda s:ratio(s['table_structure']['correct'],s['table_structure']['expected']))
    row('표 셀 정밀도 — 중복·추가 셀 포함',lambda s:ratio(s['table_structure']['correct'],s['table_structure']['observed']))
    row('표 전체 행·열 개수 일치',lambda s:ratio(s['table_dimensions_correct'],s['table_count']))
    row('표 헤더 행 번호 일치',lambda s:ratio(s['table_header_rows_correct'],s['table_count']))
    row('구성도 노드 라벨 회수 — 27장',lambda s:ratio(s['graphs']['compatible']['nodes']['correct'],s['graphs']['compatible']['nodes']['expected']))
    row('구성도 연결·방향 회수 — 27장',lambda s:ratio(s['graphs']['compatible']['edges']['correct'],s['graphs']['compatible']['edges']['expected']))
    row('구성도 노드 / 연결 정밀도 — 중복 포함',lambda s:pct(s['graphs']['compatible']['nodes']['precision'])+' / '+pct(s['graphs']['compatible']['edges']['precision']))
    row('원문 구절의 중복 출력이 검출된 이미지',lambda s:f"{s['duplicate_images']}/132장")
    row('원문 필드에는 없고 claims에만 있는 기준 항목',lambda s:str(s['source_items_only_in_claims'])+'개')
    row('완결된 JSON',lambda s:ratio(s['json_complete'],132))
    row('공통 블록 형식·좌표·참조 검사 통과',lambda s:ratio(s['common_json_valid'],132))
    row('통과 응답 → 공통 JSON 내용·구조 보존',lambda s:ratio(s['delivery_preserved'],s['common_json_valid']))
    row('통과 응답 → 조립된 문서 JSON 보존',lambda s:ratio(s['assembled_candidate_preserved'],s['common_json_valid']))
    row('채택된 비전 공통 JSON으로 전달된 기준 항목',lambda s:ratio(s['accepted_common_literal_coverage']['compatible'],s['accepted_common_literal_coverage']['total']))
    row('기존 원본 메타정보·네이티브 블록 보존',lambda s:ratio(s['native_documents_preserved'],s['native_documents_total']))
    text='''# 비전 파싱 원문 대조 재평가

2026-10-19. 기존 36문서·132장의 두 모델 응답 264개만 사용했다. 추가 유료 호출·모델 호출·검색 평가를 하지 않았다. 원본, 기존 응답, 이전 점수와 후보 JSON은 보존했다.

**현재 고정 실행 조건에서는 Qwen3.6이 구조화와 JSON 전달에서 더 안정적이다. 그러나 스캔 본문 전사에서는 Qwen3-VL이 더 나은 사례가 있으며, 두 모델 모두 무검수 사용 수준으로 판정할 수 없다.**

[원본·두 결과 나란히 보기](comparison.html) · [확인한 오류 사례](CASES.md) · [전체 264개 상세 결과](evaluation.json) · [원문 기준 항목](source-references.json) · [보존 확인](integrity.json)

## 비교 결과

아래 정보 보존·구조 지표는 **JSON이 중간에 끊겼더라도 이미 완성되어 저장된 필드**까지 진단에 포함한다. 미완성 문자열·숫자를 추정하거나 닫는 괄호를 추가하지 않았다. 이 진단은 실패 응답의 정상 채택을 뜻하지 않는다. JSON 전달은 표 아래쪽 별도 지표다.

| 지표 | Qwen3.6-35B-A3B | Qwen3-VL-30B-A3B-Instruct |
|---|---:|---:|
'''+ '\n'.join(rows)+'''

**보존율은 전체 의미 정확도가 아니다.** 원본에서 정의한 문단·셀·노드 라벨이 결과에 그대로 남았는지를 센 회수율이다. 문단에서 한 글자만 달라도 그 항목은 실패한다. 셀은 내용과 행/열/병합 범위를 함께 비교하고, 중복 출력은 정밀도에서 감점한다. 글자별 정확도·문서별 완전 성공률과 혼동하면 안 된다.

공백·줄바꿈을 무시하고 `㈜ ↔ (주)`, `× ↔ x`만 동일하게 취급했다. 숫자·날짜·IP·기호 `= ↔ ≈`는 보정하지 않았다. 엄격 문자 보존 결과도 evaluation.json에 보관했다. 3.6의 스캔 엄격 보존은 74/100, 호환 표기 허용 시 77/100이며 VL은 모두 79/100이다.

## 확인된 문제의 의미

- **누락:** 두 모델 모두 H-020의 견적번호·날짜 등 표 밖 10개 항목을 출력하지 못했다. D-102 두 번째 페이지의 본문·날짜 4개 항목도 없다. 이것은 이미지에 정보가 없어서가 아니라 저장된 응답에서 빠진 것이다.
- **오독·변경:** D-102에서 3.6은 `온새미시→은새미시`, `선금→선급`, `무상으로→무료로` 등 원문 변경을 보였다. 이 페이지는 VL의 기준 항목 23/23이 일치했다. 자연스러운 표현으로 바꾸는 것도 원문 전사에서는 오류다.
- **중복:** VL은 H-020의 표 셀과 D-001 구성도를 반복 출력했다. 3.6도 목표 상자의 원문을 texts와 nodes에 동시에 넣는 중복이 있다. 이 집계는 모델 원응답의 원문 필드만 대상으로 한다. 공통 JSON의 근거 인용·표 행 요약 중복은 제외했다.
- **표 구조:** VL의 D-044·D-102 서명란은 원래 4×2 표지만 두 열을 각각 긴 문자열 한 셀로 합쳤다. 문구가 남아 있어도 행·열 구조는 실패다. 3.6의 515/515 셀 구조 회수 역시 표 전체가 모두 정상이라는 뜻은 아니다. D-102/H-020에서는 셀 뒤의 row_count 등이 완성되지 않았다.
- **구성도:** D-069는 두 모델 모두 8노드·7연결의 실제 관계를 회수했다. 3.6의 ×/x 표기 차이 때문에 이전 엄격 라벨 지표가 낮았던 점을 분리했다. 다만 두 모델 모두 좌표 오류로 이 결과를 공통 JSON에 채택하지 못했다. VL은 제목·날짜·범례도 누락했다.
- **필드 배치:** VL의 66개 기준 항목은 읽은 내용이 claims에 있으나 원문 필드에 없다. 이를 보조 진단에 포함하면 전체 1,312/1,338 항목이 발견된다. 원문과 해석을 분리하는 계약을 지키지 않았으므로 원문 필드 점수로 승격하지 않았다.
- **좌표·상태:** D-044 표의 실제 y 범위는 약 0.23~0.31인데 3.6은 0.42~0.62로 지정했다. 모든 셀에 글자가 있지만 unreadable로 표시했고 페이지 상태는 complete다. 유효한 숫자 배열이라는 사실만으로 원본 근거 위치가 맞는 것은 아니다.

## 공통 JSON 전달 확인

통과한 169개 응답은 텍스트·표 셀 내용/행열/병합/상태/좌표, 노드·연결·claims를 공통 블록으로 옮긴 뒤 다시 읽어 원응답과 대조했다. 개별 페이지 JSON과 조립된 문서 후보 JSON 모두 값과 구조가 보존됐다. 기존 140문서의 원본 메타정보와 네이티브 블록도 모델별 후보 파일에서 그대로 유지됐다.

따라서 이번에 확인한 주된 오류 위치는 **모델 응답 생성 → 응답 검증 단계**다. 원문 오독, 반복, 잘린 JSON, 잘못된 좌표/상태가 먼저 발생했다. 변환기는 입력 오류를 교정하지 않고 그대로 전달하므로 형식 검사를 통과한 169개도 의미상 합격을 뜻하지 않는다. 기준 항목의 최종 전달 점수는 비전 결과만 세며, 네이티브 블록에 이미 있던 글자로 실패를 가리지 않았다.

## 검수 범위와 한계

- 132장 전체의 레이아웃을 11개 모음 이미지로 확인했다. 스캔 6장 전부와 네이티브 대표/문제 사례 10장, 총 **16장은 원래 해상도로 상세 대조**했다. 모든 132장의 모든 글자를 사람처럼 수작업 재검수했다는 의미는 아니다.
- 126장은 실제 PPTX XML/PDF 텍스트·표를 직접 읽어 참조를 만들었다. 원래 모델 입력에도 네이티브 문맥이 있었으므로 높은 보존율은 **문맥을 함께 준 파싱 파이프라인 성적**이다. 순수 이미지 읽기 성능은 문맥 없는 스캔 6장으로 따로 보되 표본이 작다.
- 표 33개·셀 515개와 연결선이 있는 구성도 27장·노드 165개·선 138개를 비교했다. PPTX 연결 대상 ID를 읽었고, 같은 제안서의 PDF 5개는 원본 PPTX 연결 구조와 PDF 그림을 대조했다. 스캔 D-069는 눈으로 확인한 노드/선을 사용했다. PDF 표지 배경 사각형은 표에서 제외했다.
- 같은 문서의 PPTX/PDF·개정본과 반복 양식이 포함되어 있다. 132장이 모두 독립적인 문서나 새로운 양식은 아니다. 임의 사진 의미, 복잡한 차트 축/수치, 모든 병합 셀 유형을 검증한 자료가 아니다.
- 참조는 이번에 원본으로 만든 **AI 검수 초안**이다. 독립된 사람의 정답 검수는 아직 없다. 스캔 문단 차이에는 글자 오독과 표현 변경이 함께 포함된다. 전체 환각률/의미 정확도는 산출하지 않았다.
- 실제 위치와 완전히 떨어진 bbox 사례는 찾아 기록했지만, 모든 좌표의 정밀한 픽셀 정확도를 인증하지 않았다. 그림 설명 claims의 모든 해석에 대한 사실성도 이번 정량 지표에 포함하지 않았다.
- 결과는 기존 고정 조건(DeepInfra FP8, temperature=0, max_tokens=16384 등)에서의 비교다. 새 설정 재실험이나 운영 장비 검증을 하지 않았다. 모델 자체의 보편적 우열을 단정하지 않는다.
- comparison.html은 이미지와 비교 데이터를 포함한 로컬 파일이다. 앱 브라우저 정책이 file URL을 차단하여 브라우저 화면/상호작용 검증은 하지 못했다. 정량 결과와 원문 검수는 HTML 실행에 의존하지 않는다.

## 후속 작업 제안 — 이번에는 실행하지 않음

1. 동일 원문이 texts/nodes/cells에 중복되는 경우와 원문이 claims에만 있는 경우를 검증기로 잡는다.
2. complete + unreadable 셀, 비정상 좌표, 과도한 반복을 별도 품질 실패로 다룬다. 종료된 부분 JSON을 자동 정상 처리하지 않는다.
3. 원본 이미지와 기준을 독립 검수한 뒤, 필요한 경우에만 새 설정으로 소규모 재실험한다. 새 유료 호출은 별도 요청 전까지 하지 않는다.

## 재현

오프라인 평가기 review.py는 네트워크·API 클라이언트·키 파일을 사용하지 않는다. report.py는 저장된 결과로 보고서와 비교 화면을 만든다. test_review.py의 10개 테스트는 중간 종료 문자열 미추정, 숫자 경계, 중복 감점, 표 합침, 무방향 선, 표기 호환을 확인한다.

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/vision-source-review-001/review.py
PYTHONDONTWRITEBYTECODE=1 /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 outputs/vision-source-review-001/report.py
PYTHONDONTWRITEBYTECODE=1 /Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s outputs/vision-source-review-001 -p 'test_*.py'
```
'''
    (OUT/'README.md').write_text(text)
    case_md=['# 원본 이미지 대조 사례','', '검색 성능은 포함하지 않았다. 아래는 원본 이미지와 저장 응답에서 확인한 사례다. 전체 수치는 README.md를 참고한다.','']
    for c in CASES:
        ref=refs[c['key']];case_md += [f"## {c['key']} — {c['category']}",'',f"[원본 이미지]({ref['image_path']}) · [원본 문서](<{ref['source_path']}>)",'',f"- 원본: {c['source']}",f"- Qwen3.6: {c['q36']}",f"- Qwen3-VL: {c['vl']}",f"- 판정: {c['judgment']}",'']
        for model in MODELS:case_md.append(f"[{model} 원응답](<{RUN/model/'units'/c['key']/'response.json'}>)")
        case_md.append('')
    (OUT/'CASES.md').write_text('\n'.join(case_md))
    write(OUT/'review-scope.json',dict(overview_images=list(refs),detailed_full_resolution_images=DETAILED,independent_human_review=False,network_calls=0,paid_calls=0,cases=CASES))
    bundle={}
    rr=[{r['key']:r for r in rep['records']} for rep in reports]
    for key,ref in refs.items():
        im=Image.open(ref['image_path']).convert('RGB');im.thumbnail((1500,2100));buf=io.BytesIO();im.save(buf,format='JPEG',quality=88)
        pair=[]
        for model,records in zip(MODELS,rr):
            r=records[key];raw=load(RUN/model/'units'/key/'response.json')['choices'][0]['message']['content'];wire,_,_=recover(raw)
            pair.append(dict(model=model,report=r,wire=wire,response_url=quote(os.path.relpath(RUN/model/'units'/key/'response.json',OUT))))
        bundle[key]=dict(ref=ref,image='data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode(),pair=pair,case=next((c for c in CASES if c['key']==key),None))
    template=(OUT/'viewer-template.html').read_text()
    data=json.dumps(bundle,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (OUT/'comparison.html').write_text(template.replace('/*DATA*/{}',data))
    print('report, cases, viewer saved')

if __name__=='__main__':main()
