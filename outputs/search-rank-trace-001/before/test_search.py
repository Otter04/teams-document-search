import io,json,unittest,copy
from pathlib import Path
from unittest.mock import patch
from query import plan_rules,apply_mode,es_filters,conditional_llm
from engine import rrf,SearchEngine,rerank,lexical_preferences
from content import network_diagrams

DATA=Path(__file__).resolve().parents[2]/'outputs/search-service-001'
class SearchContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=json.loads((DATA/'reference.json').read_text());cls.docs=json.loads((DATA/'documents.json').read_text());cls.blocks=json.loads((DATA/'blocks.json').read_text())
        cls.rows=[json.loads(s) for s in (DATA/'chunks.ndjson').read_text().splitlines()[1::2]]
    def plan(self,q,mode='A'):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),mode)
    def test_client_alias_and_modes(self):
        a=self.plan('Cheongram Precision MES 견적서');b=self.plan('Cheongram Precision MES 견적서','B')
        self.assertEqual(a['filters']['client'],'청람정밀');self.assertEqual(set(b['filters']),{'client'})
        self.assertEqual(b['soft_conditions']['document_type'],'견적서')
        self.assertNotIn('target_system',a['filters']);self.assertEqual(a['soft_conditions']['target_system'],'MES')
    def test_date_role_and_reference(self):
        p=self.plan('작년 12월 DB 백업 로그');self.assertEqual(p['filters']['log_start'],{'gte':'2025-12-01','lte':'2025-12-31'})
        p=self.plan('2025년 1월 14일 파일 최종 수정일');self.assertEqual(p['filters']['file_modified_at']['gte'],'2025-01-14T00:00:00+09:00')
        self.assertNotIn('document_date',p['filters'])
    def test_ambiguity_not_silent_filter(self):
        for q in ['청람정밀 말고 계약서','지난 분기 계약서','청람정밀 다온 견적서','2025년 2월 31일 문서']:
            self.assertTrue(self.plan(q)['requires_clarification'],q)
    def test_timeout_and_ungrounded_model_fallback(self):
        p=plan_rules('부하 증가 때 서버를 늘리는 구성',self.ref,'2026-10-14')
        with patch('query.urllib.request.urlopen',side_effect=TimeoutError('test')):
            got=conditional_llm(p,self.ref,'http://unused','test',.01)
        self.assertEqual(got['conditions'],p['conditions']);self.assertEqual(got['llm']['status'],'rules_fallback')
    def test_schema_valid_but_unrelated_evidence_is_rejected(self):
        p=plan_rules('부하 증가 때 서버를 늘리는 구성',self.ref,'2026-10-14')
        bad={'conditions':[{'field':'client','value':'청람정밀','evidence':'서버'}],'keywords':'서버 구성'}
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(bad)}}]}
        with patch('query.urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(response).encode())) as call:
            got=conditional_llm(p,self.ref,'http://unused','test')
        self.assertEqual(got['conditions'],{});self.assertEqual(call.call_count,2)
        self.assertEqual(got['llm']['status'],'rules_fallback')
    def test_truncated_json_is_not_adopted(self):
        p=plan_rules('부하 증가 때 서버를 늘리는 구성',self.ref,'2026-10-14')
        response={'choices':[{'finish_reason':'length','message':{'content':'{"conditions":[],"keywords":"서버"}'}}]}
        with patch('query.urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(json.dumps(response).encode())):
            got=conditional_llm(p,self.ref,'http://unused','test')
        self.assertFalse(got['used_llm']);self.assertEqual(got['llm']['attempts'],2)
    def test_rrf_equal_weights_and_stable_tie(self):
        a={'_id':'a','_source':{},'_score':1};b={'_id':'b','_source':{},'_score':2}
        r=rrf([a,b],[b,a]);self.assertEqual([x['chunk_id'] for x in r],['a','b']);self.assertEqual(r[0]['rrf_score'],r[1]['rrf_score'])
    def test_bm25_only_candidate_still_gets_cosine(self):
        p=self.plan('MES');source=dict(self.rows[0]);source['embedding']=[1.,0.]
        rows=rrf([{'_id':'only-bm25','_source':source,'_score':2}],[])
        out=rerank(rows,p,'R1',[1.,0.]);self.assertEqual(out[0]['rerank_features']['cosine'],1.)
    def test_soft_conditions_boost_candidates_without_becoming_filters(self):
        p=self.plan('청람정밀 2025년 견적서 최종본','B');self.assertEqual(set(p['filters']),{'client'})
        boosts=lexical_preferences(p);self.assertEqual(len(boosts),3)
    def test_old_identifier_evidence_is_representative(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[])
        p=self.plan('Q-2501-03 견적서')
        rows=[]
        for did,score in [('D-003',.5),('D-004',1.0)]:
            c=next(r for r in self.rows if r['doc_id']==did);rows.append({'source':c,'chunk_id':c['chunk_id'],'score':score})
        cards=engine.group(rows,p);self.assertEqual(cards[0]['doc_id'],'D-003')
        self.assertEqual(cards[0]['representative_reason'],'identifier_evidence')
    def test_explicit_draft_not_replaced_with_signed_version(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[]);p=self.plan('청람정밀 MES 계약서 초안','B')
        rows=[]
        for did in ['D-005','D-006']:
            c=next(r for r in self.rows if r['doc_id']==did);rows.append({'source':c,'chunk_id':c['chunk_id'],'score':1.})
        card=engine.group(rows,p)[0];self.assertEqual(card['doc_id'],'D-005');self.assertEqual(card['representative_reason'],'requested_status')
        self.assertTrue(any('문단' in e['location'] for e in card['excerpts']))
    def test_excerpts_are_literal_and_bounded(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[]);p=self.plan('청람정밀 MES 견적서')
        c=next(r for r in self.rows if r['doc_id']=='D-003');rs=[{'source':c,'chunk_id':c['chunk_id'],'score':1}]
        ev=engine.excerpts('D-003',rs,p);self.assertTrue(ev)
        for e in ev:
            original=self.blocks['D-003'][e['block_id']]['text']
            self.assertEqual(e['text'],original[e['start']:e['end']]);self.assertLessEqual(len(e['text']),100)
    def test_relaxation_preserves_client(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[]);seen=[]
        def none(p,v):seen.append(dict(p['filters']));return [],[],{}
        engine.retrieve=none
        out=engine.search('청람정밀 2030년 견적서',mode='A',use_llm=False)
        self.assertEqual(out['status'],'no_results');self.assertTrue(all(p.get('client')=='청람정밀' for p in seen))
        self.assertEqual([x['field'] for x in out['relaxed_conditions']],['document_date','document_type'])
    def test_es_failure_is_not_no_results_or_relaxation(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[])
        engine.retrieve=lambda p,v:(_ for _ in ()).throw(ConnectionError('offline'))
        with self.assertRaises(ConnectionError):engine.search('청람정밀 계약서',use_llm=False)
    def test_modified_order_looks_beyond_initial_30_chunks(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[0.]*1024)
        first=next(r for r in self.rows if r['doc_id']=='D-001')
        newest=max(self.rows,key=lambda r:r['metadata'].get('file_modified_at',''))
        def hit(c):return {'_id':c['chunk_id'],'_source':c,'_score':1.0}
        engine.retrieve=lambda p,v:([hit(first)],[hit(first)],{})
        with patch('engine.http',return_value={'hits':{'hits':[hit(newest),hit(first)]}}) as request:
            got=engine.search('최근 수정된 문서',use_llm=False)
        self.assertEqual(got['results'][0]['doc_id'],newest['doc_id'])
        self.assertEqual(request.call_args.args[2]['query']['bool']['must'],[{'match_all':{}}])
        self.assertEqual(request.call_args.args[2]['size'],2000)
    def test_written_sort_and_containment_are_independent(self):
        p=self.plan('가장 최근에 작성된 네트워크 구성도가 포함된 문서를 찾아줘','B')
        self.assertEqual(p['sort'],{'field':'written_date','direction':'desc'})
        self.assertEqual(p['keywords'],'');self.assertNotIn('document_type',p['conditions'])
        self.assertEqual(p['content_requirement']['kind'],'network_diagram')
        with patch('query.urllib.request.urlopen') as request:
            conditional_llm(p,self.ref,'http://unused','test')
        request.assert_not_called()
        clauses=es_filters(p)
        self.assertIn({'exists':{'field':'metadata.written_date'}},clauses)
        self.assertNotIn({'exists':{'field':'metadata.file_modified_at'}},clauses)
        proposal=self.plan('네트워크 구성도가 포함된 제안서를 찾아줘','B')
        self.assertEqual(proposal['filters']['document_type'],'제안서')
        self.assertNotIn('document_type',proposal['relaxable'])
    def test_containment_needs_adopted_connections_not_mentions(self):
        inventory=network_diagrams(self.blocks)
        self.assertIn('D-001',inventory);self.assertIn('D-069',inventory)
        self.assertEqual(inventory['D-001'][0]['loc']['slide'],5)
        bad=copy.deepcopy(self.blocks['D-001'])
        bad={k:v for k,v in bad.items() if 'deterministic_serialization_of_reviewed_visual_structure' not in v.get('warnings',[])}
        self.assertEqual(network_diagrams({'unadopted':bad}),{})
        self.assertEqual(network_diagrams({'mention':{'b':{'type':'paragraph','text':'네트워크 구성도 포함 예정'}}}),{})
    def test_written_date_orders_all_matches_and_separates_unknown(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[0.]*1024)
        def hit(did):
            c=next(r for r in self.rows if r['doc_id']==did)
            return {'_id':c['chunk_id'],'_source':c,'_score':1.}
        engine.retrieve=lambda p,v:([hit('D-082')],[hit('D-082')],{})
        with patch('engine.http',return_value={'hits':{'hits':[hit('D-082'),hit('D-069'),hit('D-098')]}}):
            got=engine.search('가장 최근에 작성된 네트워크 구성도가 포함된 문서를 찾아줘',use_llm=False)
        self.assertEqual(got['results'][0]['doc_id'],'D-069')
        self.assertEqual(got['undated_results'][0]['doc_id'],'D-098')
        self.assertEqual(got['date_coverage']['undated_documents'],1)
        self.assertFalse(got['date_coverage']['fallback_to_other_date'])
        self.assertTrue(any('terms' in c and 'doc_id' in c['terms'] for c in got['diagnostics']['filter_clauses']))
    def test_date_order_beats_family_latest_flag(self):
        docs=copy.deepcopy(self.docs)
        docs['D-007']['metadata']['written_date']='2026-01-01'
        engine=SearchEngine(docs,self.blocks,self.ref,lambda q:[])
        rows=[]
        for did in ['D-007','D-008']:
            c=next(r for r in self.rows if r['doc_id']==did)
            rows.append({'source':c,'chunk_id':c['chunk_id'],'score':1.})
        got=engine.group(rows,self.plan('가장 최근에 작성된 네트워크 구성도'))
        self.assertEqual(got[0]['doc_id'],'D-007')
        self.assertEqual(got[0]['representative_reason'],'requested_date_order')
    def test_date_fetch_continues_after_page_boundary(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[])
        c=self.rows[0];h={'_id':c['chunk_id'],'_source':c,'sort':['2025-01-01','id']}
        with patch('engine.http',side_effect=[{'hits':{'hits':[h]*2000}},{'hits':{'hits':[h]}}]) as request:
            got=engine.date_candidates(self.plan('작성일 최신순 문서'))
        self.assertEqual(len(got),2001);self.assertEqual(request.call_count,2)
        self.assertEqual(request.call_args.args[2]['search_after'],h['sort'])

if __name__=='__main__':unittest.main()
