"""Prepare search metadata from source artifacts only. Never load evaluation gold."""
import collections,copy,hashlib,json,re,unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/search-service-001'; BASE=ROOT/'outputs/elasticsearch-migration-001'
SOURCE=ROOT/'outputs/indexing-110-semantic-vector-001'
def read(p):return json.loads(Path(p).read_text())
def lines(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(s):return hashlib.sha256(s.encode()).hexdigest()[:16]
def norm_name(name):
    s=unicodedata.normalize('NFC',Path(name).stem).casefold()
    s=re.sub(r'\s*\(\d+\)|복사본|copy','',s)
    s=re.sub(r'(?:[_\s-]?)(?:rev|v)\d+(?:\.\d+)*','',s)
    s=re.sub(r'[()（）]|초안|서명본|최종본|최종','',s)
    return re.sub(r'[\s_]+','',s)
def main():
    assert not (OUT/'prepared.json').exists(),'Preserve existing search preparation'
    OUT.mkdir(parents=True,exist_ok=True)
    docs=[json.loads(s) for s in (BASE/'documents.ndjson').read_text().splitlines()[1::2]]
    chunks=[json.loads(s) for s in (BASE/'chunks.ndjson').read_text().splitlines()[1::2]]
    reference=read(BASE/'reference-rules.json');groups=collections.defaultdict(list)
    for doc in docs:
        src=doc['original']['source'];meta=doc['metadata'];name=src['file_name']
        v=re.search(r'(?:^|[_\s-])(?:v|rev)(\d+(?:\.\d+)*)',name,re.I)
        doc['version_number']=[int(s) for s in v[1].split('.')] if v else []
        doc['version_label']=('v'+v[1]) if v else meta.get('status','')
        kind=meta.get('document_type');project=str(Path(src['relative_path']).parent.parent)
        # Different filenames for revisioned diagrams can share a project/system/type.
        stem=('revisioned-diagram:'+meta.get('target_system','')) if kind in ['네트워크 구성도','서버 구성도'] and v else norm_name(name)
        group_key=project+'|'+str(kind)+'|'+stem
        doc['family_id']='family-'+digest(group_key)
        doc['copy_group']='sha256-'+src['sha256'];groups[doc['family_id']].append(doc)
        doc['file_name']=name
        doc['version_evidence']={'source':'filename, source folder, extracted metadata and observed file modification time',
          'group_key':group_key,'filename':name,'version_number':doc['version_number'],
          'status':meta.get('status'),'file_modified_at':meta.get('file_modified_at')}
    inventory=[]
    for fid,members in groups.items():
        def version_key(doc):
            return (doc['version_number'],{'초안':0,'최종':2,'서명본':3}.get(doc['metadata'].get('status'),1),
                    doc['metadata'].get('file_modified_at',''),doc['doc_id'])
        latest=max(members,key=version_key)
        # Copies of the same latest physical content have the same latest status.
        for doc in members:doc['latest_version']=doc['source_sha256']==latest['source_sha256']
        inventory.append({'family_id':fid,'members':[x['doc_id'] for x in members],
          'latest_doc_id':latest['doc_id'],'evidence':[x['version_evidence'] for x in members],
          'independent_human_review':False})
    bydoc={d['doc_id']:d for d in docs}
    # Identical file hashes are folded even when a copy lives in a different folder.
    hashgroups=collections.defaultdict(list)
    for d in docs:hashgroups[d['source_sha256']].append(d)
    for members in hashgroups.values():
        if len(members)<2:continue
        canonical=min(members,key=lambda r:(bool(re.search(r'\(\d+\)|복사본|copy',r['file_name'],re.I)),r['doc_id']))
        for doc in members:doc['family_id']=canonical['family_id'];doc['latest_version']=canonical['latest_version']
    for c in chunks:
        doc=bydoc[c['doc_id']]
        c.update({k:doc[k] for k in ['family_id','copy_group','latest_version','version_label','file_name']})
    custom=set(reference['system_terms'])
    for client in reference['clients']:custom.update([client['name'],client['folder']]+client['aliases'])
    dictionary=sorted({x for term in custom for x in re.findall(r'[가-힣A-Za-z][가-힣A-Za-z0-9]*',term) if len(x)>1})
    for name,rows in [('documents',docs),('chunks',chunks)]:
        mapping=read(BASE/('document-mapping.json' if name=='documents' else 'chunk-mapping.json'))
        mapping['settings']['analysis']['tokenizer']['rag_nori_tokenizer']['user_dictionary_rules']=dictionary
        props=mapping['mappings']['properties']
        for k in ['family_id','copy_group','version_label']:props[k]={'type':'keyword'}
        props['latest_version']={'type':'boolean'}
        props['file_name']={'type':'text','analyzer':'rag_ko','similarity':'rag_bm25'}
        if name=='documents':
            props['version_number']={'type':'integer'};props['version_evidence']={'type':'object','enabled':False}
        write(OUT/(name+'-mapping.json'),mapping)
        with (OUT/(name+'.ndjson')).open('w') as f:
            for r in rows:
                f.write(json.dumps({'create':{'_index':'rag-search-'+name+'-v001','_id':r.get('chunk_id',r['doc_id'])}})+'\n')
                f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    blocks={r['doc_id']:{b['block_id']:b for b in r['blocks']} for r in lines(SOURCE/'indexing-records.jsonl')}
    write(OUT/'blocks.json',blocks);write(OUT/'documents.json',bydoc);write(OUT/'reference.json',reference)
    write(OUT/'family-review.json',inventory);write(OUT/'nori-dictionary.json',dictionary)
    model=read(SOURCE/'embedding-manifest.json');write(OUT/'embedding-identity.json',model)
    write(OUT/'prepared.json',{'documents':len(docs),'chunks':len(chunks),'families':len({d['family_id'] for d in docs}),
      'nori_dictionary_entries':len(dictionary),'preserved_summaries':17,'gold_read':False,
      'source_hashes':{f:sha(SOURCE/f) for f in ['document-index.jsonl','indexing-records.jsonl','embedding-manifest.json','vectors.npy']},
      'files':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},'model_calls':0})
    print(json.dumps({'docs':len(docs),'chunks':len(chunks),'multi_document_families':[x['members'] for x in inventory if len(x['members'])>1]}))
if __name__=='__main__':main()
