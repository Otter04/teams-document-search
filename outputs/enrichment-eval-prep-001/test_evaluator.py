"""Evaluator regression tests. Gold-shaped responses are synthetic fixtures, never model evidence."""
import copy
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import contract as c
import run

class EvaluatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold={g['doc_id']:g for g in run.read(run.HERE/'private/gold.json')}
        cls.items={i['doc_id']:i for i in run.manifest()['documents']}
        cls.packets={d:run.packet(i) for d,i in cls.items.items()}

    def fixture(self,d='H-021'):return c.candidate_from_gold(self.gold[d])
    def score(self,d,x):return c.metrics(c.score_fields(x,self.gold[d],self.packets[d],not c.validate(x,self.packets[d])))
    def test_all_twenty_gold_fixture_shapes(self):
        for d in self.gold:
            x=self.fixture(d);self.assertEqual(c.validate(x,self.packets[d]),[])
            self.assertEqual(self.score(d,x)['recall'],1)
    def test_source_scan_cells(self):
        counts={d:sum(len(b.get('cells',[])) for b in self.packets[d]['document']['blocks']) for d in ['D-044','D-102','H-020']}
        self.assertEqual(counts,{'D-044':8,'D-102':8,'H-020':9})
    def test_scans_do_not_impersonate_model_run(self):
        for d in ['D-044','D-102','H-020']:
            doc=self.packets[d]['document'];self.assertEqual(doc['record_kind'],'design_example')
            self.assertTrue(all(r['method']=='manual_design' and r['model_id'] is None for r in doc['runs']))
    def test_numeric_corruption(self):
        x=self.fixture('H-020');x['fields']['금액']['value']='7000001'
        self.assertEqual(self.score('H-020',x)['critical_errors'],1)
        self.assertLess(self.score('H-020',x)['recall'],1)
    def test_no_normalizing_different_identifier(self):
        x=self.fixture();x['fields']['오류코드']['value']='E-SENSOR-18'
        self.assertLess(self.score('H-021',x)['recall'],1)
    def test_date_role_error(self):
        x=self.fixture('D-002');x['fields']['작성일']=copy.deepcopy(x['fields']['표지일'])
        self.assertEqual(self.score('D-002',x)['critical_errors'],1)
    def test_ambiguous_draft_date_remains_in_abstention(self):
        x=self.fixture('D-005');x['fields']['문서일자'].update(value='2025-02-19',status='extracted',reason=None)
        s=self.score('D-005',x);self.assertEqual(s['critical_errors'],1);self.assertEqual(s['unresolved_assignments'],1)
    def test_all_null_does_not_pass(self):
        x=self.fixture()
        for f in x['fields'].values():f.update(value=None,status='not_found_in_input',evidence=[],reason='not found')
        s=self.score('H-021',x);self.assertIsNone(s['precision']);self.assertEqual(s['recall'],0)
    def test_missing_response_keeps_recall_denominator(self):
        s=c.metrics(c.score_fields(None,self.gold['H-021'],self.packets['H-021'],False))
        self.assertGreater(s['needed'],0);self.assertEqual(s['recall'],0)
    def test_aliases_are_bounded(self):
        x=self.fixture('D-044');x['fields']['거래처']['value']='의료법인 새봄의료재단'
        self.assertEqual(self.score('D-044',x)['recall'],1)
        x['fields']['거래처']['value']='라움정보기술 주식회사';self.assertLess(self.score('D-044',x)['recall'],1)
    def test_fabricated_quote_rejected(self):
        x=self.fixture();x['fields']['오류코드']['evidence'][0]['quote']='이 문장은 없음'
        self.assertTrue(c.validate(x,self.packets['H-021']))
    def test_real_but_irrelevant_quote_not_supported(self):
        x=self.fixture();x['fields']['오류코드']['evidence'][0]['quote']='MES'
        self.assertFalse(c.validate(x,self.packets['H-021']))
        self.assertLess(self.score('H-021',x)['recall'],1)
        self.assertEqual(self.score('H-021',x)['alternative_evidence_pending'],1)
    def test_dangling_reference(self):
        x=self.fixture();x['fields']['오류코드']['evidence'][0]['ref']='missing'
        self.assertTrue(c.validate(x,self.packets['H-021']))
    def test_nonexistent_dates(self):
        x=self.fixture();x['fields']['작성일']['value']='2026-02-30'
        self.assertTrue(c.validate(x,self.packets['H-021']))
    def test_pending_without_visual_units(self):
        x=self.fixture('H-020');x['fields']['사업명'].update(status='pending_vision')
        self.assertTrue(c.validate(x,self.packets['H-020']))
    def test_missing_field_is_schema_failure(self):
        x=self.fixture();del x['fields']['거래처'];self.assertTrue(c.validate(x,self.packets['H-021']))
    def test_extra_field_is_schema_failure(self):
        x=self.fixture();x['fields']['제출일']=copy.deepcopy(x['fields']['작성일']);self.assertTrue(c.validate(x,self.packets['H-021']))
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):c.loads('{"a":1,"a":2}')
    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):c.loads('{"a":NaN}')
    def test_truncated_json_not_repaired(self):
        with self.assertRaises(ValueError):c.loads('{"fields":')
    def test_malformed_evidence_does_not_crash_scoring(self):
        x=self.fixture();x['fields']['오류코드']['evidence']=None
        self.assertTrue(c.validate(x,self.packets['H-021']));self.score('H-021',x)
    def test_metadata_evidence_review_cannot_change_wrong_value(self):
        x=self.fixture();x['fields']['오류코드']['value']='E-SENSOR-18'
        fs=c.score_fields(x,self.gold['H-021'],self.packets['H-021'],True)
        review={'response_sha256':'hash','reviewer_id':'test','reviewer_kind':'assistant','metadata_evidence_reviews':[{'field':'오류코드','verdict':'supported','reason':'test'}]}
        run.apply_alternative_evidence_review(fs,review,{'response_sha256':'hash'})
        self.assertFalse(next(f for f in fs if f['field']=='오류코드')['correct_supported_value'])
    def test_summary_no_auto_fact_score(self):
        x=self.fixture();x['summary']=[{'text':'영구적으로 해결됐다.','evidence':x['fields']['오류코드']['evidence']}]
        self.assertEqual(c.validate(x,self.packets['H-021']),[])
        self.assertIsNone(run.check_review(None,{'response_sha256':'hash'},self.gold['H-021'],x,self.packets['H-021']))
    def test_stale_semantic_review_rejected(self):
        with self.assertRaises(ValueError):run.check_review({'response_sha256':'old'},{'response_sha256':'new'},self.gold['H-021'],self.fixture(),self.packets['H-021'])
    def test_summary_review_requires_claims_for_every_sentence(self):
        x=self.fixture();x['summary']=[{'text':'test','evidence':x['fields']['오류코드']['evidence']}]
        r={'response_sha256':'hash','reviewer_id':'test','reviewer_kind':'assistant','status':'completed','sentences':[{'index':0,'source_text':'test','atomic_claims':[]}]}
        self.assertIsNone(run.check_review(r,{'response_sha256':'hash'},self.gold['H-021'],x,self.packets['H-021']))
    def test_preflight_and_prepare_requests_offline(self):
        with patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
            self.assertEqual(run.preflight()['fields'],460)
            for item in self.items.values():
                bodies=[run.request_body(m,item) for m in run.manifest()['models']]
                self.assertEqual(bodies[0]['messages'],bodies[1]['messages'])
                self.assertEqual(bodies[0]['response_format'],bodies[1]['response_format'])
                self.assertNotIn('summary_facts',json.dumps(bodies,ensure_ascii=False))
    def test_prepare_path_does_not_read_private_answers(self):
        old=run.read
        def restricted(p):
            if 'private' in Path(p).parts:raise AssertionError('private read from request builder')
            return old(p)
        with patch.object(run,'read',side_effect=restricted):run.request_body(run.manifest()['models'][0],self.items['H-020'])
    def test_empty_run_not_successful(self):
        with tempfile.TemporaryDirectory() as t,patch.object(run,'assert_frozen',return_value={}),patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
            result=run.evaluate(Path(t)/'responses',Path(t)/'report')
            self.assertTrue(all(x['status']=='not_run' and x['valid_documents']==0 and x['metadata']['recall']==0 for x in result))
    def test_saved_envelope_integration(self):
        with tempfile.TemporaryDirectory() as t,patch.object(run,'assert_frozen',return_value={}):
            t=Path(t);folder=t/'responses';folder.mkdir();model=run.manifest()['models'][0];did='H-021'
            req=run.request_body(model,self.items[did]);candidate=self.fixture()
            envelope={'model':model,'doc_id':did,'request_sha256':c.digest(req),'response':{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(candidate,ensure_ascii=False)}}],'usage':{'prompt_tokens':10,'completion_tokens':20,'cost':0.0}},'elapsed_ms':1}
            run.write(folder/'one.json',envelope);result=run.evaluate(folder,t/'report')
            self.assertEqual(result[0]['status'],'incomplete_responses');self.assertEqual(result[0]['valid_documents'],1)
            reviews=run.read(t/'report/semantic-review.template.json')
            self.assertNotIn('model',reviews[0]);self.assertIn('candidate_id',reviews[0])
            envelope['response']['choices'][0]['finish_reason']='length';run.write(folder/'one.json',envelope)
            result=run.evaluate(folder,t/'report');self.assertEqual(result[0]['valid_documents'],0)
    def test_wrong_request_hash_and_duplicate_envelope(self):
        with tempfile.TemporaryDirectory() as t:
            t=Path(t);m=run.manifest()['models'][0];d='H-021';r={'model':m,'doc_id':d,'request_sha256':'bad','response':{}}
            run.write(t/'one.json',r)
            with self.assertRaises(ValueError):run.load_responses(t)
            r['request_sha256']=c.digest(run.request_body(m,self.items[d]));run.write(t/'one.json',r);run.write(t/'two.json',r)
            with self.assertRaises(ValueError):run.load_responses(t)
    def test_frozen_file_tampering_detected(self):
        with tempfile.TemporaryDirectory() as t:
            t=Path(t);(t/'input.txt').write_text('original')
            run.write(t/'freeze.json',{'files':{'input.txt':run.filehash(t/'input.txt')},'external_dependencies':{}})
            with patch.object(run,'HERE',t):
                run.assert_frozen();(t/'input.txt').write_text('changed')
                with self.assertRaises(ValueError):run.assert_frozen()
    def test_explicit_semantic_review_tracks_unsupported_claim(self):
        x=self.fixture();ev=x['fields']['오류코드']['evidence'];x['summary']=[{'text':'영구적으로 해결됐다.','evidence':ev}]
        r={'response_sha256':'hash','reviewer_id':'synthetic-test-reviewer','reviewer_kind':'assistant','status':'completed','sentences':[{'index':0,'source_text':'영구적으로 해결됐다.','atomic_claims':[{'text':'영구 해결','verdict':'unsupported','reason':'Source observes only 30 minutes.','evidence':[],'covered_gold_fact_ids':[]}]}]}
        result=run.check_review(r,{'response_sha256':'hash'},self.gold['H-021'],x,self.packets['H-021'])
        self.assertEqual(result['unsupported'],1);self.assertEqual(result['facts_covered'],0)

if __name__=='__main__':unittest.main()
