"""Run on Orin: bulk create, read back every record, then atomically publish aliases."""
import hashlib,json,time,urllib.request,urllib.error,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE='http://127.0.0.1:9200'
def read(p):return json.loads(Path(p).read_text())
def write(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def api(method,path,body=None,raw=False):
    data=body if raw else (json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
    req=urllib.request.Request(BASE+path,data=data,method=method,headers={'Content-Type':'application/x-ndjson' if raw else 'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
    except urllib.error.HTTPError as e:raise RuntimeError(f'{method} {path}: {e.code} {e.read().decode()}') from e
def main():
    assert not (ROOT/'verification.json').exists(),'This migration is already verified'
    manifest=read(ROOT/'manifest.json');start=time.perf_counter()
    for f,h in manifest['files'].items():assert hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==h
    server=api('GET','/');assert server['version']['number']=='8.19.23'
    plugins=api('GET','/_cat/plugins?format=json');assert any(p['component']=='analysis-nori' for p in plugins)
    counts={};hashes={};bulk_times={};verified=0
    for name,idx,expected in [('documents',manifest['document_index'],110),('chunks',manifest['chunk_index'],1089)]:
        # Create-only: never overwrite an existing index. Resume requires explicit inspection.
        mapping=read(ROOT/('document-mapping.json' if name=='documents' else 'chunk-mapping.json'))
        verify_existing='--verify-existing' in sys.argv
        if verify_existing:
            assert api('GET','/'+idx+'/_mapping')[idx]['mappings']==mapping['mappings']
        else:api('PUT','/'+idx,mapping)
        data=(ROOT/f'{name}.ndjson').read_bytes().splitlines(keepends=True);assert len(data)==2*expected
        t=time.perf_counter();receipts=[]
        for at in ([] if verify_existing else range(0,len(data),100)):
            response=api('POST','/_bulk',b''.join(data[at:at+100]),raw=True)
            receipts.extend(response['items'])
            if response['errors']:
                write(ROOT/f'{name}-bulk-errors.json',response)
                raise RuntimeError('Bulk indexing failed; partial index and original data preserved')
        bulk_times[name]=None if verify_existing else time.perf_counter()-t
        if verify_existing:
            receipts=read(ROOT/f'{name}-bulk-receipts.json')
            assert len(receipts)==expected and all(r['create']['status']==201 for r in receipts)
        else:write(ROOT/f'{name}-bulk-receipts.json',receipts)
        api('POST','/'+idx+'/_refresh')
        counts[name]=api('GET','/'+idx+'/_count')['count'];assert counts[name]==expected
        # Compare original text, references, statuses, dates and all vector floats, not only counts.
        for at in range(0,len(data),100):
            batch=data[at:at+100];payloads=[json.loads(v) for v in batch[1::2]]
            ids=[json.loads(v)['create']['_id'] for v in batch[::2]]
            returned=api('POST','/'+idx+'/_mget',{'ids':ids})['docs']
            for identity,original,got in zip(ids,payloads,returned):
                assert got['found'] and got['_id']==identity and got['_source']==original,identity
                verified+=1
        hashes[name]=hashlib.sha256((ROOT/f'{name}.ndjson').read_bytes()).hexdigest()
    idx=manifest['chunk_index']
    analyze=api('POST','/'+idx+'/_analyze',{'analyzer':'rag_ko','text':'문서를 검색합니다. 데이터베이스 백업 작업'})
    terms=[v['token'] for v in analyze['tokens']]
    assert '문서' in terms and '검색' in terms and '백업' in terms
    write(ROOT/'nori-example.json',analyze)
    sample=api('POST','/'+idx+'/_search',{'size':1,'query':{'match':{'body':'백업'}}})['hits']['hits'][0]
    explain=api('POST','/'+idx+'/_explain/'+sample['_id'],{'query':{'match':{'body':'백업'}}})
    similarity=api('GET','/'+idx+'/_settings')[idx]['settings']['index']['similarity']['rag_bm25']
    assert similarity['type']=='BM25' and float(similarity['k1'])==1.2 and float(similarity['b'])==0.75
    assert 'k1, term saturation parameter' in json.dumps(explain) and 'b, length normalization parameter' in json.dumps(explain)
    write(ROOT/'bm25-explanation.json',explain)
    # A real vector search against the Elasticsearch index; no embedding model is invoked.
    first=json.loads((ROOT/'chunks.ndjson').read_text().splitlines()[1])
    knn=api('POST','/'+idx+'/_search',{'size':1,'_source':['chunk_id','doc_id'],
      'knn':{'field':'embedding','query_vector':first['embedding'],'k':1,'num_candidates':1100}})
    assert abs(knn['hits']['hits'][0]['_score']-1)<1e-5
    write(ROOT/'vector-smoke.json',knn)
    api('POST','/_aliases',{'actions':[
      {'add':{'index':manifest['document_index'],'alias':'rag-documents','is_write_index':True}},
      {'add':{'index':idx,'alias':'rag-chunks','is_write_index':True}}]})
    health=api('GET','/_cluster/health?wait_for_status=green&timeout=30s');assert health['status']=='green'
    write(ROOT/'verification.json',{'server_version':server['version'],'plugins':plugins,'health':health,
      'counts':counts,'fully_read_back_records':verified,'all_original_fields_and_vectors_equal':True,
      'bulk_seconds':bulk_times,'total_seconds':time.perf_counter()-start,'export_hashes':hashes,
      'nori_tokens':terms,'bm25_explain_verified':True,'vector_self_similarity_verified':True,
      'model_calls':0,'paid_calls':0,'legacy_index_deleted':False})
    print(json.dumps({'counts':counts,'verified_records':verified,'seconds':time.perf_counter()-start}))
if __name__=='__main__':main()
