import copy,json,unittest
from unittest.mock import patch
import test_search
from query import plan_rules,apply_mode
from engine import SearchEngine,date_sort_value
from streaming import stream_search

class BoundaryContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  test_search.SearchContracts.setUpClass();c=test_search.SearchContracts
  cls.docs=c.docs;cls.blocks=c.blocks;cls.rows=c.rows;cls.ref=c.ref
 def plan(self,q):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),'B')
 def test_invalid_calendar_is_not_expanded_to_a_valid_month_or_year(self):
  for q in ['2025년 0월 견적서','2025년 1월 0일 견적서','2025년 13월 계약서','2025년 2월 29일 계약서']:
   with self.subTest(q=q):
    p=self.plan(q);self.assertTrue(p['requires_clarification']);self.assertIn('invalid_calendar_date',p['warnings']);self.assertNotIn('document_date',p['conditions'])
  p=self.plan('2024년 2월 29일 계약서');self.assertFalse(p['requires_clarification']);self.assertEqual(p['required_dates']['document_date'],{'gte':'2024-02-29','lte':'2024-02-29'})
 def test_unparsed_endpoints_never_search_only_the_start(self):
  for q in ['2025년 1월부터 3월까지 견적서','2025년 1월 2일부터 5일까지 계약서','3월 계약서']:
   with self.subTest(q=q):
    p=self.plan(q);self.assertTrue(p['requires_clarification']);self.assertIn('unsupported_calendar_expression',p['warnings']);self.assertNotIn('document_date',p['filters'])
    e=SearchEngine(self.docs,self.blocks,self.ref,lambda _:self.fail('must not search a truncated range'))
    self.addCleanup(e.pool.shutdown)
    self.assertEqual(e.search(q,use_llm=False)['status'],'needs_clarification')
 def test_modified_order_compares_instants_across_offsets(self):
  docs=copy.deepcopy(self.docs)
  docs['D-003']['metadata']['file_modified_at']='2026-10-24T01:00:00Z'
  docs['D-004']['metadata']['file_modified_at']='2026-10-24T09:30:00+09:00'
  docs['D-025']['metadata']['file_modified_at']='2026-10-24T09:45:00+09:00'
  e=SearchEngine(docs,self.blocks,self.ref,lambda _:[]);self.addCleanup(e.pool.shutdown)
  rs=[{'source':next(c for c in self.rows if c['doc_id']==d),'chunk_id':d,'score':1} for d in ['D-003','D-004','D-025']]
  self.assertEqual([c['doc_id'] for c in e.group(rs,self.plan('최근 수정된 문서'))],['D-003','D-025'])
  self.assertEqual([c['doc_id'] for c in e.group(rs,self.plan('수정일 오름차순 문서'))],['D-004','D-025'])
 def test_unknown_timestamp_timezone_is_not_guessed(self):
  self.assertIsNone(date_sort_value({'file_modified_at':'2026-10-24T10:00:00'},'file_modified_at'))
  self.assertIsNone(date_sort_value({'written_date':'2025-02-30'},'written_date'))
  self.assertEqual(date_sort_value({'file_modified_at':'2026-10-24T09:00:00+09:00'},'file_modified_at'),date_sort_value({'file_modified_at':'2026-10-24T00:00:00Z'},'file_modified_at'))
 def test_incomplete_search_is_an_error_even_with_http_success(self):
  for flag in [{'timed_out':True},{'_shards':{'failed':1}},{'terminated_early':True}]:
   with self.subTest(flag=flag):
    e=SearchEngine(self.docs,self.blocks,self.ref,lambda _:[]);self.addCleanup(e.pool.shutdown)
    response={'hits':{'hits':[]},'took':1,**flag}
    with patch('engine.http',return_value=response):
     with self.assertRaisesRegex(RuntimeError,'incomplete_search_response'):e.retrieve(self.plan('견적서'),[0.]*1024)
     with self.assertRaisesRegex(RuntimeError,'incomplete_search_response'):e.date_candidates(self.plan('수정일 최신순 문서'))
 def test_partial_second_page_is_not_a_complete_date_result(self):
  e=SearchEngine(self.docs,self.blocks,self.ref,lambda _:[]);self.addCleanup(e.pool.shutdown)
  c=self.rows[0];hit={'_id':c['chunk_id'],'_source':c,'sort':['2025-01-01','id']}
  with patch('engine.http',side_effect=[{'hits':{'hits':[hit]*2000}},{'hits':{'hits':[]},'timed_out':True}]):
   with self.assertRaises(RuntimeError):e.date_candidates(self.plan('수정일 최신순 문서'))
 def test_partial_search_stream_never_emits_completion(self):
  e=SearchEngine(self.docs,self.blocks,self.ref,lambda _:[0.]*1024);self.addCleanup(e.pool.shutdown)
  with patch('engine.http',return_value={'hits':{'hits':[]},'took':1,'_shards':{'failed':1}}):
   events=[json.loads(x) for x in stream_search(e,'견적서','B','R1','2026-10-14',False) if x.strip()]
  self.assertEqual(events[-1]['stage'],'error');self.assertNotIn('complete',[x['stage'] for x in events])
  self.assertNotIn('incomplete_search_response',str(events))
if __name__=='__main__':unittest.main()
