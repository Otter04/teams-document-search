"""Explicit assistant image review, 2026-10-20; not independent human gold.

All five scan PNGs were displayed and read. These are source corrections, not
model outputs. No evaluation reference is used to generate the corrections.
Coordinates are approximate regions read from the displayed page image.
"""
import copy

TEXT_PATCHES = {
 'D-044-vision-page1': {
  2: ('한다)는', '한다)은'),
  20: ('당 당사자는', '양 당사자는'),
 },
 'D-069-vision-page1': {2: ('≈', '=')},
 'D-102-vision-page1': {
  2: ('은새미시', '온새미시'),
  6: ('19일까지 한다.', '19일까지로 한다.'),
  10: ('선급으로', '선금으로'),
  12: ('절차 준수하며', '절차 준수로 하며'),
  18: ('무료로', '무상으로'),
  22: ('서면 시정을 받은 날', '서면 시정 요구를 받은 날'),
 },
}

# Paragraph vertical ranges, in the same order as the original model texts.
# A wider enclosing region is used rather than pretending to have pixel masks.
RANGES = {
 'D-044-vision-page1': [(.095,.12),(.128,.145),(.168,.222),
  (.239,.255),(.261,.280),(.293,.310),(.312,.330),(.345,.362),
  (.366,.385),(.398,.415),(.418,.455),(.469,.486),(.489,.527),
  (.542,.559),(.560,.598),(.611,.628),(.630,.668),(.683,.701),
  (.704,.723),(.736,.753),(.756,.795),(.808,.826),(.828,.867),(.879,.897)],
 'D-102-vision-page1': [(.095,.12),(.128,.145),(.168,.222),
  (.239,.255),(.261,.297),(.312,.329),(.332,.350),(.365,.382),
  (.384,.404),(.418,.435),(.438,.475),(.488,.505),(.508,.546),
  (.561,.578),(.580,.618),(.631,.649),(.651,.689),(.703,.720),
  (.723,.743),(.756,.773),(.775,.814),(.828,.845),(.848,.887)],
}

def apply(key, w, log):
    def setv(obj, field, value, path, reason):
        if obj.get(field) != value:
            log.append(dict(path=path+'.'+field, before=copy.deepcopy(obj.get(field)),
                            after=copy.deepcopy(value), reason=reason,
                            method='assistant_image_review'))
            obj[field] = value
    for i, (old, new) in TEXT_PATCHES.get(key, {}).items():
        t = w['texts'][i]
        assert t['text'].count(old) == 1, (key, i, old)
        setv(t, 'text', t['text'].replace(old,new), f'texts[{i}]',
             '원본 PNG에서 해당 문구를 직접 읽고 오독 교정')
    if key in RANGES:
        assert len(w['texts']) == len(RANGES[key])
        for i,(lo,hi) in enumerate(RANGES[key]):
            x0,x1 = ((.20,.80) if i==0 else (.65,.86) if i==1 else (.14,.86))
            setv(w['texts'][i], 'bbox', [x0,lo,x1,hi], f'texts[{i}]',
                 '원본 페이지에 맞춰 문단 근거 영역 재지정; 근사 좌표')
    if key == 'D-044-vision-page2':
        expected = ['갑','을','상호: 의료법인 새봄의료재단','상호: 라움정보기술 주식회사',
                    '대표이사: 류정원 (인)','대표이사: 정태오 (인)','주소: (생략)',
                    '주소: 서울특별시 구로구 디지털로 000, 7층']
        table = w['tables'][0]
        assert [c['text'] for c in table['cells']] == expected
        setv(table, 'bbox', [.145,.229,.854,.314], 'tables[0]', '원본 표 위치 확인')
        ys=[.229,.247,.264,.281,.314]
        for i,c in enumerate(table['cells']):
            r,col=c['row'],c['column']; xs=[.145,.5,.854]
            setv(c,'bbox',[xs[col-1],ys[r-1],xs[col],ys[r]],f'tables[0].cells[{i}]','원본 표의 행·열 위치 확인')
            setv(c,'value_status','known',f'tables[0].cells[{i}]','8개 셀의 실제 글자를 원본에서 모두 확인')
        for i,b in enumerate([[.14,.091,.86,.128],[.14,.141,.86,.178],[.42,.195,.58,.214]]):
            setv(w['texts'][i],'bbox',b,f'texts[{i}]','원본 문단·날짜 위치 확인')
        setv(w,'warnings',[],'$', '읽기 실패 경고는 위 8개 셀의 원문 검수로 해소; 원응답 경고는 감사 기록 보존')
    return w

def reconstruct_d102_page2(prefix, log):
    """Reuse only eight closed cells; add missing prose from the viewed image."""
    table = copy.deepcopy(prefix['tables'][0])
    expected = ['갑','을','상호: 온새미시 도시공사','상호: 라움정보기술 주식회사',
                '대표이사: 최도윤 (인)','대표이사: 정태오 (인)','주소: (생략)',
                '주소: 서울특별시 구로구 디지털로 000, 7층']
    assert [c['text'] for c in table['cells']] == expected
    assert [(c['row'],c['column'],c['row_span'],c['column_span']) for c in table['cells']] == [(r,c,1,1) for r in range(1,5) for c in (1,2)]
    table.update(bbox=[.145,.25,.856,.335],row_count=4,column_count=2,
                 header_rows=[1],header_status='explicit')
    ys=[.25,.269,.286,.303,.335];xs=[.145,.5,.856]
    for c in table['cells']:
        r,col=c['row'],c['column']
        c.update(value_status='known',bbox=[xs[col-1],ys[r-1],xs[col],ys[r]])
    texts=[
      ('heading','제11조(분쟁 해결)',[.14,.091,.31,.107]),
      ('paragraph','본 계약과 관련하여 분쟁이 발생한 경우 양 당사자는 협의하여 해결하며, 협의가 이루어지지 않을 때에는 서울중앙지방법원을 관할 법원으로 한다.',[.14,.113,.86,.148]),
      ('paragraph','본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하여 갑과 을이 기명날인한 후 각 1부씩 보관한다.',[.14,.163,.86,.198]),
      ('heading','2025년 10월 24일',[.415,.217,.59,.236]),
    ]
    w=dict(status='complete',texts=[dict(kind=k,text=t,bbox=b) for k,t,b in texts],
           tables=[table],figures=[],warnings=[])
    log.append(dict(path='$',before=copy.deepcopy(prefix),after=copy.deepcopy(w),
                    method='assistant_source_reconstruction',
                    reason='잘린 응답의 닫힌 셀 8개를 원본 대조 후 보존. 누락된 4개 텍스트·표 구조·좌표는 PNG를 직접 읽어 별도 복원. 원모델 성공으로 집계하지 않음.'))
    return w
