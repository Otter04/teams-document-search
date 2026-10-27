"""Export new chunks/vectors with frozen v003 document metadata and ES mappings."""
import copy
import importlib.util
import json
import shutil
from pathlib import Path
import numpy as np
from prepare import ROOT, OUT, BASE, rows, sha, write

INDEX_SUFFIX = 'v004-rechunk'

def main():
    source = OUT/'prepared'; dest = OUT/'search-data'
    assert not (dest/'prepared.json').exists(), 'Preserve completed export'
    dest.mkdir(exist_ok=True)
    old = ROOT/'outputs/indexing-v31-001/search-data'
    manifest = json.loads((source/'embedding-manifest.json').read_text())
    assert manifest['model_fingerprint'] == json.loads((BASE/'embedding-manifest.json').read_text())['model_fingerprint']
    assert manifest['input_sha256'] == sha(source/'embedding-inputs.jsonl')
    assert manifest['vectors_sha256'] == sha(source/'vectors.npy')
    local_budget = json.loads((source/'local-token-budget.json').read_text())
    remote_budget = json.loads((source/'token-budget.json').read_text())
    assert local_budget['counts'] == remote_budget['counts'], 'Local/remote tokenizer disagreement'
    assert max(remote_budget['counts']) <= 600
    inputs = rows(source/'embedding-inputs.jsonl')
    vectors = np.load(source/'vectors.npy', allow_pickle=False)
    assert vectors.shape == (len(inputs), 1024) and np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    spec = importlib.util.spec_from_file_location('frozen_es_export', ROOT/'deploy/elasticsearch/export.py')
    X = importlib.util.module_from_spec(spec); spec.loader.exec_module(X)
    index = json.loads((BASE/'index.json').read_text())
    documents = json.loads((old/'documents.json').read_text())
    original_documents = copy.deepcopy(documents)
    raw = {c['chunk_id']:c for r in rows(source/'chunks.jsonl') for c in r['chunks']}
    raw.update({c['chunk_id']:c for c in rows(source/'semantic-chunks.jsonl')})
    assert set(raw) == {i['chunk_id'] for i in inputs}
    for did, doc in documents.items():
        doc['original']['chunk_ids'] = [i['chunk_id'] for i in inputs if i['doc_id'] == did]
        preserved = copy.deepcopy(doc)
        preserved['original']['chunk_ids'] = original_documents[did]['original']['chunk_ids']
        assert preserved == original_documents[did], 'Only chunk links may change in document metadata'
    with (dest/'chunks.ndjson').open('w') as stream:
        for pos, inp in enumerate(inputs):
            assert inp['vector_id'] == pos
            c = raw[inp['chunk_id']]; base = documents[inp['doc_id']]
            row = {k:copy.deepcopy(v) for k,v in base.items() if k not in ['original','summary','version_number','version_evidence']}
            context = c['context_header']
            if base['metadata'].get('document_type') == '실행 로그':
                context += ' | '+base['job']+' | '+base['system']
            row.update(chunk_id=inp['chunk_id'], kind=inp['kind'], vector_id=pos,
                       body=c['text'], context=context, table_header=c.get('table_header_text',''),
                       source_refs=inp['source_refs'], embedding_text_sha256=inp['embedding_text_sha256'],
                       embedding=vectors[pos].tolist(), original={'chunk':c,'embedding_input':inp})
            row['concepts'] = X.concepts('\n'.join([row['body'],row['context'],row['table_header']]), index)
            row['identifiers'] = X.identifiers('\n'.join([row['body'],row['identifier_text'],row['title']]))
            stream.write(json.dumps({'create':{'_index':'rag-search-chunks-'+INDEX_SUFFIX,'_id':row['chunk_id']}})+'\n')
            stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    with (dest/'documents.ndjson').open('w') as stream:
        for did, row in documents.items():
            stream.write(json.dumps({'create':{'_index':'rag-search-documents-'+INDEX_SUFFIX,'_id':did}})+'\n')
            stream.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    write(dest/'documents.json', documents)
    for name in ['documents-mapping.json','chunks-mapping.json','blocks.json','reference.json','nori-dictionary.json','family-review.json']:
        shutil.copyfile(old/name, dest/name)
    shutil.copyfile(source/'embedding-manifest.json',dest/'embedding-identity.json')
    result = {'documents':len(documents),'chunks':len(inputs),
              'document_index':'rag-search-documents-'+INDEX_SUFFIX,'chunk_index':'rag-search-chunks-'+INDEX_SUFFIX,
              'document_metadata_frozen':True,'source_blocks_frozen':True,'mapping_frozen':True,'gold_read':False,
              'files':{p.name:sha(p) for p in dest.iterdir() if p.is_file()}}
    write(dest/'prepared.json', result)
    print(json.dumps({k:v for k,v in result.items() if k!='files'}))

if __name__ == '__main__':
    main()
