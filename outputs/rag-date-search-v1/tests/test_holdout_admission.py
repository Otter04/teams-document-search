import copy, importlib.util, unittest
from pathlib import Path
path=Path(__file__).resolve().parents[2]/'independent-evaluation-prep-v1/holdout.py'
spec=importlib.util.spec_from_file_location('holdout_admission',path);h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)

class Admission(unittest.TestCase):
    def fixture(self):
        manifest=[{'doc_id':'H1','source_sha256':'a'*64,'family_key':'new-family','source_origin':'new_collection','reviewer_id':'reviewer'}]
        queries=[{'query_id':'Q1','query':'표지 날짜 2025년 문서','category':'cover_date','limit':5}]
        answers=[{'query_id':'Q1','expected_doc_ids':['H1'],'check':'relevance','reviewer_id':'reviewer','evidence':[{'page':1}]}]
        metadata=[{'doc_id':'H1','reviewer_id':'reviewer','fields':{f:{'value':None,'state':'unresolved','evidence':[]} for f in h.FIELDS}}]
        ix={'documents':{'H1':{'source':{'sha256':'a'*64}}}};deny={'source_hashes':[],'family_keys':[]}
        return [manifest,queries,answers,metadata,ix,deny]
    def test_complete_small_fixture_only_for_unit_checks(self):
        self.assertEqual(h.validate(*self.fixture(),min_documents=1,min_queries=1),[])
    def test_default_minimum_does_not_accept_small_fixture(self):
        errors=h.validate(*self.fixture());self.assertIn('insufficient_new_documents',errors);self.assertIn('insufficient_new_queries',errors)
    def test_empty_package_is_not_a_pass(self):
        self.assertIn('insufficient_new_documents',h.validate([],[],[],[],{'documents':{}},{'source_hashes':[],'family_keys':[]}))
    def test_original_source_and_family_rejected(self):
        a=self.fixture();a[-1]={'source_hashes':['a'*64],'family_keys':['new-family']}
        errors=h.validate(*a,min_documents=1,min_queries=1)
        self.assertIn('development_source_reused:H1',errors);self.assertIn('family_overlap_or_missing:H1',errors)
    def test_unreviewed_answers_and_missing_fields_rejected(self):
        a=self.fixture();a[2][0]['reviewer_id']='';a[3][0]['fields'].pop('작성일')
        errors=h.validate(*a,min_documents=1,min_queries=1)
        self.assertIn('answer_review_missing:Q1',errors);self.assertIn('metadata_review_or_fields_missing:H1',errors)
    def test_wrong_hash_and_unknown_answer_rejected(self):
        a=self.fixture();a[4]['documents']['H1']['source']['sha256']='b'*64;a[2][0]['expected_doc_ids']=['UNKNOWN']
        errors=h.validate(*a,min_documents=1,min_queries=1)
        self.assertIn('source_hash_mismatch:H1',errors);self.assertIn('invalid_answer_ids:Q1',errors)
    def test_value_requires_source_evidence(self):
        a=self.fixture();a[3][0]['fields']['작성일']={'state':'value','value':'2025-01-01','evidence':[]}
        self.assertIn('metadata_value_without_evidence:H1',h.validate(*a,min_documents=1,min_queries=1))

if __name__=='__main__':unittest.main()
