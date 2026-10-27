import copy
import importlib.util
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pipeline as p
spec=importlib.util.spec_from_file_location('native_search_eval',ROOT/'evaluate.py');ev=importlib.util.module_from_spec(spec);spec.loader.exec_module(ev)
SOURCE=p.unique_records(ROOT.parent/'parsing-run-003/parsed.jsonl')
META=p.unique_records(ROOT.parent/'enrichment-run-001/enriched.jsonl')
REF=p.enrich.read_json(ROOT.parent/'rag-enrichment-v1/reference-data.json')

def fixture(text):
    record=copy.deepcopy(SOURCE['D-005']);block=copy.deepcopy(record['blocks'][0]);block.update(text=text,claims=[],evidence=[],context_ids=[],content_refs=[],heading_path=[])
    record['blocks']=[block];record['coverage']['units'][0]['block_ids']=[block['block_id']]
    return record,p.enrich.extract(record,REF)

class PipelineTests(unittest.TestCase):
    def chunks(self,identity,config=None):return p.make_chunks(SOURCE[identity],META[identity],config)
    def test_roundtrip_coverage_and_determinism(self):
        a=self.chunks('D-005');self.assertEqual(a,self.chunks('D-005'));self.assertEqual(p.validate_chunks(a,SOURCE['D-005'],META['D-005']),[])
    def test_native_table_body_rows_are_not_all_headers(self):
        r=self.chunks('D-009');a=r['table_audit'][0]
        self.assertEqual(len(a['header_block_ids']),1);self.assertGreater(len(a['native_header_rows']),1)
    def test_split_table_has_header_references(self):
        config={**p.CONFIG,'body_char_limit':80,'long_block_overlap_chars':10};r=self.chunks('D-003',config)
        self.assertEqual(p.validate_chunks(r,SOURCE['D-003'],META['D-003']),[])
        tables=[c for c in r['chunks'] if c['table_id']]
        self.assertGreater(len(tables),1);self.assertTrue(all('품목' in c['table_header_text'] for c in tables))
    def test_scan_has_no_invented_body(self):
        r=self.chunks('D-044');self.assertEqual(r['chunks'],[]);self.assertEqual(len(r['pending_visual_units']),2)
        ix=p.build_index([r],REF['clients']);self.assertEqual(ix['documents']['D-044']['native_chunk_count'],0)
    def test_long_block_references_cover_every_character(self):
        r,m=fixture('문장 테스트입니다. '*500);o=p.make_chunks(r,m)
        self.assertGreater(len(o['chunks']),1);self.assertEqual(p.validate_chunks(o,r,m),[])
        self.assertTrue(all(c['body_chars']<=1200 for c in o['chunks']))
    def test_forged_text_rejected(self):
        r=self.chunks('D-005');r['chunks'][0]['text']+='없는 사실';self.assertTrue(p.validate_chunks(r,SOURCE['D-005'],META['D-005']))
    def test_pending_metadata_never_becomes_filter(self):
        r=self.chunks('D-044');self.assertNotIn('금액',r['filter_metadata']);self.assertEqual(r['metadata_statuses']['금액'],'pending_vision')
    def test_filters_exclude_unknown_values(self):
        ix=p.build_index([self.chunks('D-044'),self.chunks('D-005')],REF['clients'])
        allowed,unknown=p.apply_filters(ix,[{'field':'금액','op':'gte','value':'1'}])
        self.assertEqual(allowed,{'D-005'});self.assertEqual(unknown,{'D-044'})
    def test_unsupported_latest_filter_rejected(self):
        ix=p.build_index([self.chunks('D-005')],REF['clients'])
        with self.assertRaises(ValueError):p.apply_filters(ix,[{'field':'최신본','op':'eq','value':'Y'}])
    def test_identifier_search_keeps_exact_error_code(self):
        ix=p.build_index([self.chunks('D-010'),self.chunks('D-018')],REF['clients'])
        result=p.search(ix,'ORA-01555')['results'];self.assertEqual(result[0]['doc_id'],'D-010')
        self.assertFalse(result[0]['conditions_verified'])
    def test_new_snapshot_excludes_deleted_document(self):
        both=p.build_index([self.chunks('D-010'),self.chunks('D-018')],REF['clients'])
        remaining=p.build_index([self.chunks('D-018')],REF['clients'])
        self.assertIn('D-010',both['documents']);self.assertNotIn('D-010',remaining['documents'])
        self.assertTrue(all(e['doc_id']=='D-018' for e in remaining['entries'].values()))
    def test_document_score_is_maximum_of_all_entries(self):
        ix=p.build_index([self.chunks('D-010'),self.chunks('D-018')],REF['clients'])
        result=p.search(ix,'오류 MES ORA-01555')['results']
        self.assertTrue(all(r['score']==max(e['score'] for e in r['evidence']) for r in result))
        self.assertEqual([r['score'] for r in result],sorted([r['score'] for r in result],reverse=True))
    def test_hit_at_5_and_mrr_boundaries(self):
        self.assertEqual(ev.query_metric(['a','b','c','d','e'],['e']),{'first_rank':5,'hit_at_5':1,'rr_at_10':.2})
        self.assertEqual(ev.query_metric(['a','b','c','d','e','f'],['f'])['hit_at_5'],0)
        self.assertEqual(ev.query_metric([],['a'])['rr_at_10'],0)
    def test_context_does_not_replace_literal_body(self):
        r=self.chunks('D-005')
        for c in r['chunks']:self.assertNotIn('거래처=청람정밀',c['text']);self.assertIn('거래처=청람정밀',c['context_header'])
    def test_technical_identifier_not_split_into_bigrams(self):
        self.assertIn('w:ct-2025-0112',p.tokens('CT-2025-0112'));self.assertIn('w:10.21.10.11',p.tokens('10.21.10.11'))
    def test_noncanonical_or_invalid_date_rejected(self):
        ix=p.build_index([self.chunks('D-005')],REF['clients'])
        for value in ('2025-2-01','2025-02-30','작년'):
            with self.assertRaises(ValueError):p.apply_filters(ix,[{'field':'문서일자','op':'gte','value':value}])
    def test_date_range_matches_known_contract_period(self):
        ix=p.build_index([self.chunks('D-005')],REF['clients'])
        actual=ix['documents']['D-005']['metadata']['계약시작일']
        self.assertEqual(p.apply_filters(ix,[{'field':'계약시작일','op':'gte','value':actual}])[0],{'D-005'})
    def test_malformed_filter_shape_rejected(self):
        ix=p.build_index([self.chunks('D-005')],REF['clients'])
        for filters in ({},[None]):
            with self.assertRaises(ValueError):p.apply_filters(ix,filters)
    def test_repeated_header_source_refs_reach_index(self):
        r=self.chunks('D-003',{**p.CONFIG,'body_char_limit':80,'long_block_overlap_chars':10})
        ix=p.build_index([r],REF['clients'])
        repeated=[c for c in r['chunks'] if c['context_refs']]
        self.assertTrue(repeated)
        for c in repeated:self.assertEqual(ix['entries'][c['chunk_id']]['context_refs'],c['context_refs'])
    def test_no_matching_terms_returns_empty(self):
        ix=p.build_index([self.chunks('D-005')],REF['clients']);self.assertEqual(p.search(ix,'zzzzunknownidentifier')['results'],[])
    def test_page_slide_boundaries_preserved(self):
        r=self.chunks('D-001')
        for c in r['chunks']:self.assertLessEqual(len({ref['loc'].get('slide') for ref in c['source_refs']}),1)

if __name__=='__main__':unittest.main()
