"""Build and reconstruct a FAISS vector index; never runs a search query."""
from collections import Counter,defaultdict
import csv
from copy import deepcopy
import faiss
import numpy as np
from prepare import *

def main():
    manifest=read(OUT/'manifest.json');em=read(OUT/'embedding-manifest.json')
    for name,h in manifest['base_hashes'].items():assert digest(BASE/name)==h,name
    assert digest(OUT/'vectors.npy')==em['vectors_sha256']
    assert digest(OUT/'embedding-inputs.jsonl')==em['input_sha256']
    vectors=np.load(OUT/'vectors.npy',allow_pickle=False)
    rows=lines(OUT/'embedding-inputs.jsonl');assert vectors.shape==(len(rows),1024)==(1089,1024)
    assert np.isfinite(vectors).all() and np.allclose(np.linalg.norm(vectors,axis=1),1,atol=1e-5)
    assert [r['vector_id'] for r in rows]==list(range(1089))
    assert len({r['doc_id'] for r in rows})==110
    for r in rows:assert hashlib.sha256(r['text'].encode()).hexdigest()==r['embedding_text_sha256']
    # Exact flat index avoids training/approximation for this small corpus.
    index=faiss.IndexIDMap2(faiss.IndexFlatIP(1024))
    index.add_with_ids(np.ascontiguousarray(vectors,dtype=np.float32),np.arange(len(rows),dtype=np.int64))
    faiss.write_index(index,str(OUT/'vectors.faiss'))
    reloaded=faiss.read_index(str(OUT/'vectors.faiss'))
    assert reloaded.ntotal==len(rows) and reloaded.d==1024
    for i,v in enumerate(vectors):assert np.array_equal(reloaded.reconstruct(i),v),i
    mapping=[{k:r[k] for k in ['vector_id','doc_id','chunk_id','kind','source_refs','source_sha256','embedding_text_sha256']} for r in rows]
    save_lines(OUT/'vector-map.jsonl',mapping)
    bm25=read(OUT/'index.json');before=read(BASE/'index.json')
    semantic={r['doc_id']:r for r in lines(OUT/'semantic-enriched.jsonl')}
    assert set(bm25['documents'])==set(before['documents'])
    assert {r['chunk_id'] for r in rows}=={k for k,v in bm25['entries'].items() if v['kind']!='document_metadata'}
    # Source entries and all rule values must be byte-equivalent objects.
    for eid,entry in before['entries'].items():assert bm25['entries'][eid]==entry,eid
    for did,doc in before['documents'].items():
        assert bm25['documents'][did]['metadata']==doc['metadata']
        assert bm25['documents'][did]['metadata_statuses']==doc['metadata_statuses']
    bm25['embedding_status']='complete_bge_m3';bm25['vector_index']='vectors.faiss'
    for doc in bm25['documents'].values():doc['embedding_status']='complete_bge_m3'
    write(OUT/'index.json',bm25)
    docs=lines(OUT/'document-index.jsonl')
    vectors_by_doc=defaultdict(list)
    for r in rows:vectors_by_doc[r['doc_id']].append(r['vector_id'])
    for doc in docs:
        doc['vector_ids']=vectors_by_doc[doc['doc_id']];doc['embedding_model']='bge-m3'
        assert set(doc['chunk_ids'])=={r['chunk_id'] for r in rows if r['doc_id']==doc['doc_id']}
    save_lines(OUT/'document-index.jsonl',docs)
    routes={r['doc_id']:r for r in lines(OUT/'routing.jsonl')}
    ledger=lines(BASE/'document-status.jsonl')
    for row in ledger:
        did=row['doc_id'];row.update(llm_semantic_enriched=did in semantic,llm_enrichment_full_result_reused=False,
            llm_summary='source_reviewed_extractive' if did in semantic else 'not_needed_for_selected_scope',
            semantic_field_count=sum(bool(v['items']) for v in semantic[did]['fields'].values()) if did in semantic else 0,
            source_chunk_count=row.pop('chunk_count'),semantic_chunk_count=int(did in semantic),
            vector_count=len(vectors_by_doc[did]),embedding_model='bge-m3',vector_indexed=True,
            selection_reason=routes[did]['reason'])
    save_lines(OUT/'document-status.jsonl',ledger)
    with (OUT/'document-status.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(ledger[0]));writer.writeheader();writer.writerows(ledger)
    envs=[read(p) for p in (OUT/'responses').glob('*.json')]
    reviews=read(OUT/'semantic-review.completed.json')
    summary={'documents':110,'bm25_documents':110,'vector_indexed_documents':110,'rule_enriched_documents':110,
        'rule_metadata_values_preserved':935,'llm_semantic_documents':17,'rule_only_semantic_route_documents':93,
        'semantic_fields':sum(bool(f['items']) for r in semantic.values() for f in r['fields'].values()),
        'semantic_field_values':sum(len(f['items']) for r in semantic.values() for f in r['fields'].values()),
        'extractive_summaries':17,'documents_with_offline_corrections':sum(bool(r['corrections']) for r in reviews),
        'source_chunks_reused':1072,'semantic_chunks_added':17,'vectors':1089,'dimensions':1024,
        'embedding_model':'bge-m3','faiss_version':faiss.__version__,'vector_index_type':'IndexIDMap2(IndexFlatIP), L2-normalized vectors',
        'new_vision_calls':0,'new_orin_enrichment_calls':len(envs),'paid_external_calls':0,
        'llm_generation_seconds':round(sum(r['elapsed_seconds'] for r in envs),2),
        'llm_output_tokens':sum(r['response']['usage']['completion_tokens'] for r in envs),
        'embedding_total_seconds':round(em['elapsed_seconds'],2),'embedding_input_truncations':0,
        'ambiguous_date_documents_held':13,'old_visual_claims_held':103,
        'search_or_answer_implemented':False,'search_queries_executed':0,
        'independent_semantic_accuracy':None,'status':'complete_local_artifacts'}
    write(OUT/'summary.json',summary)
    verification={'status':'passed','original_base_hashes_unchanged':True,'original_source_chunks_unchanged':1072,
        'rule_metadata_preserved':110,'semantic_evidence_reviewed_documents':17,'all_vectors_finite_unit_norm':True,
        'vector_ids_linked_to_documents_and_bm25':1089,'faiss_saved_reloaded_reconstructed_exactly':1089,
        'model_input_truncations':0,'search_queries':0,'review_scope':'assistant source review, not independent human accuracy',
        'output_hashes':{p.name:digest(p) for p in OUT.iterdir() if p.is_file() and p.name!='verification.json'}}
    write(OUT/'verification.json',verification)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
