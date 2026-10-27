"""Record the final Orin state after cleanup, without loading or invoking any model."""
import hashlib,json,subprocess,urllib.request
from pathlib import Path
from ingest import ROOT,read,write,api
def main():
    old=Path('/media/sdcard/rag-runtime/indexing-110-semantic-vector-001/final-index')
    manifest=read(ROOT/'manifest.json');verified=0;postcopy=[]
    for rel,h in manifest['source_hashes'].items():
        p=old/rel
        if rel in ['index.json','vectors.faiss']:
            assert not p.exists();continue
        assert p.is_file(),str(p)
        actual=hashlib.sha256(p.read_bytes()).hexdigest()
        if rel=='orin-copy-verification.json' and actual!=h:
            postcopy.append({'file':rel,'mac_sha256':h,'orin_sha256':actual,
              'reason':'historical transfer receipt was finalized on Mac after that package was copied; retained unchanged'})
            continue
        assert actual==h,rel
        verified+=1
    health=api('GET','/_cluster/health');assert health['status']=='green'
    assert api('GET','/rag-documents/_count')['count']==110
    assert api('GET','/rag-chunks/_count')['count']==1089
    with urllib.request.urlopen('http://127.0.0.1:8001/v1/models',timeout=10) as r:models=json.load(r)
    assert models['data'][0]['max_model_len']==49152
    info=json.loads(subprocess.check_output(['docker','inspect','rag-elasticsearch']))[0]
    assert info['HostConfig']['Memory']==4*1024**3
    assert info['HostConfig']['Runtime']=='runc'
    assert info['HostConfig']['PortBindings']['9200/tcp']==[{'HostIp':'127.0.0.1','HostPort':'9200'}]
    for oldcontainer in read(ROOT/'cleanup-result.json')['containers']:
        assert subprocess.run(['docker','container','inspect',oldcontainer['id']],capture_output=True).returncode!=0
    state={'preserved_legacy_artifacts_hash_verified':verified,'historical_postcopy_receipt_difference':postcopy,'retired_index_files_removed':2,
       'health':health,'aliases':api('GET','/_alias/rag-documents,rag-chunks'),
       'qwen_server_models':models,'elasticsearch_container':{'id':info['Id'],'image':info['Image'],
           'memory_limit_bytes':info['HostConfig']['Memory'],'runtime':info['HostConfig']['Runtime'],
           'ports':info['HostConfig']['PortBindings'],'mounts':info['Mounts']},
       'resources':subprocess.check_output(['docker','stats','--no-stream','--format','{{.Name}} {{.MemUsage}}','rag-elasticsearch','rag-qwen36'],text=True),
       'free_memory':subprocess.check_output(['free','-m'],text=True),'model_inference_calls':0}
    write(ROOT/'final-state.json',state);print(json.dumps({'preserved_artifact_hashes':verified,'health':health['status'],'qwen_alive':True}))
if __name__=='__main__':main()
