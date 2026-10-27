"""Admission and evaluation for a new, separately reviewed corpus. No model calls."""
import argparse, importlib.util, json, re, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'rag-date-search-v1'))
import date_search as d
spec=importlib.util.spec_from_file_location('date_holdout_metrics',d.ROOT/'evaluate.py')
metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)
E=d.E
FIELDS=E.FIELDS+['표지일','작성일','파일최종수정일']

def unique(rows,key):
    result={r[key]:r for r in rows}
    if len(result)!=len(rows):raise ValueError('duplicate '+key)
    return result

def validate(manifest,queries,answers,metadata,index,deny,min_documents=30,min_queries=60):
    errors=[]
    try:
        docs=unique(manifest,'doc_id');qs=unique(queries,'query_id');ans=unique(answers,'query_id');meta=unique(metadata,'doc_id')
    except (KeyError,ValueError) as ex:return [str(ex)]
    if len(docs)<min_documents:errors.append('insufficient_new_documents')
    if len(qs)<min_queries:errors.append('insufficient_new_queries')
    if len({r.get('source_sha256') for r in manifest})!=len(manifest):errors.append('duplicate_source_hash_in_holdout')
    if len({q.get('query','').strip() for q in queries})!=len(queries):errors.append('duplicate_query_text')
    if set(docs)!=set(index['documents']) or set(meta)!=set(docs):errors.append('document_inventory_mismatch')
    if set(qs)!=set(ans):errors.append('question_answer_inventory_mismatch')
    for did,r in docs.items():
        if not re.fullmatch(r'[0-9a-f]{64}',r.get('source_sha256','')):errors.append('invalid_source_hash:'+did)
        if r.get('source_sha256') in deny['source_hashes']:errors.append('development_source_reused:'+did)
        if not r.get('family_key') or r.get('family_key') in deny['family_keys']:errors.append('family_overlap_or_missing:'+did)
        if r.get('source_origin')!='new_collection' or not r.get('reviewer_id'):errors.append('source_review_missing:'+did)
        doc=index['documents'].get(did,{})
        if r.get('source_sha256')!=doc.get('source',{}).get('sha256'):errors.append('source_hash_mismatch:'+did)
        m=meta.get(did,{})
        if not m.get('reviewer_id') or set(m.get('fields',{}))!=set(FIELDS):errors.append('metadata_review_or_fields_missing:'+did)
        for field,label in m.get('fields',{}).items():
            if not isinstance(label,dict):errors.append('invalid_metadata_label:'+did);continue
            state=label.get('state');value=label.get('value')
            if state not in {'value','not_applicable','not_observed_native','unresolved'}:errors.append('invalid_metadata_state:'+did)
            if state=='value' and (not isinstance(value,str) or not value.strip() or not label.get('evidence')):errors.append('metadata_value_without_evidence:'+did)
            if state!='value' and value is not None:errors.append('nonvalue_label_has_value:'+did)
    for qid,q in qs.items():
        if set(q)!={'query_id','query','category','limit'} or not isinstance(q.get('query'),str) or not q['query'].strip() or not isinstance(q.get('limit'),int) or not 1<=q['limit']<=100:errors.append('invalid_query_input:'+qid)
        a=ans.get(qid,{})
        expected=a.get('expected_doc_ids',[])
        if not isinstance(expected,list) or not all(isinstance(v,str) for v in expected) or len(set(expected))!=len(expected) or not set(expected)<=set(docs):errors.append('invalid_answer_ids:'+qid)
        if not a.get('reviewer_id') or not a.get('evidence'):errors.append('answer_review_missing:'+qid)
        if a.get('check') not in {'relevance','ordered','no_native_match','needs_clarification'}:errors.append('invalid_answer_mode:'+qid)
        if a.get('check') in {'relevance','ordered'} and not expected:errors.append('positive_answer_empty:'+qid)
        if a.get('check') in {'no_native_match','needs_clarification'} and expected:errors.append('nonpositive_answer_not_empty:'+qid)
    return sorted(set(errors))

def check_freeze():
    freeze=E.read_json(HERE/'frozen-implementation.json')
    for p,h in freeze['files'].items():
        if E.digest(HERE.parent.parent/p)!=h:raise ValueError('implementation changed; explicitly create a new evaluation version: '+p)

def run(package,run_path,output,validate_only=False):
    check_freeze();package=Path(package);run_path=Path(run_path);out=Path(output)
    if out.exists():raise ValueError('new evaluation output path required')
    names=['manifest','queries','answers','metadata-labels']
    data={n:E.read_lines(package/(n+'.jsonl')) for n in names}
    ix=E.read_json(run_path/'index.json');deny=E.read_json(HERE/'development-exclusions.json')
    errors=validate(data['manifest'],data['queries'],data['answers'],data['metadata-labels'],ix,deny)
    out.mkdir(parents=True)
    E.dump(out/'admission.json',{'errors':errors,'accepted':not errors,'independent_labels_require_human_review':True})
    if errors or validate_only:return {'admitted':not errors,'errors':errors,'evaluation_performed':False}
    prov=E.read_json(run_path/'provenance.json')
    for p,h in prov['inputs'].items():assert E.digest(p)==h,p
    for p,h in prov['outputs'].items():assert E.digest(run_path/p)==h,p
    # Only query text/limits are passed to the retrieval function; answer records never are.
    bundle=E.read_json(run_path/'features.json');view=d.old.view(ix,bundle,context=True,intents=True);stats=d.old.field_statistics(view,bundle,True)
    settings=E.read_json(package/'settings.json');as_of=settings['reference_date']
    d.plan('작성일 2025년 문서',as_of,ix['system_terms'],ix['clients'])
    E.timestamp('2000-01-01 00:00:00')
    guard={'active':True,'attempts':0}
    def audit(event,args):
        if guard['active'] and event in {'open','socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
            guard['attempts']+=1;raise RuntimeError('retrieval IO forbidden: '+event)
    sys.addaudithook(audit)
    results=[{'query_id':q['query_id'],**d.search(view,bundle,q['query'],as_of,ix['system_terms'],limit=q['limit'],statistics=stats)} for q in data['queries']]
    guard['active']=False
    answers=unique(data['answers'],'query_id');detail=[];positive=[];native_positive=[]
    native_ids={did for did,doc in ix['documents'].items() if doc['native_chunk_count']}
    for r in results:
        a=answers[r['query_id']];ids=[x['doc_id'] for x in r['results']]
        if a['check']=='relevance':
            m=metrics.qm.metric(ids,a['expected_doc_ids']);positive.append(m);passed=bool(m['hit_at_5'])
            if set(a['expected_doc_ids'])&native_ids:native_positive.append(metrics.qm.metric(ids,set(a['expected_doc_ids'])&native_ids))
        elif a['check']=='ordered':passed=ids==a['expected_doc_ids']
        elif a['check']=='no_native_match':passed=not ids and r['status']=='ok'
        else:passed=not ids and r['status']=='needs_clarification'
        detail.append({'query_id':r['query_id'],'check':a['check'],'passed':passed,'actual_doc_ids':ids,'expected_doc_ids':a['expected_doc_ids']})
    enriched=unique(E.read_lines(run_path/'enriched.jsonl'),'doc_id');dates=unique(E.read_lines(run_path/'date-metadata.jsonl'),'doc_id');meta_detail=[]
    for m in data['metadata-labels']:
        did=m['doc_id']
        for field,label in m['fields'].items():
            pred=(dates[did] if field in d.DATE_FIELDS else enriched[did])['fields'][field]
            value=pred['value'];state=label['state']
            expected_status='not_found_native' if state=='not_observed_native' and field not in d.DATE_FIELDS else state
            match=value==label['value'] and pred['status']=='extracted' if state=='value' else value is None and (pred['status']==expected_status if state!='unresolved' else pred['status'] in {'needs_review','pending_vision','not_found_native','not_observed_native'})
            meta_detail.append({'doc_id':did,'field':field,'expected_state':state,'expected_value':label['value'],'actual_value':value,'actual_status':pred['status'],'passed':match})
    labelled=[r for r in meta_detail if r['expected_state']!='unresolved'];filled=[r for r in labelled if r['actual_value'] is not None];positive_meta=[r for r in labelled if r['expected_state']=='value'];correct=sum(r['passed'] for r in positive_meta)
    summary={'admitted':True,'evaluation_performed':True,'positive_relevance':metrics.qm.aggregate(positive),'native_positive_relevance':metrics.qm.aggregate(native_positive),
      'separate_query_checks':{kind:{'total':sum(r['check']==kind for r in detail),'passed':sum(r['check']==kind and r['passed'] for r in detail)} for kind in ['ordered','no_native_match','needs_clarification']},
      'metadata':{'labelled_slots':len(labelled),'unresolved_slots':len(meta_detail)-len(labelled),'correct_positive_values':correct,'filled_values':len(filled),'expected_values':len(positive_meta),
        'filled_precision':correct/len(filled) if filled else None,'value_recall':correct/len(positive_meta) if positive_meta else None},
      'paid_api_calls':0,'retrieval_io_attempts':guard['attempts'],'independent_evaluation':not settings.get('synthetic_fixture',False),
      'scope':'synthetic_smoke_not_independent' if settings.get('synthetic_fixture') else 'new_source_corpus_with_supplied_human_review_labels'}
    E.save_lines(out/'search-results.jsonl',results);E.dump(out/'query-comparison.json',detail);E.dump(out/'metadata-comparison.json',meta_detail);E.dump(out/'summary.json',summary)
    E.dump(out/'provenance.json',{'inputs':{str(package/p.name):E.digest(p) for p in package.iterdir() if p.is_file()},'run_provenance_sha256':E.digest(run_path/'provenance.json'),'implementation_freeze_sha256':E.digest(HERE/'frozen-implementation.json'),
      'outputs':{p.name:E.digest(p) for p in out.iterdir() if p.is_file()}})
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('package','run','output'):p.add_argument('--'+n,required=True)
    p.add_argument('--validate-only',action='store_true');a=p.parse_args();print(E.canonical(run(a.package,a.run,a.output,a.validate_only)))
