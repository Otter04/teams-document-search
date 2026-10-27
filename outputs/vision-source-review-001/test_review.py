import unittest
from review import Prefix, recover, coverage, graph_scores, table_scores, norm, make_table

class ReviewTests(unittest.TestCase):
    def test_complete_unchanged(self):
        v,ok,_=recover('{"texts":[{"text":"정확\\n원문"}],"status":"complete"}')
        self.assertTrue(ok);self.assertEqual(v['texts'][0]['text'],'정확\n원문')
    def test_partial_string_is_not_invented(self):
        v,ok,_=recover('{"texts":[{"text":"완료"},{"text":"잘리')
        self.assertFalse(ok);self.assertEqual(v['texts'],[{'text':'완료'},{}])
    def test_partial_cell_retains_only_completed_fields(self):
        v,ok,_=recover('{"tables":[{"cells":[{"row":1,"text":"값","column":2')
        self.assertFalse(ok);self.assertEqual(v['tables'][0]['cells'][0],{'row':1,'text':'값'})
    def test_escaped_quotes(self):
        v,ok,_=recover('{"text":"\\\"갑\\\"과 을","unfinished":')
        self.assertFalse(ok);self.assertEqual(v,{'text':'"갑"과 을'})
    def test_typography_only_normalization(self):
        self.assertEqual(norm('㈜ A × 2',True),norm('(주)A x2',True))
        self.assertNotEqual(norm('129,800,000',True),norm('129,800,001',True))
    def test_repeated_nodes_penalize_precision(self):
        r={'nodes':[{'id':'a','label':'서버'}],'edges':[]}
        w={'figures':[{'nodes':[{'id':'a','label':'서버'},{'id':'a','label':'서버'}]}]}
        s=graph_scores(r,w,True)['nodes'];self.assertEqual(s['correct'],1);self.assertEqual(s['observed'],2)
    def test_undirected_reverse_is_same(self):
        r={'nodes':[{'id':'a','label':'A'},{'id':'b','label':'B'}],'edges':[{'from_node':'a','to_node':'b','direction':'undirected'}]}
        w={'figures':[{'nodes':[{'id':'x','label':'B'},{'id':'y','label':'A'}],'relations':[{'from_node':'x','to_node':'y','direction':'undirected'}]}]}
        self.assertEqual(graph_scores(r,w,True)['edges']['correct'],1)
        w['figures'][0]['relations'][0]['direction']='forward'
        self.assertEqual(graph_scores(r,w,True)['edges']['correct'],0)
    def test_collapsed_table_fails_structure(self):
        r={'tables':[make_table([['갑','을'],['회사A','회사B']])]}
        w={'tables':[make_table([['갑\n회사A','을\n회사B']])]}
        s=table_scores(r,w)['tables'][0];self.assertFalse(s['dimensions_correct']);self.assertEqual(s['structure']['correct'],0)
    def test_blank_cell_is_scored(self):
        t=make_table([['제목',''],['A','B']]);s=table_scores({'tables':[t]},{'tables':[t]})
        self.assertEqual(s['tables'][0]['structure']['correct'],4)
    def test_claims_not_admitted_as_literal(self):
        r={'texts':[{'kind':'text','text':'원본 제목'}],'tables':[],'nodes':[]}
        self.assertEqual(coverage(r,[])['compatible'],0)

if __name__=='__main__':unittest.main()
