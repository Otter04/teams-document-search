"""Read-only comparison of original files and v2. Does not run dataset generators or indexing."""
from pathlib import Path
import json,hashlib,unicodedata,zipfile,collections,difflib
from datetime import datetime,timezone
from lxml import etree as E
from pypdf import PdfReader
import pypdfium2 as pdfium
from PIL import Image,ImageChops
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
N=lambda s:unicodedata.normalize('NFC',str(s))
OLD=next(p for p in Path('/Users/kangdongkyoon/Downloads').iterdir() if N(p.name)=='RAG_예비데이터셋(클로드)')
NEW=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2')
def rows(p):return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]
def sha(b):return hashlib.sha256(b).hexdigest()
def put(n,x): (OUT/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def fmap(r):return {N(p.relative_to(r/'files')):p for p in (r/'files').rglob('*') if p.is_file()}
def pretty(b):return E.tostring(E.fromstring(b),pretty_print=True,encoding='unicode').splitlines()
a,b=fmap(OLD),fmap(NEW);docs=json.loads((ROOT/'outputs/search-service-001/documents.json').read_text());newdocs={r['doc_id']:r for r in rows(NEW/'gold/documents.jsonl')}
results=[];(OUT/'diffs').mkdir(exist_ok=True);(OUT/'images').mkdir(exist_ok=True)
for did,d in docs.items():
 rel=N(d['source_path']);old,new=a[rel],b[rel];x,y=old.read_bytes(),new.read_bytes();assert sha(x)==d['source_sha256'],did
 r={'doc_id':did,'filename':N(old.name),'format':d['format'],'old_path':str(old),'new_path':str(new),'old_sha256':sha(x),'new_sha256':sha(y),'source_path_unchanged':True,'old_mtime':datetime.fromtimestamp(old.stat().st_mtime,timezone.utc).isoformat(),'new_mtime':datetime.fromtimestamp(new.stat().st_mtime,timezone.utc).isoformat()}
 if x==y:r['classification']='byte_identical'
 elif zipfile.is_zipfile(old):
  with zipfile.ZipFile(old) as z1,zipfile.ZipFile(new) as z2:
   keys=sorted(set(z1.namelist())|set(z2.namelist()));changed=[k for k in keys if k not in z1.namelist() or k not in z2.namelist() or z1.read(k)!=z2.read(k)]
   r['changed_parts']=changed;r['zip_timestamp_changes']=sum(z1.getinfo(k).date_time!=z2.getinfo(k).date_time for k in keys if k in z1.namelist() and k in z2.namelist())
   if not changed:r['classification']='zip_container_only'
   elif changed==['docProps/core.xml']:
    t1,t2=E.fromstring(z1.read(changed[0])),E.fromstring(z2.read(changed[0]));m1={E.QName(v).localname:v.text for v in t1};m2={E.QName(v).localname:v.text for v in t2};r['internal_metadata_changes']={k:{'old':m1.get(k),'new':m2.get(k)} for k in set(m1)|set(m2) if m1.get(k)!=m2.get(k)}
    assert set(r['internal_metadata_changes'])<= {'created','modified'}
    r['classification']='internal_timestamp_only'
   else:
    r['classification']='content_changed';delta=[]
    for k in changed:
     if k.endswith('.xml') and k in z1.namelist() and k in z2.namelist():delta+=list(difflib.unified_diff(pretty(z1.read(k)),pretty(z2.read(k)),fromfile='old/'+k,tofile='v2/'+k))
    (OUT/'diffs'/f'{did}.diff').write_text('\n'.join(delta)+'\n')
    if changed==['word/document.xml']:
     texts=lambda z:[''.join(v.itertext()) for v in E.fromstring(z.read('word/document.xml')).iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t')]
     t1,t2=texts(z1),texts(z2);r['text_diff']=list(difflib.unified_diff(t1,t2,fromfile='old',tofile='v2'))
 elif d['format']=='pdf':
  p1,p2=PdfReader(old),PdfReader(new);r['old_pages']=len(p1.pages);r['new_pages']=len(p2.pages)
  r['pdf_metadata_changes']={k:{'old':str((p1.metadata or {}).get(k)),'new':str((p2.metadata or {}).get(k))} for k in set(p1.metadata or {})|set(p2.metadata or {}) if (p1.metadata or {}).get(k)!=(p2.metadata or {}).get(k)}
  r['trailer_id_changed']=str(p1.trailer.get('/ID'))!=str(p2.trailer.get('/ID'))
  texts1=[p.extract_text() for p in p1.pages];texts2=[p.extract_text() for p in p2.pages];r['text_equal']=texts1==texts2
  r['text_diff']=list(difflib.unified_diff('\n'.join(texts1).splitlines(),'\n'.join(texts2).splitlines(),fromfile='old',tofile='v2'))
  r['content_streams_equal']=len(p1.pages)==len(p2.pages) and all(p.get_contents().get_data()==q.get_contents().get_data() for p,q in zip(p1.pages,p2.pages))
  f1,f2=pdfium.PdfDocument(str(old)),pdfium.PdfDocument(str(new));checks=[]
  for i in range(min(len(f1),len(f2))):
   page1,page2=f1[i],f2[i];bmp1,bmp2=page1.render(scale=2),page2.render(scale=2);im1,im2=bmp1.to_pil().convert('RGB'),bmp2.to_pil().convert('RGB')
   eq=im1.size==im2.size and im1.tobytes()==im2.tobytes();bbox=ImageChops.difference(im1,im2).getbbox() if im1.size==im2.size else None
   checks.append({'page':i+1,'old_pixel_sha256':sha(im1.tobytes()),'new_pixel_sha256':sha(im2.tobytes()),'dimensions':list(im1.size),'equal':eq,'changed_bbox':bbox})
   if (not eq and i==0) or (did in ['D-002','D-069'] and i==0):
    im1.save(OUT/'images'/f'{did}-p{i+1}-old.png');im2.save(OUT/'images'/f'{did}-p{i+1}-v2.png')
   bmp1.close();bmp2.close();page1.close();page2.close()
  f1.close();f2.close();r['render_checks_144dpi']=checks;r['render_equal']=len(p1.pages)==len(p2.pages) and all(v['equal'] for v in checks)
  r['classification']='pdf_internal_only' if r['render_equal'] and r['text_equal'] and r['content_streams_equal'] else 'content_changed'
  if r['text_diff']:(OUT/'diffs'/f'{did}.diff').write_text('\n'.join(r['text_diff'])+'\n')
 else:r['classification']='unclassified_changed'
 results.append(r)
 print(did,r['classification'],flush=True)
put('document-comparison.json',results)
oldq={r['query_id']:r for r in rows(ROOT/'datasets/search-gold-v2/search_gold.jsonl')};newq={r['query_id']:r for r in rows(NEW/'search_gold/search_gold.jsonl')};diffs=[]
for qid,o in oldq.items():
 nn=newq[qid];keys=[k for k in sorted(set(o)|set(nn)) if o.get(k)!=nn.get(k)]
 if not keys:continue
 entry={'query_id':qid,'query':o['query'],'changed_fields':keys}
 if any(k in keys for k in ['expected_cards','answer_doc_ids','answer_families']):
  entry.update(old_answer_ids=o['answer_doc_ids'],new_answer_ids=nn['answer_doc_ids'],added_answer_ids=sorted(set(nn['answer_doc_ids'])-set(o['answer_doc_ids'])),removed_answer_ids=sorted(set(o['answer_doc_ids'])-set(nn['answer_doc_ids'])),old_cards=o['expected_cards'],new_cards=nn['expected_cards'])
  oc={c['representative']:c for c in o['expected_cards']};nc={c['representative']:c for c in nn['expected_cards']}
  entry['existing_cards_unchanged']=all(nc.get(k)==v for k,v in oc.items());entry['new_cards']=[v for k,v in nc.items() if k not in oc]
 diffs.append(entry)
put('query-comparison.json',diffs)
put('summary.json',{'original_sources_verified_against_index':len(results),'classifications':dict(collections.Counter(r['classification'] for r in results)),'changed_by_format':dict(collections.Counter(r['format'] for r in results if r['classification']!='byte_identical')),'rendered_pdf_pages_pairs':sum(len(r.get('render_checks_144dpi',[])) for r in results),'changed_original_questions':sum(q['query']!=newq[k]['query'] for k,q in oldq.items()),'answer_changes':[d['query_id'] for d in diffs if 'added_answer_ids' in d],'changed_fields':dict(collections.Counter(k for d in diffs for k in d['changed_fields'])),'model_calls':0,'indexing_executed':False})
