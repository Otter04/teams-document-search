#!/usr/bin/env python3
"""Evaluate real common-block records. No model/gold data is sent to the parser."""
import argparse
from collections import Counter,defaultdict
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
from zipfile import ZipFile

from lxml import etree
import pdfplumber
from parse import validation,digest,dump,jsonl,source_map

BASE=Path(__file__).resolve().parent.parent
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    's':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def compact(text): return ''.join(unicodedata.normalize('NFC',str(text)).split())
def loadlines(path): return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]

def project_literal(record):
    if record.get('record_kind')!='run_result': raise ValueError('Only actual run_result records may be evaluated')
    errors=validation.check(record)
    if errors: raise ValueError('; '.join(errors[:3]))
    return {'doc_id':record['doc_id'],'blocks':[
        {'type':b['type'],'text':unicodedata.normalize('NFC',b['text']),'loc':b['loc'],'heading_path':b['heading_path']}
        for b in sorted(record['blocks'],key=lambda b:b['order'])
        if b['type'] not in ('table','slide') and not b['content_refs'] and b['text']]}

def native_table_checks(records,files_root,pdf_reference):
    records={r['doc_id']:r for r in records}; paths=source_map(files_root); samples=[]
    def source(identity): return paths[records[identity]['source']['relative_path']]
    def add(identity,kind,label,expected,observed):
        rows=[{'loc':key,'reference':text,'parsed':observed.get(key),
               'match':key in observed and compact(text)==compact(observed[key])} for key,text in expected.items()]
        # XLSX blank slots are deliberately represented, but only source-populated anchors belong to this sample.
        extra=[key for key,value in observed.items() if key not in expected and compact(value)]
        samples.append({'doc_id':identity,'format':kind,'source_region':label,'cells':rows,'extra_nonblank_cells':extra,
                        'correct':sum(x['match'] for x in rows),'total':len(rows)})
    for identity in ['D-005','D-023','D-043','D-057','D-067','D-101']:
        with ZipFile(source(identity)) as z: root=etree.fromstring(z.read('word/document.xml'))
        table=root.find('w:body/w:tbl',NS)
        expected={f'{r}:{c}':''.join(tc.xpath('.//w:t/text()',namespaces=NS))
                  for r,row in enumerate(table.findall('w:tr',NS),1) for c,tc in enumerate(row.findall('w:tc',NS),1)}
        observed={f"{c['row']}:{c['column']}":c['text'] for b in records[identity]['blocks'] if b['type']=='table_row'
                  for c in b['cells'] if c['loc'].get('table_index')==1}
        add(identity,'docx','table 1',expected,observed)
    for identity in ['D-003','D-009','D-021','D-035','D-061','D-077','D-083','D-099']:
        with ZipFile(source(identity)) as z:
            wb=etree.fromstring(z.read('xl/workbook.xml')); sheet_name=wb.find('s:sheets/s:sheet',NS).get('name')
            xml=etree.fromstring(z.read('xl/worksheets/sheet1.xml')); shared=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                shared=[''.join(si.xpath('.//s:t/text()',namespaces=NS)) for si in etree.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
            expected={}
            for c in xml.findall('s:sheetData/s:row/s:c',NS):
                if c.get('t')=='inlineStr': text=''.join(c.xpath('.//s:t/text()',namespaces=NS))
                elif c.get('t')=='s': text=shared[int(c.find('s:v',NS).text)]
                else: text=c.findtext('s:v',default='',namespaces=NS)
                if text: expected[c.get('r')]=text
        observed={c['loc']['cell_range'].split(':')[0]:c['text'] for b in records[identity]['blocks']
                  if b['type']=='table_row' for c in b['cells'] if c['loc'].get('sheet')==sheet_name}
        add(identity,'xlsx',sheet_name,expected,observed)
    for identity in ['D-001','D-020','D-031','D-039','D-053','D-064']:
        with ZipFile(source(identity)) as z:
            slides=sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+.xml',n)),key=lambda n:int(re.search(r'slide(\d+)',n)[1]))
            frame=None
            for slide in slides:
                root=etree.fromstring(z.read(slide))
                frame=next((f for f in root.findall('.//p:graphicFrame',NS) if f.find('.//a:tbl',NS) is not None),None)
                if frame is not None: break
            sn=int(re.search(r'slide(\d+)',slide)[1]); sid=int(frame.find('.//p:cNvPr',NS).get('id'))
            table=frame.find('.//a:tbl',NS)
            expected={f'{r}:{c}':'\n'.join(''.join(p.xpath('.//a:t/text()',namespaces=NS)) for p in tc.findall('.//a:p',NS))
                      for r,row in enumerate(table.findall('a:tr',NS),1) for c,tc in enumerate(row.findall('a:tc',NS),1)}
        observed={f"{c['row']}:{c['column']}":c['text'] for b in records[identity]['blocks'] if b['type']=='table_row'
                  and b['loc'].get('slide')==sn and b['loc'].get('shape_ids')==[sid] for c in b['cells']}
        add(identity,'pptx',f'slide {sn}, shape {sid}',expected,observed)
    for item in pdf_reference['tables']:
        identity=item['doc_id']; record=records[identity]
        # Stable source page/table locator encoded by the parser's logical block key.
        table=next((b for b in record['blocks'] if b['type']=='table' and b['block_id'].endswith(f"-p{item['page']}-table{item['table']}")),None)
        observed={f"{c['row']}:{c['column']}":c['text'] for b in record['blocks'] if b['type']=='table_row'
                  and table and b['parent_id']==table['block_id'] for c in b['cells']}
        expected={f'{r}:{c}':value for r,row in enumerate(item['rows'],1) for c,value in enumerate(row,1)}
        add(identity,'pdf',f"page {item['page']}, table {item['table']}",expected,observed)
    return {'method':'raw OOXML anchors; separately source-reviewed PDF table references; NFC/whitespace only',
            'reference_status':'PDF annotations assistant-reviewed, independent human sign-off pending',
            'regions':len(samples),'correct':sum(s['correct'] for s in samples),'total':sum(s['total'] for s in samples),
            'extra_nonblank_cells':sum(len(s['extra_nonblank_cells']) for s in samples),'samples':samples}

def check_inventory(records,files_root,manifest):
    mapping=source_map(files_root); ids={m['doc_id'] for m in manifest}; results=[]
    if {r['doc_id'] for r in records}!=ids: raise ValueError('document inventory mismatch')
    for record in records:
        path=mapping[record['source']['relative_path']]; kind=record['source']['format']
        if kind=='pdf':
            with pdfplumber.open(path) as pdf: expected={f'native:page{i}' for i in range(1,len(pdf.pages)+1)}
        elif kind in ('pptx','xlsx'):
            with ZipFile(path) as z:
                if kind=='pptx':
                    xml=etree.fromstring(z.read('ppt/presentation.xml'))
                    count=len(xml.findall('p:sldIdLst/p:sldId',NS)); prefix='slide'
                else:
                    xml=etree.fromstring(z.read('xl/workbook.xml')); count=len(xml.findall('s:sheets/s:sheet',NS)); prefix='sheet'
            expected={f'native:{prefix}{i}' for i in range(1,count+1)}
        else: expected={'native:document' if kind=='docx' else 'native:lines'}
        observed={u['unit_id'] for u in record['coverage']['units'] if u['unit_id'].startswith('native:')}
        results.append({'doc_id':record['doc_id'],'source_hash_matches':digest(path)==record['source']['sha256'],
                        'native_unit_count':len(expected),'native_inventory_matches':expected==observed})
    return results

def run(args):
    run_dir=Path(args.run); out=run_dir/'evaluation'
    if out.exists(): raise ValueError('Evaluation directory already exists')
    out.mkdir()
    records=loadlines(run_dir/'parsed.jsonl'); manifest=loadlines(run_dir/'manifest.jsonl')
    schema_checks=[{'doc_id':r['doc_id'],'errors':validation.check(r)} for r in records]
    if any(x['errors'] for x in schema_checks):
        dump(out/'schema-errors.json',schema_checks); raise ValueError('Invalid records cannot be scored')
    projections=[project_literal(r) for r in records]; jsonl(out/'literal-input.jsonl',projections)
    audit=json.loads((run_dir/'audit.json').read_text())
    inv=check_inventory(records,Path(args.dataset)/'files',manifest)
    tables=native_table_checks(records,Path(args.dataset)/'files',json.loads(Path(args.pdf_reference).read_text()))
    dump(out/'table-checks.json',tables)
    legacy_path=BASE/'rag-evaluator/evaluate.py'
    spec=importlib.util.spec_from_file_location('legacy_evaluator',legacy_path)
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    # Use the existing evaluator's reader to preserve the same official dataset contract.
    docs,strings,queries=legacy.load_gold(Path(args.dataset))
    projected={r['doc_id']:compact('\n'.join(b['text'] for b in r['blocks'])) for r in projections}
    string_rows=[]
    for item in strings:
        string_rows.append({**item,'included':compact(item['text']) in projected[item['doc_id']]})
    groups={}
    for kind in ('docx','pptx','xlsx','pdf','txt','log'):
        selected=[s for s in string_rows if next(r for r in records if r['doc_id']==s['doc_id'])['source']['format']==kind]
        groups[kind]={'correct':sum(s['included'] for s in selected),'total':len(selected)}
    scan_ids={k for k,v in docs.items() if v.get('스캔')=='Y'}
    units=[(r['doc_id'],u) for r in records for u in r['coverage']['units']]
    pending=[{'doc_id':identity,**u} for identity,u in units if u['required'] and u['status']!='completed']
    native_units=[u for _,u in units if u['unit_id'].startswith('native:')]
    scan_strings=[s for s in string_rows if s['doc_id'] in scan_ids]
    native_strings=[s for s in string_rows if s['doc_id'] not in scan_ids]
    replacements=[r['doc_id'] for r in records if '\ufffd' in projected[r['doc_id']]]
    summary={'scope':'native_only_actual_source_run','overall_status':'incomplete' if pending else 'not_fully_evaluated',
      'model_called':False,'schema_valid_documents':len(records),'input_documents':len(records),
      'source_hash_matches':sum(x['source_hash_matches'] for x in inv),
      'native_inventory_matches':sum(x['native_inventory_matches'] for x in inv),
      'native_units_completed':sum(u['status']=='completed' for u in native_units),'native_units_total':len(native_units),
      'documents_with_native_text':sum(bool(projected[r['doc_id']]) for r in records),
      'empty_native_documents':[r['doc_id'] for r in records if not projected[r['doc_id']]],
      'strings':{'correct':sum(s['included'] for s in string_rows),'total':len(string_rows),'by_format':groups,
                 'non_scan':{'correct':sum(s['included'] for s in native_strings),'total':len(native_strings)},
                 'scan':{'correct':sum(s['included'] for s in scan_strings),'total':len(scan_strings)}},
      'native_table_cells':{'correct':tables['correct'],'total':tables['total'],'regions':tables['regions'],
                            'extra_nonblank_cells':tables['extra_nonblank_cells']},
      'pending_visual_units':len(pending),'documents_with_pending_visual_units':len({u['doc_id'] for u in pending}),
      'replacement_character_documents':replacements,
      'native_parse_errors':[a for a in audit if a['errors']],
      'not_evaluated':['vision scan text/tables','diagram nodes and edges','semantic claims and evidence',
                       'human-validated header/region segmentation and reading order','photos','retrieval'],
      'note':'A valid JSON and completed native extraction do not mean visual interpretation or whole-pipeline quality passed.'}
    report={'summary':summary,'schema_checks':schema_checks,'source_inventory_checks':inv,'string_results':string_rows,
            'pending_units':pending,'evidence_hashes':{str(p):digest(p) for p in [Path(__file__),run_dir/'parsed.jsonl',Path(args.pdf_reference)]}}
    dump(out/'report.json',report)
    info={'run_id':'PARSE-003-NATIVE','run_kind':'evaluation','environment':'local native parsers; visual units explicitly pending',
          'llm_model':'N/A','quantization':'N/A','provider':'N/A; OpenRouter planned, not called','embedding_model':'N/A',
          'prompt_version':'N/A','pipeline_version':'parser-2.0.0; common-block-1.0.0','measured_at':'2026-10-16'}
    dump(out/'run-info.json',info)
    # Only measured encoding data is passed. Do not imply that a native table sample is global vision quality.
    dump(out/'manual-metrics.json',{'encoding_error_documents':{'value':len(replacements),
         'evidence':'evaluation/report.json; strict UTF-8/CP949 decoding and replacement-character scan'}})
    cmd=[sys.executable,str(legacy_path),'--dataset',str(args.dataset),'--run-info',str(out/'run-info.json'),
         '--parsed',str(out/'literal-input.jsonl'),'--manual-metrics',str(out/'manual-metrics.json'),'--output',str(out/'legacy')]
    process=subprocess.run(cmd,capture_output=True,text=True)
    (out/'legacy-evaluator.log').write_text(process.stdout+process.stderr)
    if process.returncode: raise RuntimeError('Legacy evaluator failed; see legacy-evaluator.log')
    dump(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',required=True);p.add_argument('--dataset',required=True)
    p.add_argument('--pdf-reference',required=True);run(p.parse_args())
