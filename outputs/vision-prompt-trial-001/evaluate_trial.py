"""Offline paired source review. Same references/metrics and v3 gate both sides."""
import collections
import importlib.util
import json
from pathlib import Path
from run_trial import ROOT,OUT,BASE,load,old,q
spec=importlib.util.spec_from_file_location('review_helpers',ROOT/'outputs/vision-source-review-001/review.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)

def score(response,item,model,ref):
    raw=(response.get('choices') or [{}])[0].get('message',{}).get('content') or ''
    w,complete,closed=h.recover(raw)
    obs=h.text_items(w)
    claims=[dict(text=c['text'],kind='claim',bbox=c.get('bbox')) for f in w.get('figures',[]) for c in f.get('claims',[]) if isinstance(c.get('text'),str)]
    cov=h.coverage(ref,obs);anycov=h.coverage(ref,obs+claims)
    assessment=q.validate_response(response,item,model);assessment.pop('data')
    issues=q.check_quality(w,item.get('native_context',[]))
    duplicate_issues=[i for i in issues if i['code'].startswith('DUPLICATE_')]
    tab=h.table_scores(ref,w);graph=h.graph_scores(ref,w,True)
    cells=[c for t in w.get('tables',[]) for c in t.get('cells',[])]
    codes=dict(collections.Counter(i['code'] for i in issues))
    return dict(json_complete=complete,finish_reason=(response.get('choices') or [{}])[0].get('finish_reason'),
        trailing_whitespace_characters=len(raw)-len(raw.rstrip()),
        recovered_prefix_diagnostic_only=not complete,coverage=cov,coverage_including_claims=anycov,
        only_in_claims=[a['expected'] for a,b in zip(cov['details'],anycov['details']) if not a['compatible'] and b['compatible']],
        duplicate_issue_instances=len(duplicate_issues),duplicate_detected=bool(duplicate_issues),issue_counts=codes,
        source_phrase_duplicates=h.duplicates(ref,w),tables=tab,graph=graph,
        object_counts=dict(texts=len(w.get('texts',[])),tables=len(w.get('tables',[])),cells=sum('text' in c for c in cells),
            figures=len(w.get('figures',[])),nodes=sum('label' in n for f in w.get('figures',[]) for n in f.get('nodes',[])),
            edges=sum('to_node' in e for f in w.get('figures',[]) for e in f.get('relations',[])),claims=len(claims)),
        complete_with_unreadable=w.get('status')=='complete' and any(c.get('value_status')=='unreadable' for c in cells),
        assessment=assessment,raw_content=raw,diagnostic_wire=w)

def summary(records,side):
    rs=[r[side] for r in records];tabs=[t for r in rs for t in r['tables']['tables']]
    return dict(images=len(rs),json_complete=sum(r['json_complete'] for r in rs),
        transferred=sum(r['assessment']['transfer_allowed'] for r in rs),
        duplicate_images=sum(r['duplicate_detected'] for r in rs),
        duplicate_issue_instances=sum(r['duplicate_issue_instances'] for r in rs),
        issues_by_image=dict(collections.Counter(c for r in rs for c in r['issue_counts'])),
        only_in_claims=sum(len(r['only_in_claims']) for r in rs),
        only_in_claims_images=sum(bool(r['only_in_claims']) for r in rs),
        literal_retained=sum(r['coverage']['compatible'] for r in rs),
        anywhere_retained=sum(r['coverage_including_claims']['compatible'] for r in rs),
        reference_total=sum(r['coverage']['total'] for r in rs),
        literal_unmatched=sum(r['coverage']['total']-r['coverage']['compatible'] for r in rs),
        anywhere_unmatched=sum(r['coverage_including_claims']['total']-r['coverage_including_claims']['compatible'] for r in rs),
        complete_with_unreadable_images=sum(r['complete_with_unreadable'] for r in rs),
        table_cells_correct=sum(t['structure']['correct'] for t in tabs),table_cells_expected=sum(t['structure']['expected'] for t in tabs),
        table_cells_emitted=sum(r['object_counts']['cells'] for r in rs),
        graph_nodes_correct=sum(r['graph']['nodes']['correct'] for r in rs),graph_nodes_expected=sum(r['graph']['nodes']['expected'] for r in rs),
        graph_edges_correct=sum(r['graph']['edges']['correct'] for r in rs),graph_edges_expected=sum(r['graph']['edges']['expected'] for r in rs))

def main():
    m=load(OUT/'manifest.json');refs=load(ROOT/'outputs/vision-source-review-001/source-references.json')
    previous=load(ROOT/'outputs/vision-source-review-001/evaluation.json');reports=[];lost=[];conversion=0
    for model in m['models']:
        records=[]
        baseline={r['key']:r for mr in previous if mr['summary']['model']==model.split('/')[1] for r in mr['records']}
        for item in m['items']:
            key=old.task_id(item);directory=model.split('/')[1]+'/units/'+key
            before=score(load(BASE/directory/'response.json'),item,model,refs[key]);after=score(load(OUT/directory/'response.json'),item,model,refs[key])
            assert before['coverage']==baseline[key]['coverage']
            assert before['only_in_claims']==baseline[key]['source_items_only_in_claims']
            assert before['tables']==baseline[key]['tables']
            for side,s in [('before',before),('after',after)]:
                if side=='after' and s['assessment']['transfer_allowed']:
                    doc=load(OUT/directory/'common-block-document.json')
                    assert not q.base.common.check(doc)
                    assert h.wire_payload(s['diagnostic_wire'])==h.common_payload(doc,item)
                    conversion+=1
                (OUT/model.split('/')[1]/'units'/key/(side+'-content.txt')).write_text(s.pop('raw_content'))
                s.pop('diagnostic_wire')
            newly_missing=[];newly_literal_missing=[];recovered=[]
            for b,a in zip(before['coverage_including_claims']['details'],after['coverage_including_claims']['details']):
                assert b['expected']==a['expected']
                if b['compatible'] and not a['compatible']:newly_missing.append(a)
                if not b['compatible'] and a['compatible']:recovered.append(a['expected'])
            for b,a in zip(before['coverage']['details'],after['coverage']['details']):
                if b['compatible'] and not a['compatible']:newly_literal_missing.append(a)
            rec=dict(key=key,reference_method=refs[key]['method'],reference_status='existing_assistant_draft_not_independent_gold',
                before=before,after=after,newly_missing_anywhere=newly_missing,newly_missing_literal=newly_literal_missing,recovered_anywhere=recovered)
            records.append(rec)
            lost.extend(dict(model=model,key=key,**d) for d in newly_missing)
        reports.append(dict(model=model,before=summary(records,'before'),after=summary(records,'after'),records=records))
    old.write(OUT/'comparison.json',reports);old.write(OUT/'newly-unmatched-source-items.json',lost)
    changed=[p for p,sha in load(OUT/'preserved-input-hashes.json').items() if old.digest(p)!=sha];assert not changed
    old.write(OUT/'verification.json',dict(paired_responses=14,source_reference_unchanged=True,
        baseline_metrics_reproduced=True,only_prompt_changed_all_requests=all(i['only_system_prompt_changed'] for i in load(OUT/'input-verification.json')),
        schema_valid_converted_responses=conversion,converted_payload_preserved=conversion,
        previous_files_checked=len(load(OUT/'preserved-input-hashes.json')),changed_files=changed,
        newly_unmatched_anywhere=len(lost),independent_evaluation=False))
    print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in reports],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
