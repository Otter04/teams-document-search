import copy,json,unittest
from unittest.mock import patch,MagicMock
from engine import SearchEngine
from semantic_rewrite import rewrite_semantic,validate_text
from query_literal import plan_literal
from model_ranker import RerankerError
class LocalTests(unittest.TestCase):
    def test_rewrite_changes_only_semantic_text(self):
        p=plan_literal('청람정밀 MES 2026년 계약서',{},'2026-10-14');snapshot=copy.deepcopy(p)
        raw={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'search_query':'2026년 청람정밀 MES 계약 문서'})}}]}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(raw).encode()
        with patch('semantic_rewrite.settings',return_value={'OPENROUTER_API_KEY':'test','OPENROUTER_MODEL':'test'}),patch('semantic_rewrite.urllib.request.urlopen',return_value=response) as call:
            actual=rewrite_semantic(p)
        payload=json.loads(call.call_args.args[0].data)
        self.assertEqual(payload['messages'][1]['content'],p['query'])
        self.assertEqual(actual['llm']['status'],'rewritten');self.assertNotEqual(actual['semantic'],p['semantic'])
        for key in ['keywords','conditions','condition_evidence','requires_clarification','sort']:
            self.assertEqual(actual[key],p[key])
        self.assertEqual(p,snapshot)
    def test_invalid_numbers_or_identifier_rejected(self):
        for q,rewrite in [('MES 오류','ERP 오류'),('2025년 계약','2026년 계약'),('폐기 방법','90일 보관 후 폐기')]:
            with self.assertRaises(ValueError):validate_text(q,rewrite)
    def test_timeout_falls_back_to_original(self):
        p=plan_literal('올해 백업 로그',{},'2026-10-14')
        with patch('semantic_rewrite.settings',return_value={'OPENROUTER_API_KEY':'test','OPENROUTER_MODEL':'test'}),patch('semantic_rewrite.urllib.request.urlopen',side_effect=TimeoutError()):r=rewrite_semantic(p)
        self.assertEqual(r['semantic'],p['query']);self.assertEqual(r['llm']['status'],'rewrite_fallback')
        self.assertEqual(r['conditions'],p['conditions'])
    def make_engine(self):
        self.embedded=[];self.scored=[]
        def embed(q):self.embedded.append(q);return [1.]
        def scorer(q,ps):self.scored.append((q,len(ps)));return {'scores':list(range(len(ps)))}
        e=SearchEngine({},{},{},embed,model_ranker=scorer);self.addCleanup(e.pool.shutdown)
        def hits(prefix):return [{'_id':prefix+str(i),'_score':100-i,'_source':{'doc_id':'D-'+str(i),'body':'본문','context':'제목','table_header':''}} for i in range(50)]
        e.retrieve=lambda *a:(hits('B'),hits('V'),{'bm25':{'took_ms':0},'vector':{'took_ms':0}})
        e.group=lambda *a:[]
        return e
    def test_40_and_100_share_bm25_and_rrf_but_cap_model(self):
        e=self.make_engine()
        with patch('engine.http',return_value={'tokens':[{'token':'원문'}]}),patch('engine.rerank',side_effect=AssertionError('R1 forbidden')):
            a=e.search('원문',use_llm=False,rerank_limit=40);b=e.search('원문',use_llm=False,rerank_limit=100)
        self.assertEqual(self.scored,[('원문',40),('원문',100)])
        self.assertEqual(a['diagnostics']['bm25'],b['diagnostics']['bm25'])
        self.assertEqual(a['diagnostics']['candidate_fingerprint'],b['diagnostics']['candidate_fingerprint'])
        self.assertEqual(len(a['diagnostics']['rerank_candidates']),40)
    def test_vector_rewrite_but_original_reranker(self):
        e=self.make_engine()
        def rewrite(p):p=copy.deepcopy(p);p['semantic']='재작성';return p
        with patch('engine.http',return_value={'tokens':[]}),patch('engine.rewrite_semantic',side_effect=rewrite):
            r=e.search('원문')
        self.assertEqual(self.embedded,['재작성']);self.assertEqual(self.scored,[('원문',40)])
        self.assertEqual(r['query_plan']['keywords'],'원문')
    def test_model_failure_never_uses_r1(self):
        e=self.make_engine();e.model_ranker=None
        with patch('engine.http',return_value={'tokens':[]}),patch('engine.rerank',side_effect=AssertionError('R1 forbidden')):
            with self.assertRaises(RerankerError):e.search('원문',use_llm=False)
    def test_pair_shares_rewrite_embedding_and_candidates_once(self):
        e=self.make_engine();original=e.retrieve
        def rewrite(p):
            p=copy.deepcopy(p);p['semantic']='재작성';p['llm']={'attempted':True,'status':'rewritten'};return p
        for first in [40,100]:
            self.embedded.clear();self.scored.clear()
            with patch('engine.http',return_value={'tokens':[]}),patch('engine.rewrite_semantic',side_effect=rewrite) as rw,patch.object(e,'retrieve',side_effect=original) as retr:
                pair=e.compare_limits('원문','2026-10-14',first)
            self.assertEqual(rw.call_count,1);self.assertEqual(retr.call_count,1);self.assertEqual(self.embedded,['재작성'])
            self.assertEqual([n for q,n in self.scored],[first,140-first])
            a=pair['baseline100'];b=pair['candidate40']
            self.assertEqual(a['query_plan'],b['query_plan'])
            self.assertEqual(a['diagnostics']['candidate_fingerprint'],b['diagnostics']['candidate_fingerprint'])
            self.assertEqual(a['diagnostics']['rerank_candidates'][:40],b['diagnostics']['rerank_candidates'])
            self.assertEqual(a['timings']['common_seconds'],b['timings']['common_seconds'])
            self.assertGreaterEqual(a['timings']['equivalent_total_seconds'],a['timings']['common_seconds'])
    def test_pair_date_sort_not_counted_as_model_comparison(self):
        e=self.make_engine();e.date_candidates=lambda p:[]
        with patch('engine.http',return_value={'tokens':[]}),patch('engine.rewrite_semantic',side_effect=lambda p:p):
            r=e.compare_limits('수정일 최신순 문서','2026-10-14',100)
        self.assertTrue(r['reranker_cap_not_applicable']);self.assertEqual(self.scored,[])
if __name__=='__main__':unittest.main()
