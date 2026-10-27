import copy,json,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from source_review import candidates,review,eligible,supported_versions
from engine import SearchEngine

class SourceReviewContracts(unittest.TestCase):
 def setUp(self):
  self.rows=[{'chunk_id':'chunk-a','source':{'doc_id':'opaque-a','file_name':'자료.txt','body':'후보 본문'}}]
  self.blocks={'opaque-a':{'b1':{'text':'본문에 명시한 실제 절차와 안내 내용입니다.'}}}
 def response(self,value,finish='stop'):
  r=MagicMock();r.__enter__.return_value.read.return_value=json.dumps({'choices':[{'finish_reason':finish,'message':{'content':json.dumps(value,ensure_ascii=False)}}]}).encode();return r
 def run_review(self,value,finish='stop'):
  with patch('source_review.urllib.request.urlopen',return_value=self.response(value,finish)):
   return review('일반적인 문서 찾기 질문',self.rows,self.blocks,'http://local/v1','model')
 def test_accepts_only_candidate_with_exact_quote(self):
  got=self.run_review({'doc_id':'opaque-a','quote':'본문에 명시한 실제 절차와 안내 내용입니다.'})
  self.assertEqual(got['status'],'accepted');self.assertTrue(got['quote_verified'])
 def test_invented_id_quote_and_truncation_do_not_override_ranking(self):
  for value,finish in [({'doc_id':'outside','quote':'본문에 명시한 실제 절차와 안내 내용입니다.'},'stop'),
    ({'doc_id':'opaque-a','quote':'원문에 없는 완전히 새로운 문장입니다.'},'stop'),
    ({'doc_id':'opaque-a','quote':'본문에 명시한 실제 절차와 안내 내용입니다.'},'length')]:
   self.assertEqual(self.run_review(value,finish)['status'],'baseline_fallback')
 def test_no_supported_match_is_not_a_selected_document(self):
  self.assertEqual(self.run_review({'doc_id':None,'quote':''})['status'],'no_supported_match')
 def test_numeric_conditions_require_separate_verification_before_model_promotion(self):
  with patch('source_review.urllib.request.urlopen') as request:
   for query in ['2배 이상 늘어난 자료','약 7천만원에 납품한 기록','0.3초보다 빠른 처리 결과']:
    got=review(query,self.rows,self.blocks,'http://local/v1','model')
    self.assertEqual(got['status'],'baseline_fallback');self.assertFalse(got['attempted'])
   request.assert_not_called()
 def test_summary_only_quote_cannot_be_promoted(self):
  self.blocks={'opaque-a':{'b1':{'text':'실제 원문입니다. '*200}}}
  self.rows[0]['source']['body']='요약에만 존재하는 근거 문장입니다.'
  got=self.run_review({'doc_id':'opaque-a','quote':'요약에만 존재하는 근거 문장입니다.'})
  self.assertEqual(got['status'],'baseline_fallback')
  self.assertIn('quote_not_in_source_blocks',got['error'])
 def test_document_count_bound_and_source_data_only(self):
  rows=self.rows*40
  self.assertEqual(len(candidates(rows,self.blocks)),1)
  self.assertEqual(candidates(rows,self.blocks)[0]['text'],self.blocks['opaque-a']['b1']['text'])
 def test_exact_constraints_cannot_take_source_review_path(self):
  for key,value in [('filters',{'document_date':{'gte':'2025-01-01'}}),('identifiers',['ct-123']),('sort',{'field':'written_date'}),('requested_version','v1.0'),('requires_clarification',True)]:
   self.assertFalse(eligible({key:value}),key)
 def test_version_preference_requires_same_family_and_literal_evidence(self):
  docs={d:{'family_id':'other' if d=='unrelated' else 'family'} for d in ['old','latest','changed','unrelated','not_retrieved']}
  rows=[{'source':{'doc_id':d}} for d in ['old','latest','changed','unrelated']]
  blocks={d:{'b':{'text':'같은 원문 근거입니다.'}} for d in docs}
  blocks['latest']['b']['text']='같은 원문\n근거입니다.'
  blocks['changed']['b']['text']='실제 내용이 바뀐 문서입니다.'
  self.assertEqual(supported_versions({'doc_id':'old','quote':'같은 원문 근거입니다.'},rows,docs,blocks),['old','latest'])

class EngineFallbackContracts(unittest.TestCase):
 def test_rejected_review_keeps_baseline_results_despite_expanded_candidates(self):
  root=Path(__file__).resolve().parents[2]/'outputs/search-service-001'
  docs=json.loads((root/'documents.json').read_text());blocks=json.loads((root/'blocks.json').read_text());ref=json.loads((root/'reference.json').read_text())
  chunks=[json.loads(s) for s in (root/'chunks.ndjson').read_text().splitlines()[1::2]]
  base=[next(c for c in chunks if c['doc_id']==did) for did in ['D-001','D-003','D-005']]
  extra=next(c for c in chunks if c['doc_id']=='D-075')
  hits=lambda cs:[{'_id':c['chunk_id'],'_source':c,'_score':1.0} for c in cs]
  stats={'bm25':{'took_ms':0},'vector':{'took_ms':0}}
  e=SearchEngine(docs,blocks,ref,lambda q:[0.0]*1024)
  try:
   with patch.object(e,'retrieve',side_effect=lambda *a:([],hits(base),copy.deepcopy(stats))),patch.object(e,'diverse_branch',return_value=(hits([extra]+base),{'took_ms':0})),patch('engine.needs_review',return_value=True),patch('engine.review_source',return_value={'status':'baseline_fallback','error':'invalid quote'}):
    before=e.search('어떤 곳에서 사용하는 자료를 찾아줘','B','R1','2026-10-14',False)
    after=e.search('어떤 곳에서 사용하는 자료를 찾아줘','B','R1','2026-10-14',True)
   self.assertEqual(before['results'],after['results'])
   self.assertEqual(after['query_plan']['source_review']['status'],'baseline_fallback')
  finally:e.pool.shutdown()
if __name__=='__main__':unittest.main()
