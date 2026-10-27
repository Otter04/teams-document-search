import copy
import json
import unittest
from unittest.mock import patch
from pathlib import Path
from query import plan_rules, apply_mode
from semantic import eligible, select_rows, SemanticClient

class SemanticContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=json.loads((Path(__file__).resolve().parents[2]/'outputs/indexing-v31-001/search-data/reference.json').read_text())
    def plan(self, text):
        return apply_mode(plan_rules(text,self.ref,'2026-10-14'),'B')
    def test_clear_constraints_keep_existing_path(self):
        for q in ['2025년 계약서', '청람정밀 계약서', '가장 최근 수정된 문서', '제안서 v1.0', '최초 버전 제안서', '계약번호 CT-2025-001', '올해 백업 로그']:
            self.assertFalse(eligible(self.plan(q)),q)
        self.assertTrue(eligible(self.plan('발주처가 제안들을 비교할 기준을 알려 준 자료')))
    def test_invalid_or_ambiguous_questions_do_not_rank(self):
        for q in ['2025년 13월 자료','지난달 문서','계약서 말고 다른 문서']:
            self.assertFalse(eligible(self.plan(q)),q)
    def test_document_diversity_and_stable_order(self):
        rows=[{'source':{'doc_id':'long'},'chunk_id':str(i)} for i in range(80)]
        rows += [{'source':{'doc_id':f'short-{i}'},'chunk_id':f's-{i}'} for i in range(10)]
        chosen=select_rows(rows,limit=12)
        self.assertEqual(len(chosen),12)
        self.assertEqual(len({r['source']['doc_id'] for r in chosen}),11)
        self.assertEqual(sum(r['source']['doc_id']=='long' for r in chosen),2)
    def test_model_scores_must_be_complete_and_finite(self):
        rows=[{'source':{'doc_id':'opaque','file_name':'일반문서','body':'원문'},'chunk_id':'c'}]
        for scores in [[],[float('nan')],[float('inf')],['wrong']]:
            response=unittest.mock.MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps({'scores':scores}).encode()
            with patch('semantic.urllib.request.urlopen',return_value=response):
                with self.assertRaises(ValueError):SemanticClient()('일반 질문',copy.deepcopy(rows))
    def test_model_errors_are_not_silently_called_success(self):
        rows=[{'source':{'doc_id':'opaque','file_name':'일반문서','body':'원문'},'chunk_id':'c'}]
        with patch('semantic.urllib.request.urlopen',side_effect=TimeoutError('offline')):
            with self.assertRaises(TimeoutError):SemanticClient()('일반 질문',rows)
if __name__=='__main__':unittest.main()
