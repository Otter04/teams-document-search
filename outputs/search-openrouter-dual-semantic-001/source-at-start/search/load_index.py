"""Resumable isolated v006-token-nori-only Elasticsearch load. Never deletes or overwrites a document."""
import argparse,hashlib,json,time,urllib.request,urllib.error
from pathlib import Path
def api(method,path,body=None,raw=False):
 data=body if raw else json.dumps(body,ensure_ascii=False).encode() if body is not None else None
 req=urllib.request.Request('http://127.0.0.1:19200'+path,data=data,method=method,headers={'Content-Type':'application/x-ndjson' if raw else 'application/json'})
 with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
def maybe(path):
 try:return api('GET',path)
 except urllib.error.HTTPError as e:
  if e.code==404:return None
  raise
def settings_value(x):
 if isinstance(x,dict):return {k:settings_value(v) for k,v in x.items()}
 if isinstance(x,list):return [settings_value(v) for v in x]
 if isinstance(x,bool):return str(x).lower()
 if isinstance(x,(int,float)):return str(x)
 return x
def main():
 ap=argparse.ArgumentParser();ap.add_argument('data',type=Path);a=ap.parse_args();p=a.data;m=json.loads((p/'prepared.json').read_text());start=time.perf_counter()
 assert m['documents']==195 and m['document_index']=='rag-search-documents-v006-token-nori' and m['chunk_index']=='rag-search-chunks-v006-token-nori'
 for file,h in m['files'].items():assert hashlib.sha256((p/file).read_bytes()).hexdigest()==h,file
 before={name:api('GET','/'+name+'/_count')['count'] for name in api('GET','/_cat/indices?format=json') for name in [name['index']] if name.startswith('rag-') and name not in [m['document_index'],m['chunk_index']]}
 counts={};verified=0
 for name,idx in [('documents',m['document_index']),('chunks',m['chunk_index'])]:
  mapping=json.loads((p/(name+'-mapping.json')).read_text());existing=maybe('/'+idx)
  if existing is None:api('PUT','/'+idx,mapping)
  else:
   assert existing[idx]['mappings']==mapping['mappings'],'Existing candidate mapping differs'
   actual=existing[idx]['settings']['index']
   for key in ['analysis','similarity']:assert settings_value(actual[key])==settings_value(mapping['settings'][key]),key
  data=(p/(name+'.ndjson')).read_text().splitlines();assert len(data)==m[name]*2
  for i in range(0,len(data),100):
   batch=data[i:i+100];actions=[json.loads(x)['create'] for x in batch[::2]];wanted=[json.loads(x) for x in batch[1::2]]
   assert all(x['_index']==idx for x in actions)
   got=api('POST','/'+idx+'/_mget',{'ids':[x['_id'] for x in actions]})['docs'];missing=[]
   for j,(g,w) in enumerate(zip(got,wanted)):
    if g.get('found'):assert g['_source']==w,'Existing candidate document differs: '+g['_id']
    else:missing.extend(batch[j*2:j*2+2])
   if missing:
    result=api('POST','/_bulk',('\n'.join(missing)+'\n').encode(),True);assert not result['errors'],result
   got=api('POST','/'+idx+'/_mget',{'ids':[x['_id'] for x in actions]})['docs']
   assert [x['_source'] for x in got]==wanted;verified+=len(wanted)
  api('POST','/'+idx+'/_refresh');counts[name]=api('GET','/'+idx+'/_count')['count'];assert counts[name]==m[name]
 tokens=api('POST','/'+m['chunk_index']+'/_analyze',{'analyzer':'rag_ko','text':'청람정밀 학사정보시스템 백업'})
 assert not any(k in json.dumps(mapping) for k in ['user_dictionary','concepts'])
 after={name:api('GET','/'+name+'/_count')['count'] for name in before};assert before==after
 result={'counts':counts,'full_source_comparison':verified,'nori_example':tokens,'old_indices_counts_before':before,'old_indices_counts_after':after,'elapsed_seconds':time.perf_counter()-start}
 (Path(__file__).resolve().parents[2]/'outputs/search-openrouter-local-001/index-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(counts))
if __name__=='__main__':main()
