import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import field_search as s
IX=s.E.read_json(s.ROOT.parent/'rule-search-run-004/index.json')
PARSED=s.old.base.unique_records(s.ROOT.parent/'parsing-run-003/parsed.jsonl')
META=s.old.base.unique_records(s.ROOT.parent/'enrichment-run-001/enriched.jsonl')
TERMS=s.E.read_json(s.ROOT.parent/'rag-enrichment-v1/reference-data.json')['system_terms']
B=s.prepare(IX,PARSED,META)
class Fields(unittest.TestCase):
 def test_cutover_general_job_rule(self):
  self.assertIn('intent:cutover',s.intent_tokens('ABC 전환 작업 로그'));self.assertIn('intent:cutover',s.intent_tokens('ABC_MIGRATION_CUTOVER'))
 def test_generic_conversion_not_cutover(self):
  for x in ('클라우드 전환 제안','화면 전환','전환율 개선'):self.assertNotIn('intent:cutover',s.intent_tokens(x))
 def test_autoscale_paraphrase(self):
  for x in ('자동으로 인스턴스를 확장하는 설계','자동 서버 증설','학사 웹 (오토스케일 그룹)','ASG_AUTOSCALE'):self.assertIn('intent:autoscale',s.intent_tokens(x))
 def test_automatic_unrelated(self):
  for x in ('자동 백업','자동으로 비용을 늘리는 계획','수동 서버 증설'):self.assertNotIn('intent:autoscale',s.intent_tokens(x))
 def test_field_weights_not_document_specific(self):self.assertEqual(set(s.WEIGHTS),{'job','role','identifier','title','system','client'})
 def test_unknown_job_not_filled(self):self.assertEqual(B['features']['D-044']['job'],[])
 def test_role_from_actual_named_column(self):
  roles=B['features']['D-061']['role'];self.assertTrue(any('오토스케일' in v['text'] for v in roles));self.assertTrue(all(v['evidence'][0]['kind']=='cell' for v in roles))
 def test_not_every_table_cell_is_role(self):self.assertFalse(any('10.54.130.11' in v['text'] for v in B['features']['D-061']['role']))
 def test_log_context_every_chunk(self):
  chunks=[eid for eid,e in IX['entries'].items() if e['doc_id']=='D-036' and e['kind']=='native_chunk']
  self.assertTrue(chunks);self.assertTrue(all('TMS_MIGRATION_CUTOVER' in B['log_contexts'][eid]['text'] for eid in chunks))
 def test_no_scan_context(self):self.assertFalse(any(IX['entries'][eid]['doc_id']=='D-044' for eid in B['log_contexts']))
 def test_body_and_references_unchanged(self):
  view=s.view(IX,B,context=True,intents=True)
  for eid,entry in IX['entries'].items():
   for field in ('text','source_refs','context_refs','context_header'):self.assertEqual(entry[field],view['entries'][eid][field])
 def test_context_evidence_resolves_within_document(self):
  for eid,c in B['log_contexts'].items():
   doc=IX['entries'][eid]['doc_id'];blocks={b['block_id']:b for b in PARSED[doc]['blocks']}
   for e in c['evidence']:
    if e['kind']=='block':self.assertIn(e['quote'],blocks[e['ref']]['text'])
 def test_duplicate_field_values_do_not_multiply(self):
  duplicate=copy.deepcopy(B);duplicate['features']['D-036']['job']*=10
  a=s.search(IX,B,'TMS','2026-10-17',TERMS);b=s.search(IX,duplicate,'TMS','2026-10-17',TERMS)
  self.assertEqual([(r['doc_id'],r['score']) for r in a['results']],[(r['doc_id'],r['score']) for r in b['results']])
 def test_disabled_features_exact_baseline(self):
  a=s.search(IX,B,'TMS 전환 작업 로그','2026-10-17',TERMS,weights=False);b=s.old.search(IX,'TMS 전환 작업 로그','2026-10-17',TERMS)
  self.assertEqual([(r['doc_id'],r['score']) for r in a['results']],[(r['doc_id'],r['score']) for r in b['results']])
 def test_identifier_query_does_not_expand_embedded_database(self):
  t=s.query_feature_tokens('alpha-db02',IX,True);self.assertIn('w:alpha-db02',t);self.assertNotIn('concept:database',t)
 def test_explicit_database_term_still_expands(self):self.assertIn('concept:database',s.query_feature_tokens('DB alpha-db02',IX,True))
 def test_identifier_in_phrase_preserves_exact_term(self):
  t=s.query_feature_tokens('node-db01 오류 로그',IX,True);self.assertIn('w:node-db01',t);self.assertIn('concept:error',t);self.assertNotIn('concept:database',t)
 def test_empty_filtered_results_not_relaxed(self):self.assertEqual(s.search(IX,B,'2099년 TMS 로그','2026-10-17',TERMS)['results'],[])
 def test_score_breakdown_and_not_answer_truth(self):
  for r in s.search(IX,B,'TMS','2026-10-17',TERMS)['results']:
   self.assertAlmostEqual(r['score'],r['lexical_score']+r['field_score']);self.assertFalse(r['conditions_verified'])
if __name__=='__main__':unittest.main()
