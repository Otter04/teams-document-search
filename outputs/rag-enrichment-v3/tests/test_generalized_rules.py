"""Existing regressions plus conflicting/unsupported native input variants."""
import copy, importlib.util, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import enrich as e
spec=importlib.util.spec_from_file_location('prior_date_tests',ROOT.parent/'rag-enrichment-v2/tests/test_date_roles.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
RulesTests=prior.RulesTests
DateRoles=prior.DateRoles

class GeneralizedRules(unittest.TestCase):
    def fixture(self,lines,kind='txt',name='일반 기록.txt',folder='archive'):
        r=prior.legacy.fixture(lines,kind=kind,name=name)
        r['source']['relative_path']=folder+'/'+name
        return r

    def output(self,r):
        before=e.record_hash(r);o=e.extract(r,prior.REF)
        self.assertEqual(e.check_output(o,r),[])
        self.assertEqual(e.record_hash(r),before)
        return o

    def test_client_at_root_and_label_agree(self):
        r=self.fixture(['거래처: 청람정밀'],folder='청람정밀')
        self.assertEqual(self.output(r)['fields']['거래처']['value'],'청람정밀')

    def test_conflicting_explicit_client_and_folder_abstain(self):
        r=self.fixture(['거래처: 다온물류'],folder='청람정밀')
        self.assertEqual(self.output(r)['fields']['거래처']['status'],'needs_review')

    def test_incidental_customer_and_partial_folder_not_client(self):
        r=self.fixture(['청람정밀 연동 방식에 대한 참고 문장'],folder='청람정밀-참고')
        self.assertIsNone(self.output(r)['fields']['거래처']['value'])

    def test_title_memo_is_classified_but_body_mention_is_not(self):
        yes=self.fixture(['장비 점검 메모\n작성일: 2024-06-07'])
        no=self.fixture(['장비 현황\n담당자가 메모를 참고했다.'])
        self.assertEqual(self.output(yes)['fields']['문서종류']['value'],'기타')
        self.assertIsNone(self.output(no)['fields']['문서종류']['value'])

    def test_korean_log_context_and_final_result(self):
        r=self.fixture(['작업명: archive_rotate','2024-06-07 09:00:00 [INFO] 작업 시작 archive_rotate',
            '2024-06-07 09:01:00 [WARN] retry code=E-ARCHIVE-72',
            '2024-06-07 09:02:00 [INFO] checkpoint result=FAILED',
            '2024-06-07 09:04:00 [INFO] 작업 종료 result=SUCCESS'],kind='log',name='rotation.log')
        o=self.output(r)
        self.assertEqual(o['fields']['작업명']['value'],'archive_rotate')
        self.assertEqual(o['fields']['실행결과']['value'],'성공')
        self.assertEqual(o['fields']['로그종료']['value'],'2024-06-07 09:04')
        self.assertEqual(o['date_context']['selected_roles'],['execution_start_date'])

    def test_incomplete_korean_log_does_not_promote_checkpoint(self):
        r=self.fixture(['2024-06-07 09:00:00 [INFO] 작업 시작 archive_rotate',
            '2024-06-07 09:02:00 [ERROR] checkpoint result=FAILED'],kind='log',name='rotation.log')
        o=self.output(r)
        self.assertIsNone(o['fields']['실행결과']['value'])
        self.assertIsNone(o['fields']['로그종료']['value'])

    def test_multiple_terminal_results_abstain(self):
        r=self.fixture(['2024-06-07 09:03:00 [INFO] 작업 종료 result=FAILED',
            '2024-06-07 09:04:00 [INFO] 작업 종료 result=SUCCESS'],kind='log',name='rotation.log')
        self.assertEqual(self.output(r)['fields']['실행결과']['status'],'needs_review')

    def test_reversed_log_interval_abstains(self):
        r=self.fixture(['2024-06-07 10:00:00 [INFO] 작업 시작 archive_rotate',
            '2024-06-07 09:04:00 [INFO] 작업 종료 result=SUCCESS'],kind='log',name='rotation.log')
        self.assertEqual(self.output(r)['fields']['로그종료']['status'],'needs_review')

    def test_error_code_requires_error_context(self):
        r=self.fixture(['2024-06-07 09:00:00 [INFO] product code=E-ARCHIVE-72'],kind='log',name='rotation.log')
        self.assertIsNone(self.output(r)['fields']['오류코드']['value'])

    def test_explicit_identifier_new_shape_and_nonnumeric_rejection(self):
        r=self.fixture(['계약번호: SERVICE/2024_X9'],kind='docx',name='시험 계약서.docx')
        self.assertEqual(self.output(r)['fields']['계약번호']['value'],'SERVICE/2024_X9')
        r=self.fixture(['계약번호: 확인-필요'],kind='docx',name='시험 계약서.docx')
        self.assertIsNone(self.output(r)['fields']['계약번호']['value'])

    def proposal(self,date_line):
        r=copy.deepcopy(prior.RECORDS['D-002'])
        for b in r['blocks']:
            if b['type'] not in ('table','slide') and not b['content_refs'] and '2025.01.13' in e.squash(b['text']):
                b['text']=date_line
                return r
        self.fail('cover fixture missing')

    def test_standalone_cover_keeps_written_role_separate(self):
        o=self.output(self.proposal('2024.06.07\n작성일: 2024-06-05'))
        observations={(v['role'],v['value']) for v in o['date_context']['observations']}
        self.assertIn(('cover_date','2024-06-07'),observations)
        self.assertIn(('explicit_written_date','2024-06-05'),observations)
        self.assertEqual(o['date_context']['selected_roles'],['explicit_written_date'])

    def test_two_cover_dates_remain_ambiguous(self):
        o=self.output(self.proposal('2024.06.07\n2024.06.08'))
        self.assertEqual(o['fields']['문서일자']['status'],'needs_review')

    def test_invalid_standalone_cover_is_not_extracted(self):
        o=self.output(self.proposal('2024.02.30'))
        self.assertIsNone(o['fields']['문서일자']['value'])

    def test_labelled_printed_draft_date_is_not_written_date(self):
        r=self.fixture(['체결부 인쇄 날짜: 2024.06.07'],kind='docx',name='시험 계약서_초안.docx')
        o=self.output(r)
        self.assertEqual(o['fields']['문서일자']['status'],'needs_review')
        self.assertFalse(o['date_context']['actual_signature_verified'])

    def sheet(self):
        return next(r for r in e.read_lines(ROOT.parent/'additional-parsing-run-001/parsed.jsonl') if r['doc_id']=='H-011')

    def set_row(self,r,old_label,values):
        b=next(b for b in r['blocks'] if b['type']=='table_row' and b['cells'][0]['text']==old_label)
        for cell,value in zip(b['cells'],values+['']*(len(b['cells'])-len(values))):
            cell.update(text=str(value),value=value if value!='' else None,value_status='known' if value!='' else 'blank',formula=None)
        b['text']='\t'.join(c['text'] for c in b['cells'])

    def test_sheet_line_items_and_total_do_not_replace_representative_label(self):
        r=self.sheet();self.set_row(r,'견적금액',['품목 메모','참고'])
        self.assertIsNone(self.output(r)['fields']['금액']['value'])

    def test_sheet_two_conflicting_labelled_amounts_abstain(self):
        r=self.sheet();self.set_row(r,'VAT',['견적금액',12345])
        self.assertEqual(self.output(r)['fields']['금액']['status'],'needs_review')

    def test_sheet_amount_does_not_invent_currency_or_vat(self):
        r=self.sheet()
        self.set_row(r,'통화',['참고','추후 협의'])
        self.set_row(r,'VAT',['참고','추후 협의'])
        o=self.output(r)
        self.assertIsNotNone(o['fields']['금액']['value'])
        self.assertIsNone(o['fields']['통화']['value'])
        self.assertIsNone(o['fields']['VAT']['value'])

if __name__=='__main__':unittest.main()
