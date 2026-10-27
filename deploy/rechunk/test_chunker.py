import json
import unittest
from pathlib import Path
from tokenizers import Tokenizer
from chunker import Chunker, title_only
from prepare import intervals

ROOT = Path(__file__).resolve().parents[2]

class ChunkingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t = Tokenizer.from_file(str(ROOT/'outputs/rechunk-d001-d002-001/tokenizer/tokenizer.json'))
        t.no_padding(); t.no_truncation(); cls.chunker = Chunker(t)
        base = ROOT/'outputs/indexing-v31-001/prepared'
        cls.records = {r['doc_id']:r for r in map(json.loads, (base/'chunks.jsonl').read_text().splitlines())}
        cls.sources = {r['doc_id']:{b['block_id']:b for b in r['blocks']} for r in map(json.loads, (base/'indexing-records.jsonl').read_text().splitlines())}

    def run_doc(self, did):
        old = self.records[did]
        new = self.chunker.run(old, self.sources[did])
        self.assertEqual(intervals(old['chunks']), intervals(new['chunks']))
        self.assertTrue(all(c['token_count'] <= 600 for c in new['chunks']))
        self.assertFalse(any(title_only(c) for c in new['chunks']))
        return new

    def test_page_context_and_tables(self):
        for did in ('D-001', 'D-002'):
            result = self.run_doc(did)
            self.assertEqual(len(result['chunks']), 4)
            technical = result['chunks'][1]
            positions = {r['loc'].get('slide', r['loc'].get('page')) for r in technical['source_refs']}
            self.assertEqual(positions, {3,4,5})
            normalized = ''.join(technical['text'].split())
            self.assertIn('5분', normalized); self.assertIn('1초', normalized)
            delivery = result['chunks'][2]
            self.assertEqual(len(delivery['tables']), 3)
            self.assertIn('265,400,000', delivery['text'])

    def test_draft_banner_and_distinct_clauses(self):
        result = self.run_doc('D-005')
        self.assertIn('초안', result['chunks'][0]['text'])
        self.assertIn('계약번호', result['chunks'][0]['text'])
        # No merging two independent numbered contract clauses just to reach 400.
        import re
        for c in result['chunks']:
            self.assertLessEqual(len(re.findall(r'^제\d+조', c['text'], re.M)), 1)

    def test_screenshot_heading_and_sheet_rows(self):
        self.run_doc('D-150')
        result = self.run_doc('D-003')
        self.assertEqual(len(result['chunks']), 1)
        self.assertIn('견적번호', result['chunks'][0]['text'])
        self.assertIn('공급가액', result['chunks'][0]['text'])

    def test_logs_keep_whole_records(self):
        result = self.run_doc('D-010')
        for c in result['chunks']:
            self.assertEqual(c['chunking']['oversized_block_splits'], 0)
            for r in c['source_refs']:
                self.assertEqual(r['start'], 0)
                self.assertEqual(r['end'], len(self.sources['D-010'][r['block_id']]['text']))

    def test_long_unicode_block_exact_offsets(self):
        text = ('설정 값은 변경하지 않습니다. 😀\n' * 120)
        c = {'source_refs': [{'block_id':'b','start':0,'end':len(text),'loc':{'kind':'txt'}}],
             'text':text,'context_header':'문서 | 제목','heading_path':[],'table_header_text':'','chunk_id':'old'}
        u = {'text':text,'ref':c['source_refs'][0],'old_id':'old','old':c,'heading':'',
             'group_key':('source-stream',()),'is_heading':False,'split_reason':None}
        pieces = self.chunker.split_large(u)
        self.assertGreater(len(pieces), 1)
        self.assertEqual(''.join(p['text'] for p in pieces), text)
        self.assertTrue(all(self.chunker.count(self.chunker.embedding_text([p])) <= 600 for p in pieces))
        for p in pieces:
            self.assertEqual(text[p['ref']['start']:p['ref']['end']], p['text'])

if __name__ == '__main__':
    unittest.main()
