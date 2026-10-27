"""Freeze test inputs/settings before observing scores. No gold labels in model input."""
from prepare import ROOT,read,lines,digest,write,save_lines
from pathlib import Path
import tarfile

OUT=ROOT/'outputs/indexing-retrieval-eval-001'
INDEX=ROOT/'outputs/indexing-110-semantic-vector-001'
def main():
    assert not OUT.exists(),'Preserve existing evaluation'
    OUT.mkdir()
    source=ROOT/'outputs/field-search-run-002/evaluation/query-inputs.jsonl'
    questions=lines(source)
    assert len(questions)==61 and all(set(q)=={'query_id','query'} for q in questions)
    save_lines(OUT/'query-inputs.jsonl',questions)
    save_lines(OUT/'embedding-inputs.jsonl',[{'chunk_id':q['query_id'],'text':q['query']} for q in questions])
    frozen={'reference_date':'2026-10-17','reference_date_reason':'same as preserved original-query regression; not current date',
        'question_count':61,'settings':{'document_aggregation':'max_chunk_cosine','dense_candidates':'all 1089 vectors, no pre-filter truncation','filters':'existing frozen date_search.plan and apply_filters','bm25':'existing context/intents/field-weight code, unchanged','fusion':'equal-weight document RRF','rrf_k':60,'bm25_candidate_limit':100,'top_k':5,'mrr_cutoff':10,'ranking_tuning':False},
        'query_inputs_sha256':digest(source),'index_artifact_hashes':read(INDEX/'artifact-hashes.json'),
        'baseline':'outputs/date-search-run-002/evaluation','baseline_hashes':{n:digest(ROOT/'outputs/date-search-run-002/evaluation'/n) for n in ['summary.json','query-results.json','search-results.jsonl']},
        'source_gold_hashes':{p:h for p,h in read(ROOT/'outputs/native-search-run-001/evaluation/verification.json')['hashes'].items() if p.endswith('/gold/queries.jsonl')},
        'query_model_input':'raw question text only; no gold IDs, filters, or answers','answer_model_calls':0,'production_search_implementation':False}
    for p,h in frozen['source_gold_hashes'].items():assert digest(p)==h
    write(OUT/'freeze.json',frozen)
    with tarfile.open(ROOT/'work/query-eval-inputs.tar','w') as tar:
        tar.add(OUT/'embedding-inputs.jsonl',arcname='embedding-inputs.jsonl')
        tar.add(ROOT/'deploy/indexing/embed_bge.py',arcname='embed_bge.py')
    print('Frozen 61 queries; source gold unchanged; no answer labels sent to embedding model')
if __name__=='__main__':main()
