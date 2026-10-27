"""Build isolated, provenance-checked candidate inputs without reading evaluation labels."""
import collections
import hashlib
import json
from pathlib import Path
from tokenizers import Tokenizer
from chunker import Chunker, CONFIG, title_only

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'outputs/indexing-v31-001/prepared'
OUT = ROOT/'outputs/rechunk-v31-001'
def rows(p):
    return [json.loads(s) for s in p.read_text().splitlines() if s.strip()]
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def jsonl(p, values):
    p.write_text(''.join(json.dumps(v, ensure_ascii=False)+'\n' for v in values))
def intervals(chunks):
    result = collections.defaultdict(list)
    for c in chunks:
        for r in c['source_refs']:
            result[r['block_id']].append((r['start'], r['end']))
    merged = {}
    for bid, spans in result.items():
        out = []
        for a,b in sorted(spans):
            if out and a <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a,b))
        merged[bid] = out
    return merged

def main():
    target = OUT/'prepared'; target.mkdir(parents=True, exist_ok=True)
    assert not (OUT/'structural-verification.json').exists(), 'Do not overwrite a completed candidate'
    baseline = list(BASE.glob('*.json*')) + [BASE/'vectors.npy']
    baseline += list((ROOT/'outputs/indexing-v31-001/search-data').glob('*'))
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in baseline if p.is_file()}
    tokfile = ROOT/'outputs/rechunk-d001-d002-001/tokenizer/tokenizer.json'
    manifest = json.loads((BASE/'embedding-manifest.json').read_text())
    assert sha(tokfile) == manifest['model_hashes']['tokenizer.json']
    tok = Tokenizer.from_file(str(tokfile)); tok.no_padding(); tok.no_truncation()
    chunker = Chunker(tok)
    before = rows(BASE/'chunks.jsonl')
    sources = {r['doc_id']: {b['block_id']:b for b in r['blocks']} for r in rows(BASE/'indexing-records.jsonl')}
    old_inputs = rows(BASE/'embedding-inputs.jsonl')
    old_counts = json.loads((BASE/'token-budget.json').read_text())['counts']
    assert all(chunker.count(i['text']) == n for i,n in zip(old_inputs, old_counts))
    inputs, after, audits = [], [], []
    for record in before:
        did = record['doc_id']; blocks = sources[did]
        candidate = chunker.run(record, blocks)
        assert intervals(record['chunks']) == intervals(candidate['chunks']), did+' source coverage differs'
        for c in candidate['chunks']:
            reconstructed = '\n'.join(blocks[r['block_id']]['text'][r['start']:r['end']] for r in c['source_refs'])
            assert reconstructed == c['text']
            assert all(blocks[r['block_id']]['loc'] == r['loc'] for r in c['source_refs'])
            text = c['context_header']+'\n'+c['text']
            assert chunker.count(text) == c['token_count'] <= 600
            inputs.append({'doc_id':did, 'chunk_id':c['chunk_id'], 'kind':'source_chunk', 'text':text,
                           'source_refs':c['source_refs'], 'source_sha256':record['source']['sha256']})
        after.append(candidate)
        audits.append({'doc_id':did,'format':record['source']['format'],'file_name':record['source']['file_name'],
                       'before':len(record['chunks']),'after':len(candidate['chunks']),
                       'tokens':[c['token_count'] for c in candidate['chunks']],
                       'title_only_before':sum(map(title_only, record['chunks'])),
                       'title_only_after':sum(map(title_only, candidate['chunks'])),
                       'short_reasons':dict(collections.Counter(c['chunking']['short_reason'] for c in candidate['chunks'] if c['token_count']<400)),
                       'multi_page_chunks':sum(len({(r['loc'].get('slide'),r['loc'].get('page')) for r in c['source_refs']})>1 for c in candidate['chunks']),
                       'source_coverage_equal':True})
    sem = rows(BASE/'semantic-chunks.jsonl')
    semantic_ids = {c['chunk_id'] for c in sem}
    for item in old_inputs:
        if item['chunk_id'] in semantic_ids:
            inputs.append(dict(item))
    for i, item in enumerate(inputs):
        item.update(vector_id=i, embedding_text_sha256=hashlib.sha256(item['text'].encode()).hexdigest())
    assert len({i['chunk_id'] for i in inputs}) == len(inputs)
    jsonl(target/'chunks.jsonl', after); jsonl(target/'embedding-inputs.jsonl', inputs)
    (target/'semantic-chunks.jsonl').write_bytes((BASE/'semantic-chunks.jsonl').read_bytes())
    counts = [chunker.count(i['text']) for i in inputs]
    source_counts = [c['token_count'] for r in after for c in r['chunks']]
    oldtexts = {i['text'] for i in old_inputs}
    verification = {'config':CONFIG, 'documents':len(after),'source_chunks_before':sum(len(r['chunks']) for r in before),
        'source_chunks_after':len(source_counts),'semantic_chunks_unchanged':len(sem),'total_embedding_inputs':len(inputs),
        'within_400_600':sum(400<=n<=600 for n in source_counts),'below_400':sum(n<400 for n in source_counts),
        'above_600':sum(n>600 for n in counts),'max_tokens':max(counts),
        'title_only_before':sum(a['title_only_before'] for a in audits),'title_only_after':sum(a['title_only_after'] for a in audits),
        'oversized_block_split_parts':sum(c['chunking']['oversized_block_splits'] for r in after for c in r['chunks']),
        'multi_page_chunks':sum(a['multi_page_chunks'] for a in audits),
        'exact_embedding_inputs_reusable':sum(i['text'] in oldtexts for i in inputs),
        'all_source_reference_ranges_preserved':True,'all_chunk_bodies_reconstructed_from_source':True,
        'historical_token_counts_reproduced':len(old_counts),'tokenizer_sha256':sha(tokfile),'gold_read':False,
        'baseline_hashes':hashes,'per_document':audits}
    assert hashes == {p:sha(ROOT/p) for p in hashes}
    write(OUT/'structural-verification.json', verification)
    write(target/'local-token-budget.json', {'counts':counts,'input_sha256':sha(target/'embedding-inputs.jsonl')})
    print(json.dumps({k:v for k,v in verification.items() if k not in ['baseline_hashes','per_document']},ensure_ascii=False))

if __name__ == '__main__':
    main()
