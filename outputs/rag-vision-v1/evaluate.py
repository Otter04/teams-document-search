"""Offline draft-reference checks. Never sends annotations to a model."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import unicodedata
from run import ROOT, DEFAULT_RUN, MODELS, load, lines, write, task_id

def compact(x):return ''.join(unicodedata.normalize('NFC',str(x)).split())
def prf(expected,observed):
    expected,observed=Counter(expected),Counter(observed)
    tp=sum((expected & observed).values());n=sum(expected.values());m=sum(observed.values())
    p=tp/m if m else 0;r=tp/n if n else 0
    return dict(correct=tp,expected=n,predicted=m,precision=p,recall=r,f1=2*p*r/(p+r) if p+r else 0)
def literal(wire):
    return '\n'.join([x['text'] for x in wire['texts']]+[c['text'] for t in wire['tables'] for c in t['cells']]+
                     [n['label'] for f in wire['figures'] for n in f['nodes']])
def edge_key(a,b,d):
    return (*sorted([a,b]),d) if d in ('undirected','bidirectional') else (a,b,d)

def evaluate(out):
    manifest=load(out/'manifest.json');summaries={s['model']:s for s in load(out/'summary.json')['models']}
    allreports=[]
    annotations=ROOT/'outputs/common-block-design/annotations'
    original_strings=load(ROOT/'outputs/parsing-run-003/evaluation/report.json')['string_results']
    for model in MODELS:
        mdir=out/model.split('/')[1];items={}
        review=[]
        for item in manifest['items']:
            base=mdir/'units'/task_id(item)
            if (base/'extraction.json').exists():items[(item['doc_id'],item['unit_id'])]=load(base/'extraction.json')
            review.append(dict(doc_id=item['doc_id'],unit_id=item['unit_id'],image_path=item['image_path'],
                extraction_path=str(base/'extraction.json'),review_status='pending_human_or_source_review',
                checks=['literal completeness','table structure','diagram relations','grounded claims','bbox accuracy']))
        scan=[]
        for ref in original_strings:
            if ref['doc_id'] not in ('D-044','D-102','D-069'):continue
            observed='\n'.join(literal(v) for (doc,_),v in items.items() if doc==ref['doc_id'])
            scan.append(dict(doc_id=ref['doc_id'],reference=ref['text'],included=compact(ref['text']) in compact(observed)))
        table=load(annotations/'D-044-draft.json')
        w=items.get(('D-044','vision:page2'),dict(tables=[]))
        def cellkey(c):return (c['row'],c['column'],c['row_span'],c['column_span'],compact(c['text']))
        cells=prf([cellkey(c) for c in table['cells']],[cellkey(c) for t in w['tables'] for c in t['cells']])
        diagram=load(annotations/'D-069-draft.json')
        w=items.get(('D-069','vision:page1'),dict(figures=[]))
        expected_labels={n['node_id']:compact(n['label']) for n in diagram['nodes']}
        observed_nodes=[];observed_edges=[]
        for f in w['figures']:
            labels={n['id']:compact(n['label']) for n in f['nodes']}
            observed_nodes.extend(labels.values())
            observed_edges.extend(edge_key(labels[e['from_node']],labels[e['to_node']],e['direction']) for e in f['relations'])
        nodes=prf(expected_labels.values(),observed_nodes)
        edges=prf([edge_key(expected_labels[e['from_node']],expected_labels[e['to_node']],e['direction'])
                   for e in diagram['relations']],observed_edges)
        report=dict(model=model,execution=summaries[model],reference_status='assistant_prepared_draft_not_independently_reviewed',
          scan_required_strings={'correct':sum(r['included'] for r in scan),'total':len(scan),'details':scan},
          D044_table_anchor_content=cells,D069_nodes_exact_label=nodes,D069_edges_exact_label_direction=edges,
          semantic_claim_precision=None,bbox_accuracy=None,overall_quality_pass=None,
          notes=['Missing/invalid outputs count as misses in these draft checks.',
                 'Exact label matching can penalize wording differences; inspect source before judging semantics.',
                 'JSON validity and complete self-report do not establish accuracy.',
                 'Full 132-image semantic ground truth is not available; review queue covers every unit.'])
        write(mdir/'evaluation/draft-checks.json',report)
        write(mdir/'evaluation/source-review-queue.json',review)
        allreports.append(report)
    write(out/'evaluation-comparison.json',allreports)
    return allreports

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,default=DEFAULT_RUN)
    r=evaluate(p.parse_args().run)
    print(json.dumps([{'model':x['model'],'execution':x['execution'],'scan_strings':{k:v for k,v in x['scan_required_strings'].items() if k!='details'},
                       'table':x['D044_table_anchor_content'],'nodes':x['D069_nodes_exact_label'],'edges':x['D069_edges_exact_label_direction']} for x in r],ensure_ascii=False))
