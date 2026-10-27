import copy,importlib.util,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import enrich as e
spec=importlib.util.spec_from_file_location('legacy_rule_tests',ROOT.parent/'rag-enrichment-v1/tests/test_rules.py');legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
RulesTests=legacy.RulesTests
REF=legacy.REF;RECORDS=legacy.RECORDS

class DateRoles(unittest.TestCase):
 def output(self,r):
  o=e.extract(r,REF);self.assertEqual(e.check_output(o,r),[]);return o
 def with_label(self,label):
  r=copy.deepcopy(RECORDS['D-005']);r['blocks'][2]['text']=label;return r
 def test_explicit_written_date_resolves_draft_separately(self):
  o=self.output(self.with_label('작성일: 2025-02-07'))
  self.assertEqual(o['fields']['문서일자']['value'],'2025-02-07')
  self.assertEqual(o['date_context']['selected_roles'],['explicit_written_date'])
  self.assertIn(('signing_block_printed_date','2025-02-19'),{(v['role'],v['value']) for v in o['date_context']['observations']})
 def test_written_date_label_with_spaces(self):self.assertEqual(self.output(self.with_label('문서 작성일: 2025-02-07'))['fields']['문서일자']['value'],'2025-02-07')
 def test_two_written_dates_are_ambiguous(self):
  o=self.output(self.with_label('작성일: 2025-02-07\n작성일: 2025-02-08'));self.assertEqual(o['fields']['문서일자']['status'],'needs_review')
 def test_invalid_written_date_is_not_replaced_by_signing_date(self):
  o=self.output(self.with_label('작성일: 2025-02-30'));self.assertEqual(o['fields']['문서일자']['status'],'needs_review')
 def test_original_draft_remains_unresolved(self):
  o=self.output(RECORDS['D-005']);self.assertIsNone(o['fields']['문서일자']['value']);self.assertEqual(o['date_context']['selected_roles'],[])
 def test_cover_not_converted_to_submission(self):
  o=self.output(RECORDS['D-002']);self.assertEqual(o['fields']['문서일자']['value'],'2025-01-13');self.assertEqual(o['date_context']['selected_roles'],['cover_date'])
 def test_signature_date_is_observed_not_verified(self):
  o=self.output(RECORDS['D-006']);self.assertFalse(o['date_context']['actual_signature_verified'])
 def test_no_dates_from_scan(self):
  o=self.output(RECORDS['D-044']);self.assertEqual(o['date_context']['observations'],[]);self.assertEqual(o['fields']['문서일자']['status'],'pending_vision')
 def test_contract_period_does_not_become_document_date(self):
  o=self.output(RECORDS['D-005']);self.assertIn('contract_period_start',{x['role'] for x in o['date_context']['observations']});self.assertIsNone(o['fields']['문서일자']['value'])
 def test_mail_subject_evidence(self):
  o=self.output(RECORDS['D-030']);self.assertIn('system.mail_subject',o['fields']['대상시스템']['rule_id']);self.assertTrue(any(v['kind']=='block' for v in o['fields']['대상시스템']['evidence']))
 def test_neutral_mail_filename_uses_current_subject(self):
  r=copy.deepcopy(RECORDS['D-030']);r['source']['file_name']='견적 문의.txt';r['source']['relative_path']='sites/test/Shared Documents/다온/견적 문의.txt'
  self.assertEqual(self.output(r)['fields']['대상시스템']['value'],'WMS')
 def test_forwarded_mail_subject_not_used(self):
  r=copy.deepcopy(RECORDS['D-030']);r['blocks'][0]['text']=r['blocks'][0]['text'].replace('WMS','ERP')
  o=self.output(r);self.assertEqual(o['fields']['대상시스템']['status'],'needs_review')
 def test_explicit_system_precedes_subject(self):
  r=copy.deepcopy(RECORDS['D-030']);r['blocks'][1]['text']='대상 시스템: MES'
  self.assertEqual(self.output(r)['fields']['대상시스템']['value'],'MES')
 def test_observed_value_must_exist_in_quote(self):
  o=self.output(RECORDS['D-005']);o['date_context']['observations'][0]['value']='2025-02-07';self.assertIn('observed date value is absent from cited block',e.check_output(o,RECORDS['D-005']))
 def test_selected_roles_cannot_be_assigned_to_unresolved_date(self):
  o=self.output(RECORDS['D-005']);o['date_context']['selected_roles']=['signing_block_printed_date'];self.assertTrue(e.check_output(o,RECORDS['D-005']))
 def test_extraction_does_not_mutate_input(self):
  r=copy.deepcopy(RECORDS['D-005']);before=e.record_hash(r);self.output(r);self.assertEqual(e.record_hash(r),before)

if __name__=='__main__':unittest.main()
