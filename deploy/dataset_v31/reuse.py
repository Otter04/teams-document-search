"""Rebase frozen common blocks onto audited v2 bytes; patch only changed literals."""
import re,shutil
from common import *
def replace_refs(value,mapping):
 if isinstance(value,str):return mapping.get(value,value)
 if isinstance(value,list):return [replace_refs(x,mapping) for x in value]
 if isinstance(value,dict):return {k:replace_refs(v,mapping) for k,v in value.items()}
 return value
from types import SimpleNamespace
from collections import Counter
from pptx import Presentation
from PIL import Image
import subprocess,io

def asset_source(a):
 candidates=[ROOT/'outputs/indexing-v2-001'/a['path'],BASE/a['path']]
 candidates+=list((ROOT/'outputs').glob('*/'+a['path']))
 return next(p for p in candidates if p.is_file() and sha(p)==a['sha256'])
def remove_bbox(x):
 if isinstance(x,dict):
  x.pop('bbox',None)
  for v in x.values():remove_bbox(v)
 elif isinstance(x,list):
  for v in x:remove_bbox(v)
def main():
 originals={r['doc_id']:r for r in rows(BASE/'indexing-records.jsonl')};inventory=read(AUDIT/'inventory.json');paths=read(OUT/'source-paths.json');results=[];ledger=[];idmaps={}
 for x in inventory:
  did=x['doc_id']
  if did not in originals:continue
  r=copy.deepcopy(originals[did]);p=Path(paths[did]);oldpath=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2/files')/x['path'];changed=sha(p)!=r['source']['sha256']
  assert sha(oldpath)==r['source']['sha256']
  oldh=r['source']['sha256'][:12];newh=sha(p)[:12]
  mapping={v:v.replace(oldh,newh) for v in [b['block_id'] for b in r['blocks']]+[a['asset_id'] for a in r['assets']]};idmaps[did]=mapping;r=replace_refs(r,mapping);r['schema_version']='1.2.0';r['source']['sha256']=sha(p)
  evidence={'doc_id':did,'source_changed':changed,'previous_sha256':sha(oldpath),'current_sha256':sha(p),'new_model_calls':0}
  rendered={};fresh=None
  if changed and x['format']=='pdf':
   with P.pdfplumber.open(oldpath) as aa,P.pdfplumber.open(p) as bb:
    checks=[]
    def sig(c):return (c['text'],*[round(c[k],3) for k in ['x0','top','x1','bottom']])
    for i,(a,b) in enumerate(zip(aa.pages,bb.pages),1):
     missing=Counter(map(sig,a.chars))-Counter(map(sig,b.chars));assert not missing,(did,i,list(missing)[:4]);checks.append({'page':i,'old_chars_and_positions_preserved':len(a.chars)})
   args=SimpleNamespace(render_dpi=144,min_pdf_chars=20,soffice=None,render_font=None,work_dir=str(OUT));builder=P.Builder(p,{'doc_id':did,'relative_path':x['path']},OUT,args);P.parse_pdf(builder);fresh=builder.doc
   rendered={a['loc']['page']:a for a in fresh['assets']};evidence['pdf_geometry_checks']=checks
   # Preserve reviewed old blocks and add only genuinely new native footer lines.
   texts={(b['loc'].get('page'),b['text']) for b in r['blocks']}
   for b in fresh['blocks']:
    if b['type'] in ['paragraph','heading'] and (b['loc'].get('page'),b['text']) not in texts and any(k in b['text'] for k in ['CONFIDENTIAL','TECH BRIEFING','Raum Information Technology']):
     b=copy.deepcopy(b);b['block_id']+='-footer-v31';b['order']=len(r['blocks'])+1;r['blocks'].append(b)
     unit=next(u for u in r['coverage']['units'] if u['unit_id']=='native:page'+str(b['loc']['page']));unit['block_ids'].append(b['block_id'])
  if changed and x['format']=='pptx':
   aa=Presentation(oldpath);bb=Presentation(p);assert len(aa.slides)==len(bb.slides)
   checks=[]
   for i,(a,b) in enumerate(zip(aa.slides,bb.slides),1):
    oldtexts=Counter(s.text for s,_ in P.native.walk_shapes(a.shapes) if s.has_text_frame and s.text.strip());newtexts=Counter(s.text for s,_ in P.native.walk_shapes(b.shapes) if s.has_text_frame and s.text.strip());assert oldtexts==newtexts,(did,i,'text delta')
    imgs=[s.image.blob for s,_ in P.native.walk_shapes(a.shapes) if s.shape_type==13];newimgs=[s.image.blob for s,_ in P.native.walk_shapes(b.shapes) if s.shape_type==13];assert all(v in newimgs for v in imgs)
    checks.append({'slide':i,'literal_text_multiset_equal':True,'all_prior_embedded_images_present':True})
    # Exact shape locations for source-native text are re-linked by text, not stale shape IDs.
    for block in r['blocks']:
     if block['run_ref']=='native' and block['loc'].get('slide')==i and block['text'] and block['type'] in ['heading','paragraph'] and 'speaker_notes' not in ''.join(block['warnings']):
      matches=[s for s,_ in P.native.walk_shapes(b.shapes) if s.has_text_frame and s.text.strip()==block['text']]
      if len(matches)==1:
       block['loc']['shape_ids']=[matches[0].shape_id]
       for ev in block['evidence']:ev['loc']=copy.deepcopy(block['loc'])
   # Source slide is retained; coarse original vision boxes are invalid after redesign.
   remove_bbox(r);evidence['bbox_policy']='removed historical whole-slide coordinates; source slide/shape locators retained';evidence['pptx_checks']=checks
   args=SimpleNamespace(render_dpi=144,min_pdf_chars=20,soffice='/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice',render_font=str(ROOT/'work/font-render-arial/fonts/ArialUnicode.ttf'),render_font_family='Arial Unicode MS',work_dir=str(OUT))
   builder=P.Builder(p,{'doc_id':did,'relative_path':x['path']},OUT,args);P.parse_pptx(builder)
   assert not builder.audit['source_details']['rendering_error'],(did,builder.audit)
   rendered={a['loc']['slide']:a for a in builder.doc['assets']}
  for a in r['assets']:
   olda=next(v for v in originals[did]['assets'] if mapping[v['asset_id']]==a['asset_id'])
   dest=OUT/'reused-assets'/did/Path(a['path']).name;dest.parent.mkdir(parents=True,exist_ok=True)
   if changed and a['kind'] in ['page_image','slide_image']:
    newa=rendered[a['loc'].get('page',a['loc'].get('slide'))];shutil.copyfile(OUT/newa['path'],dest);a.update(width=newa['width'],height=newa['height'],sha256=newa['sha256'])
   else:shutil.copyfile(asset_source(olda),dest)
   a['path']=str(dest.relative_to(OUT))
  assert not check(r),(did,check(r))
  results.append(r);ledger.append(evidence);print(did,'relinked' if changed else 'unchanged',flush=True)
 lines(OUT/'reused-records.jsonl',results);write(OUT/'source-id-map.json',idmaps);write(OUT/'reuse-ledger.json',ledger)
if __name__=='__main__':main()
