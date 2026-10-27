"""Offline source-based audit. No network, API credentials, OCR, or inference.

Recovered prefixes are diagnostics only: never repair or admit broken JSON.
Source references are assistant-reviewed drafts, not independent human gold.
"""
import collections
import difflib
import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = ROOT / 'outputs/vision-comparison-run-001'
MODELS = ['qwen3.6-35b-a3b', 'qwen3-vl-30b-a3b-instruct']
def load(p): return json.loads(Path(p).read_text())
def write(p, v): Path(p).write_text(json.dumps(v, ensure_ascii=False, indent=2)+'\n')
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def uid(i): return i['doc_id']+'-'+i['unit_id'].replace(':','-')
def norm(s, compatible=False):
    s=unicodedata.normalize('NFC',str(s))
    if compatible: s=s.replace('㈜','(주)').replace('×','x')
    return re.sub(r'\s+', '', s)

class Prefix:
    """Parse completed JSON scalars and partial containers; no invented strings.

    A partially emitted string/number is omitted. Closed paths are recorded.
    This is not a JSON repairer and does not grant schema validity.
    """
    def __init__(self,s): self.s=s;self.i=0;self.closed=[]
    def ws(self):
        while self.i<len(self.s) and self.s[self.i].isspace(): self.i+=1
    def parse(self,path='$'):
        self.ws()
        if self.i>=len(self.s): return None,False
        c=self.s[self.i]
        if c in '[{':
            obj={} if c=='{' else []; end='}' if c=='{' else ']';self.i+=1
            while True:
                self.ws()
                if self.i>=len(self.s): return obj,False
                if self.s[self.i]==end:
                    self.i+=1;self.closed.append(path);return obj,True
                if c=='{':
                    key,ok=self.parse(path+'.<key>')
                    if not ok or not isinstance(key,str):return obj,False
                    self.ws()
                    if self.i>=len(self.s) or self.s[self.i]!=':':return obj,False
                    self.i+=1; val,ok=self.parse(path+'.'+key)
                    if ok or isinstance(val,(dict,list)):obj[key]=val
                else:
                    val,ok=self.parse(path+f'[{len(obj)}]')
                    if ok or isinstance(val,(dict,list)):obj.append(val)
                if not ok:return obj,False
                self.ws()
                if self.i>=len(self.s):return obj,False
                if self.s[self.i]==',':self.i+=1;continue
                if self.s[self.i]==end:
                    self.i+=1;self.closed.append(path);return obj,True
                return obj,False
        try:
            val,n=json.JSONDecoder().raw_decode(self.s[self.i:])
        except (ValueError,TypeError):return None,False
        # Reject a number cut at EOF: additional digits might be missing.
        if isinstance(val,(int,float)) and not isinstance(val,bool) and self.i+n==len(self.s):return None,False
        self.i+=n;self.closed.append(path);return val,True

def recover(s):
    try:return json.loads(s), True, []
    except ValueError:
        p=Prefix(s);v,_=p.parse();return v if isinstance(v,dict) else {},False,p.closed

def box(b):return [b[k] for k in ['x0','y0','x1','y1']]
def text_items(w):
    out=[]
    for j,t in enumerate(w.get('texts',[])):
        if isinstance(t,dict) and isinstance(t.get('text'),str):out.append(dict(kind='text',text=t['text'],bbox=t.get('bbox'),path=f'texts[{j}]'))
    for j,t in enumerate(w.get('tables',[])):
        for k,c in enumerate(t.get('cells',[])):
            if isinstance(c,dict) and isinstance(c.get('text'),str):out.append(dict(kind='cell',text=c['text'],bbox=c.get('bbox'),path=f'tables[{j}].cells[{k}]'))
    for j,f in enumerate(w.get('figures',[])):
        for k,n in enumerate(f.get('nodes',[])):
            if isinstance(n,dict) and isinstance(n.get('label'),str):out.append(dict(kind='node',text=n['label'],bbox=n.get('bbox'),path=f'figures[{j}].nodes[{k}]'))
    return out

def make_table(rows,bbox=None,header_rows=None):
    return dict(row_count=len(rows),column_count=len(rows[0]),bbox=bbox,header_rows=header_rows,
      cells=[dict(row=r+1,column=c+1,row_span=1,column_span=1,text=t) for r,row in enumerate(rows) for c,t in enumerate(row)])

def scan_refs():
    refs={}
    for doc,title,customer,ct,period,amount,scope,ceo,date in [
      ('D-044','PACS 스토리지 증설','의료법인 새봄의료재단','CT-2025-0164','2025년 4월 1일부터 2025년 4월 30일까지','일억팔천칠백만원정(₩187,000,000, 부가가치세 별도)','스토리지 300TB 증설, SAN 이중화','류정원','2025년 3월 22일'),
      ('D-102','시설관리시스템 노후 서버 교체','온새미시 도시공사','CT-2025-0377','2025년 11월 3일부터 2025년 12월 19일까지','일억이천구백팔십만원정(₩129,800,000, 부가가치세 포함)','서버 4대 교체, Windows Server 2022 전환, 조달청 우수제품 구매 절차 준수','최도윤','2025년 10월 24일')]:
        paragraphs=[title+' 계약서','계약번호: '+ct,
          f'{customer}(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)은 「{title}」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.',
          '제1조(목적)',f'본 계약은 갑의 「{title}」 수행에 필요한 제반 사항을 정함을 목적으로 한다.',
          '제2조(계약기간)',f'본 계약의 기간은 {period}로 한다.',
          '제3조(계약금액)',f'계약금액은 금 {amount}으로 한다.',
          '제4조(대금 지급)','갑은 계약 체결 후 선금으로 계약금액의 30%를, 최종 검수 완료 후 30일 이내에 잔금 70%를 지급한다.',
          '제5조(업무 범위)',f'을이 수행하는 업무의 범위는 {scope}로 하며, 세부 내용은 별첨 과업내용서에 따른다.',
          '제6조(납품 및 검수)','을은 계약기간 내에 납품 및 설치를 완료하고, 갑은 납품일로부터 14일 이내에 검수를 완료한다.',
          '제7조(지체상금)','을이 계약기간 내에 의무를 이행하지 못한 경우 지체일수 1일당 계약금액의 1천분의 1에 해당하는 금액을 지체상금으로 갑에게 납부한다.',
          '제8조(하자보수)','을은 검수 완료일로부터 1년간 납품물의 하자에 대하여 무상으로 보수한다.',
          '제9조(비밀유지)','양 당사자는 본 계약의 이행 과정에서 알게 된 상대방의 영업상·기술상 정보를 계약 종료 후 3년간 제3자에게 누설하지 아니한다.',
          '제10조(계약의 해지)','일방 당사자가 본 계약을 위반하고 서면 시정 요구를 받은 날로부터 14일 이내에 시정하지 아니하는 경우 상대방은 본 계약을 해지할 수 있다.']
        if doc=='D-044':paragraphs.append('제11조(분쟁 해결)')
        p2=['본 계약과 관련하여 분쟁이 발생한 경우 양 당사자는 협의하여 해결하며, 협의가 이루어지지 않을 때에는 서울중앙지방법원을 관할 법원으로 한다.',
          '본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하여 갑과 을이 기명날인한 후 각 1부씩 보관한다.',date]
        if doc=='D-102':p2.insert(0,'제11조(분쟁 해결)')
        t=make_table([['갑','을'],['상호: '+customer,'상호: 라움정보기술 주식회사'],['대표이사: '+ceo+' (인)','대표이사: 정태오 (인)'],['주소: (생략)','주소: 서울특별시 구로구 디지털로 000, 7층']], [.145,.229,.854,.314] if doc=='D-044' else [.145,.250,.856,.335],[1])
        for page,ps,tables in [(1,paragraphs,[]),(2,p2,[t])]:
            refs[f'{doc}-vision-page{page}']=dict(method='assistant_visual_transcription',texts=[dict(text=p,kind='text') for p in ps],tables=tables,nodes=[],edges=[])
    gr=load(ROOT/'outputs/common-block-design/annotations/D-069-draft.json')
    refs['D-069-vision-page1']=dict(method='assistant_visual_transcription',
      texts=[dict(kind='text',text=t) for t in ['여신관리시스템 DR 구축 네트워크 구성도 (Rev.1)','설치 위치: 여의도 본사 IDC | 작성일: 2025-08-27 | 작성: 라움정보기술 기술지원팀','범례: 실선 = 1G/10G 이더넷 | (주)도담캐피탈 전산 담당자 검토 필요']],
      tables=[], nodes=[dict(id=n['node_id'],label=n['label'],bbox=box(n['loc']['bbox'])) for n in gr['nodes']],
      edges=[{k:e[k] for k in ['from_node','to_node','direction']} for e in gr['relations']])
    refs['H-020-vision-page1']=dict(method='assistant_visual_transcription',texts=[dict(kind='text',text=t) for t in [
      '온라인몰 반품분류 견적서','거래처: 푸른리테일','대상 시스템: 온라인몰','문서상태: 최종','작성일: 2026-09-18','견적번호: QT-26-PR-88','견적유효기간: 2026-10-18','견적금액: KRW 7,000,000 (VAT 별도)',
      '반품 봉투의 훼손 위치를 확인하고 자동 분류 결과를 검수한다. 이 문서는 스캔 이미지로만 보관한다.','합성 평가 자료 - 실제 계약이나 고객 정보를 나타내지 않음']],
      tables=[make_table([['항목','수량','금액'],['분류 카메라','2','6600000'],['검수 교육','1','400000']],[.070,.314,.930,.417],[1])],nodes=[],edges=[])
    return refs

def references(manifest):
    from pptx import Presentation
    import pdfplumber
    docs={d['doc_id']:d for d in manifest['documents']};pres={};pdfs={};refs=scan_refs()
    for item in manifest['items']:
        key=uid(item)
        if key not in refs:
            path=docs[item['doc_id']]['path'];loc=item['loc'];texts=[];tables=[];nodes=[];edges=[]
            if loc['kind']=='pptx':
                if path not in pres:pres[path]=Presentation(path)
                p=pres[path];slide=p.slides[loc['slide']-1];W=p.slide_width;H=p.slide_height;shapes={str(s.shape_id):s for s in slide.shapes}
                connected=set()
                for s in slide.shapes:
                    start=s._element.xpath('.//a:stCxn');end=s._element.xpath('.//a:endCxn')
                    if not(start and end):continue
                    a=start[0].get('id');b=end[0].get('id')
                    if a not in shapes or b not in shapes or not getattr(shapes[a],'text','').strip() or not getattr(shapes[b],'text','').strip():continue
                    head=s._element.xpath('.//a:headEnd');tail=s._element.xpath('.//a:tailEnd')
                    hs=bool(head and head[0].get('type') not in (None,'none'));ts=bool(tail and tail[0].get('type') not in (None,'none'))
                    direction='bidirectional' if hs and ts else 'forward' if hs or ts else 'undirected'
                    if hs and not ts:a,b=b,a
                    edges.append(dict(from_node=a,to_node=b,direction=direction));connected.update([a,b])
                for s in slide.shapes:
                    bbox=[s.left/W,s.top/H,(s.left+s.width)/W,(s.top+s.height)/H];sid=str(s.shape_id)
                    if s.has_table:
                        t=s.table;cells=[]
                        for r,row in enumerate(t.rows):
                            for c,cell in enumerate(row.cells):
                                if cell.is_spanned:continue
                                cells.append(dict(row=r+1,column=c+1,row_span=cell.span_height,column_span=cell.span_width,text=cell.text))
                        tables.append(dict(row_count=len(t.rows),column_count=len(t.columns),cells=cells,bbox=bbox,header_rows=[1]))
                    elif getattr(s,'has_text_frame',False) and s.text.strip():
                        if sid in connected:nodes.append(dict(id=sid,label=s.text,bbox=bbox))
                        else:
                            for para in s.text_frame.paragraphs:
                                if para.text.strip():texts.append(dict(text=para.text,kind='text',bbox=bbox,shape_id=sid))
                method='pptx_source_xml'
            else:
                if path not in pdfs:pdfs[path]=pdfplumber.open(path)
                # Visual inventory: only D-022 has a data table among native PDF
                # target pages. Proposal cover rectangles are NOT tables.
                p=pdfs[path].pages[loc['page']-1];found=p.find_tables() if item['doc_id']=='D-022' else [];boxes=[]
                for t in found:
                    rows=t.extract()
                    if not rows or len(rows)<2 or len(rows[0])<2:continue
                    # All native PDF target tables here have unmerged rectangular cells.
                    if any(c is None for row in rows for c in row):continue
                    tables.append(make_table(rows,[t.bbox[0]/p.width,t.bbox[1]/p.height,t.bbox[2]/p.width,t.bbox[3]/p.height],[1]));boxes.append(t.bbox)
                lines=[]
                for w in p.extract_words(x_tolerance=2,y_tolerance=3):
                    if any(b[0]<=w['x0'] and w['x1']<=b[2] and b[1]<=w['top'] and w['bottom']<=b[3] for b in boxes):continue
                    row=next((row for row in lines if abs(row[0]['top']-w['top'])<3),None)
                    if row is None:lines.append([w])
                    else:row.append(w)
                for row in sorted(lines,key=lambda r:r[0]['top']):
                    chunks=[[]]
                    for w in sorted(row,key=lambda w:w['x0']):
                        if chunks[-1] and w['x0']-chunks[-1][-1]['x1']>max(14,(w['bottom']-w['top'])*1.4):chunks.append([])
                        chunks[-1].append(w)
                    for chunk in chunks:
                        texts.append(dict(kind='text',text=' '.join(w['text'] for w in chunk),bbox=[min(w['x0'] for w in chunk)/p.width,min(w['top'] for w in chunk)/p.height,max(w['x1'] for w in chunk)/p.width,max(w['bottom'] for w in chunk)/p.height]))
                method='native_pdf_words_and_bordered_tables'
            refs[key]=dict(method=method,texts=texts,tables=tables,nodes=nodes,edges=edges)
        r=refs[key];r.update(doc_id=item['doc_id'],unit_id=item['unit_id'],image_path=item['image_path'],source_path=docs[item['doc_id']]['path'],source_sha256=docs[item['doc_id']]['sha256'],image_sha256=item['image_sha256'],gold_status='assistant_reference_needs_independent_review')
    for p in pdfs.values():p.close()
    # Visually checked PDF exports of the same slide. Use independently stored
    # PPTX connectors for topology and retain each PDF's own text references.
    for pdf,ppt in [('D-002','D-001'),('D-040','D-039'),('D-054','D-053'),('D-075','D-074'),('D-076','D-074')]:
        r=refs[pdf+'-vision-page5'];s=refs[ppt+'-vision-slide5']
        r['nodes']=s['nodes'];r['edges']=s['edges'];r['graph_reference_source']=s['source_path']
        r['graph_reference_method']='paired_source_pptx_connectors_and_visual_pdf_match'
        r['texts']=[t for t in r['texts'] if not any(norm(t['text'],True) in norm(n['label'],True) for n in r['nodes'])]
    return refs

def atoms(ref):
    return ref['texts']+[dict(kind='cell',text=c['text']) for t in ref['tables'] for c in t['cells'] if c['text'].strip()]+[dict(kind='node',text=n['label'],bbox=n.get('bbox')) for n in ref['nodes']]

def coverage(ref,observed):
    details=[]
    for a in atoms(ref):
        # Retain all table/node labels, but exclude tiny standalone page numbers.
        if a['kind']=='text' and len(norm(a['text']))<3:continue
        strict=any(norm(a['text']) in norm(x['text']) for x in observed)
        compatible=any(norm(a['text'],True) in norm(x['text'],True) for x in observed)
        # Also allow a paragraph split across several adjacent extracted blocks.
        for compat in [False,True]:
            if (compatible if compat else strict):continue
            joined=''.join(norm(x['text'],compat) for x in observed)
            found=norm(a['text'],compat) in joined
            if compat:compatible=found
            else:strict=found
        near=max(observed,key=lambda x:difflib.SequenceMatcher(None,norm(a['text'],True),norm(x['text'],True)).ratio(),default={'text':''})
        similarity=difflib.SequenceMatcher(None,norm(a['text'],True),norm(near['text'],True)).ratio()
        details.append(dict(expected=a['text'],kind=a['kind'],strict=strict,compatible=compatible,nearest=None if compatible else near['text'],similarity=None if compatible else round(similarity,3)))
    return dict(total=len(details),strict=sum(x['strict'] for x in details),compatible=sum(x['compatible'] for x in details),details=details)

def prf(expected,observed):
    a=collections.Counter(expected);b=collections.Counter(observed);tp=sum((a&b).values());en=sum(a.values());on=sum(b.values())
    return dict(correct=tp,expected=en,observed=on,precision=tp/on if on else 0,recall=tp/en if en else 0,f1=2*tp/(en+on) if en+on else 0)

def table_scores(ref,w):
    # Match whole tables by cell text overlap; never align rows to improve scores.
    result=[];unused=set(range(len(w.get('tables',[]))))
    for t in ref['tables']:
        def sim(j):return sum((collections.Counter(norm(c['text'],True) for c in t['cells']) & collections.Counter(norm(c.get('text',''),True) for c in w['tables'][j].get('cells',[]))).values())
        j=max(unused,key=sim) if unused else None
        if j is not None:unused.remove(j)
        obs=w['tables'][j] if j is not None else {};cs=obs.get('cells',[])
        def key(c):return tuple(c.get(k) for k in ['row','column','row_span','column_span'])+(norm(c.get('text',''),True),)
        result.append(dict(expected_dimensions=[t['row_count'],t['column_count']],observed_dimensions=[obs.get('row_count'),obs.get('column_count')],dimensions_correct=t['row_count']==obs.get('row_count') and t['column_count']==obs.get('column_count'),
          header_rows_correct=t['header_rows']==obs.get('header_rows'),expected_header_rows=t['header_rows'],observed_header_rows=obs.get('header_rows'),
          content=prf([norm(c['text'],True) for c in t['cells']],[norm(c.get('text',''),True) for c in cs if 'text' in c]),structure=prf([key(c) for c in t['cells']],[key(c) for c in cs if 'text' in c]),observed_table_index=j,
          source_bbox=t.get('bbox'),observed_bbox=obs.get('bbox')))
    return dict(tables=result,unmatched_output_tables=sorted(unused),unmatched_output_cells=sum(sum('text' in c for c in w['tables'][j].get('cells',[])) for j in unused))

def edge(a,b,d):return (min(a,b),max(a,b),d) if d in ('undirected','bidirectional') else (a,b,d)
def graph_scores(ref,w,compatible):
    labels={n['id']:norm(n['label'],compatible) for n in ref['nodes']};on=[];oe=[]
    for f in w.get('figures',[]):
        ll={n.get('id'):norm(n.get('label',''),compatible) for n in f.get('nodes',[]) if 'label' in n}
        on.extend(norm(n['label'],compatible) for n in f.get('nodes',[]) if 'label' in n)
        oe.extend(edge(ll.get(e.get('from_node'),'UNKNOWN'),ll.get(e.get('to_node'),'UNKNOWN'),e.get('direction','unknown')) for e in f.get('relations',[]) if 'to_node' in e)
    return dict(nodes=prf(labels.values(),on),edges=prf([edge(labels[e['from_node']],labels[e['to_node']],e['direction']) for e in ref['edges']],oe))

def duplicates(ref,w):
    observed=text_items(w);source=atoms(ref);flags=[]
    # Count repetitions of a source phrase across literal fields vs source count.
    # Deliberate common-JSON row summaries/evidence are NOT included here.
    texts={norm(a['text'],True):a['text'] for a in source if len(norm(a['text'],True))>=8}
    for s,raw in texts.items():
        en=sum(norm(a['text'],True).count(s) for a in source)
        on=sum(norm(a['text'],True).count(s) for a in observed)
        if on>en:flags.append(dict(source=raw,source_occurrences=en,output_occurrences=on,excess=on-en))
    return flags

def disjoint(a,b):
    return isinstance(a,list) and isinstance(b,list) and len(a)==len(b)==4 and (a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1])

def wire_payload(w):
    # All content/structure coordinates; no generated IDs beyond model nodes.
    return dict(texts=[{k:t[k] for k in ['kind','text','bbox']} for t in w['texts']],
      tables=[{k:t[k] for k in ['bbox','row_count','column_count','header_rows','header_status','cells']} for t in w['tables']],figures=w['figures'])

def common_payload(doc,item):
    unit=next(u for u in doc['coverage']['units'] if u['unit_id']==item['unit_id'])
    bb={b['block_id']:b for b in doc['blocks']};blocks=[bb[k] for k in unit['block_ids']];out=dict(texts=[],tables=[],figures=[])
    for b in blocks:
        evidence={e['evidence_id']:e for e in b['evidence']}
        if b['type'] in ['heading','paragraph','caption']:out['texts'].append(dict(kind=b['type'],text=b['text'],bbox=box(b['loc']['bbox'])))
        elif b['type']=='table':
            t=b['table'];cells=[]
            for row in blocks:
                if row.get('parent_id')==b['block_id']:
                    for c in row.get('cells',[]):cells.append({k:(box(c['loc']['bbox']) if k=='bbox' else c[k]) for k in ['row','column','row_span','column_span','text','value_status','role','bbox']})
            out['tables'].append(dict(bbox=box(b['loc']['bbox']),row_count=t['row_count'],column_count=t['column_count'],header_rows=t['header_rows'],header_status=t['header_status'],cells=cells))
        elif b['type']=='figure':
            v=b['visual'];f=dict(kind=v['kind'],bbox=box(b['loc']['bbox']),nodes=[],relations=[],claims=[])
            for n in v['nodes']:f['nodes'].append(dict(id=n['node_id'],label=n['label'],bbox=box(n['loc']['bbox'])))
            for e in v['relations']:
                ev=evidence[e['evidence_ids'][0]]
                f['relations'].append(dict(from_node=e['from_node'],to_node=e['to_node'],direction=e['direction'],label=e['label'],bbox=box(ev['loc']['bbox'])))
            for c in b['claims']:
                ev=evidence[c['evidence_ids'][0]]
                f['claims'].append(dict(text=c['text'],status=c['status'],bbox=box(ev['loc']['bbox'])))
            out['figures'].append(f)
    return out

def audit():
    manifest=load(RUN/'manifest.json');refs=references(manifest);write(OUT/'source-references.json',refs)
    source_files={str(p):digest(p) for p in list(RUN.rglob('*.json'))+list(RUN.rglob('*.jsonl'))+[Path(d['path']) for d in manifest['documents']]+[Path(i['image_path']) for i in manifest['items']]+[Path(i['parsed']) for i in manifest['inputs']]}
    native={d['doc_id']:d for i in manifest['inputs'] for d in [json.loads(l) for l in Path(i['parsed']).read_text().splitlines()]}
    reports=[]
    for model in MODELS:
        records=[]
        candidates={d['doc_id']:d for corpus in ['original','additional'] for d in [json.loads(l) for l in (RUN/model/corpus/'parsed.candidate.jsonl').read_text().splitlines()]}
        for item in manifest['items']:
            key=uid(item);ref=refs[key];base=RUN/model/'units'/key;resp=load(base/'response.json');res=load(base/'result.json')
            raw=resp['choices'][0]['message']['content'];w,complete,closed=recover(raw);obs=text_items(w);cov=coverage(ref,obs)
            claims=[dict(text=c['text'],kind='claim',bbox=c.get('bbox')) for f in w.get('figures',[]) for c in f.get('claims',[]) if isinstance(c.get('text'),str)]
            anycov=coverage(ref,obs+claims)
            tab=table_scores(ref,w);gr=graph_scores(ref,w,True);strictgraph=graph_scores(ref,w,False)
            cells=[c for t in w.get('tables',[]) for c in t.get('cells',[])];conflicts=[c for c in cells if c.get('value_status')=='unreadable' and str(c.get('text','')).strip()]
            position=[]
            for a in atoms(ref):
                if not a.get('bbox'):continue
                matches=[x for x in obs if norm(x['text'],True)==norm(a['text'],True)]
                if matches and all(disjoint(a['bbox'],x.get('bbox')) for x in matches):position.append(dict(text=a['text'],source_bbox=a['bbox'],output_bboxes=[x.get('bbox') for x in matches]))
            delivery=None
            if res['status']=='valid':
                doc=load(base/'common-block-document.json')
                try:
                    original=wire_payload(w);converted=common_payload(doc,item)
                    delivery=dict(content_and_structure_preserved=original==converted,assembled_candidate_preserved=original==common_payload(candidates[item['doc_id']],item),
                      source_hash_preserved=doc['source']['sha256']==item['source_sha256'],
                      original=original if original!=converted else None,converted=converted if original!=converted else None)
                except (KeyError,TypeError) as e:delivery=dict(audit_error=str(e))
            records.append(dict(key=key,doc_id=item['doc_id'],unit_id=item['unit_id'],reference_method=ref['method'],response_path=str(base/'response.json'),response_sha256=digest(base/'response.json'),json_complete=complete,finish_reason=resp['choices'][0].get('finish_reason'),common_json_valid=res['status']=='valid',validation_errors=res.get('errors',[]),model_status=w.get('status'),
              coverage=cov,coverage_including_claims_diagnostic=anycov,source_items_only_in_claims=[a['expected'] for a,b in zip(cov['details'],anycov['details']) if not a['compatible'] and b['compatible']],
              tables=tab,graph_compatible=gr,graph_strict=strictgraph,duplicate_source_phrases=duplicates(ref,w),unreadable_cells_with_text=len(conflicts),complete_with_unreadable_cells=w.get('status')=='complete' and any(c.get('value_status')=='unreadable' for c in cells),
              disjoint_text_or_node_bboxes=position,delivery=delivery,extracted_literals=obs,figures=w.get('figures',[]),recovered_prefix_only=not complete))
            if not complete:write(OUT/(model+'-'+key+'-prefix-diagnostic.json'),dict(not_valid_json_not_for_ingestion=True,closed_paths=closed,recovered=w))
        def aggregate(key):
            cs=[r['coverage'] for r in records if key=='all' or (r['reference_method']=='assistant_visual_transcription')==(key=='scan')]
            return {k:sum(c[k] for c in cs) for k in ['total','strict','compatible']}
        def sumprf(ps):
            tp=sum(p['correct'] for p in ps);en=sum(p['expected'] for p in ps);on=sum(p['observed'] for p in ps)
            return dict(correct=tp,expected=en,observed=on,precision=tp/on if on else 0,recall=tp/en if en else 0,f1=2*tp/(en+on) if en+on else 0)
        tables=[t for r in records for t in r['tables']['tables']]
        extra=sum(r['tables']['unmatched_output_cells'] for r in records)
        summary=dict(model=model,images=len(records),json_complete=sum(r['json_complete'] for r in records),common_json_valid=sum(r['common_json_valid'] for r in records),coverage={k:aggregate(k) for k in ['all','native','scan']},
          source_items_only_in_claims=sum(len(r['source_items_only_in_claims']) for r in records),
          coverage_including_claims_diagnostic={k:sum(r['coverage_including_claims_diagnostic'][k] for r in records) for k in ['total','strict','compatible']},
          table_count=len(tables),table_dimensions_correct=sum(t['dimensions_correct'] for t in tables),table_header_rows_correct=sum(t['header_rows_correct'] for t in tables),table_content=sumprf([t['content'] for t in tables]),table_structure=sumprf([t['structure'] for t in tables]),unmatched_tables=sum(len(r['tables']['unmatched_output_tables']) for r in records),
          graphs={mode:{k:sumprf([r['graph_'+mode][k] for r in records if refs[r['key']]['nodes']]) for k in ['nodes','edges']} for mode in ['strict','compatible']},
          graph_images=sum(bool(refs[r['key']]['nodes']) for r in records),duplicate_images=sum(bool(r['duplicate_source_phrases']) for r in records),complete_with_unreadable_images=sum(r['complete_with_unreadable_cells'] for r in records),unreadable_cells_with_text=sum(r['unreadable_cells_with_text'] for r in records),
          disjoint_bbox_images=sum(bool(r['disjoint_text_or_node_bboxes']) for r in records),delivery_preserved=sum(r['delivery'] is not None and r['delivery'].get('content_and_structure_preserved',False) for r in records),
          assembled_candidate_preserved=sum(r['delivery'] is not None and r['delivery'].get('assembled_candidate_preserved',False) for r in records),
          delivery_errors=[dict(key=r['key'],audit=r['delivery']) for r in records if r['delivery'] is not None and not all(r['delivery'].get(k) for k in ['content_and_structure_preserved','assembled_candidate_preserved','source_hash_preserved'])])
        for k in ['table_content','table_structure']:
            s=summary[k];s['observed']+=extra;s['precision']=s['correct']/s['observed'] if s['observed'] else 0;s['f1']=2*s['correct']/(s['expected']+s['observed']) if s['expected']+s['observed'] else 0
        summary['native_documents_preserved']=sum(all(b in candidates[k]['blocks'] for b in d['blocks']) and d['source']==candidates[k]['source'] for k,d in native.items())
        summary['native_documents_total']=len(native)
        # Coverage in accepted common JSON. Failed pages contribute zero, while
        # recoverable-prefix coverage remains the separate diagnostic above.
        summary['accepted_common_literal_coverage']={k:sum(r['coverage'][k] for r in records if r['common_json_valid']) for k in ['strict','compatible']}
        summary['accepted_common_literal_coverage']['total']=sum(r['coverage']['total'] for r in records)
        reports.append(dict(summary=summary,records=records))
    write(OUT/'evaluation.json',reports)
    # Hash all existing inputs before/after review. No previous output is written.
    changed=[p for p,h in source_files.items() if digest(p)!=h]
    write(OUT/'integrity.json',dict(files=len(source_files),changed=changed,hashes=source_files,paid_calls=0,network_calls=0,source_hash_matches_manifest=all(digest(d['path'])==d['sha256'] for d in manifest['documents']),images_match_manifest=all(digest(i['image_path'])==i['image_sha256'] for i in manifest['items'])))
    print(json.dumps([r['summary'] for r in reports],ensure_ascii=False,indent=2))

if __name__=='__main__':audit()
