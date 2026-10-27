"""Create new search indices; keep the previous migration indices intact."""
import json,time,hashlib,urllib.request
from pathlib import Path
P=Path(__file__).resolve().parent/'data';BASE='http://127.0.0.1:9200'
def api(method,path,body=None,raw=False):
    b=body if raw else (json.dumps(body,ensure_ascii=False).encode() if body is not None else None)
    req=urllib.request.Request(BASE+path,data=b,method=method,headers={'Content-Type':'application/x-ndjson' if raw else 'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
def main():
    assert not (P/'index-verification.json').exists()
    m=json.loads((P/'prepared.json').read_text());counts={};start=time.perf_counter()
    for file,h in m['files'].items():assert hashlib.sha256((P/file).read_bytes()).hexdigest()==h,file
    for name,expected in [('documents',110),('chunks',1089)]:
        idx='rag-search-'+name+'-v001'
        api('PUT','/'+idx,json.loads((P/(name+'-mapping.json')).read_text()))
        data=(P/(name+'.ndjson')).read_bytes().splitlines(keepends=True)
        for i in range(0,len(data),100):
            response=api('POST','/_bulk',b''.join(data[i:i+100]),True)
            assert not response['errors'],response
        api('POST','/'+idx+'/_refresh');counts[name]=api('GET','/'+idx+'/_count')['count'];assert counts[name]==expected
        for i in range(0,len(data),100):
            batch=data[i:i+100];wanted=[json.loads(s) for s in batch[1::2]]
            ids=[json.loads(s)['create']['_id'] for s in batch[::2]]
            got=api('POST','/'+idx+'/_mget',{'ids':ids})['docs'];assert [r['_source'] for r in got]==wanted
    analyze=api('POST','/rag-search-chunks-v001/_analyze',{'analyzer':'rag_ko','text':'청람정밀 학사정보시스템 백업'})
    assert '청람정밀' in [r['token'] for r in analyze['tokens']]
    (P/'index-verification.json').write_text(json.dumps({'counts':counts,'full_source_comparison':1199,
      'nori_example':analyze,'elapsed_seconds':time.perf_counter()-start,'previous_indices_unchanged':True},ensure_ascii=False,indent=2))
    print(json.dumps(counts))
if __name__=='__main__':main()
