import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from quality import check_quality,validate_response,convert_checked,base,apply_policy

def wire():
    return dict(status='complete',texts=[dict(kind='heading',text='시험용 문서의 제목',bbox=[.1,.05,.9,.15])],tables=[],figures=[],warnings=[])
def cell(row=1,col=1,text='정상적으로 읽은 값'):
    return dict(row=row,column=col,row_span=1,column_span=1,text=text,value_status='known',role='data',bbox=[.1,.2,.4,.4])
def table(cells=None):
    return dict(bbox=[.1,.2,.8,.6],row_count=1,column_count=1,header_rows=[],header_status='none',cells=cells or [cell()])
def figure():
    return dict(kind='diagram',bbox=[.1,.2,.8,.8],nodes=[],relations=[],claims=[])
def codes(w,context=None):return {i['code'] for i in check_quality(w,context)}
def response(w,finish='stop'):
    return dict(model='qwen/qwen3.6-35b-a3b',provider='DeepInfra',choices=[dict(finish_reason=finish,message=dict(content=json.dumps(w,ensure_ascii=False)))])

class QualityTests(unittest.TestCase):
    def test_good_candidate(self):self.assertEqual(validate_response(response(wire()),{},'qwen/qwen3.6-35b-a3b')['decision'],'candidate')
    def test_exact_text_same_region_is_duplicate(self):
        w=wire();w['texts'].append(copy.deepcopy(w['texts'][0]));self.assertIn('DUPLICATE_LITERAL',codes(w))
    def test_same_text_separate_regions_is_allowed(self):
        w=wire();w['texts'].append({**w['texts'][0],'bbox':[.1,.7,.9,.8]});self.assertFalse(codes(w))
    def test_source_count_finds_duplicate_with_wrong_bbox(self):
        w=wire();w['texts'].append({**w['texts'][0],'bbox':[.1,.7,.9,.8]})
        ctx=[dict(block_id='a',text=w['texts'][0]['text'])]
        self.assertIn('DUPLICATE_SOURCE_LITERAL_REVIEW',codes(w,ctx))
    def test_source_repeats_same_count_is_allowed(self):
        w=wire();w['texts'].append({**w['texts'][0],'bbox':[.1,.7,.9,.8]})
        ctx=[dict(block_id=str(i),text=t['text']) for i,t in enumerate(w['texts'])]
        self.assertFalse(codes(w,ctx))
    def test_same_numbers_in_different_cells_allowed(self):
        w=wire();w['tables']=[table([cell(text='1'),cell(col=2,text='1')])];w['tables'][0]['column_count']=2
        self.assertFalse(codes(w));self.assertFalse(base.check_wire(w))
    def test_identical_long_values_different_cell_slots_allowed(self):
        w=wire();w['tables']=[table([cell(),cell(col=2)])];self.assertNotIn('DUPLICATE_LITERAL',codes(w))
    def test_cell_slot_duplicate(self):
        w=wire();w['tables']=[table([cell(),cell()])];self.assertIn('DUPLICATE_CELL_SLOT',codes(w))
    def test_whole_table_duplicate(self):
        w=wire();w['tables']=[table(),table()];self.assertIn('DUPLICATE_TABLE',codes(w))
    def test_whole_table_separate_regions_allowed(self):
        w=wire();a=table();b=table();b['bbox']=[.1,.7,.8,.9];w['tables']=[a,b];self.assertNotIn('DUPLICATE_TABLE',codes(w))
    def test_node_and_text_duplicate(self):
        w=wire();f=figure();f['nodes']=[dict(id='a',label='목표 1\n시험용 문서의 제목',bbox=w['texts'][0]['bbox'])];w['figures']=[f]
        self.assertIn('DUPLICATE_LITERAL',codes(w))
    def test_short_label_repetition_not_automatically_wrong(self):
        w=wire();w['texts']=[dict(kind='paragraph',text='1',bbox=[.1,.2,.3,.4])]*2;self.assertFalse(codes(w))
    def test_known_empty_cell(self):
        w=wire();w['tables']=[table([cell(text='')])];self.assertIn('KNOWN_CELL_EMPTY',codes(w))
    def test_unreadable_complete_conflict(self):
        w=wire();c=cell();c['value_status']='unreadable';w['tables']=[table([c])]
        self.assertIn('COMPLETE_WITH_UNREADABLE_CELL',codes(w));self.assertIn('UNREADABLE_CELL_WITH_TEXT',codes(w))
    def test_partial_unreadable_text_review_not_automatic_correction(self):
        w=wire();w.update(status='partial',warnings=['판독 어려움']);c=cell();c['value_status']='unreadable';w['tables']=[table([c])]
        before=copy.deepcopy(w);r=validate_response(response(w),{},'qwen/qwen3.6-35b-a3b');self.assertEqual(r['decision'],'candidate_with_warnings');self.assertEqual(w,before)
    def test_empty_unreadable_partial_can_remain_pending(self):
        w=wire();w.update(status='partial',warnings=['판독 어려움']);c=cell(text='');c['value_status']='unreadable';w['tables']=[table([c])]
        self.assertFalse(codes(w));self.assertFalse(base.check_wire(w))
    def test_claim_only_source_string_review(self):
        w=wire();f=figure();f['claims']=[dict(text='소스에 실제로 있는 계약 본문',status='observed',bbox=[.1,.2,.8,.8])];w['figures']=[f]
        ctx=[dict(block_id='b1',text='소스에 실제로 있는 계약 본문')]
        self.assertIn('SOURCE_LITERAL_ONLY_IN_CLAIMS',codes(w,ctx))
        self.assertEqual(validate_response(response(w),{'native_context':ctx},'qwen/qwen3.6-35b-a3b')['decision'],'candidate_with_warnings')
    def test_claim_without_source_not_called_wrong_field(self):
        w=wire();f=figure();f.update(kind='photo',claims=[dict(text='화면에 건물이 보인다.',status='observed',bbox=[.1,.2,.8,.8])]);w['figures']=[f];self.assertFalse(codes(w))
    def test_explanation_may_quote_existing_literal(self):
        w=wire();f=figure();f['claims']=[dict(text='제목은 시험용 문서의 제목이다.',status='observed',bbox=[.1,.2,.8,.8])];w['figures']=[f]
        self.assertFalse(codes(w,[dict(block_id='b1',text='시험용 문서의 제목')]))
    def test_repeated_claim_detected(self):
        w=wire();f=figure();f['claims']=[dict(text='화면에 건물이 보인다.',status='observed',bbox=[.1,.2,.8,.8])]*2;w['figures']=[f];self.assertIn('DUPLICATE_CLAIM',codes(w))
    def test_parallel_relations_separate_regions_allowed(self):
        w=wire();f=figure();f['nodes']=[dict(id='a',label='A',bbox=[.1,.2,.3,.7]),dict(id='b',label='B',bbox=[.6,.2,.8,.7])]
        edge=dict(from_node='a',to_node='b',direction='undirected',label=None,bbox=[.3,.3,.6,.32]);f['relations']=[edge,{**edge,'bbox':[.3,.6,.6,.62]}];w['figures']=[f]
        self.assertNotIn('DUPLICATE_RELATION',codes(w));f['relations'][1]['bbox']=edge['bbox'];self.assertIn('DUPLICATE_RELATION',codes(w))
    def test_frozen_reasoning_condition_preserved(self):
        r=response(wire());r['usage']={'completion_tokens_details':{'reasoning_tokens':1}};self.assertEqual(validate_response(r,{},r['model'])['decision'],'reject')
    def test_truncated_response_never_admitted(self):
        r=response(wire(),'length');self.assertEqual(validate_response(r,{},r['model'])['decision'],'reject')
        r['choices'][0]['message']['content']='{"status":"complete","texts":[';self.assertEqual(validate_response(r,{},r['model'])['decision'],'reject')
    def test_duplicate_json_keys_rejected(self):
        r=response(wire());r['choices'][0]['message']['content']='{"status":"complete","status":"partial"}'
        self.assertEqual(validate_response(r,{},r['model'])['decision'],'reject')
    def test_malformed_typed_input_rejected_without_crash(self):
        for v in [[],None,{'texts':3},'hello']:
            r=response(v);self.assertEqual(validate_response(r,{},r['model'])['decision'],'reject')
    def test_gate_prevents_converter_call_on_rejection(self):
        w=wire();w['tables']=[table([cell(),cell()])]
        with patch.object(base,'convert',side_effect=AssertionError('must not reach conversion')):
            with self.assertRaisesRegex(ValueError,'quality gate reject'):convert_checked({}, {},response(w),'qwen/qwen3.6-35b-a3b')
    def test_duplicate_literal_transfers_with_warning(self):
        w=wire();w['texts'].append(copy.deepcopy(w['texts'][0]))
        r=validate_response(response(w),{},'qwen/qwen3.6-35b-a3b')
        self.assertEqual(r['decision'],'candidate_with_warnings')
        self.assertFalse(r['meaning_accuracy_verified']);self.assertTrue(r['transfer_allowed'])
        self.assertEqual(r['data'],w)
    def test_status_conflict_is_warning_not_success_claim(self):
        w=wire();c=cell();c['value_status']='unreadable';w['tables']=[table([c])]
        r=validate_response(response(w),{},'qwen/qwen3.6-35b-a3b')
        self.assertEqual(r['decision'],'candidate_with_warnings');self.assertTrue(r['review_required'])
        self.assertEqual(r['data'],w)
    def test_known_empty_is_not_filled(self):
        w=wire();w['tables']=[table([cell(text='')])]
        r=validate_response(response(w),{},'qwen/qwen3.6-35b-a3b')
        self.assertEqual(r['decision'],'candidate_with_warnings');self.assertEqual(r['data'],w)
    def test_empty_bbox_still_rejected(self):
        w=wire();w['texts'][0]['bbox']=[.1,.1,.1,.1]
        self.assertEqual(validate_response(response(w),{},'qwen/qwen3.6-35b-a3b')['decision'],'reject')
    def test_dangling_relation_still_rejected(self):
        w=wire();f=figure();f['nodes']=[dict(id='a',label='A',bbox=[.1,.2,.3,.7])]
        f['relations']=[dict(from_node='a',to_node='missing',direction='directed',label=None,bbox=[.3,.3,.6,.32])];w['figures']=[f]
        self.assertEqual(validate_response(response(w),{},'qwen/qwen3.6-35b-a3b')['decision'],'reject')
    def test_unknown_rule_is_not_automatically_relaxed(self):
        self.assertTrue(apply_policy([dict(code='FUTURE_RULE',severity='review')])[0]['blocks_transfer'])
    def test_warning_conversion_preserves_data_and_marks_pending(self):
        root=Path(__file__).resolve().parents[2];m=json.loads((root/'outputs/vision-comparison-run-001/manifest.json').read_text())
        item=next(i for i in m['items'] if i['doc_id']=='D-001' and i['unit_id']=='vision:slide1')
        native=next(json.loads(l) for l in (root/'outputs/parsing-run-003/parsed.jsonl').read_text().splitlines() if json.loads(l)['doc_id']=='D-001')
        w=wire();w['texts'].append(copy.deepcopy(w['texts'][0]));before=copy.deepcopy(native)
        new,a=convert_checked(native,item,response(w),'qwen/qwen3.6-35b-a3b')
        unit=next(u for u in new['coverage']['units'] if u['unit_id']==item['unit_id'])
        blocks=[b for b in new['blocks'] if b['block_id'] in unit['block_ids']]
        self.assertEqual(native,before);self.assertEqual(unit['status'],'pending');self.assertEqual(len(blocks),2)
        self.assertEqual([b['text'] for b in blocks],[t['text'] for t in w['texts']])
        self.assertTrue(all(any('DUPLICATE_LITERAL' in s for s in b['warnings']) for b in blocks))
        self.assertEqual(a['decision'],'candidate_with_warnings');self.assertFalse(base.common.check(new))
    def test_real_conversion_preserves_native(self):
        root=Path(__file__).resolve().parents[2];m=json.loads((root/'outputs/vision-comparison-run-001/manifest.json').read_text());item=next(i for i in m['items'] if i['doc_id']=='D-001' and i['unit_id']=='vision:slide1')
        path=root/'outputs/vision-comparison-run-001/qwen3.6-35b-a3b/units/D-001-vision-slide1/response.json';resp=json.loads(path.read_text());native=next(json.loads(l) for l in (root/'outputs/parsing-run-003/parsed.jsonl').read_text().splitlines() if json.loads(l)['doc_id']=='D-001');before=copy.deepcopy(native)
        new,a=convert_checked(native,item,resp,resp['model']);self.assertEqual(native,before);self.assertEqual(a['decision'],'candidate');self.assertEqual(new['blocks'][:len(native['blocks'])],native['blocks']);self.assertFalse(base.common.check(new))

if __name__=='__main__':unittest.main()
