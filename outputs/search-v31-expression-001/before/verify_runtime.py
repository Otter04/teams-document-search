"""Read-only final service checks; no model generation or index mutation."""
import hashlib,json,subprocess,urllib.request
from pathlib import Path
P=Path(__file__).resolve().parent
def get(url):
    with urllib.request.urlopen(url,timeout=10) as r:return json.load(r)
health=get('http://127.0.0.1:8020/health');assert health['ready']
assert health['defaults']['filter_mode']=='B' and health['defaults']['reranker']=='R1'
counts={name:get('http://127.0.0.1:9200/'+name+'/_count')['count'] for name in
 ['rag-documents','rag-chunks','rag-search-documents-v001','rag-search-chunks-v001']}
assert list(counts.values())==[110,1089,110,1089]
aliases=get('http://127.0.0.1:9200/_alias/rag-documents,rag-chunks')
assert set(aliases)=={'rag-documents-v001','rag-chunks-v001'}
model=get('http://127.0.0.1:8001/v1/models')['data'][0]['id']
status=subprocess.check_output(['docker','ps','--filter','name=rag-','--format','{{.Names}}: {{.Status}}'],text=True)
listen=subprocess.check_output(['ss','-ltn'],text=True)
port_lines=[s for s in listen.splitlines() if ':8020 ' in s]
assert port_lines and all('127.0.0.1:8020' in s for s in port_lines)
result={'health':health,'counts':counts,'old_aliases_unchanged':True,'qwen_model_id':model,
 'container_status':status,'api_loopback':port_lines,
 'code_hashes':{n:hashlib.sha256((P/n).read_bytes()).hexdigest() for n in ['query.py','engine.py','service.py','index.html','selected.json']}}
(P/'evaluation/runtime-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps({'ready':True,'counts':counts,'old_aliases_unchanged':True,'api_loopback':True}))
