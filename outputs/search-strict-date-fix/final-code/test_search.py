import io,json,unittest,copy
from pathlib import Path
from unittest.mock import patch
from query import plan_rules,apply_mode,es_filters,conditional_llm
from engine import rrf,SearchEngine,rerank,lexical_preferences,verified_preferences,condition_matches,lexical
from content import network_diagrams
from streaming import stream_search

DATA=Path(__file__).resolve().parents[2]/'outputs/search-service-001'
class SearchContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref=json.loads((DATA/'reference.json').read_text());cls.docs=json.loads((DATA/'documents.json').read_text());cls.blocks=json.loads((DATA/'blocks.json').read_text())
        cls.rows=[json.loads(s) for s in (DATA/'chunks.ndjson').read_text().splitlines()[1::2]]
    def plan(self,q,mode='A'):return apply_mode(plan_rules(q,self.ref,'2026-10-14'),mode)
    def test_verified_metadata_can_enter_candidates_without_text_overlap(self):
        p=self.plan('부가세 포함 견적','B')
        template=copy.deepcopy(self.docs['D-100'])
        unknown=copy.deepcopy(template);unknown['metadata_statuses']['vat']='not_found_text'
        wrong=copy.deepcopy(template);wrong['metadata']['vat']='별도'
        policy,ids=verified_preferences(p,{'matching':template,'unknown':unknown,'wrong':wrong},self.ref)
        self.assertEqual(ids,['matching']);self.assertFalse(policy['hard_filter'])
        p['preferred_doc_ids']=ids
        self.assertIn('matching',str(lexical(p)))
        self.assertEqual(es_filters(p),[])
    def test_log_job_and_date_both_require_source_evidence(self):
        p=self.plan('올해 백업 로그','B');template=copy.deepcopy(self.docs['D-109'])
        incidental=copy.deepcopy(template);incidental['metadata']['job_name']='정기점검'
        old=copy.deepcopy(template);old['metadata']['log_start']='2025-03-08 01:05'
        unknown=copy.deepcopy(template);unknown['metadata_statuses']['job_name']='not_found_text'
        policy,ids=verified_preferences(p,{'match':template,'incidental_backup':incidental,'modified_this_year':old,'unknown':unknown},self.ref)
        self.assertEqual(ids,['match']);self.assertEqual(policy['job_concepts'],['backup'])
        self.assertEqual(verified_preferences(self.plan('올해 여름쯤 백업 로그','B'),self.docs,self.ref),(None,[]))
    def test_log_calendar_range_includes_end_of_last_day(self):
        bounds={'gte':'2026-01-01','lte':'2026-12-31'}
        self.assertTrue(condition_matches({'log_start':'2026-12-31 23:59'},'log_start',bounds))
        self.assertFalse(condition_matches({'log_start':'2027-01-01 00:00'},'log_start',bounds))
    def test_unsupported_latest_version_cannot_inherit_metadata_priority(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[])
        p=self.plan('부가세 포함 견적','B');p['preferred_doc_ids']=['D-003']
        rows=[]
        for did,score in [('D-004',1.),('D-003',.5)]:
            c=next(r for r in self.rows if r['doc_id']==did)
            rows.append({'source':c,'chunk_id':c['chunk_id'],'score':score})
        card=engine.group(rows,p)[0]
        self.assertEqual(card['doc_id'],'D-003');self.assertTrue(card['verified_condition_match'])
        p['requested_version']='v2'
        card=engine.group(rows,p)[0]
        self.assertEqual(card['doc_id'],'D-004');self.assertFalse(card['verified_condition_match'])
    def test_client_alias_and_modes(self):
        a=self.plan('Cheongram Precision MES 견적서');b=self.plan('Cheongram Precision MES 견적서','B')
        self.assertEqual(a['filters']['client'],'청람정밀');self.assertEqual(set(b['filters']),{'client'})
        self.assertEqual(b['soft_conditions']['document_type'],'견적서')
        self.assertNotIn('target_system',a['filters']);self.assertEqual(a['soft_conditions']['target_system'],'MES')
    def test_date_role_and_reference(self):
        p=self.plan('작년 12월 DB 백업 로그');self.assertEqual(p['filters']['log_start'],{'gte':'2025-12-01','lte':'2025-12-31'})
        p=self.plan('2025년 1월 14일 파일 최종 수정일');self.assertEqual(p['filters']['file_modified_at']['gte'],'2025-01-14T00:00:00+09:00')
        self.assertNotIn('document_date',p['filters'])
    def test_approximate_season_keeps_only_explicit_year(self):
        p=self.plan('재작년 겨울 무렵 쇼핑몰 첫 견적','A')
        self.assertFalse(p['requires_clarification'])
        self.assertEqual(p['filters']['document_date'],{'gte':'2024-01-01','lte':'2024-12-31'})
        self.assertNotIn('document_date',p['soft_conditions'])
        self.assertEqual(p['date_interpretation']['policy'],'explicit_year_only')
        self.assertEqual(p['requested_version_order'],'earliest')
        self.assertTrue(self.plan('겨울쯤 견적서')['requires_clarification'])
        self.assertEqual(self.plan('재작년 견적서')['filters']['document_date']['gte'],'2024-01-01')
        self.assertFalse(self.plan('작년 여름쯤 관리 계약')['requires_clarification'])
        for q in ['새봄병원 PACS 계약서','새봄의료재단 EMR 유지보수 계약']:
            self.assertFalse(self.plan(q)['requires_clarification'])
            self.assertIsNone(self.plan(q)['date_interpretation'])
    def test_query_expansion_does_not_guess_client(self):
        from engine import lexical
        p=self.plan('운송 시스템 서버 옮긴 작업 로그','B')
        self.assertNotIn('client',p['conditions'])
        self.assertEqual(len(p['lexical_expansions']),2)
        self.assertIn('migration',str(lexical(p)))
        self.assertNotIn('target_system',p['filters'])
    def test_first_version_uses_numeric_order_not_v1_assumption(self):
        engine=SearchEngine(copy.deepcopy(self.docs),self.blocks,self.ref,lambda q:[])
        p=self.plan('처음 뽑은 가격표','B');rows=[]
        for did,version in [('D-003','v2'),('D-004','v10')]:
            engine.docs[did]['version_label']=version
            c=next(r for r in self.rows if r['doc_id']==did)
            rows.append({'source':c,'chunk_id':c['chunk_id'],'score':1.})
        card=engine.group(rows,p)[0]
        self.assertEqual(card['doc_id'],'D-003')
        self.assertEqual(card['representative_reason'],'earliest_matching_version')
        p['requested_version']='v10'
        self.assertEqual(engine.group(rows,p)[0]['doc_id'],'D-004')
        self.assertIsNone(self.plan('처음 발생한 오류 로그')['requested_version_order'])
    def test_candidates_beyond_30_are_scored_without_new_model(self):
        source=dict(self.rows[0]);source['embedding']=[1.,0.]
        rows=rrf([{'_id':str(i),'_source':source,'_score':1.} for i in range(50)],[])
        out=rerank(rows,self.plan('MES'),'R1',[1.,0.])
        self.assertEqual(len(out),50)
        self.assertEqual(sum(r['support_eligible'] for r in out),30)
    def test_weak_tail_does_not_inflate_document_support_bonus(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[])
        c=next(r for r in self.rows if r['doc_id']=='D-003');p=self.plan('MES')
        def row(score,eligible):return {'source':c,'chunk_id':c['chunk_id'],'score':score,'support_eligible':eligible}
        card=engine.group([row(.8,True),row(.7,True),row(.6,False)],p)[0]
        self.assertAlmostEqual(card['score'],.87)
        # A candidate admitted from the tail can still become the best evidence.
        card=engine.group([row(.9,False),row(.8,True),row(.7,True)],p)[0]
        self.assertAlmostEqual(card['score'],1.05)
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
        p=self.plan('청람정밀 2025년 견적서 최종본','B');self.assertEqual(set(p['filters']),{'client','document_date','document_type'})
        boosts=lexical_preferences(p);self.assertEqual(len(boosts),1)
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
        self.assertEqual(out['relaxed_conditions'],[])
        self.assertEqual(len(seen),1)
        self.assertIn('document_date',seen[0])
    def test_contract_coverage_is_not_signing_or_written_year(self):
        p=self.plan('청람정밀 2025년 ERP 유지보수 계약','B')
        self.assertIn('contract_period',p['required_dates'])
        self.assertNotIn('document_date',p['filters'])
        clauses=es_filters(p)
        self.assertIn({'range':{'metadata.contract_start':{'lte':'2025-12-31'}}},clauses)
        self.assertIn({'range':{'metadata.contract_end':{'gte':'2025-01-01'}}},clauses)
        for q in ['2025년에 작성된 ERP 유지보수 계약','2025년 체결한 유지보수 계약']:
            self.assertNotIn('contract_period',self.plan(q,'B')['required_dates'])
    def test_no_results_never_removes_dates_in_either_mode(self):
        for mode in ['A','B']:
            engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[]);seen=[]
            def none(p,v):seen.append(copy.deepcopy(p['filters']));return [],[],{}
            engine.retrieve=none
            got=engine.search('다온로지스 2030년 견적서',mode=mode,use_llm=False)
            self.assertEqual(got['results'],[]);self.assertEqual(got['relaxed_conditions'],[])
            self.assertTrue(all(x['document_date']['gte']=='2030-01-01' for x in seen))
    def test_date_guard_rejects_unknown_and_outside_and_other_versions(self):
        docs=copy.deepcopy(self.docs);engine=SearchEngine(docs,self.blocks,self.ref,lambda q:[])
        p=self.plan('2024년 12월 견적서','B')
        rows=[]
        for did in ['D-077','D-078']:
            c=next(r for r in self.rows if r['doc_id']==did)
            rows.append({'source':c,'chunk_id':c['chunk_id'],'score':1.})
        cards=engine.group(rows,p)
        self.assertEqual([c['doc_id'] for c in cards],['D-077'])
        self.assertEqual(cards[0]['other_versions'],[])
        docs['D-077']['metadata_statuses']['document_date']='not_found_text'
        self.assertEqual(engine.group(rows,p),[])
    def test_dated_backup_search_requires_actual_job_both_branches(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[]);seen=[]
        def none(p,v):seen.append(copy.deepcopy(p));return [],[],{}
        engine.retrieve=none
        engine.search('올해 백업 로그',use_llm=False)
        p=seen[0];self.assertIn('log_start',p['filters']);self.assertIn('D-063',p['required_job_doc_ids'])
        self.assertNotIn('D-073',p['required_job_doc_ids'])
        self.assertIn({'terms':{'doc_id':p['required_job_doc_ids']}},es_filters(p))
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
    def test_streamed_ranks_match_search_without_changing_results(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[0.]*1024)
        source=next(r for r in self.rows if r['doc_id']=='D-003')
        hits=[{'_id':source['chunk_id'],'_source':source,'_score':1.}]
        result={'hits':{'hits':hits},'took':1}
        with patch('engine.http',return_value=result):
            baseline=engine.search('청람정밀 MES 견적서',ranker='R1',use_llm=False)
            events=[json.loads(line) for line in stream_search(engine,'청람정밀 MES 견적서','B','R1',None,False) if line.strip()]
        kinds=[e['stage'] for e in events]
        self.assertEqual(kinds[:3],['started','analysis','searching'])
        self.assertEqual(set(kinds[3:5]),{'bm25','vector'})
        self.assertEqual(kinds[5:],['combined','adjusted','complete'])
        final=events[-1]['data'];self.assertEqual(final['results'],baseline['results'])
        self.assertEqual(final['diagnostics'],baseline['diagnostics'])
        combined=next(e['data']['rows'] for e in events if e['stage']=='combined')[0]
        self.assertEqual(combined['branch_ranks'],{'bm25':1,'vector':1})
        self.assertEqual(combined['title'],self.docs[source['doc_id']]['file_name'])
        self.assertEqual(combined['chunk_id'],source['chunk_id']);self.assertNotIn('score',combined)
        self.assertNotIn('embedding',combined);self.assertTrue(combined['locations'])
    def test_stream_error_does_not_claim_completion(self):
        class Broken:
            def search(self,*args,**kwargs):raise ConnectionError('private server detail')
        events=[json.loads(x) for x in stream_search(Broken(),'test','B','R1',None,False) if x.strip()]
        self.assertEqual([x['stage'] for x in events],['started','error'])
        self.assertNotIn('private server detail',str(events))
    def test_clarification_stream_has_no_invented_rankings(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:self.fail('must not embed'))
        events=[json.loads(x) for x in stream_search(engine,'청람정밀 말고 계약서','B','R1',None,False) if x.strip()]
        self.assertEqual([x['stage'] for x in events],['started','analysis','complete'])
        self.assertEqual(events[-1]['data']['status'],'needs_clarification')
    def test_date_stream_labels_global_sort_instead_of_reranker(self):
        engine=SearchEngine(self.docs,self.blocks,self.ref,lambda q:[0.]*1024)
        source=next(r for r in self.rows if r['doc_id']=='D-069')
        h={'_id':source['chunk_id'],'_source':source,'_score':1.}
        with patch('engine.http',return_value={'hits':{'hits':[h]},'took':1}):
            events=[json.loads(x) for x in stream_search(engine,'가장 최근에 작성된 네트워크 구성도가 포함된 문서','B','R1',None,False) if x.strip()]
        kinds=[e['stage'] for e in events];self.assertIn('date_order',kinds);self.assertNotIn('adjusted',kinds)
        self.assertTrue(next(e['data'] for e in events if e['stage']=='combined')['date_order_overrides'])

if __name__=='__main__':unittest.main()
