import copy,json,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from query import plan_rules,apply_mode
from rewrite import needs_rewrite,rewrite

class RewriteContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.ref=json.loads((Path(__file__).resolve().parents[2]/'outputs/indexing-v31-001/search-data/reference.json').read_text())
 def plan(self,q):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),'B')
 def response(self,text,finish='stop'):
  r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':finish,'message':{'content':text}}]}).encode();return r
 def test_preserves_all_explicit_conditions(self):
  p=self.plan('2025년 계약서');before=copy.deepcopy(p)
  with patch('rewrite.urllib.request.urlopen',return_value=self.response('계약 조건')):
   got=rewrite(p,self.ref,'unused','model')
  for k in ['query','conditions','filters','required_dates','condition_evidence','sort']:
   self.assertEqual(got[k],before[k])
  self.assertEqual(p,before);self.assertEqual(got['rewrite']['status'],'accepted')
 def test_invalid_outputs_never_replace_original_query(self):
  p=self.plan('업무를 처리할 업체가 지켜야 하는 조건을 찾아줘')
  for text,finish in [('2027년 업체 선정','stop'),('청람정밀 업체 선정','stop'),('조건\n설명','stop'),('잘린 결과','length')]:
   with patch('rewrite.urllib.request.urlopen',return_value=self.response(text,finish)):
    got=rewrite(p,self.ref,'unused','model')
   self.assertEqual(got['rewrite']['status'],'rules_fallback')
   self.assertEqual(got['keywords'],p['keywords'])
 def test_timeouts_keep_original_conditions(self):
  p=self.plan('업무 처리 결과를 어디에 적어 놓았는지 찾아줘')
  with patch('rewrite.urllib.request.urlopen',side_effect=TimeoutError()):got=rewrite(p,self.ref,'unused','model')
  self.assertEqual(got['semantic'],p['semantic']);self.assertFalse(got['used_llm'])
 def test_only_unanchored_questions_need_model_wording(self):
  self.assertTrue(needs_rewrite(self.plan('업무를 맡길 회사를 고를 때 어떤 조건을 보는지 알려 준 자료')))
  for q in ['2025년 계약서','청람정밀 계약서','최신 수정된 문서','SSD 폐기 방법에 답해 준 자료']:
   self.assertFalse(needs_rewrite(self.plan(q)),q)
if __name__=='__main__':unittest.main()
