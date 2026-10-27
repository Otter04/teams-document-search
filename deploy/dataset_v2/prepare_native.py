"""Read source bytes only. Extract native blocks and unique image jobs, not gold."""
import argparse, collections, io, re, subprocess, unicodedata, zipfile
from types import SimpleNamespace
from lxml import etree as ET
from PIL import Image
from pptx import Presentation
from common import *
N=lambda s:unicodedata.normalize('NFC',str(s))
def main():
 assert not (OUT/'native-new.jsonl').exists(),'Preserve prepared run'
 OUT.mkdir(exist_ok=True);(OUT/'assets').mkdir(exist_ok=True)
 write(OUT/'common-block.schema.json',SCHEMA)
 # Routing is reduced to identity and path; audit labels never enter extraction.
 inventory=[{'doc_id':x['doc_id'],'path':x['source_path']} for x in read(AUDIT/'new-document-routing.json')]
 records=[];jobs=[];decisions=[]
 args=SimpleNamespace(render_dpi=144,min_pdf_chars=20,soffice=None,render_font=None,work_dir=str(OUT))
 for item in inventory:
  path=Path(item['path']);fmt=path.suffix[1:].lower() or 'no_extension';did=item['doc_id']
  if fmt in ['bin','tgz','zip']:
   decisions.append({'doc_id':did,'action':'excluded','reason':'firmware or archive; unsupported scope','source_sha256':sha(path)});continue
  b=P.Builder(path,{'doc_id':did,'relative_path':N(path.relative_to(FILES))},OUT,args)
  b.doc['schema_version']='1.1.0';b.doc['source']['format']=fmt
  if fmt=='pptx':
   P.parse_pptx(b)
   # Native editable text/tables already extracted. Embedded raster frames need vision.
   b.doc['warnings']=[w for w in b.doc['warnings'] if w!='no slide renderer configured']
   b.doc['coverage']['units']=[u for u in b.doc['coverage']['units'] if not u['unit_id'].startswith('vision:')];b.queue=[]
   deck=Presentation(path)
   for sn,slide in enumerate(deck.slides,1):
    for shape,parents in P.native.walk_shapes(slide.shapes):
     if shape.shape_type==13:
      key=f'slide{sn}-image{shape.shape_id}';loc={'kind':'pptx','slide':sn,'shape_ids':[shape.shape_id]}
      a=b.asset(key,Image.open(io.BytesIO(shape.image.blob)).convert('RGB'),loc,'embedded_image')
      ctx=[x['block_id'] for x in b.doc['blocks'] if x['loc'].get('slide')==sn]
      b.pending(key,loc,'embedded screenshot or photo; native surrounding text retained separately',a,ctx)
     elif shape.shape_type not in [1,13,14,17,19,6]:
      raise ValueError(f'{did}: visual shape requiring explicit support: {shape.shape_type}')
   decisions.append({'doc_id':did,'action':'native_pptx_and_embedded_images','native_shapes':[str(s.shape_type) for slide in deck.slides for s in slide.shapes]})
  elif fmt in ['pdf','docx','xlsx','log','txt']:P.PARSERS[fmt](b)
  elif fmt=='hwpx':
   with zipfile.ZipFile(path) as z:
    for name in sorted(x for x in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml',x)):
     root=ET.fromstring(z.read(name));unit=b.unit('native:'+name,{'kind':fmt,'section':name,'paragraph_index':1})
     # Reject real complex tables until a structural adapter can represent them.
     assert not root.xpath('//*[local-name()="tbl"]'),'HWPX native table adapter required'
     for pn,p in enumerate(root.xpath('//*[local-name()="p"]'),1):
      text=''.join(p.xpath('.//*[local-name()="t"]/text()'))
      if text.strip():b.add(f'{Path(name).stem}-p{pn}','heading' if pn==1 else 'paragraph',text,{'kind':fmt,'section':name,'paragraph_index':pn},unit=unit)
    assert not [x for x in z.namelist() if x.startswith('BinData/')],'Embedded HWPX image not handled'
  elif fmt in ['ini','rtf','no_extension']:
   if fmt=='rtf':
    proc=subprocess.run(['/usr/bin/textutil','-convert','txt','-stdout',str(path)],capture_output=True,check=True);text=proc.stdout.decode('utf-8');b.doc['source']['encoding']='rtf decoded by macOS textutil'
   else:text=path.read_text(encoding='utf-8-sig');b.doc['source']['encoding']='utf-8-sig'
   unit=b.unit('native:lines',{'kind':fmt,'line_start':1,'line_end':max(1,len(text.splitlines()))})
   for n,line in enumerate(text.splitlines(),1):
    if line.strip():b.add(f'line{n}','paragraph',line,{'kind':fmt,'line_start':n,'line_end':n},unit=unit)
  elif fmt in ['jpg','png']:
   a=b.asset('image',Image.open(path).convert('RGB'),{'kind':fmt},'embedded_image');b.pending('image',{'kind':fmt},'standalone source image requires vision',a)
  else:raise ValueError(fmt)
  assert not check(b.doc),(did,check(b.doc))
  for j in b.queue:
   assert j['asset_path'],(did,j)
   j.update(id=did+'-'+j['unit_id'].replace(':','-'),planned_service='Orin local vLLM',model='qwen3.6-35b-a3b')
   image=Image.open(OUT/j['asset_path']).convert('RGB');j['pixel_sha256']=hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
   jobs.append(j)
  records.append(b.doc)
 unique={};aliases={}
 for j in jobs:
  # Vision only sees the image, so exact pixels reuse safely across slide versions.
  h=j['pixel_sha256']
  if h in unique:aliases[j['id']]=unique[h]['id']
  else:unique[h]=j
 lines(OUT/'native-new.jsonl',records);write(OUT/'vision-jobs.json',jobs);write(OUT/'vision-unique.json',list(unique.values()));write(OUT/'vision-aliases.json',aliases)
 write(OUT/'native-routing.json',decisions)
 paths={x['doc_id']:x['path'] for x in inventory if x['doc_id'] in {r['doc_id'] for r in records}}
 for x in read(AUDIT/'document-comparison.json'):paths[x['doc_id']]=x['new_path']
 write(OUT/'source-paths.json',paths)
 write(OUT/'source-freeze.json',{did:sha(p) for did,p in paths.items()})
 write(OUT/'baseline-freeze.json',{str(p.relative_to(ROOT)):sha(p) for folder in [BASE,ROOT/'outputs/search-service-001'] for p in folder.iterdir() if p.is_file()})
 print(json.dumps({'new_documents':len(records),'image_units':len(jobs),'unique_image_requests':len(unique),'duplicate_image_reuse':len(aliases)},ensure_ascii=False))
if __name__=='__main__':main()
