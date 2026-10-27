"""Rebase frozen common blocks onto audited v2 bytes; patch only changed literals."""
import re,shutil
from common import *
def replace_refs(value,mapping):
 if isinstance(value,str):return mapping.get(value,value)
 if isinstance(value,list):return [replace_refs(x,mapping) for x in value]
 if isinstance(value,dict):return {k:replace_refs(v,mapping) for k,v in value.items()}
 return value
def main():
 assert not (OUT/'reused-records.jsonl').exists()
 original={r['doc_id']:r for r in rows(BASE/'indexing-records.jsonl')};results=[];ledger=[];idmap={}
 for audit in read(AUDIT/'document-comparison.json'):
  did=audit['doc_id'];r=copy.deepcopy(original[did]);path=Path(audit['new_path'])
  assert sha(path)==audit['new_sha256'];assert r['source']['sha256']==audit['old_sha256']
  old=audit['old_sha256'][:12];new=audit['new_sha256'][:12]
  mapping={v:v.replace(old,new) for v in [b['block_id'] for b in r['blocks']]+[a['asset_id'] for a in r['assets']]}
  r=replace_refs(r,mapping);r['schema_version']='1.1.0';r['source']['sha256']=audit['new_sha256'];idmap[did]=mapping
  changed=audit['classification']=='content_changed';patches=[]
  for a in r['assets']:
   # Re-render changed PDF pages. Equal pages can retain exact prior image bytes.
   olda=next(v for v in original[did]['assets'] if mapping[v['asset_id']]==a['asset_id'])
   dest=OUT/'reused-assets'/did/Path(a['path']).name;dest.parent.mkdir(parents=True,exist_ok=True)
   if changed and a['loc'].get('page')==1:
    pdf=P.pypdfium2.PdfDocument(path);page=pdf[0];bmp=page.render(scale=olda['width']/page.get_width());im=bmp.to_pil().convert('RGB');im.save(dest)
    a.update(width=im.width,height=im.height,sha256=sha(dest));bmp.close();page.close();pdf.close()
   else:
    candidates=[ROOT/'outputs/parsing-run-003'/olda['path'],ROOT/'outputs/additional-parsing-run-001'/olda['path']]
    src=next((p for p in candidates if p.exists() and sha(p)==olda['sha256']),None)
    if src is None:
     src=next((p for p in (ROOT/'outputs').glob('*/'+olda['path']) if p.is_file() and sha(p)==olda['sha256']),None)
    assert src,(did,olda['path']);shutil.copyfile(src,dest)
   a['path']=str(dest.relative_to(OUT))
  if changed:
   candidates=[b for b in r['blocks'] if re.match(r'^계약번호\s*:',b['text'])]
   assert len(candidates)==1,(did,len(candidates));block=candidates[0];before=block['text']
   if r['source']['format']=='docx':
    from docx import Document
    after=next(p.text for p in Document(path).paragraphs if re.match(r'^계약번호\s*:',p.text))
   elif did not in ['D-044','D-102']:
    with P.pdfplumber.open(path) as pdf:
     line=next(x for x in pdf.pages[0].extract_text_lines() if '계약번호:' in x['text']);after=line['text']
     a=next(x for x in r['assets'] if x['loc'].get('page')==1)
     block['loc']['bbox']=P.bbox(a,[line['x0'],line['top'],line['x1'],line['bottom']],pdf.pages[0].width,pdf.pages[0].height)
   else:
    # Explicit prior image audit verified the added word on both scanned originals.
    after=before+'   |   계약구분: 구매'
    block['loc']['bbox'].update(x0=.50,y0=.12,x1=.88,y1=.15,precision='approximate')
   assert re.search(r'계약구분:\s*(용역|유지보수|구매|라이선스)',after),did
   block['text']=after;block['evidence']=[{'evidence_id':'v2_literal','kind':'literal','loc':copy.deepcopy(block['loc']),'quote':after}]
   # A separate derivation run makes the changed literal distinct from reused vision.
   run='v2-source-delta';r['runs'].append({'run_id':run,'method':'native_parser' if did not in ['D-044','D-102'] else 'reviewed_correction','implementation':'audited-source-delta-1.0','model_id':None,'provider':None,'quantization':None,'prompt_version':None,'input_asset_ids':[]})
   block['run_ref']=run;patches.append({'block_id':block['block_id'],'before':before,'after':after,'basis':'source-native-read' if did not in ['D-044','D-102'] else 'assistant visual audit of v2 first page'})
  assert not check(r),(did,check(r))
  results.append(r);ledger.append({'doc_id':did,'old_sha256':audit['old_sha256'],'new_sha256':audit['new_sha256'],'classification':audit['classification'],'new_model_calls':0,'patches':patches})
 lines(OUT/'reused-records.jsonl',results);write(OUT/'reuse-ledger.json',ledger);write(OUT/'source-id-map.json',idmap)
 print('Rebased',len(results),'documents; patched',sum(bool(x['patches']) for x in ledger))
if __name__=='__main__':main()
