import copy,json,unittest
from pathlib import Path
from query import plan_rules,apply_mode
from engine import SearchEngine
DATA=Path(__file__).resolve().parents[2]/'outputs/indexing-v31-001/search-data'
class DomainExpressions(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.ref=json.loads((DATA/'reference.json').read_text());cls.docs=json.loads((DATA/'documents.json').read_text());cls.blocks=json.loads((DATA/'blocks.json').read_text())
 def plan(self,q):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),'B')
 def groups(self,q):return [x for x in self.plan(q)['lexical_expansions'] if x.get('basis')=='compound_domain_vocabulary']
 def test_paraphrases_activate_only_conjunctive_subject_and_action(self):
  for q in ['저장 매체의 폐기 절차','SSD를 처분하는 방법','제안 심사 기술 점수 기준','품질 평가의 가중치 자료']:
   self.assertEqual(len(self.groups(q)),2,q)
  for q in ['저장장치 구매 견적','노후 장비 처분','투자 자산 처분 비중','서버 품질 측정','품질 비중 현황']:
   self.assertEqual(self.groups(q),[],q)
 def test_no_guessed_entity_or_score_and_explicit_date_is_locked(self):
  p=self.plan('2025년 저장장치 처분 지침')
  self.assertNotIn('client',p['conditions']);self.assertEqual(p['filters']['document_date'],{'gte':'2025-01-01','lte':'2025-12-31'})
  p=self.plan('공공기관의 기술 심사 비중')
  self.assertNotIn('client',p['conditions']);self.assertNotIn('80',str(p['lexical_expansions']))
 def test_reply_request_adds_response_evidence_not_questionnaire(self):
  p=self.plan('SSD 폐기 방법에 답해 준 자료')
  self.assertEqual(len(p['lexical_expansions']),3)
  self.assertEqual(p['lexical_expansions'][-1]['alternatives'],['답변','회신'])
  self.assertEqual(len(self.plan('SSD 폐기 방법을 물어본 자료')['lexical_expansions']),2)
 def test_preference_requires_both_concepts_in_actual_source(self):
  template=copy.deepcopy(self.docs['D-178']);docs={x:copy.deepcopy(template) for x in ['both','object_only','action_only']}
  blocks={d:{'b':{'text':t}} for d,t in [('both','디스크 물리 파쇄'),('object_only','디스크 구매'),('action_only','노후 장비 폐기')]}
  for d in docs:docs[d]['doc_id']=d;docs[d]['file_name']='안내.txt'
  e=SearchEngine(docs,blocks,self.ref,lambda q:[])
  self.assertEqual(e.expression_preferences(self.plan('저장장치 처분 방법')),['both']);e.pool.shutdown()
if __name__=='__main__':unittest.main()
