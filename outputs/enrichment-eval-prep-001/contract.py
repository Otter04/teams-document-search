"""Candidate contract and deterministic checks. No network or key handling."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from jsonschema import Draft202012Validator

FIELDS=['문서종류','거래처','문서일자','대상시스템','상태','계약번호','계약유형','계약시작일','계약종료일','금액','통화','VAT','견적번호','견적유효기간','사이트','작업명','로그시작','로그종료','실행결과','오류코드','사업명','표지일','작성일']
STATUSES=['extracted','needs_review','pending_vision','not_found_in_input','not_applicable']
CRITICAL={'문서일자','표지일','작성일','금액','통화','VAT','계약번호','견적번호','계약시작일','계약종료일','견적유효기간','로그시작','로그종료','실행결과'}

def unique(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('duplicate JSON key: '+k)
        d[k]=v
    return d

def loads(s):return json.loads(s,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON value')))
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(v):return hashlib.sha256(canonical(v).encode()).hexdigest()
def norm(v):return re.sub(r'\s+','',unicodedata.normalize('NFC',str(v)))
def obj(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}

def schema():
    text={'type':'string','minLength':1};nullable={'type':['string','null']}
    ev=obj({'kind':{'enum':['block','source']},'ref':text,'quote':text})
    evidences={'type':'array','items':ev}
    field=obj({'value':nullable,'status':{'enum':STATUSES},'evidence':evidences,'candidates':{'type':'array','items':obj({'value':text,'evidence':{**evidences,'minItems':1}})},'reason':nullable})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',**obj({'schema_version':{'const':'llm_enrichment_candidate_v1'},'doc_id':text,'fields':obj({f:field for f in FIELDS}),'summary':{'type':'array','maxItems':3,'items':obj({'text':text,'evidence':{**evidences,'minItems':1}})}})}

def evidence_errors(evs,packet):
    d=packet['document'];blocks={b['block_id']:b for b in d['blocks']};errors=[]
    for e in evs:
        if e['kind']=='block':
            b=blocks.get(e['ref']);source=b.get('text','') if b else None
        else:source=d['source'].get(e['ref'])
        if not isinstance(source,str) or norm(e['quote']) not in norm(source):errors.append('missing_reference_or_fabricated_quote:'+e['ref'])
    return errors

def validate(candidate,packet):
    errors=[str(e.message) for e in Draft202012Validator(schema()).iter_errors(candidate)]
    if errors:return errors
    if candidate['doc_id']!=packet['document']['doc_id']:errors.append('wrong_doc_id')
    pending=any(u['required'] and u['status']!='completed' for u in packet['document']['coverage']['units'])
    for name,f in candidate['fields'].items():
        if f['status']=='extracted':
            if f['value'] is None or not f['value'].strip() or not f['evidence'] or f['candidates'] or f['reason'] is not None:errors.append(name+':inconsistent_extracted')
            v=f['value'] or ''
            try:
                if name in ['문서일자','표지일','작성일','계약시작일','계약종료일','견적유효기간']:
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):raise ValueError()
                    datetime.strptime(v,'%Y-%m-%d')
                if name in ['로그시작','로그종료']:
                    if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}',v):raise ValueError()
                    datetime.strptime(v,'%Y-%m-%d %H:%M')
                if name=='금액' and not re.fullmatch(r'\d+',v):raise ValueError()
            except ValueError:errors.append(name+':invalid_value_format')
        elif f['value'] is not None or not f['reason'] or not f['reason'].strip():errors.append(name+':inconsistent_null_status')
        if f['status']=='pending_vision' and not pending:errors.append(name+':no_pending_visual_input')
        errors.extend(name+':'+x for x in evidence_errors(f['evidence'],packet))
        for c in f['candidates']:errors.extend(name+':'+x for x in evidence_errors(c['evidence'],packet))
    for s in candidate['summary']:errors.extend('summary:'+x for x in evidence_errors(s['evidence'],packet))
    return errors

def candidate_from_gold(gold):
    """Synthetic evaluator test fixture only; must never be passed off as a model response."""
    def ev(xs):return [{k:e[k] for k in ['kind','ref','quote']} for e in xs]
    return {'schema_version':'llm_enrichment_candidate_v1','doc_id':gold['doc_id'],'fields':{n:{'value':g['value'],'status':g['expected_status'],'evidence':ev(g['evidence']),'candidates':[],'reason':None if g['value'] is not None else g['reason']} for n,g in gold['fields'].items()},'summary':[]}

def value_visible(name,gold,quotes):
    rawtext=unicodedata.normalize('NFC',' '.join(quotes));text=norm(rawtext);value=gold['value']
    if value is None:return False
    if name in ['문서일자','표지일','작성일','계약시작일','계약종료일','견적유효기간']:
        y,m,d=value.split('-');return bool(re.search(r'(?<!\d)'+y+r'\s*(?:[-.]|년)\s*0?'+str(int(m))+r'\s*(?:[-.]|월)\s*0?'+str(int(d))+r'(?!\d)',rawtext))
    if name=='금액':return bool(re.search(r'(?<!\d)'+re.escape(value)+r'(?!\d)',text.replace(',','')))
    aliases=gold['accepted_values']
    if name=='통화' and value=='KRW':aliases=aliases+['₩','￦']
    if name=='문서종류' and value=='기타':aliases=aliases+['메모','메일']
    if name=='실행결과':aliases=aliases+({'성공':['SUCCESS'],'실패':['FAILED']}.get(value,[]))
    return any(norm(a) in text for a in aliases)

def score_fields(candidate,gold,packet,valid=True):
    results=[]
    for n,g in gold['fields'].items():
        p=candidate.get('fields',{}).get(n,{}) if candidate else {}
        value=p.get('value');filled=isinstance(value,str) and bool(value.strip())
        expected=g['value'] is not None and g['input_observable'];unknown=not g['value_scorable']
        value_match=filled and expected and norm(value) in {norm(v) for v in g['accepted_values']}
        evs=p.get('evidence',[]);evs=evs if isinstance(evs,list) else []
        supplied={(e.get('kind'),e.get('ref')) for e in evs if isinstance(e,dict)}
        # Alternative valid evidence remains reviewable; do not call it hallucinated solely for a different location.
        groups=g.get('evidence_alternatives',[g['evidence']])
        evidence_supported=valid and any(
            {(e['kind'],e['ref']) for e in group}<=supplied and
            value_visible(n,g,[e.get('quote','') for e in evs if isinstance(e,dict) and (e.get('kind'),e.get('ref')) in {(x['kind'],x['ref']) for x in group}])
            for group in groups)
        correct=bool(value_match and p.get('status')=='extracted' and evidence_supported)
        abstained=valid and value is None and p.get('status') in g['accepted_statuses']
        critical=bool(n in CRITICAL and filled and (not expected or not value_match))
        results.append({'field':n,'expected_value':g['value'],'predicted_value':value,'expected_value_observable':expected,'filled_scorable':filled and not unknown,'correct_supported_value':correct,'value_match':bool(value_match),'status_correct':p.get('status') in g['accepted_statuses'] if valid else False,'abstention_target':g['value'] is None and g['expected_status']!='not_applicable','correct_abstention':abstained,'critical_error':critical,'unsupported_assignment_to_unresolved':unknown and filled,'alternative_evidence_review':bool(value_match and valid and not evidence_supported),'not_applicable_target':g['expected_status']=='not_applicable'})
    return results

def metrics(items):
    counts={'correct':sum(x['correct_supported_value'] for x in items),'filled':sum(x['filled_scorable'] for x in items),'needed':sum(x['expected_value_observable'] for x in items),'abstention_targets':sum(x['abstention_target'] for x in items),'correct_abstentions':sum(x['correct_abstention'] and x['abstention_target'] for x in items),'critical_errors':sum(x['critical_error'] for x in items),'unresolved_assignments':sum(x['unsupported_assignment_to_unresolved'] for x in items),'alternative_evidence_pending':sum(x['alternative_evidence_review'] for x in items),'status_correct':sum(x['status_correct'] for x in items),'fields':len(items)}
    counts['precision']=counts['correct']/counts['filled'] if counts['filled'] else None
    counts['recall']=counts['correct']/counts['needed'] if counts['needed'] else None
    counts['abstention_accuracy']=counts['correct_abstentions']/counts['abstention_targets'] if counts['abstention_targets'] else None
    return counts
