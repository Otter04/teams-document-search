import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import contract
import run
import evaluate

def fixture():
    parsed=run.ROOT/'outputs/parsing-run-003'
    doc=next(d for d in run.lines(parsed/'parsed.jsonl') if d['doc_id']=='D-044')
    q=next(x for x in run.lines(parsed/'vision-pending.jsonl') if x['doc_id']=='D-044' and x['loc']['page']==2)
    return doc,q

def wire():
    return {'status':'complete','texts':[{'kind':'heading','text':'계약서','bbox':[.1,.1,.8,.2]}],
      'tables':[{'bbox':[.1,.3,.8,.6],'row_count':2,'column_count':2,'header_rows':[1],
        'header_status':'explicit','cells':[
        {'row':r,'column':c,'row_span':1,'column_span':1,'text':str(r)+str(c),
         'value_status':'known','role':'header' if r==1 else 'data','bbox':[.1,.3,.8,.6]}
        for r in [1,2] for c in [1,2]]}],
      'figures':[{'kind':'diagram','bbox':[.1,.6,.8,.9],
        'nodes':[{'id':'a','label':'장비 A','bbox':[.1,.6,.4,.8]}, {'id':'b','label':'장비 B','bbox':[.5,.6,.8,.8]}],
        'relations':[{'from_node':'a','to_node':'b','direction':'undirected','label':None,'bbox':[.4,.69,.5,.71]}],
        'claims':[{'text':'두 상자 사이에 선이 있다.','status':'observed','bbox':[.1,.6,.8,.9]}]}],
      'warnings':[]}

class ContractTests(unittest.TestCase):
    def test_valid_conversion_preserves_native_and_provenance(self):
        d,q=fixture();before=copy.deepcopy(d)
        new=contract.convert(d,q,wire(),run.MODELS[0])
        self.assertEqual(d,before)
        self.assertEqual(new['blocks'][:len(d['blocks'])],d['blocks'])
        self.assertEqual([],contract.common.check(new))
        newblocks=new['blocks'][len(d['blocks']):]
        self.assertTrue(all(b['run_ref'].startswith('vision') for b in newblocks))
        self.assertEqual(newblocks[-1]['text'],'')
        self.assertEqual(newblocks[-1]['claims'][0]['status'],'observed')

    def test_bad_structure_rejected(self):
        for mutate in [lambda d:d['tables'][0]['cells'].pop(),
                       lambda d:d['tables'][0]['cells'][0].update(column=2),
                       lambda d:d['figures'][0]['relations'][0].update(to_node='missing'),
                       lambda d:d['texts'][0].update(bbox=[.8,.1,.1,.2]),
                       lambda d:d['figures'][0]['nodes'].append(d['figures'][0]['nodes'][0]),
                       lambda d:d.update(status='partial')]:
            d=wire();mutate(d)
            self.assertTrue(contract.check_wire(d))

    def test_merged_cell_and_blank_cell(self):
        d=wire();t=d['tables'][0]
        t['cells']=[c for c in t['cells'] if not(c['row']==1 and c['column']==2)]
        t['cells'][0]['column_span']=2
        t['cells'][-1].update(text='',value_status='blank')
        original,item=fixture()
        self.assertEqual([],contract.common.check(contract.convert(original,item,d,run.MODELS[1])))

    def test_partial_stays_pending(self):
        d=wire();d.update(status='partial',warnings=['下部 unreadable'])
        original,item=fixture();new=contract.convert(original,item,d,run.MODELS[0])
        unit=next(u for u in new['coverage']['units'] if u['unit_id']==item['unit_id'])
        self.assertEqual(unit['status'],'pending')

    def test_truncated_provider_and_invalid_json_rejected(self):
        for resp in [dict(provider='DeepInfra',choices=[dict(finish_reason='length',message={'content':json.dumps(wire())})]),
                     dict(provider='Other',choices=[dict(finish_reason='stop',message={'content':json.dumps(wire())})]),
                     dict(provider='DeepInfra',choices=[dict(finish_reason='stop',message={'content':'```json {} ```'})])]:
            with self.assertRaises(ValueError):run.parse_response(resp)

    def test_resume_does_not_spend_again(self):
        item={'doc_id':'X','unit_id':'vision:page1'}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);base=out/run.MODELS[0].split('/')[1]/'units'/run.task_id(item)
            result={'status':'valid','cost_usd':.01}
            run.write(base/'result.json',result)
            with patch.object(run,'api_call',side_effect=AssertionError('network forbidden')):
                self.assertEqual(run.process_item(out,item,run.MODELS[0],{},'fake'),result)

    def test_ambiguous_timeout_blocks_duplicate(self):
        item={'doc_id':'X','unit_id':'vision:page1'}
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);base=out/run.MODELS[0].split('/')[1]/'units'/run.task_id(item)
            run.write(base/'inflight.json',{})
            with patch.object(run,'api_call',side_effect=AssertionError('network forbidden')):
                with self.assertRaises(RuntimeError):run.process_item(out,item,run.MODELS[0],{},'fake')

    def test_payload_image_context_and_no_answers(self):
        doc,q=fixture();q={**q,'image_path':str(run.ROOT/'outputs/parsing-run-003'/q['asset_path']),
                         'native_context':[]}
        q['image_sha256']=run.digest(q['image_path'])
        m=dict(prompt=contract.PROMPT,response_schema=contract.SCHEMA,temperature=0,seed=42,max_tokens=16384)
        p=run.make_payload(q,run.MODELS[0],m)
        self.assertFalse(p['reasoning']['enabled'])
        self.assertFalse(p['provider']['allow_fallbacks'])
        self.assertEqual(p['provider']['only'],['deepinfra/fp8'])
        content=p['messages'][1]['content']
        self.assertEqual(set(json.loads(content[0]['text'])),{'source_location','native_context'})
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))
        self.assertNotIn('reasoning',run.make_payload(q,run.MODELS[1],m))

    def test_offline_response_to_evaluation_integration(self):
        manifest=run.load(run.DEFAULT_RUN/'manifest.json')
        item=next(i for i in manifest['items'] if i['doc_id']=='D-044' and i['loc']['page']==2)
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);run.write(out/'manifest.json',manifest)
            def response(payload,key):
                return {'id':'offline-test-only','model':payload['model'],'provider':'DeepInfra',
                    'usage':{'prompt_tokens':100,'completion_tokens':100,'cost':0.0},
                    'choices':[{'finish_reason':'stop','message':{'content':json.dumps(wire(),ensure_ascii=False)}}]}
            with patch.object(run,'api_call',side_effect=response) as api:
                for model in run.MODELS:
                    self.assertEqual(run.process_item(out,item,model,manifest,'fake-key')['status'],'valid')
                    run.process_item(out,item,model,manifest,'fake-key')
                self.assertEqual(api.call_count,2)
            summary=run.summarize(out,manifest)
            self.assertTrue(all(s['valid_units']==1 and s['unattempted_units']==131 for s in summary))
            checks=evaluate.evaluate(out)
            self.assertTrue(all(c['overall_quality_pass'] is None for c in checks))
            self.assertTrue(all(c['D044_table_anchor_content']['recall']==0 for c in checks))
            for model in run.MODELS:
                for corpus,count in [('original',110),('additional',30)]:
                    self.assertEqual(len(run.lines(out/model.split('/')[1]/corpus/'parsed.candidate.jsonl')),count)

if __name__=='__main__':unittest.main()
