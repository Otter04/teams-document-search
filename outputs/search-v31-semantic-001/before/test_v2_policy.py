import copy,unittest
from unittest.mock import patch
from test_search import SearchContracts
from query import plan_rules,apply_mode
from engine import SearchEngine,CONFIG

class V2Policies(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  SearchContracts.setUpClass();cls.ref=SearchContracts.ref;cls.docs=SearchContracts.docs;cls.blocks=SearchContracts.blocks;cls.rows=SearchContracts.rows
 def plan(self,q):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),'B')
 def test_same_identifier_prefers_signed_without_overriding_explicit_draft(self):
  e=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[])
  rs=[{'source':next(c for c in self.rows if c['doc_id']==did),'chunk_id':did,'score':score} for did,score in [('D-005',1.),('D-006',.8)]]
  self.assertEqual(e.group(rs,self.plan('CT-2025-0112'))[0]['doc_id'],'D-006')
  self.assertEqual(e.group(rs,self.plan('CT-2025-0112 초안'))[0]['doc_id'],'D-005')
 def test_copy_resolution_requires_same_version_timestamp_and_name(self):
  docs=copy.deepcopy(self.docs);a=docs['D-075'];b=docs['D-076'];b['metadata']['file_modified_at']=a['metadata']['file_modified_at']
  e=SearchEngine(docs,self.blocks,self.ref,lambda q:[]);p=self.plan('온라인몰 제안서')
  self.assertEqual(e.clean_copy('D-076',['D-075','D-076'],p),'D-075')
  self.assertEqual(e.clean_copy('D-076',['D-075','D-076'],self.plan('제안서 복사본')),'D-076')
  b['metadata']['file_modified_at']='2030-01-01T00:00:00Z'
  self.assertEqual(e.clean_copy('D-076',['D-075','D-076'],p),'D-076')
 def test_duplicate_chunks_cannot_inflate_document_score(self):
  e=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[]);c=next(c for c in self.rows if c['doc_id']=='D-003')
  row={'source':c,'chunk_id':c['chunk_id'],'score':.6};p=self.plan('견적서')
  self.assertEqual(e.group([row],p)[0]['score'],e.group([row]*100,p)[0]['score'])
 def test_clean_name_cannot_override_a_requested_identifier(self):
  docs=copy.deepcopy(self.docs);a=docs['D-075'];b=docs['D-076'];b['metadata']['file_modified_at']=a['metadata']['file_modified_at']
  a['identifier_text']='QT-2030-1111';b['identifier_text']='QT-2030-2222'
  e=SearchEngine(docs,self.blocks,self.ref,lambda q:[])
  self.assertEqual(e.clean_copy('D-076',['D-075','D-076'],self.plan('QT-2030-2222')),'D-076')
 def test_expression_preference_requires_all_literal_groups(self):
  docs={};blocks={}
  for did,body in [('complete','hostname edge-l4\nslb virtual-server VS-ONE 192.0.2.8'),('partial','hostname edge-l4'),('wrongtype','slb virtual-server')]:
   docs[did]={'doc_id':did,'file_name':did,'family_id':did,'metadata':{'document_type':'기타' if did=='wrongtype' else '장비 설정'},'metadata_statuses':{'document_type':'extracted'}}
   blocks[did]={'b':{'text':body}}
  e=SearchEngine(docs,blocks,self.ref,lambda q:[]);p=self.plan('분산 장비의 가상 IP 설정')
  self.assertEqual(e.expression_preferences(p),['complete']);self.assertNotIn('client',p['filters'])
 def test_artifact_type_does_not_turn_generic_table_into_inventory(self):
  self.assertEqual(self.plan('장비 랙 위치 정리한 표')['conditions']['document_type'],'장비 목록')
  self.assertNotIn('document_type',self.plan('매출 정리한 표')['conditions'])
  self.assertEqual(self.plan('접속해서 실행한 명령 기록')['conditions']['document_type'],'실행 로그')
 def test_runtime_budget_is_passed_to_query_analyzer(self):
  e=SearchEngine({}, {},self.ref,lambda q:self.fail('should clarify'))
  def stop(p,*args,**kw):p['requires_clarification']=True;return p
  with patch('engine.conditional_llm',side_effect=stop) as call,patch.dict(CONFIG,{'llm_budget_seconds':12.}):
   e.search('서버 상태를 확인한 자료를 찾아줘');self.assertEqual(call.call_args.kwargs['timeout'],12.)
if __name__=='__main__':unittest.main()
