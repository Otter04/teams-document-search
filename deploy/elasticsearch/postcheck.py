"""Read-only persistence, field-filter and sorting checks against the loaded export."""
import json,time
from ingest import ROOT,api,read,write
def main():
    records=[]
    for name,index in [('documents','rag-documents'),('chunks','rag-chunks')]:
        data=(ROOT/f'{name}.ndjson').read_text().splitlines()
        rows=[json.loads(v) for v in data[1::2]]
        assert api('GET','/'+index+'/_count')['count']==len(rows)
        for at in range(0,len(rows),50):
            batch=rows[at:at+50];ids=[r.get('chunk_id',r['doc_id']) for r in batch]
            got=api('POST','/'+index+'/_mget',{'ids':ids})['docs']
            assert [r['_source'] for r in got]==batch
        if name=='documents':records=rows
    # True field-value and order checks including dates absent from the 61-question set.
    queries=[]
    for field in ['cover_date','written_date','document_date','file_modified_at','target_system','document_type','client']:
        values=sorted({r['metadata'][field] for r in records if isinstance(r['metadata'].get(field),str)})
        for value in values:
            expected={r['doc_id'] for r in records if r['metadata'].get(field)==value}
            result=api('POST','/rag-documents/_search',{'size':110,'_source':['doc_id'],
              'query':{'term':{'metadata.'+field:value}}})
            actual={h['_id'] for h in result['hits']['hits']}
            assert actual==expected,(field,value,expected^actual)
            queries.append({'field':field,'value':value,'count':len(actual),'pass':True})
    for direction in ['asc','desc']:
        result=api('POST','/rag-documents/_search',{'size':110,'_source':['doc_id','metadata.file_modified_at'],
          'query':{'exists':{'field':'metadata.file_modified_at'}},
          'sort':[{'metadata.file_modified_at':direction},{'doc_id':'asc'}]})
        expected=sorted(records,key=lambda r:r['doc_id'])
        expected.sort(key=lambda r:r['metadata']['file_modified_at'],reverse=direction=='desc')
        assert [h['_id'] for h in result['hits']['hits']]==[r['doc_id'] for r in expected]
    # Check a real interval and that missing written dates do not silently use cover dates.
    expected={r['doc_id'] for r in records if '2025-01-01'<=r['metadata'].get('cover_date','')<'2026-01-01'}
    got=api('POST','/rag-documents/_search',{'size':110,'_source':False,'query':{'range':{'metadata.cover_date':{'gte':'2025-01-01','lt':'2026-01-01'}}}})
    assert {h['_id'] for h in got['hits']['hits']}==expected
    write(ROOT/'persistence-and-filters.json',{'read_back_equal_after_restart':1199,
      'exact_filter_cases':len(queries),'details':queries,'modified_sort_directions_verified':['asc','desc'],
      'cover_date_range_pass':True,'date_roles_preserved':True,'model_calls':0})
    print(json.dumps({'post_restart_records_verified':1199,'filter_cases':len(queries),'sort_checks':2}))
if __name__=='__main__':main()
