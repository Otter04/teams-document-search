import copy
import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import condition_search as s
TERMS=s.E.read_json(s.ROOT.parent/'rag-enrichment-v1/reference-data.json')['system_terms']
IX=s.E.read_json(s.ROOT.parent/'rule-search-run-004/index.json')
def c(q):return s.explicit_conditions(q,TERMS)
def filters(q):return {f['field']:f['value'] for f in c(q)['filters']}
class Conditions(unittest.TestCase):
    def test_log_and_system(self):self.assertEqual(filters('ERP 작업 로그'),{'문서종류':'실행 로그','대상시스템':'ERP'})
    def test_log_only(self):self.assertEqual(filters('오토스케일링 테스트 로그'),{'문서종류':'실행 로그'})
    def test_general_diagram_is_union(self):self.assertEqual(filters('전용회선 구성도')['문서종류'],['네트워크 구성도','서버 구성도'])
    def test_specific_diagram_overrides_substring(self):self.assertEqual(filters('서버 구성도')['문서종류'],'서버 구성도')
    def test_network_diagram(self):self.assertEqual(filters('네트워크 구성도')['문서종류'],'네트워크 구성도')
    def test_english_case_and_particle(self):self.assertEqual(filters('mes의 계약서')['대상시스템'],'MES')
    def test_korean_system(self):self.assertEqual(filters('학사정보시스템 견적서')['대상시스템'],'학사정보시스템')
    def test_multiple_systems_abstain(self):
        p=c('MES ERP 연동 계약서');self.assertNotIn('대상시스템',filters('MES ERP 연동 계약서'));self.assertIn('multiple_target_systems',p['warnings'])
    def test_multiple_kinds_abstain(self):self.assertNotIn('문서종류',filters('견적 관련 메일'))
    def test_negation_abstains(self):
        for q in ('ERP 아닌 MES 로그','계약서 말고 견적서','로그를 제외한 자료','계약서 또는 견적서'):self.assertEqual(c(q)['filters'],[])
    def test_quoted_text_abstains(self):self.assertEqual(c('"MES 로그"가 들어간 메모')['filters'],[])
    def test_identifiers_not_system_names(self):
        for q in ('MES2','tms-db01','prefix_ERP','ERP.xlsx','PACS-123'):self.assertNotIn('대상시스템',filters(q))
    def test_content_word_not_document_kind(self):self.assertNotIn('문서종류',filters('로그분석 플랫폼'))
    def test_unknown_system_not_invented(self):self.assertNotIn('대상시스템',filters('CRM 로그'));self.assertNotIn('대상시스템',filters('DB DR 로그'))
    def test_date_composition(self):
        p=s.plan('작년 12월 ERP 로그','2026-10-17',TERMS);self.assertEqual(sum(f['field']=='문서종류' for f in p['filters']),1)
        self.assertIn({'field':'대상시스템','op':'eq','value':'ERP'},p['filters'])
    def test_no_filters_exact_scores(self):
        a=s.search(IX,'ORA-01555','2026-10-17',TERMS,kinds=False,systems=False);b=s.previous.search(IX,'ORA-01555','2026-10-17')
        self.assertEqual([(r['doc_id'],r['score']) for r in a['results']],[(r['doc_id'],r['score']) for r in b['results']])
    def test_unknown_metadata_not_allowed(self):
        ix=copy.deepcopy(IX);ix['documents']['D-036']['metadata_statuses']['대상시스템']='needs_review'
        r=s.search(ix,'TMS 로그','2026-10-17',TERMS);self.assertNotIn('D-036',[x['doc_id'] for x in r['results']]);self.assertIn('D-036',r['unresolved_filter_documents'])
    def test_no_silent_relaxation(self):self.assertEqual(s.search(IX,'2099년 ERP 로그','2026-10-17',TERMS)['results'],[])
    def test_conditions_not_answer_verification(self):
        r=s.search(IX,'TMS 로그','2026-10-17',TERMS);self.assertTrue(r['results']);self.assertFalse(r['conditions_verified'])
        self.assertTrue(all(x['metadata_conditions_checked'] and not x['conditions_verified'] for x in r['results']))
    def test_candidate_filter_before_cap(self):
        ix={'documents':{},'entries':{},'postings':{'w:needle':{}},'entry_count':120,'average_length':1,'clients':[],'rules':{'concepts':[]},'config':{'bm25_k1':1.2,'bm25_b':.75}}
        for i in range(120):
            identity=f'SYN-{i:03d}';eid=identity+'-entry';meta={'문서종류':'실행 로그' if i==119 else '제안서'}
            ix['documents'][identity]={'source':{},'metadata':meta,'metadata_statuses':{'문서종류':'extracted'},'native_chunk_count':1,'pending_visual_units':[]}
            ix['entries'][eid]={'doc_id':identity,'length':1,'text':'needle','source_refs':[]};ix['postings']['w:needle'][eid]=1
        self.assertEqual(s.search(ix,'needle 로그','2026-10-17',TERMS,limit=5)['results'][0]['doc_id'],'SYN-119')
if __name__=='__main__':unittest.main()
