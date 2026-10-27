"""Source-backed rules for added formats. No query labels or answer IDs."""
import re
from datetime import datetime
from common import *
sys.path.insert(0,str(ROOT/'deploy/rag_app'))
import runtime
E=runtime.E;d=runtime.d
# Validation extension is explicit; existing structural/reference checks still run.
E.previous._validation=P.validation
runtime.common.VALIDATOR=validator
BASE_EXTRACT=E.extract
def extract(record,reference):
 E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(record))
 m=BASE_EXTRACT(record,reference);fields=m['fields'];fmt=record['source']['format'];name=record['source']['file_name']
 blocks=[b for b in record['blocks'] if b['text'].strip() and not b['content_refs'] and b['type'] not in ['slide','table']]
 def put(field,value,rule,block=None,source=None):
  if not value:return
  ev=E.evidence(record,block) if block else E.evidence(record,selector=source or 'file_name')
  old=fields[field]
  if old['status']=='extracted' and old['value']!=value:
   fields[field]={'value':None,'status':'needs_review','rule_id':None,'evidence':[],'candidates':[{'value':old['value'],'rule_id':old['rule_id'],'evidence':old['evidence']},{'value':value,'rule_id':rule,'evidence':[ev]}],'reason':'conflicting source-backed values'}
  elif old['status']!='needs_review':fields[field]={'value':value,'status':'extracted','rule_id':rule,'evidence':[ev],'candidates':[],'reason':None}
 if fields['문서종류']['status']!='extracted':
  typ=None
  if fmt in ['ini','rtf','no_extension','yaml','json','xml','jmx']:typ='장비 설정'
  elif re.search(r'메모|질의|답변',name) or fmt=='html':typ='기타'
  elif re.search(r'아키텍처.*정의서|설계서|구조 설명|사양.*산정서',name):typ='설계서'
  elif '제안요청서' in name:typ='제안요청서'
  elif '발주서' in name:typ='발주서'
  elif '검수확인서' in name:typ='검수확인서'
  elif '착수보고' in name:typ='착수보고서'
  elif fmt=='csv':typ='테스트 결과'
  elif re.search(r'물품목록|IP 할당표|이관대상',name):typ='장비 목록'
  elif re.search(r'솔루션 소개',name):typ='매뉴얼·교육자료'
  elif fmt in ['jpg','png']:typ='사진·캡처'
  elif re.search(r'매뉴얼|교육|실습교재|가이드|점검 절차',name):typ='매뉴얼·교육자료'
  elif '납품확인서' in name:typ='납품확인서'
  elif '설치완료보고서' in name:typ='설치완료보고서'
  elif re.search(r'선번장|장비 리스트|도입물품',name):typ='장비 목록'
  if typ:put('문서종류',typ,'v2.type.explicit_name_or_format')
 for b in blocks:
  for line in b['text'].splitlines():
   hit=re.search(r'계약(?:구분|유형)\s*:\s*(용역|유지보수|구매|라이선스)(?![가-힣])',line)
   if hit:put('계약유형',hit[1],'v2.contract.explicit_category',b)
   hit=re.match(r'사\s*업\s*명\s*:\s*(.+)',line)
   if hit:put('사업명',hit[1].strip(),'v2.project.explicit_label',b)
   # Session timestamp is not an authored date or the time a later command ran.
   hit=re.match(r'=~=~=~ PuTTY log (\d{4})\.(\d{2})\.(\d{2}) (\d{2}:\d{2}):\d{2}',line)
   if hit:
    stamp=f'{hit[1]}-{hit[2]}-{hit[3]} {hit[4]}';datetime.strptime(stamp,'%Y-%m-%d %H:%M')
    put('로그시작',stamp,'v2.log.session_header',b)
    # Representative date is supported by the explicit source session header.
    put('문서일자',stamp[:10],'date.log_start',b)
    m['date_context']['observations'].append({'role':'execution_start_date','value':stamp[:10],'rule_id':'date.log_start','evidence':[E.evidence(record,b)],'assertion':'source_statement_only'})
    m['date_context'].update(selected_roles=['execution_start_date'],selection_reason='explicit_session_start')
 # Scope statuses must reflect the selected type, not an earlier unknown type.
 typ=fields['문서종류']['value']
 for f,v in fields.items():
  if v['status'] in ['not_found_text','pending_vision'] and typ is not None and f in E.FIELD_SCOPE and typ not in E.FIELD_SCOPE[f]:
   v.update(status='not_applicable',reason='outside metadata scope for this document type')
 assert not E.check_output(m,record),(record['doc_id'],E.check_output(m,record))
 return m
