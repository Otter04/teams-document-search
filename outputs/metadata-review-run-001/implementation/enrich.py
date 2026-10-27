"""Native enrichment with explicit date roles; no gold, generator or model access."""
import copy,importlib.util,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('legacy_native_enrichment',ROOT.parent/'rag-enrichment-v1/enrich.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
for name in ('FIELDS','ALL_FIELDS','STATUSES','FIELD_SCOPE','DATE','STAMP','ERROR','digest','canonical','record_hash','dump','save_lines','read_json','read_lines','squash','dated','timestamp','input_errors','evidence'):
 globals()[name]=getattr(previous,name)
VERSION='rules-0.2.0'
DATE_ROLES={'date.proposal_cover':'cover_date','date.diagram_header':'diagram_header_date',
 'date.memo_header':'memo_date','date.log_start':'execution_start_date','date.inspection':'inspection_date',
 'date.contract_signing_block':'signing_block_printed_date'}
LABEL_ROLES={'문서작성일':'explicit_written_date','작성일':'explicit_written_date','문서일자':'explicit_document_date','견적일자':'quote_date','date':'email_sent_date'}
EXPLICIT=re.compile(r'^\s*(문서\s*작성일|작성일|문서일자|견적일자|Date)\s*[:\t ]+\s*('+DATE+')',re.I)

def field_value(candidates,reason=None):
 values={v['value'] for v in candidates}
 if len(values)==1 and reason is None:
  evs=[]
  for c in candidates:
   for e in c['evidence']:
    if e not in evs:evs.append(e)
  return {'value':next(iter(values)),'status':'extracted','rule_id':'+'.join(sorted({c['rule_id'] for c in candidates})), 'evidence':evs,'candidates':[],'reason':None}
 return {'value':None,'status':'needs_review','rule_id':None,'evidence':[],'candidates':candidates,'reason':reason or 'conflicting explicit candidates with the same selected date role'}

def dates(record,result):
 old=result['fields']['문서일자'];observations=[];invalid=[]
 def add(role,value,rule,ev):
  item={'role':role,'value':value,'rule_id':rule,'evidence':ev,'assertion':'source_statement_only'}
  if item not in observations:observations.append(item)
 # Preserve established, source-backed non-label date patterns from v1.
 candidates=[old] if old['status']=='extracted' else old['candidates']
 for c in candidates:
  for rule in c['rule_id'].split('+'):
   if rule in DATE_ROLES:add(DATE_ROLES[rule],c['value'],rule,c['evidence'])
 blocks=[b for b in record['blocks'] if b['type'] not in ('slide','table') and not b['content_refs'] and b['text'].strip()]
 first=next(iter(sorted(blocks,key=lambda b:b['order'])),None)
 for block in blocks:
  for line in block['text'].splitlines():
   match=EXPLICIT.match(line)
   if not match:continue
   role=LABEL_ROLES[re.sub(r'\s+','',match[1]).casefold()]
   if role=='email_sent_date' and (record['source']['format']!='txt' or block is not first or not re.match(r'^From:',block['text'],re.I)):continue
   try:value=dated(re.search(DATE,match[2]))
   except ValueError:invalid.append('invalid explicit document date');continue
   add(role,value,'date.role.'+role,[evidence(record,block)])
 for field,role in [('계약시작일','contract_period_start'),('계약종료일','contract_period_end')]:
  f=result['fields'][field]
  if f['status']=='extracted':add(role,f['value'],f['rule_id'],f['evidence'])
 primary=[o for o in observations if o['role'] in LABEL_ROLES.values()]
 fallback=[o for o in observations if o['role'] in DATE_ROLES.values()]
 selected=primary or fallback
 draft=result['fields']['상태']['value']=='초안'
 if primary:reason='explicit_document_date_precedes_other_date_roles'
 elif draft and any(o['role']=='signing_block_printed_date' for o in fallback):reason='draft_signing_date_does_not_establish_document_date'
 else:reason='source_specific_representative_date' if fallback else 'no_supported_document_date'
 if selected or invalid:
  cs=[{'value':o['value'],'rule_id':o['rule_id'],'evidence':o['evidence']} for o in selected]
  conflict='; '.join(invalid) if invalid else reason if reason=='draft_signing_date_does_not_establish_document_date' else None
  result['fields']['문서일자']=field_value(cs,conflict)
 elif old['status']=='extracted' and old['rule_id']=='date.explicit_label':
  # Reject a label embedded in prose or an old forwarded header.
  result['fields']['문서일자']=field_value([], 'date label is outside supported document/header context')
 chosen=result['fields']['문서일자']
 result['date_context']={'observations':observations,'selected_roles':sorted({o['role'] for o in selected}) if chosen['status']=='extracted' else [],'selection_reason':reason,'actual_signature_verified':False}

def mail_system(record,result,reference):
 field=result['fields']['대상시스템']
 if 'system.explicit_label' in (field['rule_id'] or ''):return
 blocks=sorted((b for b in record['blocks'] if b['text'].strip() and b['type'] not in ('slide','table') and not b['content_refs']),key=lambda b:b['order'])
 if record['source']['format']!='txt' or not blocks or not re.match(r'^From:',blocks[0]['text'],re.I):return
 candidates=copy.deepcopy([field] if field['status']=='extracted' else field['candidates'])
 candidates=[{k:c[k] for k in ('value','rule_id','evidence')} for c in candidates]
 added=False
 for line in blocks[0]['text'].splitlines():
  if not re.match(r'^Subject\s*:',line,re.I):continue
  for term in reference['system_terms']:
   if re.search(r'(?<![A-Za-z0-9가-힣])'+re.escape(term)+r'(?![A-Za-z0-9가-힣])',line,re.I):
    candidates.append({'value':term,'rule_id':'system.mail_subject','evidence':[evidence(record,blocks[0])]});added=True
 if added:result['fields']['대상시스템']=field_value(candidates,'conflicting filename and current mail subject systems' if len({c['value'] for c in candidates})>1 else None)

def extract(record,reference):
 result=previous.extract(record,reference)
 dates(record,result);mail_system(record,result,reference)
 result.update(schema_version='1.1.0',rules_version=VERSION)
 return result

def schema():
 s=previous.schema();s['title']='Native enrichment with date roles 1.1.0'
 s['properties']['schema_version']={'const':'1.1.0'};s['properties']['rules_version']={'const':VERSION}
 ev=s['properties']['fields']['properties']['문서일자']['properties']['evidence']
 observation={'type':'object','additionalProperties':False,'required':['role','value','rule_id','evidence','assertion'],'properties':{
  'role':{'enum':sorted(set(DATE_ROLES.values())|set(LABEL_ROLES.values())|{'contract_period_start','contract_period_end'})},
  'value':{'type':'string','pattern':r'^\d{4}-\d{2}-\d{2}$'},'rule_id':{'type':'string','minLength':1},'evidence':{**ev,'minItems':1},'assertion':{'const':'source_statement_only'}}}
 s['properties']['date_context']={'type':'object','additionalProperties':False,'required':['observations','selected_roles','selection_reason','actual_signature_verified'],'properties':{
  'observations':{'type':'array','items':observation},'selected_roles':{'type':'array','items':{'type':'string'},'uniqueItems':True},
  'selection_reason':{'type':'string','minLength':1},'actual_signature_verified':{'const':False}}}
 s['required'].append('date_context');return s

def check_output(output,record):
 from jsonschema import Draft202012Validator
 errors=[e.message for e in Draft202012Validator(schema()).iter_errors(output)]
 if errors:return errors
 compatible=copy.deepcopy(output);context=compatible.pop('date_context');compatible.update(schema_version='1.0.0',rules_version=previous.VERSION)
 errors+=previous.check_output(compatible,record)
 blocks={b['block_id']:b for b in record['blocks']}
 for o in context['observations']:
  try:previous.date.fromisoformat(o['value'])
  except ValueError:errors.append('invalid observed calendar date')
  for e in o['evidence']:
   b=blocks.get(e['ref'])
   if e['kind']!='block' or b is None or e['quote']!=b['text'] or e['loc']!=b['loc'] or b['content_refs']:errors.append('invalid observed date evidence')
   else:
    values=set()
    for m in re.finditer(DATE,e['quote']):
     try:values.add(dated(m))
     except ValueError:pass
    if o['value'] not in values:errors.append('observed date value is absent from cited block')
 field=output['fields']['문서일자']
 expected={o['role'] for o in context['observations'] if o['value']==field['value']} if field['status']=='extracted' else set()
 if not set(context['selected_roles'])<=expected:errors.append('selected date role/value mismatch')
 if field['status']=='extracted' and not context['selected_roles']:errors.append('missing selected date role')
 if output['fields']['상태']['value']=='초안' and 'signing_block_printed_date' in context['selected_roles']:errors.append('draft signing date cannot establish document date')
 return errors
