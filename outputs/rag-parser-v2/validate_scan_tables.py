"""Independent scan table checks against a separate, image-reviewed reference."""
import argparse,json,hashlib
from pathlib import Path
from validate import compact,all_elements


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return intersection/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection)


def evaluate(records,reference):
    records={r['doc_id']:r for r in records};results=[];extra=[]
    expected={(t['doc_id'],t['page'],t['table']) for t in reference['tables']}
    for identity in reference['scan_documents']:
        r=records[identity]
        for page in r['details']['pages']:
            for t in page.get('tables',[]):
                if (identity,page['page'],t['table']) not in expected:extra.append([identity,page['page'],t['table']])
    for ref in reference['tables']:
        r=records[ref['doc_id']]
        rows=[e for e in all_elements(r) if e['type']=='table_row' and e['loc'].get('page')==ref['page'] and e['loc'].get('table')==ref['table']]
        actual={(c['row'],c['column']):c for row in rows for c in row['cells']}
        cells=[]
        for rn,row in enumerate(ref['rows'],1):
            for cn,text in enumerate(row,1):
                c=actual.get((rn,cn));cells.append({'row':rn,'column':cn,'reference':text,'parsed':c['text'] if c else None,
                                                  'text_match':bool(c is not None and compact(c['text'])==compact(text)),
                                                  'position_and_span_match':bool(c is not None and c['row_span']==1 and c['col_span']==1)})
        page=r['details']['pages'][ref['page']-1]
        grid=next((t for t in page.get('tables',[]) if t['table']==ref['table']),None)
        shape=bool(grid and (grid['row_count'],grid['column_count'])==(len(ref['rows']),len(ref['rows'][0])))
        boxes=[c['bbox_normalized'] for c in actual.values()]
        box=[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)] if boxes else None
        results.append({'doc_id':ref['doc_id'],'page':ref['page'],'table':ref['table'],'shape_match':shape,
                        'bbox_iou':iou(box,ref['bbox_normalized']) if box else 0,
                        'extra_cells':len(set(actual)-{(c['row'],c['column']) for c in cells}),'cells':cells})
    cells=[c for r in results for c in r['cells']];correct=sum(c['text_match'] for c in cells)
    return {'summary':{'expected_tables':len(results),'shape_matches':sum(r['shape_match'] for r in results),
                       'extra_tables':len(extra),'extra_cells':sum(r['extra_cells'] for r in results),
                       'cells':len(cells),'correct_cells':correct,'cell_accuracy':correct/len(cells),
                       'position_and_span_matches':sum(c['position_and_span_match'] for c in cells),
                       'table_bbox_iou_min':min(r['bbox_iou'] for r in results)},'tables':results,'unexpected_tables':extra,
            'comparison':'NFC and whitespace removed only; punctuation preserved; all 5 scan pages checked for extra tables'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--parsed',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Use a new output file')
    result=evaluate([json.loads(l) for l in a.parsed.read_text().splitlines()],json.loads(a.reference.read_text()))
    result['evidence_hashes']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [a.parsed,a.reference,Path(__file__)]}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result['summary'],ensure_ascii=False))

if __name__=='__main__':main()
