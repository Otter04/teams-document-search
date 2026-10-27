"""Source-only v3.1 native adapters. Gold and generators are never read."""
import csv,io,re,shutil,subprocess,unicodedata
from types import SimpleNamespace
from lxml import etree as ET,html
from PIL import Image
from pptx import Presentation
from common import *
N=lambda x:unicodedata.normalize('NFC',str(x))
SOFFICE='/Users/kangdongkyoon/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/soffice'
def main():
 inventory=read(AUDIT/'inventory.json');paths=P.source_map(FILES);jobs=[];records=[];routing=[]
 write(OUT/'common-block.schema.json',SCHEMA)
 basefiles=[p for p in BASE.iterdir() if p.is_file()]+list((ROOT/'deploy/search').glob('*.py'))+list((ROOT/'deploy/search').glob('*.json'))
 frozen={str(p.relative_to(ROOT)):sha(p) for p in basefiles}
 if (OUT/'baseline-freeze.json').exists():assert read(OUT/'baseline-freeze.json')==frozen
 else:write(OUT/'baseline-freeze.json',frozen)
 selected=[x for x in inventory if x['format'] not in ['bin','tgz','zip']]
 write(OUT/'source-paths.json',{x['doc_id']:str(paths[x['path']]) for x in selected})
 write(OUT/'source-freeze.json',{x['doc_id']:sha(paths[x['path']]) for x in selected})
 write(OUT/'collection-freeze.json',{x['doc_id']:{'mtime_ns':paths[x['path']].stat().st_mtime_ns,'bytes':paths[x['path']].stat().st_size} for x in selected})
 for x in selected:
  if not x['new']:continue
  did=x['doc_id'];p=paths[x['path']];fmt=x['format'];args=SimpleNamespace(render_dpi=144,min_pdf_chars=20,soffice=None,render_font=None,work_dir=str(OUT))
  b=P.Builder(p,{'doc_id':did,'relative_path':x['path']},OUT,args);b.doc['schema_version']='1.2.0'
  native_fmt=fmt;conversion=None
  if fmt in ['doc','xls','ppt']:
   native_fmt={'doc':'docx','xls':'xlsx','ppt':'pptx'}[fmt];folder=OUT/'converted'/did;folder.mkdir(parents=True,exist_ok=True)
   target=folder/(p.stem+'.'+native_fmt)
   if not target.exists():
    proc=subprocess.run([SOFFICE,'-env:UserInstallation='+str((folder/'profile').resolve().as_uri()),'--headless','--convert-to',native_fmt,'--outdir',str(folder),str(p)],capture_output=True,text=True,timeout=120)
    write(folder/'conversion-log.json',{'returncode':proc.returncode,'stdout':proc.stdout,'stderr':proc.stderr})
    assert proc.returncode==0 and target.exists(),(did,proc.stdout,proc.stderr)
   conversion={'source_sha256':sha(p),'derivative_sha256':sha(target),'path':str(target.relative_to(OUT)),'tool':'LibreOfficeDev 26.8.0.0.alpha0','original_preserved':True};write(folder/'provenance.json',conversion);b.path=target
  if native_fmt=='pptx':
   P.parse_pptx(b);b.doc['warnings']=[w for w in b.doc['warnings'] if w!='no slide renderer configured'];b.doc['coverage']['units']=[u for u in b.doc['coverage']['units'] if not u['unit_id'].startswith('vision:')];b.queue=[]
   deck=Presentation(b.path)
   for sn,slide in enumerate(deck.slides,1):
    for shape,parents in P.native.walk_shapes(slide.shapes):
     if shape.shape_type==13:
      key=f'slide{sn}-image{shape.shape_id}';loc={'kind':'pptx','slide':sn,'shape_ids':[shape.shape_id]}
      a=b.asset(key,Image.open(io.BytesIO(shape.image.blob)).convert('RGB'),loc,'embedded_image');ctx=[z['block_id'] for z in b.doc['blocks'] if z['loc'].get('slide')==sn]
      b.pending(key,loc,'embedded raster requires source review',a,ctx)
     elif shape.shape_type not in [1,13,14,17,19,6]:raise ValueError((did,str(shape.shape_type)))
  elif native_fmt in P.PARSERS:P.PARSERS[native_fmt](b)
  elif fmt=='rtf':
   t=subprocess.run(['/usr/bin/textutil','-convert','txt','-stdout',str(p)],capture_output=True,check=True).stdout.decode();add_lines(b,t,fmt)
  elif fmt=='csv':
   t=p.read_text(encoding='utf-8-sig');reader=csv.reader(io.StringIO(t));data=list(reader);width=max(map(len,data));assert all(len(r)==width for r in data),'ragged CSV requires explicit review'
   u=b.unit('native:csv',{'kind':fmt,'line_start':1,'line_end':len(t.splitlines())});cells=[];line=1
   reader=csv.reader(io.StringIO(t))
   for rn,row in enumerate(reader,1):
    for cn,value in enumerate(row,1):cells.append(P.cell(rn,cn,value,{'kind':fmt,'line_start':line,'line_end':reader.line_num,'row':rn,'column':cn},role='header' if rn==1 else 'data'))
    line=reader.line_num+1
   b.table('csv',cells,len(data),width,{'kind':fmt,'line_start':1,'line_end':len(t.splitlines())},header_rows=[1],header_status='explicit',unit=u)
  elif fmt in ['yaml','json','xml','jmx']:
   t=p.read_text(encoding='utf-8-sig')
   if fmt=='json':json.loads(t)
   if fmt in ['xml','jmx']:ET.fromstring(t.encode(),ET.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
   add_lines(b,t,fmt)
  elif fmt=='html':
   t=p.read_text(encoding='utf-8-sig');tree=html.fromstring(t)
   for e in tree.xpath('//script|//style|//noscript'):e.drop_tree()
   u=b.unit('native:html',{'kind':fmt,'line_start':1,'line_end':len(t.splitlines())})
   def hloc(e):return {'kind':fmt,'line_start':e.sourceline or 1,'line_end':e.sourceline or 1,'structure_path':e.getroottree().getpath(e)}
   for n,e in enumerate(tree.xpath('//title|//h1|//h2|//h3|//p[not(ancestor::table)]|//li[not(ancestor::table)]|//table'),1):
    if e.tag=='table':
     trs=e.xpath('./tr|./thead/tr|./tbody/tr|./tfoot/tr');cells=[];width=0;occupied=set()
     for rn,tr in enumerate(trs,1):
      col=1
      for td in tr.xpath('./th|./td'):
       while (rn,col) in occupied:col+=1
       rs=int(td.get('rowspan','1'));cs=int(td.get('colspan','1'));text=' '.join(' '.join(td.itertext()).split())
       cells.append(P.cell(rn,col,text,hloc(td),rs,cs,role='header' if td.tag=='th' else 'data'))
       occupied.update((rr,cc) for rr in range(rn,rn+rs) for cc in range(col,col+cs));col+=cs;width=max(width,col-1)
     assert occupied=={(r,c) for r in range(1,len(trs)+1) for c in range(1,width+1)},'HTML grid has gaps'
     headers=[rn for rn,tr in enumerate(trs,1) if tr.xpath('./th') and not tr.xpath('./td')]
     b.table('element'+str(n),cells,len(trs),width,hloc(e),header_rows=headers,header_status='explicit' if headers else 'unknown',unit=u)
    else:
     text=' '.join(e.itertext()).strip()
     if text:b.add('element'+str(n),'heading' if e.tag in ['title','h1','h2','h3'] else 'paragraph',text,hloc(e),unit=u)
  else:raise ValueError(fmt)
  if conversion:
   def relink(v):
    if isinstance(v,dict):
     if v.get('kind')==native_fmt:v['kind']=fmt;v['conversion_artifact']=conversion['path']
     for c in v.values():relink(c)
    elif isinstance(v,list):
     for c in v:relink(c)
   relink(b.doc);relink(b.queue);b.doc['runs'][0]['implementation']='parser-v31 / '+conversion['tool']+' conversion; original format locators'
  assert not check(b.doc),(did,check(b.doc))
  for j in b.queue:
   assert j['asset_path'];j.update(id=did+'-'+j['unit_id'].replace(':','-'),planned_service='Orin local vLLM',model='qwen3.6-35b-a3b')
   im=Image.open(OUT/j['asset_path']).convert('RGB');j['pixel_sha256']=hashlib.sha256(str(im.size).encode()+im.tobytes()).hexdigest();jobs.append(j)
  records.append(b.doc);routing.append({'doc_id':did,'format':fmt,'blocks':len(b.doc['blocks']),'pending_visuals':len(b.queue),'conversion':conversion,'warnings':b.doc['warnings']})
  write(OUT/'native-progress.json',{'last':did,'completed':len(records)});print(did,len(b.doc['blocks']),len(b.queue),flush=True)
 lines(OUT/'native-new.jsonl',records);write(OUT/'vision-jobs-unreviewed.json',jobs);write(OUT/'native-routing.json',routing)
def add_lines(b,t,fmt):
 u=b.unit('native:lines',{'kind':fmt,'line_start':1,'line_end':max(1,len(t.splitlines()))});stack=[]
 for n,line in enumerate(t.splitlines(),1):
  if not line.strip():continue
  loc={'kind':fmt,'line_start':n,'line_end':n}
  if fmt=='yaml':
   indent=len(line)-len(line.lstrip());key=re.match(r'\s*([\w.-]+):',line)
   if key:
    while stack and stack[-1][0]>=indent:stack.pop()
    stack.append((indent,key[1]));loc['structure_path']='.'.join(k for _,k in stack)
  b.add('line'+str(n),'paragraph',line,loc,unit=u)
if __name__=='__main__':main()
