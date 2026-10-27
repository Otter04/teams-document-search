"""Offline fixtures test repair boundaries; fixtures are never model results."""
import copy
import json
import socket
import unittest
from unittest.mock import patch
from adapter import ec, read, PREP, OUT
from enrichment_policy_v2 import normalize, assess
from evaluate_policy_v2 import metadata_audit


class EvidenceNotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = {g['doc_id']: g for g in read(PREP/'private/gold.json')}
        cls.packet = read(PREP/'public/inputs/H-001.json')

    def fixture(self):
        return ec.candidate_from_gold(self.gold['H-001'])

    def envelope(self, candidate, finish='stop'):
        return {'http_status': 200, 'response': {'choices': [{'finish_reason': finish,
                'message': {'content': json.dumps(candidate, ensure_ascii=False)}}]}}

    def test_real_response_fixed_without_mutation(self):
        env = read(OUT/'results/enrichment/H-001/envelope.json')
        before = copy.deepcopy(env)
        with patch.object(socket, 'socket', side_effect=AssertionError('no network')):
            result = assess(env, self.packet)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(result['corrections']), 1)
        self.assertEqual(metadata_audit(result['candidate'], self.gold['H-001'], self.packet), [])
        original = ec.loads(env['response']['choices'][0]['message']['content'])
        self.assertEqual({k:f['value'] for k,f in original['fields'].items()},
                         {k:f['value'] for k,f in result['candidate']['fields'].items()})
        self.assertEqual(env, before)

    def test_all_reviewed_fixture_shapes_preserved(self):
        for did, gold in self.gold.items():
            candidate = ec.candidate_from_gold(gold)
            packet = read(PREP/'public/inputs'/f'{did}.json')
            fixed, changes = normalize(candidate, packet)
            self.assertEqual(fixed, candidate)
            self.assertEqual(changes, [])
            self.assertEqual(ec.validate(fixed, packet), [])

    def test_bounded_aliases_and_korean_prefix(self):
        for ref in ['file_name', 'source.file_name', 'document.source.file_name']:
            for prefix in ['file_name: ', '파일명： ', 'document.source.file_name: ']:
                candidate = self.fixture()
                e = candidate['fields']['문서종류']['evidence'][0]
                e.update(ref=ref, quote=prefix+self.packet['document']['source']['file_name'])
                fixed, changes = normalize(candidate, self.packet)
                self.assertEqual(ec.validate(fixed, self.packet), [])
                self.assertTrue(changes)
                self.assertEqual(normalize(fixed, self.packet), (fixed, []))

    def test_wrong_filename_never_replaced(self):
        candidate = self.fixture()
        candidate['fields']['문서종류']['evidence'][0]['quote'] = 'file_name: 다른 계약서.docx'
        fixed, changes = normalize(candidate, self.packet)
        self.assertEqual(fixed, candidate); self.assertEqual(changes, [])
        self.assertTrue(ec.validate(fixed, self.packet))

    def test_partial_or_extra_text_never_stripped(self):
        for quote in ['file_name: 계약서', '파일명: '+self.packet['document']['source']['file_name']+' 확인됨']:
            candidate = self.fixture()
            candidate['fields']['문서종류']['evidence'][0]['quote'] = quote
            fixed, changes = normalize(candidate, self.packet)
            self.assertEqual(changes, []); self.assertTrue(ec.validate(fixed, self.packet))

    def test_filename_internal_spaces_not_erased(self):
        candidate = self.fixture()
        candidate['fields']['문서종류']['evidence'][0]['quote'] = 'file_name: '+self.packet['document']['source']['file_name'].replace(' ', '')
        fixed, changes = normalize(candidate, self.packet)
        self.assertEqual(changes, []); self.assertTrue(ec.validate(fixed, self.packet))

    def test_summary_and_pending_candidate_evidence_use_same_boundary(self):
        candidate = self.fixture()
        evidence = {'kind':'source', 'ref':'document.source.file_name',
                    'quote':'파일명: '+self.packet['document']['source']['file_name']}
        candidate['summary'] = [{'text':'계약서다.', 'evidence':[copy.deepcopy(evidence)]}]
        candidate['fields']['사업명'].update(value=None, status='needs_review', reason='검토 필요',
                                           candidates=[{'value':'후보', 'evidence':[copy.deepcopy(evidence)]}])
        fixed, changes = normalize(candidate, self.packet)
        self.assertEqual(len(changes), 2)
        self.assertEqual(fixed['summary'][0]['text'], '계약서다.')
        self.assertEqual(fixed['fields']['사업명']['candidates'][0]['value'], '후보')
        self.assertEqual(ec.validate(fixed, self.packet), [])

    def test_wrong_reference_and_kind_not_repaired(self):
        for kind, ref in [('source', 'missing.file_name'), ('block', 'file_name')]:
            candidate = self.fixture()
            candidate['fields']['문서종류']['evidence'][0].update(kind=kind, ref=ref)
            fixed, changes = normalize(candidate, self.packet)
            self.assertEqual(changes, []); self.assertTrue(ec.validate(fixed, self.packet))

    def test_body_negation_not_fuzzy_matched(self):
        candidate = self.fixture()
        candidate['fields']['거래처']['evidence'] = [{'kind':'block', 'ref':'H-001-8c8b34a47a6a-p12',
                                                   'quote':'기존 설비의 PLC 프로그램 변경은 범위에 포함한다.'}]
        fixed, changes = normalize(candidate, self.packet)
        self.assertEqual(changes, []); self.assertTrue(ec.validate(fixed, self.packet))

    def test_wrong_amount_stays_wrong_and_is_audited_out(self):
        candidate = self.fixture()
        candidate['fields']['금액']['value'] = '48000001'
        fixed, _ = normalize(candidate, self.packet)
        self.assertEqual(fixed['fields']['금액']['value'], '48000001')
        self.assertIn('금액:wrong_or_unresolved_value', metadata_audit(fixed, self.gold['H-001'], self.packet))

    def test_real_quote_wrong_evidence_remains_pending(self):
        candidate = self.fixture()
        candidate['fields']['문서종류']['evidence'][0]['quote'] = 'MES'
        fixed, changes = normalize(candidate, self.packet)
        self.assertEqual(changes, [])
        self.assertIn('문서종류:metadata_evidence_review_required', metadata_audit(fixed, self.gold['H-001'], self.packet))

    def test_wrong_date_role_not_corrected(self):
        gold = self.gold['H-007']; packet = read(PREP/'public/inputs/H-007.json')
        candidate = ec.candidate_from_gold(gold)
        candidate['fields']['작성일'] = copy.deepcopy(candidate['fields']['표지일'])
        fixed, _ = normalize(candidate, packet)
        self.assertIn('작성일:wrong_or_unresolved_value', metadata_audit(fixed, gold, packet))

    def test_transport_truncation_json_and_schema_errors_stay_blocked(self):
        candidate = self.fixture()
        cases = [self.envelope(candidate, 'length')]
        bad_http = self.envelope(candidate); bad_http['http_status'] = 500; cases.append(bad_http)
        for raw in ['{"x":1,"x":2}', '{"x":"unescaped\nline"}', '{']:
            env = self.envelope(candidate); env['response']['choices'][0]['message']['content'] = raw; cases.append(env)
        wrong_schema = self.fixture(); del wrong_schema['fields']['금액']
        cases.append(self.envelope(wrong_schema))
        for env in cases:
            self.assertTrue(assess(env, self.packet)['errors'])
            self.assertEqual(assess(env, self.packet)['corrections'], [])

    def test_status_and_unknown_document_not_repaired(self):
        candidate = self.fixture(); candidate['fields']['文書種類'] = candidate['fields'].pop('문서종류')
        self.assertTrue(assess(self.envelope(candidate), self.packet)['errors'])
        candidate = self.fixture(); candidate['fields']['문서종류']['reason'] = 'extra'
        self.assertIn('문서종류:inconsistent_extracted', assess(self.envelope(candidate), self.packet)['errors'])
        candidate = self.fixture(); candidate['doc_id'] = 'H-999'
        self.assertIn('wrong_doc_id', assess(self.envelope(candidate), self.packet)['errors'])


if __name__ == '__main__':
    unittest.main()
