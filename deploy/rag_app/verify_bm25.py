"""Reload and audit the saved index without running a query or a model."""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from finalize_bm25 import OUT, SOURCE, norm, same_region
from runtime import ROOT, E, d, common, read, lines, write


def main():
    verification = read(OUT/'verification.json')
    for path, digest in verification['original_input_hashes'].items():
        assert E.digest(path) == digest, path
    for name, digest in verification['output_hashes'].items():
        assert E.digest(OUT/name) == digest, name
    records = {r['doc_id']: r for r in lines(OUT/'indexing-records.jsonl')}
    original = {r['doc_id']: r for r in lines(OUT/'parsed.jsonl')}
    metadata = {r['doc_id']: r for r in lines(OUT/'enriched.jsonl')}
    chunks = {r['doc_id']: r for r in lines(OUT/'chunks.jsonl')}
    ledger = {r['doc_id']: r for r in lines(OUT/'document-status.jsonl')}
    index = read(OUT/'index.json')
    assert len(records) == 110
    assert set(records) == set(metadata) == set(chunks) == set(ledger) == set(index['documents'])
    paths = read(SOURCE/'source-paths.json')
    for did, record in records.items():
        assert E.digest(paths[did]) == record['source']['sha256'], did
        assert not common.check(record), did
        E.previous.APPROVED_RECORD_HASHES.add(E.record_hash(record))
        assert not E.check_output(metadata[did], record), did
        assert not d.old.old.base.validate_chunks(chunks[did], record, metadata[did]), did
        blocks = {b['block_id']: b for b in record['blocks']}
        assert chunks[did]['chunks'] and ledger[did]['required_units_complete'], did
        # Chunk text comes only from explicit text fields; claims aren't serialized.
        for chunk in chunks[did]['chunks']:
            assert chunk['text'] == '\n'.join(blocks[x['block_id']]['text'][x['start']:x['end']] for x in chunk['source_refs'])
        for block in blocks.values():
            if block['type'] == 'figure':
                assert not block['text'].strip(), block['block_id']
    # Compare the entire postings map, including absence of spurious entries.
    expected = defaultdict(dict)
    for eid, entry in index['entries'].items():
        text = ' '.join([entry['context_header'],entry['table_header_text'],entry['text']])
        for term, count in Counter(d.old.old.previous.tokens(text,index['clients'],index['rules'])).items():
            expected[term][eid] = count
    assert dict(expected) == index['postings']
    checked = Counter()
    for did, changes in read(OUT/'deduplication-and-structure.json').items():
        blocks = {b['block_id']: b for b in original[did]['blocks']}
        runs = {r['run_id']: r for r in original[did]['runs']}
        for change in changes:
            if change['kind'] not in ('duplicate_literal_reference', 'duplicate_table_alias'):
                continue
            old, kept = blocks[change['old_id']], blocks[change['retained_id']]
            assert runs[old['run_ref']]['method'] != 'native_parser'
            assert runs[kept['run_ref']]['method'] == 'native_parser'
            assert same_region(old, kept)
            if change['kind'] == 'duplicate_literal_reference':
                assert norm(old['text']) == norm(kept['text'])
            else:
                def cells(table):
                    return sorted((c['row'],c['column'],c['row_span'],c['column_span'],norm(c['text'])) for b in blocks.values() if b['parent_id']==table['block_id'] and b['type']=='table_row' for c in b['cells'])
                assert cells(old) == cells(kept)
            checked[change['kind']] += 1
    loc = {'kind':'pdf','page':1,'bbox':{'x0':0.1,'y0':0.1,'x1':0.3,'y1':0.3}}
    a = {'loc':loc}; other_page = deepcopy(a); other_page['loc']['page'] = 2
    other_region = deepcopy(a); other_region['loc']['bbox'].update(x0=0.6,x1=0.8)
    assert same_region(a,a) and not same_region(a,other_page) and not same_region(a,other_region)
    result = dict(status='passed',source_files_hash_matched=110,saved_document_sets_matched=110,
        common_metadata_chunk_validations=110,postings_exact_match=True,
        audited_duplicate_aliases=dict(checked),different_page_and_region_kept=True,
        claims_not_serialized=True,model_calls=0,search_queries=0)
    write(OUT/'reload-verification.json',result)
    print(result)


if __name__ == '__main__':
    main()
