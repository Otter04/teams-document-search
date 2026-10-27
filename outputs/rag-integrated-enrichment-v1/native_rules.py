#!/usr/bin/env python3
"""Deterministic metadata from actual native blocks. No model or gold access."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
VERSION = 'rules-reviewed-1.0.0'
APPROVED_RECORD_HASHES = set()
FIELDS = ['문서종류','거래처','문서일자','대상시스템','상태','계약번호','계약유형',
          '계약시작일','계약종료일','금액','통화','VAT','견적번호','견적유효기간',
          '사이트','작업명','로그시작','로그종료','실행결과','오류코드']
ALL_FIELDS = FIELDS + ['사업명']
STATUSES = ['extracted','pending_vision','needs_review','not_found_text','not_applicable']
FIELD_SCOPE = {
    **{f:{'계약서'} for f in ('계약번호','계약유형','계약시작일','계약종료일')},
    **{f:{'계약서','견적서','제안서'} for f in ('금액','통화','VAT')},
    '견적유효기간':{'견적서'},'사이트':{'네트워크 구성도','서버 구성도'},
    **{f:{'실행 로그'} for f in ('작업명','로그시작','로그종료','실행결과')},
    '오류코드':{'실행 로그','기타'}}
DATE = r'(\d{4})\s*(?:[-.]|년)\s*(\d{1,2})\s*(?:[-.]|월)\s*(\d{1,2})\s*(?:일|\.)?'
STAMP = r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2}(?:[.,]\d+)?)?'
ERROR = r'\b(?:ORA-\d{5}|(?:BKP|NET|HC|FS)-[EW]\d{4}|HTTP-\d{3})\b'

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def canonical(obj): return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def record_hash(obj): return hashlib.sha256(canonical(obj).encode()).hexdigest()
def dump(path,obj): Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def save_lines(path,rows): Path(path).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
def unique(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(f'duplicate JSON key: {k}')
        d[k]=v
    return d
def read_json(path): return json.loads(Path(path).read_text(),object_pairs_hook=unique)
def read_lines(path): return [json.loads(x,object_pairs_hook=unique) for x in Path(path).read_text().splitlines() if x.strip()]
def squash(s): return re.sub(r'\s+','',unicodedata.normalize('NFC',s))
def dated(m): return date(*(int(m[i]) for i in (1,2,3))).isoformat()
def timestamp(text):
    m=re.search(STAMP,text)
    if not m:return None
    return datetime.strptime(m[1]+' '+m[2],'%Y-%m-%d %H:%M').strftime('%Y-%m-%d %H:%M')

_validation=None
def input_errors(record):
    global _validation
    if _validation is None:
        spec=importlib.util.spec_from_file_location('native_block_validator',ROOT.parent/'common-block-design/validate_design.py')
        _validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(_validation)
    errors=_validation.check(record)
    if record.get('record_kind')!='run_result':errors.append('only actual run_result input is allowed')
    if any(r.get('method')!='native_parser' for r in record.get('runs',[])) and record_hash(record) not in APPROVED_RECORD_HASHES:
        errors.append('mixed vision input must match an explicitly reviewed record hash')
    return errors

def evidence(record,block=None,selector=None):
    if block is not None:
        return {'kind':'block','ref':block['block_id'],'quote':block['text'],'loc':block['loc']}
    return {'kind':'source','ref':selector,'quote':record['source'][selector],'loc':None}

def extract(record,reference):
    problems=input_errors(record)
    if problems: raise ValueError('; '.join(problems[:4]))
    blocks=[b for b in sorted(record['blocks'],key=lambda b:b['order'])
            if b['text'].strip() and b['type'] not in ('table','slide') and not b['content_refs']]
    line_items=[(b,line) for b in blocks for line in b['text'].splitlines() if line.strip()]
    pending=[u for u in record['coverage']['units'] if u['required'] and u['status']!='completed']
    if any(u['unit_id'].startswith('native:') for u in pending):
        raise ValueError('native parsing must finish before native enrichment')
    visual=[u for u in pending if u['unit_id'].startswith('vision:')]
    candidates={f:[] for f in ALL_FIELDS}; invalid={f:[] for f in ALL_FIELDS}
    def add(field,value,rule,ev):
        if value is None or not str(value).strip():return
        value=unicodedata.normalize('NFC',str(value)).strip()
        entry={'value':value,'rule_id':rule,'evidence':[ev] if isinstance(ev,dict) else ev}
        if entry not in candidates[field]:candidates[field].append(entry)
    def date_match(field,match,rule,ev):
        try:add(field,dated(match),rule,ev)
        except ValueError:invalid[field].append('invalid calendar date')
    def chosen(field):
        vals={c['value'] for c in candidates[field]}
        return next(iter(vals)) if len(vals)==1 and not invalid[field] else None
    name=record['source']['file_name']; kind=record['source']['format']
    nameev=evidence(record,selector='file_name')
    path=record['source']['relative_path']; pathev=evidence(record,selector='relative_path')
    initial=blocks[:8]
    # Classify explicit titles rather than incidental references in the body.
    if kind=='log':add('문서종류','실행 로그','type.log_extension',nameev)
    if kind=='txt':
        if any('[정기점검 결과 보고]' in b['text'] for b in initial):
            b=next(b for b in initial if '[정기점검 결과 보고]' in b['text'])
            add('문서종류','실행 로그','type.inspection_report',evidence(record,b))
        elif (any(re.match(r'(From:|\d{4}-\d{2}-\d{2} 고객 통화 메모)',b['text']) for b in initial)
              or re.search(r'(?:메모|메일|memo|email)(?=[_.\s(]|$)',name,re.I)
              or (blocks and re.search(r'(?:메모|메일|memo|email)\s*$',blocks[0]['text'].splitlines()[0],re.I))):
            add('문서종류','기타','type.correspondence',evidence(record,initial[0]) if initial else nameev)
    if kind not in ('log','txt'):
        for label,pattern in [('계약서',r'(?:^|[_\s])계약서(?=[_.\s(]|$)'),
                              ('견적서',r'(?:^|[_\s])견적서(?=[_.\s(]|$)'),
                              ('제안서',r'(?:^|[_\s])제안서(?=[_.\s(]|$)'),
                              ('네트워크 구성도',r'네트워크\s*구성도|network_diagram'),
                              ('서버 구성도',r'서버\s*구성|server_architecture')]:
            if re.search(pattern,name,re.I):add('문서종류',label,'type.filename',nameev)
        for b in initial:
            text=b['text'].strip()
            for label,pattern in [('계약서',r'^.{0,160}\s계약서$|^계약서$'),
                                  ('견적서',r'^견\s*적\s*서$'),('제안서',r'^제안서$'),
                                  ('네트워크 구성도',r'^.{0,120}네트워크\s*구성도(?:\s*\(Rev\..*\))?$'),
                                  ('서버 구성도',r'^.{0,120}서버\s*구성\s*(?:현황|도)\s*$')]:
                if re.search(pattern,text,re.I):add('문서종류',label,'type.native_title',evidence(record,b))
    doc_type=chosen('문서종류')
    for status in ('초안','최종','서명본'):
        if re.search(r'(?<![가-힣])'+status+r'(?![가-힣])',name):add('상태',status,'status.filename_marker',nameev)
        for b in initial:
            if re.search(r'^\s*(?:【|문서\s*상태\s*:)\s*'+status+r'(?![가-힣])',b['text']):
                add('상태',status,'status.explicit_banner',evidence(record,b))

    # Exact folder/party aliases. Do not infer a client from IP ranges or host prefixes.
    parts=path.split('/'); folder=None
    if 'Shared Documents' in parts:
        i=parts.index('Shared Documents')+1
        if i<len(parts):folder=parts[i]
    for client in reference['clients']:
        aliases=sorted(set([client['name'],client['folder']]+client['aliases']),key=len,reverse=True)
        if any(squash(part).casefold()==squash(a).casefold() for part in parts[:-1] for a in aliases):
            add('거래처',client['name'],'client.folder_alias',pathev)
        for b,t in line_items:
            party=(re.match(r'^\s*(수신|고객사|고객|거래처|발주처|Client|Customer)\s*[:\t ]',t,re.I) or '귀중' in t
                   or re.search(r'이하\s*["“]갑',t))
            if not party:continue
            # Match before the supplier/contract body, not every company mentioned.
            segment=re.split(r'귀중|이하\s*["“]갑',t)[0]
            for alias in aliases:
                if re.search(r'(?<![A-Za-z0-9가-힣])'+re.escape(alias)+r'(?![A-Za-z0-9가-힣])',segment,re.I):
                    add('거래처',client['name'],'client.explicit_party_alias',evidence(record,b));break

    system_sources=[]
    for b,t in line_items:
        m=re.search(r'(?:Target\s*system|대상\s*시스템|\bsystem)\s*:\s*([^/|\t\n]+)',t,re.I)
        if m:system_sources.append((m[1].strip(),evidence(record,b),'system.explicit_label'))
    if not system_sources:
        system_sources=[(name,nameev,'system.filename_term')]
        # Native first title, rather than all body text (which may name other systems).
        if blocks and kind not in ('log','txt'):
            first=next((b for b in initial if not b['text'].startswith('【')),blocks[0])
            system_sources.append((first['text'],evidence(record,first),'system.title_term'))
        for b,t in line_items:
            if re.match(r'^(건명|관련 사업)\s*[:\t ]',t):
                system_sources.append((t,evidence(record,b),'system.named_project'))
    for text,ev,rule in system_sources:
        for term in reference['system_terms']:
            if re.search(r'(?<![A-Za-z0-9가-힣])'+re.escape(term)+r'(?![A-Za-z0-9가-힣])',text,re.I):
                add('대상시스템',term,rule,ev)

    money_sources=[]
    # Native TXT paragraphs can contain several labelled lines; the original block
    # remains the citation owner even when a rule examines one line at a time.
    for b,t in line_items:
        ev=evidence(record,b)
        for field,pattern in [('계약번호',r'계약\s*번호\s*[:\t ]+\s*([A-Z0-9]+(?:[-_/][A-Z0-9]+)+)\b'),
                              ('견적번호',r'견적\s*(?:번호\s*[:\t ]+|\(\s*)([A-Z0-9]+(?:[-_/][A-Z0-9]+)+)\b')]:
            for m in re.finditer(pattern,t,re.I):
                if len(m[1])<=80 and re.search(r'\d',m[1]):add(field,m[1],'identifier.explicit_context',ev)
        for m in re.finditer(r'(견적일자|작성일|문서일자|^Date)\s*[:\t ]+\s*('+DATE+')',t,re.I):
            date_match('문서일자',re.search(DATE,m[2]),'date.explicit_label',ev)
        if doc_type=='제안서' and (b['loc'].get('slide')==1 or b['loc'].get('page')==1):
            m=re.match(r'^\s*(?:(?:표지\s*(?:일자|날짜|일))\s*:\s*)?'+DATE+r'\s*(?:\||$)',t) if b['type']!='table_row' else None
            if m:date_match('문서일자',m,'date.proposal_cover',ev)
        if doc_type=='서버 구성도' and '사업:' in t and '설치 위치:' in t:
            m=re.search(r'\|\s*'+DATE+r'\s*$',t)
            if m:date_match('문서일자',m,'date.diagram_header',ev)
        if doc_type=='계약서':
            m=re.match(r'^\s*(?:체결부|날인부)\s*인쇄\s*(?:날짜|일자)\s*:\s*'+DATE,t)
            if m:
                date_match('문서일자',m,'date.contract_signing_block',ev)
                if chosen('상태')=='초안':invalid['문서일자'].append('draft printed date does not establish document creation date')
            if re.fullmatch(r'\s*'+DATE+r'\s*',t):
                # A standalone date near the signing block, not a date range in the body.
                following=[x for x in blocks if b['order']<x['order']<=b['order']+3]
                if any(x['type']=='table_row' and re.search(r'갑\s+을',x['text']) for x in following):
                    date_match('문서일자',re.search(DATE,t),'date.contract_signing_block',ev)
                    if chosen('상태')=='초안':
                        invalid['문서일자'].append('draft signing-block date may be planned signing date, not document creation date')
            if '계약' in t and ('기간은' in squash(t) or '계약기간:' in squash(t)):
                dates=list(re.finditer(DATE,t))
                if len(dates)==2:
                    try:
                        start,end=map(dated,dates)
                        if start>end:raise ValueError('reversed contract period')
                        add('계약시작일',start,'contract.explicit_period',ev)
                        add('계약종료일',end,'contract.explicit_period',ev)
                    except ValueError:
                        invalid['계약시작일'].append('invalid/reversed contract period')
                        invalid['계약종료일'].append('invalid/reversed contract period')
            m=re.search(r'계약\s*유형\s*[:\t ]+\s*(용역|유지보수|구매|라이선스|NDA|기타)(?![가-힣])',t)
            if m:add('계약유형',m[1],'contract.explicit_type',ev)
        if doc_type in ('계약서','견적서','제안서') and re.search(r'(?:계약|견적|제안)\s*금액\s*(?:은|:)',t):
            amounts=list(re.finditer(r'(₩|￦|KRW|USD|EUR|JPY)\s*([0-9]+(?:,[0-9]{3})*)(?!\d|[,.]\d)',t))
            if len(amounts)==1:
                m=amounts[0]; amount=m[2].replace(',','')
                add('금액',amount,'amount.labelled_representative',ev)
                add('통화',{'₩':'KRW','￦':'KRW'}.get(m[1],m[1]),'currency.same_amount_span',ev)
                money_sources.append((t,ev))
            else:invalid['금액'].append('representative amount is unsupported or ambiguous')
        # A two-cell key/value row is distinct from a quantity/unit-price line item.
        if doc_type in ('계약서','견적서','제안서') and b['type']=='table_row':
            cells=[cell.strip() for cell in t.split('\t') if cell.strip()]
            if len(cells)==2:
                label,value=cells;label=squash(label)
                if re.fullmatch(r'(?:계약|견적|제안)금액',label):
                    m=re.fullmatch(r'(?:(KRW|USD|EUR|JPY|₩|￦)\s*)?(\d+(?:,\d{3})*)(?:\s*원)?',value)
                    if m:
                        add('금액',m[2].replace(',',''),'amount.labelled_table_value',ev)
                        if m[1]:add('통화',{'₩':'KRW','￦':'KRW'}.get(m[1],m[1]),'currency.labelled_table_value',ev)
                if label in ('통화','Currency') and value in ('KRW','USD','EUR','JPY'):add('통화',value,'currency.explicit_table_label',ev)
                if label in ('VAT','부가세','부가가치세') and value in ('별도','포함'):add('VAT',value,'vat.explicit_table_label',ev)
        if doc_type=='견적서':
            m=re.search(r'유효기간\s*[:\t ]+\s*'+DATE,t)
            if m:date_match('견적유효기간',m,'quote.explicit_valid_until',ev)
        m=re.search(r'설치\s*위치\s*:\s*(.*?)(?=\s*\||\s+작성일\s*:|\t|$)',t)
        if m and doc_type in ('네트워크 구성도','서버 구성도'):
            add('사이트',m[1],'site.explicit_location',ev)
        for pattern in [r'^(?:건명|관련 사업)\s*[:\t ]+\s*(.+)',r'「([^」]+)」\s*\(이하\s*"본 사업"']:
            m=re.search(pattern,t)
            if m:add('사업명',m[1],'project.explicit_name',ev)
        if kind=='txt':
            m=re.match(r'^'+DATE+r'\s+고객 통화 메모',t)
            if m:date_match('문서일자',m,'date.memo_header',ev)
            if '[정기점검 결과 보고]' in t:
                add('작업명','정기점검','job.inspection_heading',ev)
            if re.match(r'점검일시\s*:',t):
                stamps=[m[0] for m in re.finditer(STAMP,t)]
                if len(stamps)==2:
                    try:
                        start,end=map(timestamp,stamps)
                        if start>end:raise ValueError('reversed inspection interval')
                        add('로그시작',start,'time.inspection_interval',ev)
                        add('로그종료',end,'time.inspection_interval',ev)
                        add('문서일자',start[:10],'date.inspection',ev)
                    except ValueError:invalid['로그시작'].append('invalid inspection interval')
            m=re.match(r'종합 결과\s*:\s*(성공|실패|경고)(?![가-힣])',t)
            if m:add('실행결과',m[1],'result.explicit_inspection',ev)
        if kind=='log':
            for pattern in [r'Job name\s*:\s*(\S+)',r'Job:\s*\[([^\]]+)\]',r'\btarget:\s*([^/]+)\s*/',r'^\s*(?:작업\s*명|job_name)\s*[:=]\s*([^\t|]+?)\s*$']:
                m=re.search(pattern,t,re.I)
                if m:add('작업명',m[1],'job.explicit_label',ev)
            try:ts=timestamp(t)
            except ValueError:ts=None;invalid['로그시작'].append('invalid log timestamp')
            if ts and re.search(r'\bJob\s+\S+\s+started\b|\bJob:\s*\[[^\]]+\]\s+launched with parameters\b|deploy\.sh start|작업\s*시작(?=\s|$)',t,re.I):
                add('로그시작',ts,'time.explicit_start',ev)
                add('문서일자',ts[:10],'date.log_start',ev)
            result=re.search(r'(?:Result:\s*|deploy finished:\s*|completed with the following status:\s*\[|작업\s*(?:종료|완료)\s+result\s*=\s*)(COMPLETED_WITH_WARNINGS|SUCCESS|FAILED|FAILURE|COMPLETED|WARNING|WARNINGS)\b',t,re.I)
            if result:
                value={'SUCCESS':'성공','COMPLETED':'성공','FAILED':'실패','FAILURE':'실패','WARNING':'경고','WARNINGS':'경고','COMPLETED_WITH_WARNINGS':'경고'}[result[1].upper()]
                add('실행결과',value,'result.explicit_terminal',ev)
                if ts:add('로그종료',ts,'time.explicit_terminal',ev)
        if (kind=='log' and re.search(r'\b(?:ERROR|WARN)\b',t)) or (kind=='txt' and re.search(r'실패|오류|경고|ERROR|WARN',t)):
            for m in re.finditer(ERROR,t):add('오류코드',m[0],'error.explicit_error_context',ev)
            for m in re.finditer(r'(?:\bcode\s*=|오류\s*코드\s*[:=]?)\s*([A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+)\b',t,re.I):
                if re.search(r'\d',m[1]):add('오류코드',m[1],'error.explicit_code_label',ev)
    for text,ev in money_sources:
        for m in re.finditer(r'(?:VAT|부가가치세|부가세)\s*(포함|별도)',text,re.I):
            add('VAT',m[1],'vat.same_representative_amount',ev)

    if chosen('로그시작') and chosen('로그종료') and chosen('로그시작')>chosen('로그종료'):
        invalid['로그시작'].append('log end precedes start')
        invalid['로그종료'].append('log end precedes start')

    fields={}
    for field in ALL_FIELDS:
        cs=candidates[field];values={c['value'] for c in cs}
        if len(values)==1 and not invalid[field]:
            evs=[]
            for c in cs:
                for ev in c['evidence']:
                    if ev not in evs:evs.append(ev)
            fields[field]={'value':next(iter(values)),'status':'extracted','rule_id':'+'.join(sorted({c['rule_id'] for c in cs})),
                           'evidence':evs,'candidates':[],'reason':None}
        else:
            conflict=bool(invalid[field] or len(values)>1)
            outside=doc_type is not None and field in FIELD_SCOPE and doc_type not in FIELD_SCOPE[field]
            status='needs_review' if conflict else 'not_applicable' if outside else 'pending_vision' if visual else 'not_found_text'
            reason='; '.join(invalid[field]) if invalid[field] else 'conflicting explicit candidates' if conflict else (
                'field is outside the declared metadata scope for this document type; not a claim of source absence' if outside else
                'unresolved with native rules; visual units remain unprocessed' if visual else 'no supported unambiguous value in reviewed literal scope')
            if field=='계약유형' and doc_type=='계약서' and not conflict:
                reason+='; contract type is not inferred from the project name'
            fields[field]={'value':None,'status':status,'rule_id':None,'evidence':[],'candidates':cs,'reason':reason}
    return {'schema_version':'1.0.0','record_kind':'enrichment_result','doc_id':record['doc_id'],
            'source':record['source'],'input_record_sha256':record_hash(record),'rules_version':VERSION,
            'scope':'reviewed_literals_and_source_metadata','model_called':False,'status':'partial',
            'source_text_present':bool(blocks),'fields':fields,
            'pending_visual_units':[{'unit_id':u['unit_id'],'loc':u['loc'],'reason':u['reason']} for u in visual],
            'deferred':{'summary':'not_run','family':'not_run','latest_version':'not_run','vision':'pending' if visual else 'not_required_by_parser'}}

def schema():
    ev={'type':'object','additionalProperties':False,'required':['kind','ref','quote','loc'],'properties':{
        'kind':{'enum':['block','source']},'ref':{'type':'string','minLength':1},'quote':{'type':'string','minLength':1},
        'loc':{'type':['object','null']}}}
    candidate={'type':'object','additionalProperties':False,'required':['value','rule_id','evidence'],'properties':{
        'value':{'type':'string','minLength':1},'rule_id':{'type':'string','minLength':1},'evidence':{'type':'array','minItems':1,'items':ev}}}
    field={'type':'object','additionalProperties':False,'required':['value','status','rule_id','evidence','candidates','reason'],
        'properties':{'value':{'type':['string','null']},'status':{'enum':STATUSES},'rule_id':{'type':['string','null']},
        'evidence':{'type':'array','items':ev},'candidates':{'type':'array','items':candidate},'reason':{'type':['string','null']}},
        'allOf':[{'if':{'properties':{'status':{'const':'extracted'}}},'then':{'properties':{
            'value':{'type':'string','minLength':1},'rule_id':{'type':'string','minLength':1},'evidence':{'minItems':1},'candidates':{'maxItems':0},'reason':{'const':None}}},
            'else':{'properties':{'value':{'const':None},'rule_id':{'const':None},'evidence':{'maxItems':0},'reason':{'type':'string','minLength':1}}}}]}
    props={'schema_version':{'const':'1.0.0'},'record_kind':{'const':'enrichment_result'},'doc_id':{'type':'string','minLength':1},
           'source':{'type':'object'},'input_record_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'},'rules_version':{'const':VERSION},
           'scope':{'const':'reviewed_literals_and_source_metadata'},'model_called':{'const':False},'status':{'const':'partial'},
           'source_text_present':{'type':'boolean'},'fields':{'type':'object','required':ALL_FIELDS,'additionalProperties':False,'properties':{f:field for f in ALL_FIELDS}},
           'pending_visual_units':{'type':'array','items':{'type':'object','required':['unit_id','loc','reason'],'additionalProperties':False,
               'properties':{'unit_id':{'type':'string'},'loc':{'type':'object'},'reason':{'type':['string','null']}}}},
           'deferred':{'type':'object','additionalProperties':False,'required':['summary','family','latest_version','vision'],'properties':{
               'summary':{'const':'not_run'},'family':{'const':'not_run'},'latest_version':{'const':'not_run'},'vision':{'enum':['pending','not_required_by_parser']}}}}
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','title':'Native enrichment result 1.0.0','type':'object',
            'required':list(props),'properties':props,'additionalProperties':False}

def check_output(output,record):
    from jsonschema import Draft202012Validator
    errors=[e.message for e in Draft202012Validator(schema()).iter_errors(output)]
    if errors:return errors
    if output['doc_id']!=record['doc_id'] or output['source']!=record['source'] or output['input_record_sha256']!=record_hash(record):
        errors.append('source/input identity mismatch')
    blocks={b['block_id']:b for b in record['blocks']}
    for name,field in output['fields'].items():
        if field['status']=='pending_vision' and not output['pending_visual_units']:errors.append('vision pending without source unit')
        if field['status']=='not_applicable':
            doc_type=output['fields']['문서종류']['value']
            if doc_type is None or name not in FIELD_SCOPE or doc_type in FIELD_SCOPE[name]:errors.append('incorrect field applicability')
        items=[field]+field['candidates']
        for item in items:
            for ev in item['evidence']:
                if ev['kind']=='source':
                    if ev['ref'] not in ('file_name','relative_path') or ev['quote']!=record['source'].get(ev['ref']) or ev['loc'] is not None:
                        errors.append('invalid source evidence')
                else:
                    b=blocks.get(ev['ref'])
                    if b is None or ev['quote']!=b['text'] or ev['loc']!=b['loc'] or b['content_refs']:
                        errors.append('invalid block evidence')
        v=field['value']
        if v is None:continue
        try:
            if name in ('문서일자','계약시작일','계약종료일','견적유효기간'):
                if date.fromisoformat(v).isoformat()!=v:raise ValueError()
            if name in ('로그시작','로그종료'):
                if datetime.strptime(v,'%Y-%m-%d %H:%M').strftime('%Y-%m-%d %H:%M')!=v:raise ValueError()
            if name=='금액' and not re.fullmatch(r'\d+',v):raise ValueError()
        except ValueError:errors.append(f'invalid normalized {name}')
    expected=[{'unit_id':u['unit_id'],'loc':u['loc'],'reason':u['reason']} for u in record['coverage']['units']
              if u['required'] and u['status']!='completed' and u['unit_id'].startswith('vision:')]
    if output['pending_visual_units']!=expected:errors.append('visual queue mismatch')
    if output['source_text_present']!=any(b['text'].strip() and b['type'] not in ('table','slide') and not b['content_refs'] for b in record['blocks']):
        errors.append('native text coverage mismatch')
    return errors

def run(args):
    out=Path(args.output)
    if out.exists():raise ValueError('output must be a new directory')
    records=read_lines(args.parsed);reference=read_json(args.reference)
    if len({r['doc_id'] for r in records})!=len(records):raise ValueError('duplicate input doc_id')
    outputs=[]
    for r in records:
        enriched=extract(r,reference);errors=check_output(enriched,r)
        if errors:raise ValueError(r['doc_id']+': '+'; '.join(errors))
        outputs.append(enriched)
    out.mkdir(parents=True)
    save_lines(out/'enriched.jsonl',outputs)
    queue=[{'doc_id':r['doc_id'],'field':f,'status':v['status'],'reason':v['reason'],
            'pending_visual_unit_ids':[u['unit_id'] for u in r['pending_visual_units']] if v['status']=='pending_vision' else []}
           for r in outputs for f,v in r['fields'].items() if v['status']!='extracted']
    save_lines(out/'pending-fields.jsonl',queue)
    dump(out/'provenance.json',{'measured_at_utc':datetime.now(timezone.utc).isoformat(),'rules_version':VERSION,'model_called':False,
        'network_calls':0,'input_documents':len(records),'parsed_path':str(Path(args.parsed).resolve()),'parsed_sha256':digest(args.parsed),
        'reference_path':str(Path(args.reference).resolve()),'reference_sha256':digest(args.reference),'reference_origin':reference['provenance'],
        'code_sha256':digest(__file__),'contract_sha256':digest(ROOT/'CONTRACT.md'),'schema_sha256':record_hash(schema()),
        'output_sha256':digest(out/'enriched.jsonl'),'scored_field_status_counts':dict(Counter(v['status'] for r in outputs for f,v in r['fields'].items() if f in FIELDS)),
        'gold_labels_read_by_extractor':False,'source_documents_modified':False})
    print(json.dumps({'documents':len(outputs),'fields':len(outputs)*len(FIELDS),'output':str(out)},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parsed',required=True);parser.add_argument('--reference',required=True);parser.add_argument('--output',required=True)
    run(parser.parse_args())
