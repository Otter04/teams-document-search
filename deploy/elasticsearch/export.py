"""Lossless export of the existing reviewed artifacts. No model calls or labels."""
import copy, hashlib, json, re, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/vector-deps'))
sys.path.insert(0,str(ROOT/'work/schema-deps'))
import numpy as np
sys.path.insert(0,str(ROOT/'deploy/rag_app'))
from runtime import E,d

SRC=ROOT/'outputs/indexing-110-semantic-vector-001'
OUT=ROOT/'outputs/elasticsearch-migration-001'
DOC_INDEX='rag-documents-v001'; CHUNK_INDEX='rag-chunks-v001'
FIELDS={'문서종류':'document_type','거래처':'client','문서일자':'document_date',
 '대상시스템':'target_system','상태':'status','계약번호':'contract_id','계약유형':'contract_type',
 '계약시작일':'contract_start','계약종료일':'contract_end','금액':'amount','통화':'currency',
 'VAT':'vat','견적번호':'quote_id','견적유효기간':'quote_validity','사이트':'site','작업명':'job_name',
 '로그시작':'log_start','로그종료':'log_end','실행결과':'execution_result','오류코드':'error_code','사업명':'project_name',
 '표지일':'cover_date','작성일':'written_date','파일최종수정일':'file_modified_at'}
DATE_KEYS={'document_date','contract_start','contract_end','cover_date','written_date','log_start','log_end'}
def read(p):return json.loads(Path(p).read_text())
def lines(p):return [json.loads(s) for s in Path(p).read_text().splitlines() if s.strip()]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def concepts(text,index):
    # Keep the existing bilingual vocabulary and intent rules, not Korean bigrams.
    return sorted(set(['concept:'+h['concept'] for h in d.old.old.previous.concepts(text,index['rules'])]+d.old.intent_tokens(text)))
def identifiers(text):
    return sorted(set(m.group(0).casefold() for m in re.finditer(r'[A-Za-z0-9]+(?:[._:/-][A-Za-z0-9]+)+',text)
                      if any(c.isdigit() for c in m.group(0))))
def settings():
    return {'number_of_shards':1,'number_of_replicas':0,
     'analysis':{'tokenizer':{'rag_nori_tokenizer':{'type':'nori_tokenizer','decompound_mode':'mixed'}},
       'analyzer':{'rag_ko':{'type':'custom','tokenizer':'rag_nori_tokenizer',
          'filter':['nori_part_of_speech','nori_readingform','lowercase']}}},
     'similarity':{'rag_bm25':{'type':'BM25','k1':1.2,'b':0.75}}}
def mapping(chunk=False):
    keyword={'type':'keyword'}; text={'type':'text','analyzer':'rag_ko','similarity':'rag_bm25'}
    date={'type':'date','format':'strict_date_optional_time||yyyy-MM-dd HH:mm:ss||yyyy-MM-dd HH:mm'}
    meta={v:copy.deepcopy(date if v in DATE_KEYS else keyword) for v in FIELDS.values()}
    meta['file_modified_at']={'type':'date_nanos'}
    # Keep the existing monetary representation exact; numeric filtering is a future explicit policy.
    props={k:copy.deepcopy(keyword) for k in ['doc_id','chunk_id','kind','source_sha256','embedding_text_sha256','source_path','format']}
    props.update({k:copy.deepcopy(text) for k in ['title','body','context','table_header','summary','metadata_text','job','role','identifier_text','system','client']})
    props.update({'metadata':{'properties':meta,'dynamic':'strict'},
      'metadata_statuses':{'properties':{v:keyword for v in FIELDS.values()},'dynamic':'strict'},
      'concepts':keyword,'identifiers':keyword,
      'original':{'type':'object','enabled':False},'source_refs':{'type':'object','enabled':False},
      'feature_evidence':{'type':'object','enabled':False}})
    if chunk:props.update({'embedding':{'type':'dense_vector','dims':1024,'index':True,
                    'similarity':'cosine','index_options':{'type':'flat'}},'vector_id':{'type':'integer'}})
    return {'settings':settings(),'mappings':{'dynamic':'strict','properties':props}}
def main():
    assert not (OUT/'manifest.json').exists(),'Preserve completed export'
    OUT.mkdir(parents=True,exist_ok=True)
    frozen={str(p.relative_to(SRC)):sha(p) for p in SRC.rglob('*') if p.is_file()}
    index=read(SRC/'index.json');docs=lines(SRC/'document-index.jsonl')
    parsed={r['doc_id']:r for r in lines(SRC/'indexing-records.jsonl')}
    metadata={r['doc_id']:r for r in lines(SRC/'enriched.jsonl')}
    for r in parsed.values():E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(r))
    bundle=d.old.prepare(index,parsed,metadata)
    inputs=lines(SRC/'embedding-inputs.jsonl');vmap=lines(SRC/'vector-map.jsonl')
    vectors=np.load(SRC/'vectors.npy',allow_pickle=False)
    assert vectors.shape==(1089,1024) and np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5)
    rawchunks={c['chunk_id']:c for r in lines(SRC/'chunks.jsonl') for c in r['chunks']}
    rawchunks.update({r['chunk_id']:r for r in lines(SRC/'semantic-chunks.jsonl')})
    assert len(rawchunks)==1089 and len(docs)==110
    assert len({r['chunk_id'] for r in inputs})==1089
    documents={}
    for doc in docs:
        did=doc['doc_id'];prior=index['documents'][did];f=bundle['features'][did]
        values={FIELDS[k]:v for k,v in prior['metadata'].items() if prior['metadata_statuses'][k]=='extracted'}
        statuses={FIELDS[k]:v for k,v in prior['metadata_statuses'].items()}
        for k,v in prior['date_metadata']['fields'].items():
            statuses[FIELDS[k]]=v['status']
            if v['status']=='extracted':values[FIELDS[k]]=v['value']
        feature_text={k:'\n'.join(x['text'] for x in vv) for k,vv in f.items()}
        meta_text=' '.join(f'{k} {v}' for k,v in prior['metadata'].items())
        documents[did]={'doc_id':did,'kind':'document','source_sha256':doc['source']['sha256'],
          'source_path':doc['source']['relative_path'],'format':doc['source']['format'],
          'title':feature_text['title'],'summary':doc['summary'],'metadata_text':meta_text,
          **{k:feature_text[k] for k in ['job','role','system','client']},'identifier_text':feature_text['identifier'],
          'metadata':values,'metadata_statuses':statuses,'feature_evidence':f,'original':doc,
          'identifiers':identifiers(feature_text['identifier']+' '+doc['source']['file_name']),
          'concepts':concepts(meta_text+' '+feature_text['job'],index)}
    chunks=[]
    for pos,inp in enumerate(inputs):
        vm=vmap[pos];vid=inp['vector_id'];cid=inp['chunk_id'];did=inp['doc_id']
        assert vid==pos==vm['vector_id'] and cid==vm['chunk_id'] and did==vm['doc_id']
        assert sha_text(inp['text'])==inp['embedding_text_sha256']==vm['embedding_text_sha256']
        c=rawchunks[cid];base=documents[did]
        row={k:copy.deepcopy(v) for k,v in base.items() if k not in ['original','summary']}
        context=c.get('context_header','')
        if base['metadata'].get('document_type')=='실행 로그':context+=' | '+base['job']+' | '+base['system']
        row.update({'chunk_id':cid,'kind':inp['kind'],'vector_id':vid,'body':c['text'],'context':context,
          'table_header':c.get('table_header_text',''),'source_refs':inp['source_refs'],
          'embedding_text_sha256':inp['embedding_text_sha256'],'embedding':vectors[vid].tolist(),
          'original':{'chunk':c,'embedding_input':inp}})
        row['concepts']=concepts('\n'.join([row['body'],row['context'],row['table_header']]),index)
        row['identifiers']=identifiers('\n'.join([row['body'],row['identifier_text'],row['title']]))
        chunks.append(row)
    write(OUT/'document-mapping.json',mapping());write(OUT/'chunk-mapping.json',mapping(True))
    for name,rows,idx in [('documents',list(documents.values()),DOC_INDEX),('chunks',chunks,CHUNK_INDEX)]:
        with (OUT/f'{name}.ndjson').open('w') as f:
            for r in rows:
                f.write(json.dumps({'create':{'_index':idx,'_id':r.get('chunk_id',r['doc_id'])}})+'\n')
                f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
    write(OUT/'manifest.json',{'source_directory':str(SRC),'source_hashes':frozen,
      'document_index':DOC_INDEX,'chunk_index':CHUNK_INDEX,'documents':110,'chunks':1089,
      'source_chunks':1072,'semantic_chunks':17,'vector_dims':1024,'vector_index_type':'flat',
      'reason':'preserve exact full-precision retrieval for the small existing corpus; no quantization change',
      'model_calls':0,'paid_calls':0,'handoff_other_changes_applied':False,
      'files':{f:sha(OUT/f) for f in ['documents.ndjson','chunks.ndjson','document-mapping.json','chunk-mapping.json']}})
    for rel,h in frozen.items():assert sha(SRC/rel)==h
    print(json.dumps({'documents':110,'chunks':1089,'model_calls':0}))
def sha_text(s):return hashlib.sha256(s.encode()).hexdigest()
if __name__=='__main__':main()
