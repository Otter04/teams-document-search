"""Offline diagnostics of retained model responses, including rejected geometry.

Does not repair responses or change admission rules. Raw-content diagnostics are
reported separately from the existing validated common-block evaluation.
"""
from collections import Counter
import statistics
from run import ROOT, DEFAULT_RUN, MODELS, load, write, digest, task_id, now
from contract import VALIDATOR
from evaluate import compact, literal, prf, edge_key

def graph_scores(w,ref):
    labels={n['node_id']:compact(n['label']) for n in ref['nodes']}
    observed_nodes=[];observed_edges=[]
    for f in w.get('figures',[]):
        observed={n['id']:compact(n['label']) for n in f['nodes']}
        observed_nodes.extend(observed.values())
        observed_edges.extend(edge_key(observed.get(e['from_node'],'UNKNOWN'),observed.get(e['to_node'],'UNKNOWN'),e['direction']) for e in f['relations'])
    return {'nodes':prf(labels.values(),observed_nodes),
            'edges':prf([edge_key(labels[e['from_node']],labels[e['to_node']],e['direction']) for e in ref['relations']],observed_edges)}

def audit(out=DEFAULT_RUN):
    manifest=load(out/'manifest.json');reports=[]
    originals=load(ROOT/'outputs/parsing-run-003/evaluation/report.json')['string_results']
    table_ref=load(ROOT/'outputs/common-block-design/annotations/D-044-draft.json')
    graph_ref=load(ROOT/'outputs/common-block-design/annotations/D-069-draft.json')
    for model in MODELS:
        mdir=out/model.split('/')[1];results=[];raws={};missing=[];finishes=Counter()
        for item in manifest['items']:
            base=mdir/'units'/task_id(item)
            if not (base/'result.json').exists():missing.append(task_id(item));continue
            result=load(base/'result.json');results.append(result)
            if not (base/'response.json').exists():continue
            response=load(base/'response.json')
            try:
                import json
                choice=response['choices'][0]
                finishes.update([choice.get('finish_reason','unknown')])
                if choice['finish_reason']!='stop' or response['model']!=model or response['provider']!='DeepInfra':continue
                wire=json.loads(choice['message']['content'])
                if list(VALIDATOR.iter_errors(wire)):continue
                raws[(item['doc_id'],item['unit_id'])]=wire
            except (ValueError,KeyError,IndexError,TypeError):continue
        scan=[]
        for ref in originals:
            if ref['doc_id'] not in ('D-044','D-102','D-069'):continue
            text='\n'.join(literal(w) for (doc,_),w in raws.items() if doc==ref['doc_id'])
            scan.append({'doc_id':ref['doc_id'],'expected':ref['text'],'found':compact(ref['text']) in compact(text)})
        def ck(c):return (c['row'],c['column'],c['row_span'],c['column_span'],compact(c['text']))
        tw=raws.get(('D-044','vision:page2'),{'tables':[]})
        table=prf([ck(c) for c in table_ref['cells']],[ck(c) for t in tw['tables'] for c in t['cells']])
        graph=graph_scores(raws.get(('D-069','vision:page1'),{}),graph_ref)
        failure=[{k:r.get(k) for k in ['doc_id','unit_id','status','errors','http_status','cost_usd']} for r in results if r['status']!='valid']
        status_conflicts=[];repeat_flags=[];cell_statuses=Counter()
        for (doc,unit),w in raws.items():
            cells=[c for t in w['tables'] for c in t['cells']]
            cell_statuses.update(c['value_status'] for c in cells)
            unreadable=[c for c in cells if c['value_status']=='unreadable']
            if unreadable and w['status']=='complete':
                status_conflicts.append({'doc_id':doc,'unit_id':unit,'reported_status':w['status'],
                    'unreadable_cells':len(unreadable),'unreadable_cells_with_text':sum(bool(c['text'].strip()) for c in unreadable)})
            texts=Counter(compact(t['text']) for t in w['texts'] if t['text'].strip())
            repeats=sum(n-1 for n in texts.values() if n>1)
            if repeats:repeat_flags.append({'doc_id':doc,'unit_id':unit,'exact_repeated_text_blocks':repeats})
        times=[r['elapsed_seconds'] for r in results if 'elapsed_seconds' in r]
        partial=[{'doc_id':doc,'unit_id':unit,'status':w['status'],'warnings':w['warnings']} for (doc,unit),w in raws.items() if w['status']!='complete']
        byunit={(r['doc_id'],r['unit_id']):r for r in results}
        documents={}
        for item in manifest['items']:
            d=documents.setdefault(item['doc_id'],{'doc_id':item['doc_id'],'corpus':item['corpus'],'target_units':0,'valid_units':0,'failed_units':0,'missing_units':0})
            d['target_units']+=1;r=byunit.get((item['doc_id'],item['unit_id']))
            d['missing_units' if r is None else 'valid_units' if r['status']=='valid' else 'failed_units']+=1
        report={'model':model,'evaluated_at':now(),'expected_units':len(manifest['items']),'responses':len(results),'schema_and_reference_valid':sum(r['status']=='valid' for r in results),
            'raw_schema_valid_before_geometry_checks':len(raws),'missing_units':missing,'failure_cases':failure,
            'finish_reasons':dict(finishes),
            'all_units_valid_documents':sum(d['valid_units']==d['target_units'] for d in documents.values()),
            'documents':list(documents.values()),
            'error_messages':dict(Counter(e for r in results for e in r.get('errors',[]))),
            'partial_or_unreadable':partial,
            'cell_value_status_counts':dict(cell_statuses),
            'complete_with_unreadable_cells':status_conflicts,
            'exact_text_repetition_flags_need_source_review':repeat_flags,
            'cost_usd_known_returned_responses':sum(r.get('cost_usd') or 0 for r in results),
            'usage_missing_cost_units':sum(r.get('cost_usd') is None for r in results),
            'latency_seconds':{'median':statistics.median(times) if times else None,'max':max(times) if times else None},
            'raw_diagnostics_not_admitted_to_common_blocks':{
                'scan_strings':{'correct':sum(s['found'] for s in scan),'total':len(scan),'details':scan},
                'D044_table_anchor_content':table,'D069_exact_graph':graph},
            'interpretation':'Diagnostics only. Rejected geometry remains rejected; exact-match checks use pre-existing assistant draft annotations. Claims, bounding-box correctness and global semantic accuracy are not certified.'}
        write(mdir/'evaluation/response-audit.json',report);reports.append(report)
    write(out/'response-audit-comparison.json',reports)
    return reports

if __name__=='__main__':
    import json
    print(json.dumps([{k:r[k] for k in ['model','responses','schema_and_reference_valid','raw_schema_valid_before_geometry_checks','cost_usd_known_returned_responses']} for r in audit()],ensure_ascii=False))
