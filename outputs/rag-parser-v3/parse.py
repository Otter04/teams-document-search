#!/usr/bin/env python3
"""Native source parsing into common blocks 1.0.0; visual work stays pending.

Reads source bytes and an ID/path-only manifest, never gold or previous outputs.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unicodedata
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries
import pdfplumber
import pypdfium2
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

import native

VERSION = 'parser-2.0.0'
DESIGN = Path(__file__).resolve().parent.parent/'common-block-design'
spec=importlib.util.spec_from_file_location('common_validation',DESIGN/'validate_design.py')
validation=importlib.util.module_from_spec(spec); spec.loader.exec_module(validation)

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,obj): Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jsonl(path,rows): Path(path).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
def source_map(root): return {unicodedata.normalize('NFC',str(p.relative_to(root))):p for p in root.rglob('*') if p.is_file()}


class Builder:
    def __init__(self,path,item,out,args):
        self.path,self.out,self.args=path,out,args
        self.doc={'schema_version':'1.0.0','record_kind':'run_result','doc_id':item['doc_id'],
          'source':{'file_name':unicodedata.normalize('NFC',path.name),'format':path.suffix[1:].lower(),
                    'relative_path':item['relative_path'],'sha256':digest(path),'web_url':None,'encoding':None},
          'coverage':{'scope':'full_document','unit_inventory_complete':True,'units':[]},
          'runs':[{'run_id':'native','method':'native_parser','implementation':VERSION,'model_id':None,
                   'provider':None,'quantization':None,'prompt_version':None,'input_asset_ids':[]}],
          'assets':[],'blocks':[],'warnings':[]}
        self.prefix=item['doc_id']+'-'+self.doc['source']['sha256'][:12]
        self.queue=[]; self.audit={'doc_id':item['doc_id'],'source_details':{},'errors':[]}

    def unit(self,key,loc,status='completed',reason=None):
        u={'unit_id':key,'loc':loc,'required':True,'status':status,'reason':reason,'block_ids':[]}
        self.doc['coverage']['units'].append(u); return u

    def add(self,key,typ,text,loc,parent=None,heading=(),unit=None):
        b={'block_id':self.prefix+'-'+key,'parent_id':parent,'order':len(self.doc['blocks'])+1,
           'type':typ,'text':text,'loc':loc,'heading_path':list(heading),'run_ref':'native',
           'evidence':[],'claims':[],'context_ids':[],'content_refs':[],'warnings':[]}
        if text:
            b['evidence']=[{'evidence_id':'source','kind':'literal','loc':loc,'quote':text}]
        self.doc['blocks'].append(b)
        if unit is not None: unit['block_ids'].append(b['block_id'])
        return b

    def table(self,key,cells,rows,cols,loc,parent=None,header_rows=(),header_status='unknown',unit=None):
        t=self.add(key,'table','',loc,parent,unit=unit)
        t['table']={'row_count':rows,'column_count':cols,'header_rows':list(header_rows),
                    'header_status':header_status,'continued_from':None}
        byrow=defaultdict(list)
        for c in cells: byrow[c['row']].append(c)
        for rn,values in sorted(byrow.items()):
            values.sort(key=lambda c:c['column'])
            rloc=values[0]['loc'].copy(); rloc.pop('bbox',None)
            if rloc['kind']=='xlsx':
                start=values[0]['loc']['cell_range'].split(':')[0]
                end=values[-1]['loc']['cell_range'].split(':')[-1]
                rloc['cell_range']=start+':'+end
            r=self.add(key+'-r'+str(rn),'table_row','\t'.join(c['text'] for c in values),rloc,t['block_id'],unit=unit)
            r['cells']=values
        return t

    def asset(self,key,image,loc,kind='page_image'):
        path=self.out/'assets'/self.doc['doc_id']/(key+'.png'); path.parent.mkdir(parents=True,exist_ok=True)
        image.save(path)
        a={'asset_id':self.prefix+'-'+key,'path':str(path.relative_to(self.out)),
           'kind':kind,'loc':loc,'width':image.width,'height':image.height,'sha256':digest(path)}
        self.doc['assets'].append(a); return a

    def pending(self,key,loc,reason,asset=None,context_ids=()):
        u=self.unit('vision:'+key,loc,'pending',reason)
        self.queue.append({'doc_id':self.doc['doc_id'],'unit_id':u['unit_id'],'source_sha256':self.doc['source']['sha256'],
            'loc':loc,'asset_id':asset['asset_id'] if asset else None,'asset_path':asset['path'] if asset else None,
            'context_block_ids':list(context_ids),'reason':reason,'status':'pending_model_selection',
            'planned_service':'OpenRouter','model':None})
        return u


def cell(row,col,text,loc,row_span=1,column_span=1,value=None,formula=None,number_format=None,status=None,role='unknown'):
    return {'row':row,'column':col,'row_span':row_span,'column_span':column_span,'text':text,
            'value':native.serial(value),'value_status':status or ('known' if text else 'blank'),
            'formula':formula,'number_format':number_format,'role':role,'loc':loc}

def bbox(asset,coords,width,height):
    x0,y0,x1,y1=coords
    values=[min(1,max(0,v)) for v in [x0/width,y0/height,x1/width,y1/height]]
    if values[0]>=values[2] or values[1]>=values[3]: raise ValueError('degenerate source geometry')
    return {'frame_asset_id':asset['asset_id'],**dict(zip(('x0','y0','x1','y1'),values)),'precision':'exact'}

def usable_pdf_table(table):
    # Some slide-to-PDF background borders produce sub-point ghost cells.
    # Reject that layout candidate; its text remains in the normal text stream.
    cells={tuple(c) for row in table.rows for c in row.cells if c}
    return len(cells)>=2 and all(c[2]-c[0]>=2 and c[3]-c[1]>=2 for c in cells)

def render_copy_with_font(source,target,family):
    """Substitute fonts in an isolated render copy only; never touch source bytes."""
    with ZipFile(source) as src,ZipFile(target,'w',ZIP_DEFLATED) as out:
        for item in src.infolist():
            data=src.read(item.filename)
            if item.filename.endswith('.xml'):
                root=etree.fromstring(data)
                for node in root.xpath('//*[@typeface]'): node.set('typeface',family)
                for props in root.xpath('//*[local-name()="rPr" or local-name()="defRPr" or local-name()="endParaRPr"]'):
                    for name in ('latin','ea','cs'):
                        tag='{http://schemas.openxmlformats.org/drawingml/2006/main}'+name
                        font=props.find(tag)
                        if font is None: font=etree.SubElement(props,tag)
                        font.set('typeface',family)
                data=etree.tostring(root)
            out.writestr(item,data)

def visible_slide_text(slide):
    parts=[]
    for shape,_ in native.walk_shapes(slide.shapes):
        if shape.has_text_frame: parts.append(shape.text)
        if shape.has_table:
            parts.extend(c.text for row in shape.table.rows for c in row.cells if not c.is_spanned)
    return '\n'.join(parts)

def hangul_counts(text): return Counter(c for c in text if '\uac00'<=c<='\ud7a3')

def render_pdf(path,out_builder,kind='pdf'):
    rendered=pypdfium2.PdfDocument(path); assets=[]
    try:
        for i in range(len(rendered)):
            page=rendered[i]; bitmap=page.render(scale=out_builder.args.render_dpi/72)
            try:
                image=bitmap.to_pil().convert('RGB')
                loc={'kind':kind,('page' if kind=='pdf' else 'slide'):i+1}
                assets.append(out_builder.asset(('page-' if kind=='pdf' else 'slide-')+str(i+1),image,loc,
                                                'page_image' if kind=='pdf' else 'slide_image'))
            finally: bitmap.close(); page.close()
    finally: rendered.close()
    return assets

def parse_docx(b):
    u=b.unit('native:document',{'kind':'docx','paragraph_index':1})
    blocks,warnings,details=native.parse_docx(b.path,b.args)
    b.audit['source_details']=details
    b.doc['warnings'] += [json.dumps(w,ensure_ascii=False) for w in warnings]
    table_groups=defaultdict(list)
    for old in blocks:
        if old['type']=='table_row': table_groups[old['loc']['table']].append(old)
    done=set(); heading_ids=[]
    for old in blocks:
        if old['type']!='table_row':
            loc={'kind':'docx','paragraph_index':old['loc']['paragraph']}
            new=b.add('p'+str(old['loc']['paragraph']),old['type'],old['text'],loc,heading=old['heading_path'],unit=u)
            if old['type']=='heading': heading_ids=[new['block_id']]
            else: new['context_ids']=heading_ids.copy()
            continue
        tn=old['loc']['table']
        if tn in done: continue
        done.add(tn); rows=table_groups[tn]; grouped=defaultdict(list)
        for row in rows:
            for c in row['cells']: grouped[c['anchor_row'],c['anchor_column']].append(c)
        cells=[]
        for (r,c),values in grouped.items():
            rs=max(v['row'] for v in values)-r+1; cs=max(v['column'] for v in values)-c+1
            loc={'kind':'docx','table_index':tn,'row_index':r,'cell_index':c}
            cells.append(cell(r,c,values[0]['text'],loc,rs,cs))
        marked=[r['loc']['row'] for r in rows if r.get('header_method')=='marked']
        t=b.table('table'+str(tn),cells,max(c['row']+c['row_span']-1 for c in cells),
                  max(c['column']+c['column_span']-1 for c in cells),{'kind':'docx','table_index':tn},
                  header_rows=marked,header_status='explicit' if marked else 'unknown',unit=u)
        t['context_ids']=heading_ids.copy()
    for i,identifier in enumerate(details['header_footer_identifiers'],1):
        b.add('header-id'+str(i),'paragraph',identifier['text'],{'kind':'docx','media_part':identifier['loc']['part']},unit=u)
    with ZipFile(b.path) as z:
        for name in z.namelist():
            if name.startswith('word/media/') and not name.endswith('/'):
                import io
                loc={'kind':'docx','media_part':name}
                try: a=b.asset('media-'+Path(name).stem,Image.open(io.BytesIO(z.read(name))).convert('RGB'),loc,'embedded_image')
                except Exception as exc:
                    a=None; b.doc['warnings'].append(f'image rendering failed: {name}: {type(exc).__name__}')
                b.pending('media-'+Path(name).stem,loc,'embedded document image requires visual interpretation',a)
        xml=z.read('word/document.xml')
        if b'<w:tbl' in xml and warnings:
            b.doc['warnings'].append('Nested or irregular table structures require review; see source details.')

def parse_text(b):
    blocks,warnings,details=native.parse_text(b.path,b.args)
    b.doc['source']['encoding']=details['encoding']; b.audit['source_details']=details
    kind=b.doc['source']['format']
    u=b.unit('native:lines',{'kind':kind,'line_start':1,'line_end':max(1,details['source_lines'])})
    for old in blocks:
        new=b.add('line'+str(old['loc']['line_start']),old['type'],old['text'],{'kind':kind,**old['loc']},unit=u)
        if kind=='log': new['log']={'timestamp_raw':old['timestamp'],'timezone':None,'level':old['level'],'error_codes':old['error_codes']}
    b.doc['warnings'] += [json.dumps(w,ensure_ascii=False) for w in warnings]

def parse_xlsx(b):
    wb=openpyxl.load_workbook(b.path,data_only=False); cache=openpyxl.load_workbook(b.path,data_only=True)
    b.audit['source_details']={'sheets':[],'hidden_sheet_policy':'include','formula_policy':'saved_cache_only'}
    try:
        for si,sheet in enumerate(wb,1):
            if sheet.max_row*sheet.max_column>2_000_000: raise ValueError('worksheet exceeds cell guard')
            bounds=[c for row in sheet for c in row if c.value is not None]
            rmax=max([c.row for c in bounds]+[m.max_row for m in sheet.merged_cells.ranges]+[1])
            cmax=max([c.column for c in bounds]+[m.max_col for m in sheet.merged_cells.ranges]+[1])
            if rmax*cmax>2_000_000: raise ValueError('worksheet exceeds cell guard')
            loc={'kind':'xlsx','sheet':sheet.title,'cell_range':f'A1:{get_column_letter(cmax)}{rmax}'}
            u=b.unit('native:sheet'+str(si),loc); merged={}; anchors={}
            for m in sheet.merged_cells.ranges:
                anchors[m.min_row,m.min_col]=m
                for r in range(m.min_row,m.max_row+1):
                    for c in range(m.min_col,m.max_col+1): merged[r,c]=(m.min_row,m.min_col)
            headers={range_boundaries(t.ref)[1] for t in sheet.tables.values() if t.headerRowCount}
            header_status='explicit' if headers else 'unknown'
            if not headers:
                headers={r for r in range(1,rmax+1) if len([c for c in sheet[r] if c.value is not None])>=3
                         and all(isinstance(c.value,str) and c.data_type!='f' for c in sheet[r] if c.value is not None)}
                if headers: header_status='inferred'
            cells=[]
            for r in range(1,rmax+1):
                for c in range(1,cmax+1):
                    if (r,c) in merged and merged[r,c]!=(r,c): continue
                    original=sheet.cell(r,c); formula=original.value if original.data_type=='f' else None
                    value=cache[sheet.title].cell(r,c).value if formula else original.value
                    area=anchors.get((r,c)); address=str(area) if area else original.coordinate
                    cloc={'kind':'xlsx','sheet':sheet.title,'cell_range':address}
                    cells.append(cell(r,c,native.text_value(value),cloc,
                        area.max_row-area.min_row+1 if area else 1,area.max_col-area.min_col+1 if area else 1,
                        value,formula,original.number_format,'missing_cache' if formula and value is None else None,
                        'header' if r in headers else 'unknown'))
                    if formula and value is None: b.doc['warnings'].append(f'missing formula cache: {sheet.title}!{original.coordinate}')
            if bounds:
                t=b.table('sheet'+str(si),cells,rmax,cmax,loc,header_rows=sorted(headers),header_status=header_status,unit=u)
                t['heading_path']=[sheet.title]
                if header_status=='inferred': t['warnings'].append('header candidate: >=3 populated text cells; not semantic validation')
            b.audit['source_details']['sheets'].append({'name':sheet.title,'state':sheet.sheet_state,'rows':rmax,'columns':cmax,
                'hidden_rows':[r for r,d in sheet.row_dimensions.items() if d.hidden],
                'hidden_columns':[c for c,d in sheet.column_dimensions.items() if d.hidden]})
            if sheet._images or sheet._charts:
                b.pending('sheet-visual'+str(si),loc,'worksheet image/chart needs rendering; renderer not implemented')
    finally: wb.close(); cache.close()

def parse_pptx(b):
    deck=Presentation(b.path); assets=[]; render_error=None; render_checks=[]
    # Isolated profile and copied source avoid side effects in the dataset or user's Office session.
    if b.args.soffice:
        try:
            with tempfile.TemporaryDirectory(prefix='rag-slides-',dir=b.args.work_dir) as td:
                td=Path(td).resolve(); target=td/(b.doc['doc_id']+'.pptx')
                env=os.environ.copy(); font_path=getattr(b.args,'render_font',None)
                if font_path:
                    font_dir=td/'fonts';font_dir.mkdir();shutil.copyfile(font_path,font_dir/Path(font_path).name)
                    family=b.args.render_font_family
                    render_copy_with_font(b.path,target,family)
                    config=etree.Element('fontconfig'); etree.SubElement(config,'dir').text=str(font_dir)
                    etree.SubElement(config,'cachedir').text=str(td/'font-cache')
                    config_path=td/'fonts.conf'; config_path.write_bytes(etree.tostring(config))
                    env.update(SAL_FONTPATH=str(font_dir),FONTCONFIG_FILE=str(config_path),XDG_CACHE_HOME=str(td/'font-cache'))
                else: shutil.copyfile(b.path,target)
                profile=td/'profile'
                p=subprocess.run([b.args.soffice,'-env:UserInstallation='+profile.as_uri(),'--headless','--convert-to','pdf',
                                  '--outdir',str(td),str(target)],env=env,capture_output=True,text=True,timeout=120)
                pdf=target.with_suffix('.pdf')
                if p.returncode or not pdf.exists(): raise RuntimeError('slide PDF rendering did not produce output')
                with pdfplumber.open(pdf) as rendered:
                    if len(rendered.pages)!=len(deck.slides): raise RuntimeError('rendered slide count mismatch')
                    for sn,(slide,page) in enumerate(zip(deck.slides,rendered.pages),1):
                        expected=hangul_counts(visible_slide_text(slide)); actual=hangul_counts(page.extract_text() or '')
                        missing=expected-actual
                        render_checks.append({'slide':sn,'source_hangul_chars':sum(expected.values()),'missing_hangul_chars':sum(missing.values())})
                if any(x['missing_hangul_chars'] for x in render_checks):
                    raise RuntimeError('Korean text missing/mis-mapped in render; do not use as vision input')
                assets=render_pdf(pdf,b,'pptx')
                if len(assets)!=len(deck.slides): raise RuntimeError('rendered slide count mismatch')
        except Exception as exc: render_error=type(exc).__name__+': '+str(exc)
    else: render_error='no slide renderer configured'
    if render_error: b.doc['warnings'].append(render_error)
    b.audit['source_details']={'slides':len(deck.slides),'rendering_error':render_error,'render_text_checks':render_checks,
        'render_font_substitution':getattr(b.args,'render_font_family',None) if getattr(b.args,'render_font',None) else None,
        'visual_routing':'all slides reviewed conservatively'}
    for sn,slide in enumerate(deck.slides,1):
        loc={'kind':'pptx','slide':sn}; u=b.unit('native:slide'+str(sn),loc)
        container=b.add('s'+str(sn),'slide','',loc,unit=u)
        text_shapes=[s for s,_ in native.walk_shapes(slide.shapes) if s.has_text_frame and s.text.strip()]
        title_shape=slide.shapes.title or (min(text_shapes,key=lambda s:(s.top,s.left)) if text_shapes else None)
        title_id=None
        for shape,parents in native.walk_shapes(slide.shapes):
            key=f's{sn}-shape{shape.shape_id}'; sloc={**loc,'shape_ids':[shape.shape_id]}
            if sn<=len(assets) and not parents:
                coords=native.bbox_shape(shape)
                if coords[2]>coords[0] and coords[3]>coords[1]: sloc['bbox']=bbox(assets[sn-1],coords,deck.slide_width,deck.slide_height)
            if shape.has_text_frame and shape.text.strip():
                typ='heading' if title_shape is not None and title_shape.shape_id==shape.shape_id else 'paragraph'
                new=b.add(key,typ,shape.text.strip(),sloc,container['block_id'],unit=u)
                if typ=='heading':
                    title_id=new['block_id']
                    if slide.shapes.title is None: new['warnings'].append('title candidate from topmost text shape')
            if shape.has_table:
                cells=[]
                for rn,row in enumerate(shape.table.rows,1):
                    for cn,c in enumerate(row.cells,1):
                        if c.is_spanned: continue
                        cells.append(cell(rn,cn,c.text,sloc,c.span_height if c.is_merge_origin else 1,c.span_width if c.is_merge_origin else 1))
                b.table(key+'-table',cells,len(shape.table.rows),len(shape.table.columns),sloc,container['block_id'],unit=u)
        if slide.has_notes_slide:
            notes=slide.notes_slide.notes_text_frame
            if notes and notes.text.strip():
                note=b.add(f's{sn}-notes','paragraph',notes.text,loc,container['block_id'],unit=u)
                note['warnings'].append('speaker_notes; slide number is source locator, not a visible page region')
        if title_id:
            for new in b.doc['blocks']:
                if new['block_id'] in u['block_ids']:
                    new['heading_path']=[title_shape.text.strip()]
                    if new['type'] not in ('slide','heading'): new['context_ids']=[title_id]
        b.pending('slide'+str(sn),loc,'slide visual layout/relationships require review (including native shapes)',
                  assets[sn-1] if sn<=len(assets) else None,u['block_ids'])

def parse_pdf(b):
    assets=render_pdf(b.path,b); b.audit['source_details']={'pages':[]}
    with pdfplumber.open(b.path) as pdf:
        for pn,page in enumerate(pdf.pages,1):
            loc={'kind':'pdf','page':pn}; u=b.unit('native:page'+str(pn),loc)
            text=page.extract_text(x_tolerance=2,y_tolerance=3) or ''
            low_text=len(''.join(text.split()))<b.args.min_pdf_chars
            candidates=page.find_tables() if not low_text else []
            tables=[t for t in candidates if usable_pdf_table(t)]
            table_boxes=[t.bbox for t in tables]; events=[]
            for ti,t in enumerate(tables,1): events.append((t.bbox[1],t.bbox[0],'table',ti,t))
            outside=page.filter(lambda o:o.get('object_type')!='char' or not any(native.in_box(o,box) for box in table_boxes))
            for li,line in enumerate(outside.extract_text_lines(x_tolerance=2,y_tolerance=3),1):
                events.append((line['top'],line['x0'],'line',li,line))
            for _,_,typ,index,value in sorted(events,key=lambda x:(x[0],x[1])):
                if typ=='line':
                    coords=[value['x0'],value['top'],value['x1'],value['bottom']]
                    bl=b.add(f'p{pn}-line{index}','heading' if native.CLAUSE.fullmatch(value['text'].strip()) else 'paragraph',value['text'],
                             {**loc,'bbox':bbox(assets[pn-1],coords,page.width,page.height)},unit=u)
                else:
                    t=value; extracted=t.extract(); xs=sorted({v for row in t.rows for c in row.cells if c for v in (c[0],c[2])})
                    ys=sorted({v for row in t.rows for c in row.cells if c for v in (c[1],c[3])})
                    cells=[]; occupied=set()
                    for row,geometry in zip(extracted,t.rows):
                        for content,rect in zip(row,geometry.cells):
                            if rect is None: continue
                            c=xs.index(rect[0])+1;r=ys.index(rect[1])+1
                            cs=xs.index(rect[2])-c+1;rs=ys.index(rect[3])-r+1
                            cloc={**loc,'bbox':bbox(assets[pn-1],rect,page.width,page.height)}
                            cells.append(cell(r,c,content or '',cloc,rs,cs))
                            occupied.update((rr,cc) for rr in range(r,r+rs) for cc in range(c,c+cs))
                    # A geometric hole is explicitly unreadable, never silently dropped.
                    for r in range(1,len(ys)):
                        for c in range(1,len(xs)):
                            if (r,c) not in occupied:
                                cells.append(cell(r,c,'',{**loc,'bbox':bbox(assets[pn-1],[xs[c-1],ys[r-1],xs[c],ys[r]],page.width,page.height)},status='unreadable'))
                    table=b.table(f'p{pn}-table{index}',cells,len(ys)-1,len(xs)-1,
                                  {**loc,'bbox':bbox(assets[pn-1],t.bbox,page.width,page.height)},unit=u)
                    if any(c['value_status']=='unreadable' for c in cells):
                        table['warnings'].append('unresolved grid gaps require visual review')
            graphics=[o for o in page.lines+page.rects+page.curves if not any(native.in_box(o,box) for box in table_boxes)]
            reason=None
            if low_text and (page.images or page.chars or graphics): reason='page has insufficient native text; vision extraction required'
            elif page.images: reason='native text page includes image content'
            elif len(graphics)>=3: reason='non-table vector graphics need visual review'
            if reason: b.pending('page'+str(pn),loc,reason,assets[pn-1],u['block_ids'])
            b.audit['source_details']['pages'].append({'page':pn,'native_nonspace_chars':len(''.join(text.split())),
                'tables':len(tables),'rejected_degenerate_table_candidates':len(candidates)-len(tables),
                'images':len(page.images),'non_table_graphic_objects':len(graphics),'vision_reason':reason})


PARSERS={'docx':parse_docx,'pptx':parse_pptx,'xlsx':parse_xlsx,'pdf':parse_pdf,'txt':parse_text,'log':parse_text}

def run(args):
    root=Path(args.files_root).resolve(); out=Path(args.output).resolve()
    if out.exists() or out==root or root in out.parents: raise ValueError('Use a new output directory outside source files')
    entries=[json.loads(l) for l in Path(args.manifest).read_text().splitlines() if l.strip()]
    if not entries or len({e['doc_id'] for e in entries})!=len(entries): raise ValueError('empty/duplicate manifest IDs')
    mapping=source_map(root)
    resolved=[]
    for entry in entries:
        if set(entry)!={'doc_id','relative_path'}: raise ValueError('Only ID and relative_path allowed in parser manifest')
        path=mapping[unicodedata.normalize('NFC',entry['relative_path'])]
        if root not in path.resolve().parents: raise ValueError('source path escapes root')
        resolved.append((entry,path))
    out.mkdir(parents=True); Path(args.work_dir).mkdir(parents=True,exist_ok=True)
    records=[]; audit=[]; queue=[]; inventory=[]; start=time.perf_counter()
    for item,path in resolved:
        b=Builder(path,item,out,args); t=time.perf_counter()
        try: PARSERS[path.suffix[1:].lower()](b)
        except Exception as exc:
            b.audit['errors'].append(type(exc).__name__+': '+str(exc))
            b.doc['warnings'].append(b.audit['errors'][-1])
            b.doc['coverage']['unit_inventory_complete']=False
            for u in b.doc['coverage']['units']:
                if u['status']=='completed': u.update(status='failed',reason='document extraction interrupted')
        errors=validation.check(b.doc); b.audit['schema_errors']=errors
        b.audit['elapsed_seconds']=round(time.perf_counter()-t,4)
        b.audit['native_status']='failed' if b.audit['errors'] or errors else 'completed'
        b.audit['full_status']='incomplete' if b.queue or b.doc['warnings'] or b.audit['native_status']=='failed' else 'completed'
        records.append(b.doc); audit.append(b.audit); queue.extend(b.queue)
        inventory.append({'doc_id':item['doc_id'],'source_sha256':b.doc['source']['sha256'],
                          'units':[{'unit_id':u['unit_id'],'loc':u['loc'],'required':u['required']} for u in b.doc['coverage']['units']]})
        print(f"{item['doc_id']} native={b.audit['native_status']} blocks={len(b.doc['blocks'])} vision_pending={len(b.queue)}",flush=True)
    jsonl(out/'parsed.jsonl',records); jsonl(out/'vision-pending.jsonl',queue)
    jsonl(out/'source-inventory.jsonl',inventory); dump(out/'audit.json',audit)
    shutil.copyfile(args.manifest,out/'manifest.jsonl')
    dump(out/'provenance.json',{'parser_version':VERSION,'schema_version':'1.0.0','mode':'native_only',
        'model_called':False,'planned_vision_service':'OpenRouter','render_dpi':args.render_dpi,
        'render_font':{'family':args.render_font_family,'file_sha256':digest(args.render_font)} if args.render_font else None,
        'started_with_source_bytes':True,'gold_or_old_parsed_inputs':False,
        'measured_at_utc':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':round(time.perf_counter()-start,3),
        'documents':len(records),'blocks':sum(len(r['blocks']) for r in records),'pending_vision_units':len(queue),
        'code_hashes':{p.name:digest(p) for p in Path(__file__).parent.glob('*.py')},
        'schema_sha256':digest(DESIGN/'common-block.schema.json'),'manifest_sha256':digest(args.manifest),
        'native_status_counts':dict(Counter(a['native_status'] for a in audit)),
        'full_status_counts':dict(Counter(a['full_status'] for a in audit))})
    return 1 if any(a['native_status']=='failed' for a in audit) else 0

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--files-root',required=True);p.add_argument('--manifest',required=True);p.add_argument('--output',required=True)
    p.add_argument('--work-dir',required=True);p.add_argument('--soffice');p.add_argument('--render-dpi',type=int,default=144)
    p.add_argument('--render-font',help='Local font file for an isolated slide render copy')
    p.add_argument('--render-font-family',default='Arial Unicode MS')
    p.add_argument('--min-pdf-chars',type=int,default=20)
    a=p.parse_args()
    if not 72<=a.render_dpi<=300: p.error('render DPI must be 72..300')
    raise SystemExit(run(a))

if __name__=='__main__': main()
