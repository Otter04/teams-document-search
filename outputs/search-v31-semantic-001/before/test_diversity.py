import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from engine import SearchEngine,CONFIG
from query import plan_rules,apply_mode,es_filters

DATA=Path(__file__).resolve().parents[2]/'outputs/indexing-v31-001/search-data'
class DiverseCandidates(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.docs=json.loads((DATA/'documents.json').read_text());cls.blocks=json.loads((DATA/'blocks.json').read_text());cls.ref=json.loads((DATA/'reference.json').read_text())
 def engine(self):return SearchEngine(copy.deepcopy(self.docs),self.blocks,self.ref,lambda q:[])
 def plan(self,q):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),'B')
 def test_saturated_document_is_excluded_on_refill_and_dates_remain(self):
  e=self.engine();p=self.plan('올해 백업 로그')
  def hit(d,n,score):return {'_id':d+str(n),'_score':score,'_source':{'doc_id':d}}
  first=[hit('long',n,2.-n/100) for n in range(6)]
  second=[hit('other'+str(n),0,1.-n/100) for n in range(6)]
  with patch.dict(CONFIG,{'candidate_batch':6,'vector_k':6,'candidate_per_document':2}),patch('engine.http',side_effect=[{'hits':{'hits':first}},{'hits':{'hits':second}}]) as call:
   hits,stats=e.diverse_branch(p,[1.],'vector',[])
  self.assertEqual(len(hits),6);self.assertEqual(sum(h['_source']['doc_id']=='long' for h in hits),2)
  self.assertEqual(len(stats['rounds']),2)
  for c in call.call_args_list:
   for clause in es_filters(p):self.assertIn(clause,c.args[2]['knn']['filter'])
  self.assertIn('long',str(call.call_args_list[1].args[2]['knn']['filter'][-1]))
  e.pool.shutdown()
 def test_lexical_exact_evidence_and_ties_are_preserved(self):
  e=self.engine();hits=[{'_id':str(n),'_score':10.-n/100,'_source':{'doc_id':'single'}} for n in range(50)]
  with patch('engine.http',return_value={'hits':{'hits':hits}}):
   kept,stats=e.diverse_branch(self.plan('전환 훈련'),[1.],'bm25',[])
  self.assertEqual([h['_id'] for h in kept],[h['_id'] for h in hits]);e.pool.shutdown()
 def test_earliest_original_and_conjunctive_config_evidence(self):
  e=self.engine()
  self.assertEqual(self.plan('맨 처음 설계안')['requested_version_order'],'earliest')
  self.assertEqual(e.docs['D-190']['family_id'],e.docs['D-191']['family_id'])
  self.assertFalse(e.docs['D-190']['latest_version'])
  p=self.plan('사이트 주소 들어간 쿠버네티스 설정')
  self.assertIn('D-193',e.expression_preferences(p));self.assertNotIn('D-191',e.expression_preferences(p))
  self.assertNotIn('client',p['conditions']);e.pool.shutdown()
 def test_refill_http_success_with_failed_shards_is_rejected(self):
  e=self.engine()
  with patch('engine.http',return_value={'_shards':{'failed':1},'hits':{'hits':[]}}):
   with self.assertRaisesRegex(RuntimeError,'incomplete'):e.diverse_branch(self.plan('로그'),[1.],'vector',[])
  e.pool.shutdown()
 def test_named_revision_family_and_native_equivalence(self):
  e=self.engine()
  self.assertEqual(e.docs['D-170']['family_id'],e.docs['D-171']['family_id'])
  self.assertEqual(e.docs['D-171']['version_label'],'v0.7')
  self.assertFalse(e.docs['D-170']['latest_version']);self.assertTrue(e.docs['D-171']['latest_version'])
  self.assertEqual(e.literal_fingerprints['D-162'],e.literal_fingerprints['D-163'])
  self.assertNotEqual(e.literal_fingerprints['D-170'],e.literal_fingerprints['D-171']);e.pool.shutdown()
 def test_version_words_do_not_override_dates_or_contained_objects(self):
  self.assertEqual(self.plan('터널 장비 단자를 처음엔 다른 번호로 잡았던 표')['requested_version_order'],'earliest')
  self.assertIsNone(self.plan('처음 발생한 오류 로그')['requested_version_order'])
  self.assertTrue(self.plan('생산 현장 망 그림 제일 새 판')['boost']['latest_version'])
  self.assertNotIn('document_type',self.plan('가장 최근에 작성된 네트워크 구성도가 포함된 문서')['conditions'])
if __name__=='__main__':unittest.main()
