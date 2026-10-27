#!/usr/bin/env python3
"""Offline-only preflight, request preparation, scoring, and review workflow.

No network imports, API keys, online model calls, or automatic retries.
Saved response envelope: model, doc_id, request_sha256, response (OpenRouter
chat-completion object), optional elapsed_ms. See README.txt.
"""
import argparse
import copy
import hashlib
import json
import statistics
from pathlib import Path
from contract import FIELDS, candidate_from_gold, digest, evidence_errors, loads, metrics, norm, schema, score_fields, validate

HERE=Path(__file__).resolve().parent

def read(p):return loads(Path(p).read_text())
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def filehash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def slug(m):return m.split('/')[-1]
def manifest():return read(HERE/'manifest.json')
def packet(item):return read(HERE/item['input_path'])
def blind_id(model,doc_id):
    # Rotate A/B per document. The routing file is kept separate from the review form.
    index=manifest()['models'].index(model)
    flip=int(hashlib.sha256(doc_id.encode()).hexdigest()[-1],16)%2
    return doc_id+'-'+('A' if index==flip else 'B')

def assert_frozen():
    frozen=read(HERE/'freeze.json')
    for p,h in frozen['files'].items():
        if not (HERE/p).is_file() or filehash(HERE/p)!=h:raise ValueError('Frozen file changed: '+p)
    for p,h in frozen['external_dependencies'].items():
        if not Path(p).is_file() or filehash(p)!=h:raise ValueError('Frozen dependency changed: '+p)
    return frozen

def request_body(m,item):
    """Only public inputs, public schema/prompt/reference and run configuration are read."""
    cfg=manifest()['settings'];body={k:copy.deepcopy(v) for k,v in cfg.items() if k!='qwen36_reasoning_enabled'}
    body.update(model=m,messages=[{'role':'system','content':(HERE/'public/system-prompt.txt').read_text()},{'role':'user','content':json.dumps({'input':packet(item),'reference_data':read(HERE/'public/reference-data.json')},ensure_ascii=False,separators=(',',':'))}],response_format={'type':'json_schema','json_schema':{'name':'llm_enrichment_candidate_v1','strict':True,'schema':read(HERE/'public/response.schema.json')}})
    if m=='qwen/qwen3.6-35b-a3b':body['reasoning']={'enabled':False}
    return body

def preflight():
    from jsonschema import Draft202012Validator
    m=manifest();ids=[x['doc_id'] for x in m['documents']]
    if len(ids)!=20 or len(set(ids))!=20:raise ValueError('Need exactly 20 unique documents')
    gold=read(HERE/'private/gold.json');gmap={g['doc_id']:g for g in gold}
    if set(gmap)!=set(ids) or len(gold)!=20:raise ValueError('Gold set differs from input set')
    Draft202012Validator.check_schema(schema())
    from build_pack import load_module, ROOT
    common=load_module('preflight_common',ROOT/'outputs/common-block-design/validate_design.py')
    facts=0;field_count=0
    for item in m['documents']:
        if filehash(HERE/item['input_path'])!=item['input_sha256']:raise ValueError('Input changed')
        p=packet(item);g=gmap[item['doc_id']]
        errors=common.check(p['document'])
        if errors:raise ValueError(errors)
        if p['source_metadata']['source_sha256']!=p['document']['source']['sha256']:raise ValueError('mtime/source binding failed')
        c=candidate_from_gold(g);errors=validate(c,p)
        if errors:raise ValueError((item['doc_id'],errors))
        if set(g['fields'])!=set(FIELDS):raise ValueError('Gold field set mismatch')
        for f in g['fields'].values():
            errors=evidence_errors([{k:e[k] for k in ['kind','ref','quote']} for e in f['evidence']],p)
            if errors:raise ValueError(errors)
            field_count+=1
        for f in g['summary_facts']:
            if not f['evidence']:raise ValueError('Summary fact without evidence')
            errors=evidence_errors([{k:e[k] for k in ['kind','ref','quote']} for e in f['evidence']],p)
            if errors:raise ValueError(errors)
            facts+=1
        for a in p['document']['assets']:
            if filehash(a['path'])!=a['sha256']:raise ValueError('Source image changed')
        for model in m['models']:
            body=request_body(model,item)
            if any(term in body['messages'][1]['content'] for term in ['accepted_values','summary_facts','expected_status','label-adjustments']):raise ValueError('Private evaluation material leaked')
    source_checks=read(HERE/'private/source-checks.json')
    for r in source_checks:
        if filehash(r['source_path'])!=r['source_sha256']:raise ValueError('Original source changed')
        if str(Path(r['source_path']).stat().st_mtime_ns)!=r['source_mtime_ns']:raise ValueError('Original mtime changed during preparation')
        pm=packet(next(i for i in m['documents'] if i['doc_id']==r['doc_id']))['source_metadata']
        if pm['modified_at_ns']!=r['source_mtime_ns']:raise ValueError('Collected mtime differs from source snapshot')
    return {'documents':20,'fields':field_count,'summary_facts':facts,'scan_documents':3,'scan_pages':5,'original_hashes_verified':len(source_checks),'paid_calls':0,'schema_and_reference_checks':'passed','semantic_gold_review':'assistant_source_checked_not_independent_human'}

def prepare():
    result=preflight();requests=[]
    for item in manifest()['documents']:
        previous=None
        for model in manifest()['models']:
            body=request_body(model,item);mh=digest(body['messages'])
            if previous is not None and previous!=mh:raise ValueError('Paired inputs differ')
            previous=mh
            path=f'requests/{slug(model)}/{item["doc_id"]}.json';write(HERE/path,body)
            requests.append({'doc_id':item['doc_id'],'model':model,'path':path,'request_sha256':digest(body),'messages_sha256':mh,'input_characters':len(body['messages'][1]['content'])})
    write(HERE/'requests/index.json',{'status':'prepared_not_sent','requests':requests,'count':len(requests)})
    write(HERE/'reports/preflight.json',result)
    return {**result,'prepared_requests':len(requests),'sent_requests':0}

def freeze():
    if (HERE/'freeze.json').exists():raise ValueError('Already frozen; use a new version for changed criteria')
    preflight()
    files={}
    for p in HERE.rglob('*'):
        if p.is_file() and p.suffix in ['.json','.txt','.py'] and not any(x in p.parts for x in ['reports','responses','__pycache__']):files[str(p.relative_to(HERE))]=filehash(p)
    root=HERE.parent.parent
    deps=['outputs/common-block-design/common-block.schema.json','outputs/common-block-design/validate_design.py','outputs/rag-enrichment-v3/enrich.py','outputs/rag-enrichment-v3/native_rules.py','outputs/parsing-run-003/parsed.jsonl','outputs/additional-parsing-run-001/parsed.jsonl','outputs/model-selection-review-001/selected-cases.json']
    result={'version':'enrichment-selection-1','files':files,'external_dependencies':{str(root/p):filehash(root/p) for p in deps},'meaning':'Frozen before any model calls; AI-reviewed development set; not independent human gold.'}
    write(HERE/'freeze.json',result);return {'frozen_files':len(files)}

def clean_baseline(c):
    c=copy.deepcopy(c)
    for f in c['fields'].values():
        for e in f['evidence']:e.pop('loc',None)
        for candidate in f['candidates']:
            for e in candidate['evidence']:e.pop('loc',None)
    return c

def load_responses(folder):
    expected={(r['model'],r['doc_id']):r for r in read(HERE/'requests/index.json')['requests']};result={}
    for path in sorted(Path(folder).rglob('*.json')):
        envelope=read(path)
        key=(envelope.get('model'),envelope.get('doc_id'))
        if key not in expected:raise ValueError('Unexpected model/document envelope: '+str(path))
        if key in result:raise ValueError('Duplicate response envelope for '+str(key))
        if envelope.get('request_sha256')!=expected[key]['request_sha256']:raise ValueError('Response/request hash mismatch: '+str(path))
        response=envelope.get('response',{});content=None;errors=[]
        if not isinstance(response,dict):raise ValueError('Response must be an object')
        if response.get('error'):errors.append('api_error')
        choices=response.get('choices',[])
        if not isinstance(choices,list):choices=[]
        if len(choices)!=1:errors.append('missing_or_multiple_choices')
        else:
            content=choices[0].get('message',{}).get('content')
            if choices[0].get('finish_reason')!='stop':errors.append('not_normal_stop')
        c=None
        try:
            if not isinstance(content,str):raise ValueError('content_not_string')
            c=loads(content)
        except (ValueError,TypeError) as e:errors.append('invalid_json:'+str(e))
        usage=response.get('usage') or {}
        if not isinstance(usage,dict):raise ValueError('Usage must be an object')
        result[key]={'candidate':c,'errors':errors,'response_sha256':digest(envelope),'usage':usage,'elapsed_ms':envelope.get('elapsed_ms'),'file':str(path)}
    return result

def check_review(review,entry,gold,candidate,packet):
    """Review is an explicit assertion by an identified reviewer, never an automatic LLM judge."""
    if review is None:return None
    if review.get('response_sha256')!=entry['response_sha256']:raise ValueError('Stale semantic review')
    if not review.get('reviewer_id') or review.get('reviewer_kind') not in ['human','assistant']:return None
    if review.get('status')!='completed':return None
    sentences=review.get('sentences',[])
    if len(sentences)!=len(candidate['summary']):raise ValueError('Review must cover every summary sentence')
    atoms=[];covered=set()
    goldids={f['fact_id'] for f in gold['summary_facts']}
    for i,s in enumerate(sentences):
        if s.get('index')!=i or s.get('source_text')!=candidate['summary'][i]['text']:raise ValueError('Sentence review mismatch')
        if not s.get('atomic_claims'):return None
        for a in s['atomic_claims']:
            if not a.get('text') or a.get('verdict') not in ['supported','unsupported','uncertain'] or not a.get('reason'):return None
            if a['verdict']=='supported' and (not a.get('evidence') or evidence_errors(a['evidence'],packet)):raise ValueError('Supported atomic claim lacks valid evidence')
            ids=set(a.get('covered_gold_fact_ids',[]))
            if not ids<=goldids:raise ValueError('Unknown summary fact ID')
            if a['verdict']=='supported':covered|=ids
            atoms.append(a)
    return {'reviewer_id':review['reviewer_id'],'reviewer_kind':review['reviewer_kind'],'claims':len(atoms),'supported':sum(a['verdict']=='supported' for a in atoms),'unsupported':sum(a['verdict']=='unsupported' for a in atoms),'uncertain':sum(a['verdict']=='uncertain' for a in atoms),'facts_covered':len(covered),'facts_expected':len(goldids)}

def apply_alternative_evidence_review(fields,review,entry):
    if not review:return
    if review.get('response_sha256')!=entry['response_sha256']:raise ValueError('Stale metadata evidence review')
    if not review.get('reviewer_id') or review.get('reviewer_kind') not in ['human','assistant']:return
    byname={x['field']:x for x in fields}
    seen=set()
    for r in review.get('metadata_evidence_reviews',[]):
        name=r.get('field')
        if name not in byname or name in seen:raise ValueError('Unknown/duplicate metadata evidence review')
        seen.add(name);x=byname[name]
        if not x['alternative_evidence_review']:continue
        if r.get('verdict') in ['supported','unsupported'] and r.get('reason'):
            x['alternative_evidence_review']=False
            x['correct_supported_value']=r['verdict']=='supported'
            x['evidence_review_verdict']=r['verdict']

def evaluate(folder,out,baseline=False,review_path=None):
    assert_frozen();m=manifest();gold={g['doc_id']:g for g in read(HERE/'private/gold.json')}
    baseline_map={c['doc_id']:clean_baseline(c) for c in read(HERE/'private/rules-baseline.json')}
    responses={} if baseline else load_responses(folder)
    reviews={}
    if review_path:
        for r in read(review_path):
            choices=[(model,r['doc_id']) for model in m['models'] if blind_id(model,r['doc_id'])==r.get('candidate_id')]
            if len(choices)!=1:raise ValueError('Unknown blinded candidate ID')
            key=choices[0]
            if key in reviews:raise ValueError('Duplicate review')
            reviews[key]=r
    template=[];all_models=[];models=['rules-only'] if baseline else m['models']
    for model in models:
        documents=[];all_fields=[];times=[];costs=[];missing_cost=0;tokens_in=0;tokens_out=0;semantic=[]
        for item in m['documents']:
            did=item['doc_id'];p=packet(item);g=gold[did]
            entry={'candidate':baseline_map[did],'errors':[],'response_sha256':digest(baseline_map[did]),'usage':{}} if baseline else responses.get((model,did))
            c=entry['candidate'] if entry else None;errors=list(entry['errors']) if entry else ['response_not_received']
            if c is not None:errors+=validate(c,p)
            valid=c is not None and not errors
            usable=c if isinstance(c,dict) and isinstance(c.get('fields'),dict) and all(isinstance(x,dict) for x in c['fields'].values()) else None
            fs=score_fields(usable,g,p,valid)
            if entry and not baseline:apply_alternative_evidence_review(fs,reviews.get((model,did)),entry)
            all_fields+=fs
            base=baseline_map[did];base_valid=not validate(base,p);bs=score_fields(base,g,p,base_valid)
            gains=[x['field'] for x,b in zip(fs,bs) if x['correct_supported_value'] and not b['correct_supported_value']]
            conflicts=[x['field'] for x,b in zip(fs,bs) if b['correct_supported_value'] and x['predicted_value'] is not None and not x['value_match']]
            # Fixed merge simulation only: preserve existing non-null rules value, flag conflicting proposals.
            merged=copy.deepcopy(base);merge_pending=[]
            if valid:
                for name,pred in c['fields'].items():
                    old=merged['fields'][name]
                    if pred['status']!='extracted':continue
                    if old['value'] is None:
                        if old['status']=='needs_review':merge_pending.append(name)
                        else:merged['fields'][name]=copy.deepcopy(pred)
                    elif norm(old['value'])!=norm(pred['value']):merge_pending.append(name)
            merge_fs=score_fields(merged,g,p,not validate(merged,p))
            doc={'doc_id':did,'input_kind':item['input_kind'],'received':entry is not None,'valid':valid,'errors':errors,'fields':fs,'rules_gain_fields':gains,'rules_correct_value_conflicts':conflicts,'merge_review_pending':merge_pending,'merged_metrics':metrics(merge_fs),'semantic_summary':None}
            if entry and not baseline:
                u=entry['usage'];tokens_in+=u.get('prompt_tokens',0) or 0;tokens_out+=u.get('completion_tokens',0) or 0
                if isinstance(u.get('cost'),(int,float)):costs.append(u['cost'])
                else:missing_cost+=1
                if isinstance(entry.get('elapsed_ms'),(int,float)):times.append(entry['elapsed_ms'])
            if valid and not baseline:
                rv=check_review(reviews.get((model,did)),entry,g,c,p)
                doc['semantic_summary']=rv
                if rv is not None:semantic.append(rv)
                template.append({'candidate_id':blind_id(model,did),'doc_id':did,'response_sha256':entry['response_sha256'],'reviewer_id':None,'reviewer_kind':None,'status':'pending','instructions':'Decompose every sentence into factual claims. Check evidence AND meaning. Assign each gold fact only when all its conditions/negations/numbers are retained. Do not infer correctness from citation presence.','metadata_evidence_reviews':[{'field':x['field'],'verdict':'pending','reason':None,'candidate_evidence':c['fields'][x['field']]['evidence']} for x in fs if x['alternative_evidence_review']],'sentences':[{'index':i,'source_text':s['text'],'candidate_evidence':s['evidence'],'atomic_claims':[]} for i,s in enumerate(c['summary'])],'gold_summary_facts':g['summary_facts']})
            documents.append(doc)
        totals=metrics(all_fields);valid_count=sum(d['valid'] for d in documents);received=sum(d['received'] for d in documents)
        gate=valid_count==20 and totals['precision'] is not None and totals['precision']>=.95 and totals['recall'] is not None and totals['recall']>=.95 and totals['critical_errors']==0 and totals['alternative_evidence_pending']==0
        if baseline:status='rule_baseline_not_model_selection'
        elif received==0:status='not_run'
        elif received<20:status='incomplete_responses'
        elif not gate:status='metadata_gate_failed_or_review_pending'
        elif len(semantic)!=20:status='metadata_gate_passed_summary_review_pending'
        else:status='reviewed_comparison_ready_not_automatic_selection'
        all_models.append({'model':model,'status':status,'received':received,'valid_documents':valid_count,'metadata':totals,'metadata_gate_pass':gate,'per_field':{f:metrics([x for x in all_fields if x['field']==f]) for f in FIELDS},'by_input_kind':{k:metrics([x for d in documents if d['input_kind']==k for x in d['fields']]) for k in ['native','reviewed_scan']},'summary':{'reviewed_documents':len(semantic),'required_documents':20,'semantic_accuracy':sum(x['supported'] for x in semantic)/sum(x['claims'] for x in semantic) if semantic and sum(x['claims'] for x in semantic) else None,'core_fact_recall':sum(x['facts_covered'] for x in semantic)/sum(len(g['summary_facts']) for g in gold.values()) if len(semantic)==20 else None,'meaning':'No semantic score without explicit completed review; empty summary has zero core-fact recall.'},'usage':{'reported_cost_sum':sum(costs) if costs else None,'cost_missing_responses':missing_cost,'prompt_tokens':tokens_in,'completion_tokens':tokens_out,'median_elapsed_ms':statistics.median(times) if times else None,'max_elapsed_ms':max(times) if times else None},'documents':documents})
    write(Path(out)/'evaluation.json',{'evaluation_kind':'offline_rules_baseline' if baseline else 'saved_model_responses','independent_human_gold':False,'models':all_models,'model_calls_by_evaluator':0})
    if not baseline:
        write(Path(out)/'semantic-review.template.json',sorted(template,key=lambda r:r['candidate_id']))
        write(Path(out)/'review-routing.private.json',[{'candidate_id':blind_id(model,item['doc_id']),'model':model,'doc_id':item['doc_id']} for model in models for item in m['documents']])
    return [{'model':x['model'],'status':x['status'],'valid_documents':x['valid_documents'],'metadata':x['metadata']} for x in all_models]

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    for name in ['prepare','check','freeze']:s.add_parser(name)
    e=s.add_parser('evaluate');e.add_argument('--responses',type=Path,default=HERE/'responses');e.add_argument('--out',type=Path,required=True);e.add_argument('--review',type=Path)
    b=s.add_parser('baseline');b.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command=='prepare':
        if (HERE/'freeze.json').exists():assert_frozen();result={'status':'already_frozen_prepared_no_resend'}
        else:write(HERE/'public/response.schema.json',schema());result=prepare()
    elif a.command=='check':
        if (HERE/'freeze.json').exists():assert_frozen()
        result=preflight()
    elif a.command=='freeze':result=freeze()
    elif a.command=='baseline':result=evaluate(None,a.out,baseline=True)
    else:result=evaluate(a.responses,a.out,review_path=a.review)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
