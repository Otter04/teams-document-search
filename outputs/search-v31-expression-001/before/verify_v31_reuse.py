"""Read-only source equality and index count verification; never writes to Elasticsearch."""
import argparse,json,urllib.request,hashlib
from pathlib import Path

def api(path,body=None):
 req=urllib.request.Request('http://127.0.0.1:9200'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=60) as r:return json.load(r)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--data',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();counts={};verified={};hashes={}
 for name,idx in [('documents','rag-search-documents-v003'),('chunks','rag-search-chunks-v003')]:
  p=a.data/(name+'.ndjson');raw=p.read_bytes();hashes[p.name]=hashlib.sha256(raw).hexdigest();lines=raw.decode().splitlines();total=0
  for i in range(0,len(lines),200):
   batch=lines[i:i+200];ids=[json.loads(s)['create']['_id'] for s in batch[::2]];expected=[json.loads(s) for s in batch[1::2]]
   got=api('/'+idx+'/_mget',{'ids':ids})['docs'];assert all(x.get('found') for x in got)
   assert [x['_source'] for x in got]==expected,'stored index source changed';total+=len(got)
  verified[name]=total;counts[idx]=api('/'+idx+'/_count')['count'];assert counts[idx]==total
 for idx,want in [('rag-search-documents-v001',110),('rag-search-chunks-v001',1089),('rag-search-documents-v002',155),('rag-search-chunks-v002',1244)]:
  counts[idx]=api('/'+idx+'/_count')['count'];assert counts[idx]==want
 result={'counts':counts,'exact_source_comparison':verified,'reference_hashes':hashes,'index_writes':False}
 a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
