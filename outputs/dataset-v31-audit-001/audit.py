"""Read-only source and label inventory; no generator, model or indexing calls."""
from pathlib import Path
import json,hashlib,unicodedata,collections,zipfile,re
from lxml import etree as E
from pypdf import PdfReader
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
V2=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v2');V3=Path('/Users/kangdongkyoon/Downloads/RAG_예비데이터셋_v3.1')
N=lambda s:unicodedata.normalize('NFC',str(s))
def rows(p):return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def fmap(root):return {N(p.relative_to(root/'files')):p for p in (root/'files').rglob('*') if p.is_file()}
a,b=fmap(V2),fmap(V3);d2={d['doc_id']:d for d in rows(V2/'gold/documents.jsonl')};d3={d['doc_id']:d for d in rows(V3/'gold/documents.jsonl')}
indexed=json.loads((R/'outputs/indexing-v2-001/search-data/documents.json').read_text());inventory=[];missing=[]
for did,d in d3.items():
 rel=N(d['경로'].lstrip('/')+'/'+d['파일명']);p=b.get(rel)
 if p is None:missing.append({'doc_id':did,'path':rel});continue
 x={'doc_id':did,'path':rel,'file_name':N(p.name),'format':p.suffix.lower().lstrip('.') or 'no_extension','bytes':p.stat().st_size,'sha256':sha(p),'index_target_label':d.get('색인대상'),'scan_label':d.get('스캔'),'magic_hex':p.read_bytes()[:16].hex(),'new':did not in d2,'indexed_before':did in indexed,'mtime':p.stat().st_mtime}
 if did in indexed:
  old=a[N(indexed[did]['source_path'])];assert sha(old)==indexed[did]['source_sha256'],did
  x['old_sha256']=sha(old);x['mtime_changed']=old.stat().st_mtime!=p.stat().st_mtime
  if x['sha256']==x['old_sha256']:x['classification']='byte_identical'
  elif zipfile.is_zipfile(old) and zipfile.is_zipfile(p):
   with zipfile.ZipFile(old) as z1,zipfile.ZipFile(p) as z2:
    k1,k2=set(z1.namelist()),set(z2.namelist());changed=sorted(k for k in k1|k2 if k not in k1 or k not in k2 or z1.read(k)!=z2.read(k));x['changed_parts']=changed
    if not changed:x['classification']='zip_container_only'
    elif set(changed)<= {'docProps/core.xml'}:x['classification']='internal_properties_only'
    else:x['classification']='package_changed_requires_review'
    if p.suffix.lower()=='.pptx':
     def texts(z):return {k:E.fromstring(z.read(k)).xpath('//*[local-name()="t"]/text()') for k in sorted(z.namelist()) if re.fullmatch(r'ppt/slides/slide\d+.xml',k)}
     x['slide_text_equal']=texts(z1)==texts(z2);x['slide_count']=len(texts(z2))
     x['media_equal']=all(k in k1 and k in k2 and z1.read(k)==z2.read(k) for k in k1|k2 if k.startswith('ppt/media/'))
  elif p.suffix.lower()=='.pdf':
   q1,q2=PdfReader(old),PdfReader(p);t1=[q.extract_text() or '' for q in q1.pages];t2=[q.extract_text() or '' for q in q2.pages];x.update(old_pages=len(t1),pages=len(t2),text_equal=t1==t2)
   x['content_streams_equal']=len(t1)==len(t2) and all(u.get_contents().get_data()==v.get_contents().get_data() for u,v in zip(q1.pages,q2.pages))
   x['classification']='pdf_changed_requires_review'
   x['text_preview_added']=[l for l in '\n'.join(t2).splitlines() if l not in '\n'.join(t1).splitlines()][:12]
  else:x['classification']='changed_requires_review'
 elif did in d2:x['classification']='previously_excluded'
 else:x['classification']='new'
 inventory.append(x)
qs2={q['query_id']:q for q in rows(R/'outputs/indexing-v2-001/evaluation/gold-v2.jsonl')};qs3=rows(V3/'search_gold/search_gold.jsonl');by3={q['query_id']:q for q in qs3};qchanges=[];badrefs=[]
for qid,q in qs2.items():
 if qid not in by3:qchanges.append({'query_id':qid,'removed':True});continue
 n=by3[qid];ks=[k for k in set(q)|set(n) if q.get(k)!=n.get(k)]
 if ks:qchanges.append({'query_id':qid,'changed_keys':sorted(ks),'old_query':q['query'],'new_query':n['query'],'old_required':[c['representative'] for c in q['expected_cards'] if c['priority']=='필수'],'new_required':[c['representative'] for c in n['expected_cards'] if c['priority']=='필수']})
for q in qs3:
 for c in q.get('expected_cards',[]):
  ids=[c['representative']]+[x['doc_id'] for x in c.get('other_versions',[])+c.get('same_file_copies',[])]
  for did in ids:
   if did not in d3 or d3[did].get('색인대상')!='Y':badrefs.append({'query_id':q['query_id'],'doc_id':did})
new=[x for x in inventory if x['new']];old=[x for x in inventory if x['indexed_before']]
summary={'physical_files':len(b),'manifest_documents':len(d3),'manifest_unique_ids':len(d3),'missing_files':missing,'unregistered_files':sorted(set(b)-{x['path'] for x in inventory}),'index_target_counts':dict(collections.Counter(x['index_target_label'] for x in inventory)),'previously_indexed':len(old),'old_classifications':dict(collections.Counter(x['classification'] for x in old)),'old_mtime_changes':sum(x.get('mtime_changed',False) for x in old),'new_files':len(new),'new_formats':dict(collections.Counter(x['format'] for x in new)),'new_scan_labels':dict(collections.Counter(x['scan_label'] for x in new)),'query_count':len(qs3),'query_unique_ids':len(by3),'old_query_count':len(qs2),'new_query_count':len(set(by3)-set(qs2)),'old_query_text_changes':[x['query_id'] for x in qchanges if x.get('old_query')!=x.get('new_query')],'old_required_answer_changes':[x['query_id'] for x in qchanges if x.get('old_required')!=x.get('new_required')],'old_expected_card_changes':[x['query_id'] for x in qchanges if 'expected_cards' in x.get('changed_keys',[])],'invalid_answer_references':badrefs,'model_calls':0,'indexing_started':False}
save('inventory.json',inventory);save('query-changes.json',qchanges);save('summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
for x in new:print(x['doc_id'],x['format'],x['file_name'],x['index_target_label'],x['magic_hex'])
