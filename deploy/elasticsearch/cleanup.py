"""Orin-only, explicit allowlist cleanup after verified migration. Preserve source evidence."""
import hashlib,json,subprocess,sys
from pathlib import Path
from ingest import ROOT,read,write,api
OLD=Path('/media/sdcard/rag-runtime/indexing-110-semantic-vector-001')
STOPPED=['rag-bge-m3-eval-001','rag-bge-m3-index-001',
 'rag-qwen36-cache8-mmoff-failed-20261020','rag-qwen36-cache8-mm-failed-20261020',
 'rag-qwen36-49152-autocache-failed-20261020','rag-qwen36-16384-20261020']
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert read(ROOT/'verification.json')['all_original_fields_and_vectors_equal']
    assert read(ROOT/'persistence-and-filters.json')['read_back_equal_after_restart']==1199
    assert api('GET','/rag-documents/_count')['count']==110
    assert api('GET','/rag-chunks/_count')['count']==1089
    m=read(ROOT/'manifest.json');files=[]
    for name in ['index.json','vectors.faiss']:
        p=OLD/'final-index'/name
        assert p.is_file() and not p.is_symlink() and digest(p)==m['source_hashes'][name]
        files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p),
          'reason':'retired Python BM25/FAISS backend; immutable Mac baseline preserved'})
    # Only remove exact duplicates with an intact canonical evidence file in final-index.
    for p in sorted(OLD.rglob('*')):
        if not p.is_file() or p.is_symlink() or 'final-index' in p.relative_to(OLD).parts:continue
        rel=p.relative_to(OLD);canonical=OLD/'final-index'/rel
        if canonical.is_file() and not canonical.is_symlink() and digest(p)==digest(canonical):
            files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p),
              'reason':'byte-identical duplicate','retained_path':str(canonical)})
    for name in ['documents.ndjson','chunks.ndjson']:
        p=ROOT/name;assert digest(p)==m['files'][name]
        files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p),
          'reason':'temporary bulk transfer; verified Elasticsearch data and matching Mac export retained'})
    containers=[]
    archive=ROOT/'retired-container-records';archive.mkdir(exist_ok=True)
    for name in STOPPED:
        info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
        assert info['State']['Status']=='exited' and not info['State']['Running'],name
        logs=subprocess.run(['docker','logs',name],capture_output=True,check=True)
        (archive/(name+'.log')).write_bytes(logs.stdout+b'\n[stderr]\n'+logs.stderr)
        evidence={'name':name,'id':info['Id'],'state':info['State'],'image':info['Config']['Image'],
          'mounts':info['Mounts'],'command':info['Config']['Cmd']}
        write(archive/(name+'.json'),evidence);containers.append(evidence)
    plan={'files':files,'file_bytes':sum(f['bytes'] for f in files),'containers':containers,
      'never_delete':['model weights','canonical raw responses','parsed blocks','review records','vectors.npy','new Elasticsearch data'],
      'source_archival_note':'Mac baseline remains immutable for evaluation reproducibility',
      'executed':False}
    write(ROOT/'cleanup-plan.json',plan)
    if '--execute' not in sys.argv:
        print(json.dumps({'files':len(files),'file_bytes':plan['file_bytes'],'containers':len(containers)}));return
    # Re-check every hash immediately before deletion. No recursive directory removal or prune.
    for item in files:
        p=Path(item['path']);assert not p.is_symlink() and digest(p)==item['sha256']
        if item.get('retained_path'):assert digest(Path(item['retained_path']))==item['sha256']
        p.unlink()
    for info in containers:
        subprocess.run(['docker','rm',info['id']],check=True,capture_output=True)
    assert all(not Path(f['path']).exists() for f in files)
    plan['executed']=True;write(ROOT/'cleanup-result.json',plan)
    (OLD/'BACKEND_MIGRATED.md').write_text('2026-10-20: Active indexing backend is Elasticsearch with Nori.\n'
      'The retired final-index/index.json and vectors.faiss and exact duplicate work files were removed after verification.\n'
      'Canonical parsed data, raw responses, review records and vectors.npy remain in final-index/.\n'
      'The immutable complete baseline remains on the Mac. New index: ../elasticsearch-001/.\n')
    print(json.dumps({'deleted_files':len(files),'deleted_file_bytes':plan['file_bytes'],'removed_containers':len(containers)}))
if __name__=='__main__':main()
