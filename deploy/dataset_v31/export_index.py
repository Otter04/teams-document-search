"""Export reviewed v2 artifacts to new Elasticsearch indices; no search tuning."""
import argparse,collections,re,shutil
import numpy as np
from enrichment import *
X=load('v2_es_export',ROOT/'deploy/elasticsearch/export.py')
S=load('v2_search_prepare',ROOT/'deploy/search/prepare.py')
SOURCE=OUT/'prepared';DEST=OUT/'search-data'

def main():
 assert read(SOURCE/'assembly.json')['state']=='assembled_pending_embedding_and_index_load'
 assert not (DEST/'prepared.json').exists(),'Preserve completed export'
 DEST.mkdir(exist_ok=True)
 manifest=read(SOURCE/'embedding-manifest.json');inputs=rows(SOURCE/'embedding-inputs.jsonl');vectors=np.load(SOURCE/'vectors.npy',allow_pickle=False)
 assert sha(SOURCE/'embedding-inputs.jsonl')==manifest['input_sha256'] and sha(SOURCE/'vectors.npy')==manifest['vectors_sha256']
 assert manifest['model_fingerprint']==read(BASE/'embedding-manifest.json')['model_fingerprint']
 assert vectors.shape==(len(inputs),1024) and np.isfinite(vectors).all() and np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5)
 index=read(SOURCE/'index.json');docs=rows(SOURCE/'document-index.jsonl')
 parsed={r['doc_id']:r for r in rows(SOURCE/'indexing-records.jsonl')};meta={r['doc_id']:r for r in rows(SOURCE/'enriched.jsonl')}
 for r in parsed.values():E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(r))
 bundle=d.old.prepare(index,parsed,meta)
 raw={c['chunk_id']:c for r in rows(SOURCE/'chunks.jsonl') for c in r['chunks']};raw.update({c['chunk_id']:c for c in rows(SOURCE/'semantic-chunks.jsonl')})
 assert set(raw)=={r['chunk_id'] for r in inputs} and len(docs)==195
 documents={}
 for doc in docs:
  did=doc['doc_id'];prior=index['documents'][did];features=bundle['features'][did];src=doc['source']
  values={X.FIELDS[k]:v for k,v in prior['metadata'].items() if prior['metadata_statuses'][k]=='extracted'}
  statuses={X.FIELDS[k]:v for k,v in prior['metadata_statuses'].items()}
  for k,v in prior['date_metadata']['fields'].items():
   statuses[X.FIELDS[k]]=v['status']
   if v['status']=='extracted':values[X.FIELDS[k]]=v['value']
  texts={k:'\n'.join(x['text'] for x in vs) for k,vs in features.items()};mt=' '.join(f'{k} {v}' for k,v in prior['metadata'].items())
  r={'doc_id':did,'kind':'document','source_sha256':src['sha256'],'source_path':src['relative_path'],'format':src['format'],
   'title':texts['title'],'summary':doc['summary'],'metadata_text':mt,**{k:texts[k] for k in ['job','role','system','client']},
   'identifier_text':texts['identifier'],'metadata':values,'metadata_statuses':statuses,'feature_evidence':features,'original':doc,
   'identifiers':X.identifiers(texts['identifier']+' '+src['file_name']),'concepts':X.concepts(mt+' '+texts['job'],index)}
  version=re.search(r'(?:^|[_\s-])(?:v|rev)(\d+(?:\.\d+)*)',src['file_name'],re.I)
  r['version_number']=[int(s) for s in version[1].split('.')] if version else []
  r['version_label']='v'+version[1] if version else values.get('status','')
  kind=values.get('document_type');stem=('revisioned-diagram:'+values.get('target_system','')) if kind in ['네트워크 구성도','서버 구성도'] and version else S.norm_name(src['file_name'])
  key=str(Path(src['relative_path']).parent.parent)+'|'+str(kind)+'|'+stem
  r.update(family_id='family-'+S.digest(key),copy_group='sha256-'+src['sha256'],file_name=src['file_name'],
   version_evidence={'source':'filename, source folder, extracted metadata and observed file modification time','group_key':key,'filename':src['file_name'],'version_number':r['version_number'],'status':values.get('status'),'file_modified_at':values.get('file_modified_at')})
  documents[did]=r
 families=collections.defaultdict(list);copies=collections.defaultdict(list)
 for r in documents.values():families[r['family_id']].append(r);copies[r['source_sha256']].append(r)
 family_review=[]
 for fid,members in families.items():
  latest=max(members,key=lambda r:(r['version_number'],{'초안':0,'최종':2,'서명본':3}.get(r['metadata'].get('status'),1),r['metadata'].get('file_modified_at',''),r['doc_id']))
  for r in members:r['latest_version']=r['source_sha256']==latest['source_sha256']
  family_review.append({'family_id':fid,'members':[r['doc_id'] for r in members],'latest_doc_id':latest['doc_id'],'evidence':[r['version_evidence'] for r in members],'independent_human_review':False})
 for members in copies.values():
  canonical=min(members,key=lambda r:(bool(re.search(r'\(\d+\)|복사본|copy',r['file_name'],re.I)),r['doc_id']))
  for r in members:r.update(family_id=canonical['family_id'],latest_version=canonical['latest_version'])
 chunks=[]
 for pos,inp in enumerate(inputs):
  assert inp['vector_id']==pos and hashlib.sha256(inp['text'].encode()).hexdigest()==inp['embedding_text_sha256']
  c=raw[inp['chunk_id']];base=documents[inp['doc_id']]
  row={k:copy.deepcopy(v) for k,v in base.items() if k not in ['original','summary','version_number','version_evidence']}
  context=c['context_header']
  if base['metadata'].get('document_type')=='실행 로그':context+=' | '+base['job']+' | '+base['system']
  row.update(chunk_id=inp['chunk_id'],kind=inp['kind'],vector_id=pos,body=c['text'],context=context,table_header=c.get('table_header_text',''),source_refs=inp['source_refs'],embedding_text_sha256=inp['embedding_text_sha256'],embedding=vectors[pos].tolist(),original={'chunk':c,'embedding_input':inp})
  row['concepts']=X.concepts('\n'.join([row['body'],row['context'],row['table_header']]),index)
  row['identifiers']=X.identifiers('\n'.join([row['body'],row['identifier_text'],row['title']]))
  chunks.append(row)
 reference=read(ROOT/'outputs/search-service-001/reference.json')
 dictionary=read(ROOT/'outputs/search-service-001/nori-dictionary.json')
 for name,items in [('documents',list(documents.values())),('chunks',chunks)]:
  mapping=X.mapping(name=='chunks');mapping['settings']['analysis']['tokenizer']['rag_nori_tokenizer']['user_dictionary_rules']=dictionary
  props=mapping['mappings']['properties']
  for k in ['family_id','copy_group','version_label']:props[k]={'type':'keyword'}
  props['latest_version']={'type':'boolean'};props['file_name']={'type':'text','analyzer':'rag_ko','similarity':'rag_bm25'}
  if name=='documents':props['version_number']={'type':'integer'};props['version_evidence']={'type':'object','enabled':False}
  write(DEST/(name+'-mapping.json'),mapping)
  with (DEST/(name+'.ndjson')).open('w') as f:
   for r in items:
    f.write(json.dumps({'create':{'_index':'rag-search-'+name+'-v003','_id':r.get('chunk_id',r['doc_id'])}})+'\n')
    f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
 write(DEST/'documents.json',documents);write(DEST/'blocks.json',{did:{b['block_id']:b for b in r['blocks']} for did,r in parsed.items()})
 write(DEST/'reference.json',reference);write(DEST/'nori-dictionary.json',dictionary);write(DEST/'family-review.json',family_review);write(DEST/'embedding-identity.json',manifest)
 info={'documents':len(documents),'chunks':len(chunks),'document_index':'rag-search-documents-v003','chunk_index':'rag-search-chunks-v003',
  'preserved_summaries':17,'new_selective_summaries':len(rows(SOURCE/'semantic-enriched.jsonl'))-17,'gold_read':False,'search_logic':'unchanged search-1.6.1','files':{p.name:sha(p) for p in DEST.iterdir() if p.is_file()}}
 write(DEST/'prepared.json',info);print(json.dumps({k:v for k,v in info.items() if k!='files'}))
if __name__=='__main__':main()
