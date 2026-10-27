#!/usr/bin/env python3
"""Independent source checks and explicit OCR references. Never used by the parser."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from zipfile import ZipFile
from lxml import etree


NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    's':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def compact(s):return ''.join(unicodedata.normalize('NFC',s).split())


def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(previous[j]+1,current[-1]+1,previous[j-1]+(x!=y)))
        previous=current
    return previous[-1]


def all_elements(record):
    def walk(b):
        yield b
        for child in b.get('elements',[]):yield from walk(child)
    for b in record['blocks']:yield from walk(b)


def validate(records, files_root, ocr_reference, pdf_reference):
    records={r['doc_id']:r for r in records}
    paths={unicodedata.normalize('NFC',str(p.relative_to(files_root))):p for p in files_root.rglob('*') if p.is_file()}
    def source(identity):return paths[unicodedata.normalize('NFC',records[identity]['source']['relative_path'])]
    samples=[]
    def add(identity,kind,label,expected,observed):
        outcomes=[]
        for loc,text in expected.items():
            actual=observed.get(loc)
            outcomes.append({'loc':loc,'reference':text,'parsed':actual,'match':actual is not None and compact(text)==compact(actual)})
        samples.append({'doc_id':identity,'format':kind,'table':label,'method':'source OOXML comparison' if kind!='pdf' else 'rendered-page transcription',
                        'cells':outcomes,'extra_locations':sorted(set(observed)-set(expected)),
                        'correct':sum(c['match'] for c in outcomes),'total':len(outcomes)})
    # Six DOCX tables, spanning companies; read raw XML independently of python-docx.
    for identity in ['D-005','D-023','D-043','D-057','D-067','D-101']:
        with ZipFile(source(identity)) as z:root=etree.fromstring(z.read('word/document.xml'))
        table=root.find('w:body/w:tbl',NS)
        expected={f'{ri}:{ci}':''.join(tc.xpath('.//w:t/text()',namespaces=NS))
                  for ri,row in enumerate(table.findall('w:tr',NS),1) for ci,tc in enumerate(row.findall('w:tc',NS),1)}
        observed={f"{c['row']}:{c['column']}":c['text'] for b in records[identity]['blocks'] if b['type']=='table_row' and b['loc']['table']==1 for c in b['cells']}
        add(identity,'docx','table 1',expected,observed)
    # Eight worksheet regions, including all four server-workbook examples.
    for identity in ['D-003','D-009','D-021','D-035','D-061','D-077','D-083','D-099']:
        with ZipFile(source(identity)) as z:
            wb=etree.fromstring(z.read('xl/workbook.xml'))
            sheet_name=wb.find('s:sheets/s:sheet',NS).get('name')
            xml=etree.fromstring(z.read('xl/worksheets/sheet1.xml'))
            shared=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                shared=[''.join(si.xpath('.//s:t/text()',namespaces=NS)) for si in etree.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
            expected={}
            for cell in xml.findall('s:sheetData/s:row/s:c',NS):
                if cell.get('t')=='inlineStr':text=''.join(cell.xpath('.//s:t/text()',namespaces=NS))
                elif cell.get('t')=='s':text=shared[int(cell.find('s:v',NS).text)]
                else:text=cell.findtext('s:v',default='',namespaces=NS)
                if text:expected[cell.get('r')]=text
        observed={c['address']:c['text'] for b in records[identity]['blocks'] if b['loc'].get('sheet')==sheet_name
                  for c in b['cells'] if c['address']==c['source_cell']}
        add(identity,'xlsx',sheet_name,expected,observed)
    # Six actual PowerPoint tables, matched to slide and shape ID from OOXML.
    for identity in ['D-001','D-020','D-031','D-039','D-053','D-064']:
        with ZipFile(source(identity)) as z:
            slides=sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+.xml',n)),key=lambda n:int(re.search(r'slide(\d+)',n)[1]))
            for slide in slides:
                root=etree.fromstring(z.read(slide))
                frames=root.findall('.//p:graphicFrame',NS)
                frame=next((f for f in frames if f.find('.//a:tbl',NS) is not None),None)
                if frame is not None:break
            sn=int(re.search(r'slide(\d+)',slide)[1]);shape_id=int(frame.find('.//p:cNvPr',NS).get('id'))
            table=frame.find('.//a:tbl',NS)
            expected={f'{rn}:{cn}':'\n'.join(''.join(p.xpath('.//a:t/text()',namespaces=NS)) for p in cell.findall('.//a:p',NS))
                      for rn,row in enumerate(table.findall('a:tr',NS),1) for cn,cell in enumerate(row.findall('a:tc',NS),1)}
        observed={f"{c['row']}:{c['column']}":c['text'] for b in all_elements(records[identity]) if b['type']=='table_row' and b['loc']['slide']==sn and b['loc']['shape_id']==shape_id for c in b['cells']}
        add(identity,'pptx',f'slide {sn} shape {shape_id}',expected,observed)
    for item in pdf_reference['tables']:
        identity=item['doc_id']
        expected={f'{rn}:{cn}':value for rn,row in enumerate(item['rows'],1) for cn,value in enumerate(row,1)}
        observed={f"{c['row']}:{c['column']}":c['text'] for b in records[identity]['blocks'] if b['type']=='table_row' and b['loc']['page']==item['page'] and b['loc']['table']==item['table'] for c in b['cells']}
        add(identity,'pdf',f"page {item['page']} table {item['table']}",expected,observed)
    # CER references are external QA artifacts. No reference is visible to parse.py.
    ocr_results=[]
    for reference in ocr_reference['documents']:
        record=records[reference['doc_id']]
        lines=[e for e in all_elements(record) if e['type']=='ocr_line']
        assigned=set();regions=[]
        for region in reference['regions']:
            selected=[]
            for i,line in enumerate(lines):
                b=line['loc']['bbox_normalized'];x=(b[0]+b[2])/2;y=(b[1]+b[3])/2
                a=region['bbox']
                if line['loc']['page']==region['page'] and a[0]<=x<=a[2] and a[1]<=y<=a[3]:
                    assert i not in assigned,'overlapping OCR reference regions'
                    selected.append(line['text']);assigned.add(i)
            predicted='\n'.join(selected)
            target=region['text']
            errors=distance(compact(target),compact(predicted))
            strict_ref=' '.join(unicodedata.normalize('NFC',target).split())
            strict_pred=' '.join(unicodedata.normalize('NFC',predicted).split())
            regions.append({'page':region['page'],'bbox':region['bbox'],'reference':target,'parsed':predicted,
                            'reference_chars':len(compact(target)),'edit_errors':errors,
                            'spacing_reference_chars':len(strict_ref),'spacing_edit_errors':distance(strict_ref,strict_pred)})
        unmatched=[l['text'] for i,l in enumerate(lines) if i not in assigned]
        n=sum(r['reference_chars'] for r in regions)
        e=sum(r['edit_errors'] for r in regions)+sum(len(compact(t)) for t in unmatched)
        ocr_results.append({'doc_id':reference['doc_id'],'reference_chars':n,'edit_errors':e,'cer_no_whitespace':e/n,
                            'spacing_reference_chars':sum(r['spacing_reference_chars'] for r in regions),
                            'spacing_edit_errors':sum(r['spacing_edit_errors'] for r in regions)+sum(len(t) for t in unmatched),
                            'unassigned_lines':unmatched,'regions':regions})
    loc_errors=[];element_count=0
    for identity,r in records.items():
        for b in all_elements(r):
            element_count+=1;loc=b.get('loc',{})
            if not loc:loc_errors.append([identity,'empty_loc'])
            if 'bbox_normalized' in loc:
                x0,y0,x1,y1=loc['bbox_normalized']
                if not (0<=x0<=x1<=1 and 0<=y0<=y1<=1):loc_errors.append([identity,'bad_ocr_bbox'])
            if 'bbox' in loc:
                x0,y0,x1,y1=loc['bbox'];page=r['details']['pages'][loc['page']-1]
                if not (-1<=x0<=x1<=page['width']+1 and -1<=y0<=y1<=page['height']+1):loc_errors.append([identity,'bad_pdf_bbox'])
    table_n=sum(s['total'] for s in samples);table_ok=sum(s['correct'] for s in samples)
    no_char=sum(r['reference_chars'] for r in ocr_results);no_error=sum(r['edit_errors'] for r in ocr_results)
    enc_errors=[r['doc_id'] for r in records.values() if any('\ufffd' in b['text'] for b in r['blocks']) or 'UnicodeDecodeError' in r.get('error','')]
    summary={'documents':len(records),'parser_status_counts':dict(Counter(r['status'] for r in records.values())),
             'block_count':sum(len(r['blocks']) for r in records.values()),'element_count_with_locations':element_count,
             'location_errors':loc_errors,'encoding_error_documents':enc_errors,
             'cp949_documents':[r['doc_id'] for r in records.values() if r.get('details',{}).get('encoding')=='cp949'],
             'source_hashes_match':all(hashlib.sha256(source(i).read_bytes()).hexdigest()==r['source']['sha256'] for i,r in records.items()),
             'table_samples':len(samples),'table_cells':table_n,'correct_table_cells':table_ok,'table_cell_accuracy':table_ok/table_n,
             'ocr_reference_chars':no_char,'ocr_edit_errors':no_error,'ocr_cer_no_whitespace':no_error/no_char,
             'ocr_cer_with_spacing':sum(r['spacing_edit_errors'] for r in ocr_results)/sum(r['spacing_reference_chars'] for r in ocr_results)}
    return {'summary':summary,'table_results':samples,'ocr_results':ocr_results}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--files-root',required=True,type=Path);ap.add_argument('--parsed',required=True,type=Path)
    ap.add_argument('--ocr-reference',required=True,type=Path);ap.add_argument('--pdf-table-reference',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    a=ap.parse_args()
    if a.output.exists():raise ValueError('출력 파일이 이미 있습니다')
    report=validate([json.loads(l) for l in a.parsed.read_text().splitlines()],a.files_root,
                    json.loads(a.ocr_reference.read_text()),json.loads(a.pdf_table_reference.read_text()))
    report['evidence_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [a.parsed,a.ocr_reference,a.pdf_table_reference,Path(__file__)]}
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
