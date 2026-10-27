"""Build a reviewed offline evaluation package. No HTTP, credentials, or model client."""
import copy
import hashlib
import importlib.util
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FIELDS = ['문서종류','거래처','문서일자','대상시스템','상태','계약번호','계약유형','계약시작일','계약종료일','금액','통화','VAT','견적번호','견적유효기간','사이트','작업명','로그시작','로그종료','실행결과','오류코드','사업명','표지일','작성일']
SCANS = {'D-044','D-102','H-020'}
SCOPE = {**{f:{'계약서'} for f in ['계약번호','계약유형','계약시작일','계약종료일']}, **{f:{'계약서','견적서','제안서'} for f in ['금액','통화','VAT']}, '견적유효기간':{'견적서'}, '사이트':{'네트워크 구성도','서버 구성도'}, **{f:{'실행 로그'} for f in ['작업명','로그시작','로그종료','실행결과']}, '오류코드':{'실행 로그','기타'}}

def read(p): return json.loads(Path(p).read_text())
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def objsha(v): return hashlib.sha256(canon(v).encode()).hexdigest()
def norm(s): return re.sub(r'\s+','',unicodedata.normalize('NFC',str(s))).replace('㈜','(주)')
def load_module(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def reviewed_record(original,refs):
    r=copy.deepcopy(original);r['record_kind']='design_example'
    r['blocks']=[];r['runs']=[{'run_id':'source-review','method':'manual_design','implementation':'assistant-source-review-2026-10-19','model_id':None,'provider':None,'quantization':None,'prompt_version':None,'input_asset_ids':[a['asset_id'] for a in r['assets']]}]
    r['coverage']={'scope':'excerpt','unit_inventory_complete':True,'units':[]}
    r['warnings']=['Evaluation-only reviewed fixture covering every source page; not a model run or production ingestion. Paragraph whitespace normalized.']
    def block(bid,typ,text,loc,parent=None):
        b={'block_id':bid,'parent_id':parent,'order':len(r['blocks'])+1,'type':typ,'text':text,'loc':loc,'heading_path':[],'run_ref':'source-review','evidence':[{'evidence_id':'source','kind':'literal','loc':loc,'quote':text}] if text else [],'claims':[],'context_ids':[],'content_refs':[],'warnings':[]};r['blocks'].append(b);return b
    for ref in refs:
        page=int(ref['unit_id'].replace('vision:page',''));loc={'kind':'pdf','page':page};start=len(r['blocks'])
        # Existing reference groups texts and tables separately; preserve the footer after H-020's table.
        texts=ref['texts'];footer=texts[-1:] if r['doc_id']=='H-020' else []
        for i,t in enumerate(texts[:-1] if footer else texts,1):block(f"{r['doc_id']}-review-p{page}-text{i}",'paragraph',t['text'],loc)
        for ti,t in enumerate(ref['tables'],1):
            tid=f"{r['doc_id']}-review-p{page}-table{ti}";b=block(tid,'table','',loc)
            b['table']={k:copy.deepcopy(t[k]) for k in ['row_count','column_count','header_rows']};b['table'].update(header_status='explicit',continued_from=None)
            for row in range(1,t['row_count']+1):
                cells=[]
                for c in t['cells']:
                    if c['row']==row:cells.append({**c,'value':c['text'],'value_status':'known' if c['text'] else 'blank','formula':None,'number_format':None,'role':'header' if row in t['header_rows'] else 'data','loc':loc})
                block(tid+f'-r{row}','table_row','\t'.join(c['text'] for c in cells),loc,tid)['cells']=cells
        for t in footer:block(f"{r['doc_id']}-review-p{page}-footer",'paragraph',t['text'],loc)
        r['coverage']['units'].append({'unit_id':f'review:page{page}','loc':loc,'required':True,'status':'completed','reason':None,'block_ids':[b['block_id'] for b in r['blocks'][start:]]})
    return r

def evidence(r,needle=None,field=None,value=None):
    """Resolve a reviewed anchor, not a model prediction or a gold ID in the public input."""
    blocks=[b for b in r['blocks'] if b.get('text','').strip() and not b.get('content_refs')]
    def ev(b):return {'kind':'block','ref':b['block_id'],'quote':b['text'],'loc':b['loc']}
    if needle is not None:
        found=[b for b in blocks if norm(needle) in norm(b['text'])]
        if not found:raise ValueError((r['doc_id'],'anchor missing',needle))
        return [ev(found[0])]
    if field=='문서종류':return [{'kind':'source','ref':'file_name','quote':r['source']['file_name'],'loc':None}]
    if field=='거래처':return [{'kind':'source','ref':'relative_path','quote':r['source']['relative_path'],'loc':None}]
    if field=='상태':
        return evidence(r,'문서상태') if any('문서상태' in b['text'] for b in blocks) else [{'kind':'source','ref':'file_name','quote':r['source']['file_name'],'loc':None}]
    if field in ['문서일자','표지일','작성일','계약시작일','계약종료일','견적유효기간']:
        digits=value.split('-');pat=r'\b'+digits[0]+r'\s*(?:[-.]|년)\s*0?'+str(int(digits[1]))+r'\s*(?:[-.]|월)\s*0?'+str(int(digits[2]))+r'(?!\d)'
        found=[b for b in blocks if re.search(pat,b['text'])]
        if found:return [ev(found[0])]
    anchors={'대상시스템':['대상 시스템','대상시스템'], '계약번호':['계약번호'],'계약유형':['계약유형'],'계약시작일':['계약기간','본 계약의 기간은'],'계약종료일':['계약기간','본 계약의 기간은'],'금액':['계약금액은','계약금액:','총 제안금액','제안금액:','견적금액'],'통화':['통화','계약금액은','계약금액:','총 제안금액','제안금액:','견적금액:'],'VAT':['VAT','부가가치세'],'견적번호':['견적번호'],'견적유효기간':['견적유효기간'],'사이트':['설치 위치'],'작업명':['작업명'],'로그시작':['작업 시작'],'로그종료':['작업 종료'],'실행결과':['작업 종료'],'사업명':['이하 "본 사업"']}
    for a in anchors.get(field,[]):
        found=[b for b in blocks if norm(a) in norm(b['text']) and (field!='대상시스템' or norm(value) in norm(b['text']))]
        if found:return [ev(found[0])]
    found=[b for b in blocks if norm(value) in norm(b['text'])]
    if found:return [ev(found[0])]
    raise ValueError((r['doc_id'],field,value,'no evidence'))

# Human-readable statements below were authored after reading all selected native texts and scan pages.
# They are semantic review targets, not strings the candidate must reproduce verbatim.
SUMMARY = {
 'D-005':[('설비 데이터 1초 수집을 업무 범위로 정한다.','설비 데이터 1초'),('ERP 생산실적 자동 연동과 MES 서버 가상화 전환이 범위다.','ERP 생산실적 자동'),('계약금액은 248,000,000원이며 부가세 별도다.','계약금액은'),('내부 검토용 초안이다.','내부 검토용')],
 'D-044':[('스토리지 300TB 증설과 SAN 이중화가 업무 범위다.','스토리지 300TB'),('계약기간은 2025-04-01부터 2025-04-30까지다.','본 계약의 기간은'),('계약금액은 187,000,000원이며 부가세 별도다.','계약금액은')],
 'D-102':[('서버 4대 교체와 Windows Server 2022 전환이 범위다.','서버 4대'),('조달청 우수제품 구매 절차를 준수한다.','조달청'),('계약금액은 129,800,000원이며 부가세 포함이다.','계약금액은')],
 'D-002':[('MES의 설비 데이터를 1초 단위로 실시간 수집하는 것을 제안한다.','설비 데이터 1 초'),('ERP 생산실적 자동 연동과 MES 서버 가상화 전환을 목표로 한다.','ERP 생산실적 자동'),('제안금액은 265,400,000원이며 부가세 별도다.','총 제안금액')],
 'D-007':[('MES 네트워크 구성도 Rev.1이다.','네트워크 구성도 (Rev.1)'),('설치 위치는 화성 1공장 전산실이다.','설치 위치'),('서버팜은 10.21.10.0/24로 표시되어 있다.','10.21.10.0/24')],
 'H-001':[('성형기 12대를 250ms 주기로 수집하고 PLC 프로그램 변경은 제외한다.','대상은 성형기'),('게이트웨이는 단절 시 원시 데이터를 72시간 보관한다.','네트워크 단절'),('검수는 누락률 0.2% 이하와 시각 오차 50ms 이하를 확인한다.','검수는 누락률')],
 'H-002':[('야간 장애 접수 후 45분 이내 원격 대응을 시작한다.','야간 장애'),('온도 센서 교체는 제외하고 수신 프로그램을 유지보수한다.','온도 센서 자체'),('백업 복원 훈련은 분기마다 실시한다.','백업 복원')],
 'H-006':[('금형 8기가 검토 대상이며 성형기 12대 사업과 별개다.','검토 대상은'),('수집 간격은 200ms로 제안한다.','금형 온도 변동'),('ERP 생산실적 연동은 읽기 전용이다.','생산실적 ERP')],
 'H-007':[('팔레트 라벨과 온도 이력을 연결한다.','냉장 입고'),('TMS와는 일별 집계 파일만 교환한다.','출고 배차'),('센서 수신 지연과 무선 연결 단절을 구분해 알린다.','구역별 센서')],
 'H-011':[('산업용 게이트웨이 4대와 설치 용역을 견적한다.','산업용 게이트웨이'),('대표 견적금액은 9,600,000원이다.','견적금액'),('운송비는 공급가액에 포함하고 수량 변경 시 재발행한다.','운송비는')],
 'H-015':[('대사 모듈의 수량은 1, 운영 교육의 수량은 2다.','대사 모듈'),('대표 견적금액은 9,000,000원이다.','견적금액'),('운송비는 공급가액에 포함하고 수량 변경 시 재발행한다.','운송비는')],
 'H-016':[('소성로별 가스 사용량을 작업 지시와 연결해 주간 원가를 집계한다.','소성로별'),('MES 생산수량은 입력으로만 사용한다.','소성로별'),('가스 계량 누락 구간을 추정하지 않고 확인 목록에 남긴다.','가스 계량 누락')],
 'H-018':[('PACS 복제망 VLAN 260을 EMR 접속망 VLAN 120과 분리한다.','PACS 복제망'),('복제 노드에서 보관 노드로 TCP 11112만 허용한다.','방화벽은'),('설치 위치는 동관 전산실이다.','설치 위치')],
 'H-020':[('반품 봉투의 훼손 위치와 자동 분류 결과를 검수하는 견적이다.','반품 봉투'),('분류 카메라의 수량은 2, 검수 교육의 수량은 1이다.','분류 카메라'),('견적금액은 7,000,000원이며 VAT 별도다.','견적금액')],
 'H-021':[('성형기 4호의 센서 값 고정 현상을 점검했다.','성형기 4호'),('E-SENSOR-17은 케이블 접촉 불량으로 확인됐다.','E-SENSOR-17'),('재연결 후 30분 관찰에서 동일 경고가 재발하지 않았다.','센서를 재연결')],
 'H-022':[('알림 수신자를 주간 운영팀과 야간 당직자로 구분한다.','냉장구역'),('경보가 4분 연속 지속할 때만 전화 알림을 보낸다.','경보가 4분'),('순간 상승은 화면 기록만 남긴다.','순간 상승')],
 'H-023':[('복제 대기량이 120건 이하일 때 전환을 시작한다.','복제 대기량'),('원본 영상 삭제는 이번 작업에서 수행하지 않는다.','원본 영상 삭제'),('과거 EMR 실패 기록은 현재 PACS 전환 상태가 아니다.','과거 EMR 작업')],
 'H-026':[('gateway_cutover 작업은 최종 SUCCESS로 종료했다.','작업 종료'),('E-CONN-12 경고 뒤 재연결에 성공했다.','재연결 시도'),('버퍼 480건을 재전송했다.','버퍼 480건')],
 'H-027':[('cold_ingest_restart 작업은 최종 FAILED로 종료했다.','작업 종료'),('E-TEMP-08 sensor handshake timeout 오류가 있었다.','sensor handshake'),('재시도 횟수를 초과했다.','재시도 횟수')],
 'H-030':[('order_reconcile 작업은 최종 SUCCESS로 종료했다.','작업 종료'),('미저장 승인 주문은 23건이었다.','미저장 승인'),('취소 2건을 제외하고 주문 21건을 복구했다.','주문 21건')]
}

def main():
    if (HERE/'freeze.json').exists():raise ValueError('Package frozen. Build a new version instead of overwriting inputs or gold.')
    from jsonschema import Draft202012Validator
    selected=read(ROOT/'outputs/model-selection-review-001/selected-cases.json')['cases']
    scans=read(HERE/'scan-review.json');common=load_module('common_review_check',ROOT/'outputs/common-block-design/validate_design.py')
    originals={r['doc_id']:r for p in {c['parsed_jsonl'] for c in selected} for r in rows(ROOT/p)}
    dlabels={r['doc_id']:r for r in rows(ROOT/'outputs/metadata-policy-v1/documents.source-v1.jsonl')}
    hlabels={r['doc_id']:r for r in rows(ROOT/'outputs/additional-dataset-v1/package/metadata-labels.jsonl')}
    source_metadata={r['doc_id']:r for p in ['outputs/date-search-run-002/source-metadata.jsonl','outputs/additional-search-run-002/source-metadata.jsonl'] for r in rows(ROOT/p)}
    date_metadata={r['doc_id']:r for p in ['outputs/date-search-run-002/date-metadata.jsonl','outputs/additional-search-run-002/date-metadata.jsonl'] for r in rows(ROOT/p)}
    reference={'clients':[],'system_terms':[]}
    for p in ['outputs/rag-enrichment-v1/reference-data.json','outputs/additional-dataset-v1/reference-data.json']:
        ref=read(ROOT/p);reference['clients']+=ref['clients'];reference['system_terms']+=ref['system_terms']
    reference['system_terms']=sorted(set(reference['system_terms']))
    write(HERE/'public/reference-data.json',reference)
    manifest=[];gold=[];baseline=[];changes=[];reviewtext=[];source_checks=[]
    # Inventory is restricted to the two user-provided datasets; credentials and unrelated folders are not read.
    droot=next(p for p in Path('/Users/kangdongkyoon/Downloads').iterdir() if norm(p.name)==norm('RAG_예비데이터셋(클로드)'))/'files'
    hroot=ROOT/'outputs/additional-dataset-v1/files'
    paths={norm(p.relative_to(base).as_posix()):p for base in [droot,hroot] for p in base.rglob('*') if p.is_file()}
    rule=load_module('eval_rule_baseline',ROOT/'outputs/rag-enrichment-v3/enrich.py')
    previous_input_check=rule.previous.input_errors
    def fixture_check(doc):
        return common.check(doc) if doc['doc_id'] in SCANS and doc['record_kind']=='design_example' else previous_input_check(doc)
    rule.previous.input_errors=fixture_check
    for case in selected:
        did=case['doc_id'];original=originals[did];r=reviewed_record(original,[v for k,v in sorted(scans.items()) if v['doc_id']==did]) if did in SCANS else copy.deepcopy(original)
        errors=common.check(r)
        if errors:raise ValueError((did,errors))
        source=paths[norm(case['source_relative_path'])]
        assert sha(source)==case['source_sha256']
        # Verify native literal content against fresh read-only reads of source storage, not model output.
        native_units=[]
        if source.suffix in ['.docx','.pptx']:
            with zipfile.ZipFile(source) as z:
                names=['word/document.xml'] if source.suffix=='.docx' else sorted(n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+.xml',n))
                native_units=[''.join(e.itertext()) for n in names for e in ET.fromstring(z.read(n)).iter() if e.tag.endswith('}t')]
        elif source.suffix=='.xlsx':
            import openpyxl
            wb=openpyxl.load_workbook(source,data_only=True)
            native_units=[str(c.value) for s in wb for row in s for c in row if c.value is not None]
        elif source.suffix=='.pdf' and did not in SCANS:
            from pypdf import PdfReader
            native_units=[p.extract_text() for p in PdfReader(source).pages]
        elif source.suffix in ['.txt','.log']:native_units=[source.read_text()]
        literals=[c['text'] for b in r['blocks'] for c in b.get('cells',[]) if c['text'].strip()]+[b['text'] for b in r['blocks'] if b['type'] not in ['table_row','table','slide'] and b['text'].strip()]
        missing=[]
        if native_units:
            corpus=norm(''.join(native_units))
            for literal in literals:
                # PPTX/PDF reading order can differ; each line is checked without altering stored input.
                if norm(literal) not in corpus and not all(norm(x) in corpus for x in (literal.split() if source.suffix=='.pdf' else literal.splitlines()) if x.strip()):missing.append(literal)
        source_checks.append({'doc_id':did,'source_path':str(source),'source_sha256':sha(source),'source_mtime_ns':str(source.stat().st_mtime_ns),'native_source_content_checks':len(literals) if native_units else 0,'unmatched_literals':missing,'review_method':'full_page_image_review' if did in SCANS else 'native_storage_read_and_selected_content_review','check_limit':'PDF text extraction reading order can differ; unmatched complete spans fall back to checking their whitespace-separated fragments. This is content presence, not full visual layout certification.'})
        if missing:raise ValueError((did,'source literal mismatch',missing[:2]))
        for a in r['assets']:
            ap=ROOT/Path(case['parsed_jsonl']).parent/a['path'];assert sha(ap)==a['sha256'];a['path']=str(ap)
        write(HERE/f'public/inputs/{did}.json',{'version':'enrichment-input-1','document':r,'source_metadata':source_metadata[did],'input_review':{'kind':'assistant_source_reviewed_fixture' if did in SCANS else 'native_parser_output','human_independent_review':False,'production_ingestion':False}})
        raw={f:None for f in FIELDS};statuses={}
        if did.startswith('D-'):
            for f in FIELDS[:20]:
                v=dlabels[did].get(f);raw[f]=str(v) if v is not None and v!='N/A' else None
            for f in ['표지일','작성일']:raw[f]=date_metadata[did]['fields'][f]['value']
        else:
            for f in FIELDS:
                v=hlabels[did]['fields'].get(f,{}).get('value');raw[f]=str(v) if v is not None else None
        if did in ['D-005','D-044','D-102']:
            changes.append({'doc_id':did,'field':'계약유형','old':raw['계약유형'],'new':None,'reason':'No explicit contract-type label; purpose/supply/purchase-process wording does not establish this field under the fixed policy.'});raw['계약유형']=None
            raw['사업명']=dlabels[did]['사업명']
        if did in SCANS:
            for f in ['표지일','작성일']:raw[f]=None
        if did=='H-020':
            updates={'문서일자':'2026-09-18','작성일':'2026-09-18','금액':'7000000','통화':'KRW','VAT':'별도','견적번호':'QT-26-PR-88','견적유효기간':'2026-10-18'}
            for f,v in updates.items():changes.append({'doc_id':did,'field':f,'old':raw[f],'new':v,'reason':'Now observed in the shared source-reviewed scan input; old native-only labels remain unchanged.'})
            raw.update(updates)
        if did in ['D-002','D-007']:
            changes.append({'doc_id':did,'field':'사업명','old':dlabels[did]['사업명'],'new':None,'reason':'Business name previously excluded from scoring; this evaluation requires an explicit business-name label or named 본 사업 clause, not a title-only inference.'})
        if did=='D-005':statuses.update(문서일자='needs_review',작성일='needs_review')
        fields={}
        doc_type=raw['문서종류'];pending=any(u['status']!='completed' for u in r['coverage']['units'])
        for f,v in raw.items():
            if v is not None:
                e=evidence(r,field=f,value=v)
                fields[f]={'value':v,'expected_status':'extracted','accepted_statuses':['extracted'],'evidence':e,'accepted_values':[v],'reason':'Source-grounded value under the fixed field policy.','value_scorable':True,'input_observable':True}
            else:
                outside=f in SCOPE and doc_type not in SCOPE[f]
                status=statuses.get(f,'not_applicable' if outside else 'pending_vision' if pending else 'not_found_in_input')
                e=evidence(r,'2025년 2월 19일') if did=='D-005' and f in ['문서일자','작성일'] else []
                accepted=[status]
                if status=='pending_vision':accepted.append('not_found_in_input')
                fields[f]={'value':None,'expected_status':status,'accepted_statuses':accepted,'evidence':e,'accepted_values':[],'reason':'Draft signing-block date has no explicit written-date role.' if status=='needs_review' else 'Outside field applicability.' if outside else 'No permitted unambiguous value in frozen input; unresolved visual coverage retained.' if pending else 'No permitted explicit value in reviewed input.','value_scorable':status!='needs_review','input_observable':False}
        # Known aliases are accepted only for the same client, never arbitrary normalization of codes/dates.
        client=next(c for c in reference['clients'] if c['name']==raw['거래처'])
        fields['거래처']['accepted_values']=list(dict.fromkeys([client['name'],client['folder']]+client['aliases']))
        for f,g in fields.items():
            if g['value'] is None:continue
            alternatives=[g['evidence']]
            if f in ['문서종류','상태','대상시스템']:
                alternatives.append([{'kind':'source','ref':'file_name','quote':r['source']['file_name'],'loc':None}])
                for b in r['blocks']:
                    text=b.get('text','')
                    needles=([g['value'],'메모','메일'] if g['value']=='기타' else [g['value']])
                    if any(norm(x) in norm(text) for x in needles) and (f=='문서종류' and (b['order']<=3 or '제목' in text) or f=='상태' and '문서상태' in text or f=='대상시스템' and ('대상 시스템' in text or '대상시스템' in text or b['order']<=3)):
                        alternatives.append([{'kind':'block','ref':b['block_id'],'quote':text,'loc':b['loc']}])
            if f=='거래처':
                for b in r['blocks']:
                    text=b.get('text','')
                    if any(norm(a) in norm(text) for a in g['accepted_values']) and any(x in text for x in ['거래처','귀중','갑','상호']):
                        alternatives.append([{'kind':'block','ref':b['block_id'],'quote':text,'loc':b['loc']}])
            g['evidence_alternatives']=alternatives
        facts=[]
        for i,(statement,anchor) in enumerate(SUMMARY[did],1):
            ev=evidence(r,anchor)
            extra={('H-011',1):'설치 용역',('H-015',1):'운영 교육',('H-020',2):'검수 교육',('H-016',2):'만 사용한다.',('H-026',1):'작업명',('H-026',2):'재연결 성공',('H-027',1):'작업명',('H-030',1):'작업명',('H-030',3):'취소 주문 2건'}.get((did,i))
            if extra:
                for item in evidence(r,extra):
                    if item not in ev:ev.append(item)
            facts.append({'fact_id':f'{did}-F{i}','statement':statement,'evidence':ev,'review_status':'assistant_source_checked_pending_human','matching':'semantic; paraphrases accepted; negation/numbers/conditions must be preserved'})
        gold.append({'doc_id':did,'review_status':'assistant_source_checked_pending_independent_human','human_reviewer':None,'fields':fields,'summary_facts':facts,'summary_constraints':['No invented submission date, actual signature, completed deployment, or permanent incident resolution.','No quoted/forwarded historical outcome as current outcome.','Use proposal/contract/observation modality as stated; preserve exclusions.']})
        result=rule.extract(r,reference)
        bfields={}
        for f in FIELDS:
            if f in result['fields']:
                x=result['fields'][f];bfields[f]={'value':x['value'],'status':'not_found_in_input' if x['status']=='not_found_native' else x['status'],'evidence':x['evidence'],'candidates':[{'value':c['value'],'evidence':c['evidence']} for c in x['candidates']],'reason':x['reason']}
            else:
                role='cover_date' if f=='표지일' else 'explicit_written_date';obs=[o for o in result['date_context']['observations'] if o['role']==role]
                vals={o['value'] for o in obs};status='extracted' if len(vals)==1 else 'needs_review' if vals else 'not_found_in_input'
                bfields[f]={'value':next(iter(vals)) if len(vals)==1 else None,'status':status,'evidence':[e for o in obs for e in o['evidence']] if len(vals)==1 else [],'candidates':[],'reason':None if len(vals)==1 else 'No unique explicit date role from rules.'}
        baseline.append({'doc_id':did,'schema_version':'llm_enrichment_candidate_v1','fields':bfields,'summary':[]})
        manifest.append({'doc_id':did,'group':case['group'],'input_kind':'reviewed_scan' if did in SCANS else 'native','input_path':f'public/inputs/{did}.json','input_sha256':sha(HERE/f'public/inputs/{did}.json'),'source_sha256':sha(source)})
        reviewtext.append(did+' '+case['file_name']+'\n'+'\n'.join(f"{f}: {g['value']} [{g['expected_status']}]" for f,g in fields.items())+'\n요약 사실:\n'+'\n'.join(x['statement'] for x in facts))
    write(HERE/'private/gold.json',gold);write(HERE/'private/label-adjustments.json',changes)
    write(HERE/'private/rules-baseline.json',baseline);write(HERE/'private/source-checks.json',source_checks)
    (HERE/'private/REVIEW.txt').write_text('\n\n'.join(reviewtext)+'\n')
    write(HERE/'manifest.json',{'version':'enrichment-selection-1','models':['qwen/qwen3.6-35b-a3b','qwen/qwen3-vl-30b-a3b-instruct'],'documents':manifest,'count':20,'planned_calls':40,'calls_made':0,'independent_holdout':False,'review_status':'assistant_reviewed_not_human_verified','baseline_adapter':'Unchanged rules-0.3.0 extraction; only input-kind check accepts the three reviewed fixtures; outputs are evaluation candidates, not native run records.','settings':{'temperature':0.7,'top_p':0.8,'top_k':20,'presence_penalty':1.5,'repetition_penalty':1.0,'min_p':0.0,'frequency_penalty':0.0,'seed':42,'max_tokens':16384,'provider':{'only':['deepinfra/fp8'],'allow_fallbacks':False,'require_parameters':True},'qwen36_reasoning_enabled':False},'thresholds':{'filled_value_precision':0.95,'observable_value_recall':0.95,'valid_documents':20,'critical_errors':0}})
    print(json.dumps({'documents':len(manifest),'fields':sum(len(g['fields']) for g in gold),'summary_facts':sum(len(g['summary_facts']) for g in gold),'label_adjustments':len(changes),'source_checks':len(source_checks)},ensure_ascii=False))

if __name__=='__main__':main()
