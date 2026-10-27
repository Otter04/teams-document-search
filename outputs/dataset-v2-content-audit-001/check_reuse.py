from pathlib import Path
import json,collections,zipfile,unicodedata,hashlib,posixpath
from lxml import etree as E
from pypdf import PdfReader
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[1];NEW=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2');N=lambda s:unicodedata.normalize('NFC',str(s))
def rows(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def put(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
comp=json.loads((OUT/'document-comparison.json').read_text());changed={x['doc_id'] for x in comp if x['classification']=='content_changed'};docs={r['doc_id']:r for r in rows(NEW/'gold/documents.jsonl')};files={N(p.relative_to(NEW/'files')):p for p in (NEW/'files').rglob('*') if p.is_file()}
def path(did):
 d=docs[did];return files[N(d['경로'].lstrip('/')+'/'+d['파일名'] if '파일名' in d else d['경로'].lstrip('/')+'/'+d['파일명'])]
base=ROOT/'outputs/indexing-110-semantic-vector-001';vectors=rows(base/'embedding-inputs.jsonl');semantic=rows(base/'semantic-enriched.jsonl')
added=set(json.loads((NEW/'gold/added_v2_doc_ids.json').read_text()));route=[]
supported={'docx','pptx','xlsx','pdf','txt','log'}
for did in sorted(added):
 d=docs[did];p=path(did);ext=p.suffix.lower().lstrip('.')
 route.append({'doc_id':did,'filename':d['파일명'],'type':d['문서종류'],'format':ext or 'no_extension','label_index_target':d['색인대상'],'parser_dispatch_supported':ext in supported,'source_path':str(p),'action':'exclude_by_dataset_scope' if d['색인대상']=='N' else 'new_content_processing_after_user_request','requires_format_adapter':ext not in supported and d['색인대상']=='Y'})
put('new-document-routing.json',route)
unit_names=[p.name for p in (ROOT/'outputs/vision-reuse-review-001/units').iterdir() if p.is_dir()];changedunits=['D-044-vision-page1','D-102-vision-page1'];assert set(changedunits)<=set(unit_names)
put('reuse-assessment.json',{'content_unchanged_document_count':110-len(changed),'changed_document_ids':sorted(changed),'existing_embedding_vectors':len(vectors),'unchanged_document_vector_candidates':sum(v['doc_id'] not in changed for v in vectors),'changed_document_vectors_to_check':sum(v['doc_id'] in changed for v in vectors),'semantic_documents':len(semantic),'semantic_changed_source_documents':sorted({d['doc_id'] for d in semantic}&changed),'vision_units':len(unit_names),'unchanged_vision_unit_candidates':len(unit_names)-len(changedunits),'vision_units_needing_patch':changedunits,'new_index_targets':sum(x['label_index_target']=='Y' for x in route),'new_parser_supported':sum(x['label_index_target']=='Y' and x['parser_dispatch_supported'] for x in route),'new_parser_adapter_required':sum(x['requires_format_adapter'] for x in route),'model_calls':0,'indexing_executed':False,'caveat':'Content reuse candidates only. Refresh source hashes/mtime provenance/IDs and validate exact embedding input strings and model fingerprint before adopting vectors.'})
# Verify added answer evidence without executing included generators.
evidence=[]
for did,needle in [('D-133','10.54.128.0/17'),('D-139','HTTP 502 Bad Gateway'),('D-140','ping 10.65.200.1')]:
 p=path(did);lines=p.read_text().splitlines();evidence.append({'doc_id':did,'needle':needle,'source_path':str(p),'matches':[{'line':i+1,'text':s} for i,s in enumerate(lines) if needle in s]})
p=path('D-155')
with zipfile.ZipFile(p) as z:
 shared=[]
 if 'xl/sharedStrings.xml' in z.namelist():
  shared=[''.join(v.itertext()) for v in E.fromstring(z.read('xl/sharedStrings.xml'))]
 for name in z.namelist():
  if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
   for c in E.fromstring(z.read(name)).iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
    txt=''.join(c.itertext());
    if c.get('t')=='s':txt=shared[int(txt)]
    if 'fms-gis01' in txt:evidence.append({'doc_id':'D-155','source_path':str(p),'member':name,'cell':c.get('r'),'text':txt})
p=path('D-119')
with zipfile.ZipFile(p) as z:
 for sn in [2,3]:
  slide=f'ppt/slides/slide{sn}.xml';rels=f'ppt/slides/_rels/slide{sn}.xml.rels';relmap={r.get('Id'):posixpath.normpath(posixpath.join('ppt/slides',r.get('Target'))) for r in E.fromstring(z.read(rels))}
  for el in E.fromstring(z.read(slide)).iter('{http://schemas.openxmlformats.org/drawingml/2006/main}blip'):
   target=relmap[el.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')];dest=OUT/'images'/f'D-119-slide{sn}-{Path(target).name}';dest.write_bytes(z.read(target));evidence.append({'doc_id':'D-119','slide':sn,'embedded_image':str(dest),'source_path':str(p),'status':'visual_review_pending'})
evidence.append({'doc_id':'D-151','source_path':str(path('D-151')),'status':'visual_review_pending'})
put('added-answer-evidence.json',evidence)
# Compare source file mtimes, but do not reinterpret them as authored dates.
put('mtime-review.json',{'different_local_filesystem_mtimes':sum(x['old_mtime']!=x['new_mtime'] for x in comp),'examples':[{'doc_id':x['doc_id'],'old':x['old_mtime'],'new':x['new_mtime'],'content_class':x['classification']} for x in comp[:3]],'decision':'Record v2 observed timestamps and import provenance separately; do not claim content was revised solely because local copy/regeneration time differs. No source date fields changed in this audit.'})
print(json.dumps(json.loads((OUT/'reuse-assessment.json').read_text()),ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False,indent=2))
