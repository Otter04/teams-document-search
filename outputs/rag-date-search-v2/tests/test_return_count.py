import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import date_search as d
import test_dates as base_cases

class ReturnCount(unittest.TestCase):
    def test_count_is_not_a_numeric_content_condition(self):
        ix,b=base_cases.Dates().synthetic_index(150)
        r=d.search(ix,b,'가장 최근 수정된 문서 상위 3개','2026-10-18',[],limit=10)
        self.assertEqual([v['doc_id'] for v in r['results']],['D149','D148','D147'])
        self.assertEqual(r['query_plan']['content_query'],'')
        self.assertEqual(r['ranked_documents_before_limit'],150)

    def test_count_preserves_real_content_condition(self):
        p=d.plan('가장 최근 수정된 문서 unicornxyz 상위 3개','2026-10-18',[],[])
        self.assertEqual(p['content_query'],'unicornxyz')
        ix,b=base_cases.Dates().synthetic_index(5)
        self.assertEqual(d.search(ix,b,'가장 최근 수정된 문서 unicornxyz 상위 3개','2026-10-18',[])['results'],[])

    def test_item_quantity_is_not_return_count(self):
        p=d.plan('가장 최근 수정된 센서 3개 문서','2026-10-18',[],[])
        self.assertNotIn('requested_limit',p)
        self.assertIn('3개',p['content_query'])

    def test_invalid_or_conflicting_count_requires_clarification(self):
        for count in ['상위 0개','상위 101개','상위 2개 최대 3개']:
            with self.subTest(count=count):
                self.assertTrue(d.plan('가장 최근 수정된 문서 '+count,'2026-10-18',[],[])['requires_clarification'])

    def test_caller_limit_still_caps_output(self):
        ix,b=base_cases.Dates().synthetic_index(5)
        r=d.search(ix,b,'가장 최근 수정된 문서 상위 3개','2026-10-18',[],limit=2)
        self.assertEqual([v['doc_id'] for v in r['results']],['D004','D003'])

if __name__=='__main__':unittest.main()
