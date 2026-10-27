import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import enrich
spec=importlib.util.spec_from_file_location('state_eval',ROOT/'evaluate.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)
REF=enrich.read_json(ROOT/'reference-data.json')
RECORDS={r['doc_id']:r for r in enrich.read_lines(ROOT.parent/'parsing-run-003/parsed.jsonl')}

def fixture(lines,kind='docx',name='시험 계약서.docx',visual=False):
    r=copy.deepcopy(RECORDS['D-005'])
    r['source'].update(file_name=name,format=kind,relative_path='sites/test/Shared Documents/청람정밀/'+name)
    proto=copy.deepcopy(r['blocks'][0]);r['blocks']=[];r['assets']=[]
    for i,text in enumerate(lines,1):
        b=copy.deepcopy(proto);b.update(block_id=f'test-{i}',parent_id=None,order=i,type='paragraph',text=text,
            loc={'kind':kind,**({'line_start':i,'line_end':i} if kind in ('txt','log') else {'paragraph_index':i})},
            heading_path=[],evidence=[],claims=[],context_ids=[],content_refs=[],warnings=[])
        r['blocks'].append(b)
    loc=r['blocks'][0]['loc']
    r['coverage']['units']=[{'unit_id':'native:document','loc':loc,'required':True,'status':'completed','reason':None,'block_ids':[b['block_id'] for b in r['blocks']]}]
    if visual:r['coverage']['units'].append({'unit_id':'vision:figure1','loc':loc,'required':True,'status':'pending','reason':'image not interpreted','block_ids':[]})
    return r

class RulesTests(unittest.TestCase):
    def get(self,r):return enrich.extract(r,REF)
    def test_scans_keep_pending_but_allow_filename_and_folder(self):
        o=self.get(RECORDS['D-044']);self.assertEqual(o['fields']['금액']['status'],'pending_vision')
        self.assertIsNone(o['fields']['금액']['value']);self.assertEqual(o['fields']['상태']['value'],'서명본')
        self.assertEqual(len(o['pending_visual_units']),2)
        self.assertEqual(o['fields']['로그종료']['status'],'not_applicable')
    def test_labelled_amount_not_total_and_vat(self):
        r=fixture(['견적금액: ₩100,000 (부가가치세 별도)','합계 110,000'],name='견적서_테스트.docx')
        o=self.get(r);self.assertEqual(o['fields']['금액']['value'],'100000');self.assertEqual(o['fields']['VAT']['value'],'별도')
    def test_usd_no_invented_vat(self):
        o=self.get(fixture(['계약금액은 USD 39,800으로 한다.']))
        self.assertEqual(o['fields']['통화']['value'],'USD');self.assertIsNone(o['fields']['VAT']['value'])
    def test_conflicting_amounts_abstain(self):
        o=self.get(fixture(['계약금액: KRW 100','계약금액: KRW 200']))
        self.assertEqual(o['fields']['금액']['status'],'needs_review');self.assertEqual(len(o['fields']['금액']['candidates']),2)
    def test_comma_after_amount_is_punctuation(self):
        o=self.get(fixture(['계약금액은 금 일억원정(₩100,000,000, 부가가치세 별도)으로 한다.']))
        self.assertEqual(o['fields']['금액']['value'],'100000000')
    def test_decimal_amount_is_not_silently_truncated(self):
        o=self.get(fixture(['계약금액: USD 39,800.50']))
        self.assertEqual(o['fields']['금액']['status'],'needs_review')
    def test_multiline_inspection_paragraph(self):
        r=fixture(['[정기점검 결과 보고]\n고객사: 청람정밀\n대상 시스템: MES\n점검일시: 2025-08-04 14:00 ~ 2025-08-04 17:30','종합 결과: 경고 (용량 확인)'],kind='txt',name='점검.txt')
        o=self.get(r);self.assertEqual(o['fields']['로그시작']['value'],'2025-08-04 14:00')
        self.assertEqual(o['fields']['로그종료']['value'],'2025-08-04 17:30')
    def test_rollback_start_is_not_job_start(self):
        o=self.get(fixture(['[2025-01-01 22:00:00] ===== deploy.sh start =====','[2025-01-01 22:10:00] rollback started','[2025-01-01 22:11:00] ===== deploy finished: FAILED ====='],kind='log',name='deploy.log'))
        self.assertEqual(o['fields']['로그시작']['value'],'2025-01-01 22:00')
    def test_draft_signing_date_kept_for_review(self):
        o=self.get(RECORDS['D-005'])
        self.assertEqual(o['fields']['문서일자']['status'],'needs_review')
        self.assertEqual(o['fields']['문서일자']['candidates'][0]['value'],'2025-02-19')
    def test_proposal_site_outside_metadata_field_scope(self):
        o=self.get(fixture(['제안서','설치 위치: 서울 전산실'],name='사업_제안서.docx'))
        self.assertIsNone(o['fields']['사이트']['value'])
    def test_multiple_explicit_systems_in_one_block(self):
        o=self.get(fixture(['대상 시스템: MES\n대상 시스템: ERP']))
        self.assertEqual(o['fields']['대상시스템']['status'],'needs_review')
    def test_bad_calendar_date(self):
        o=self.get(fixture(['작성일: 2025-02-30']))
        self.assertEqual(o['fields']['문서일자']['status'],'needs_review')
    def test_reversed_period(self):
        o=self.get(fixture(['본 계약의 기간은 2025년 9월 1일부터 2025년 3월 1일까지로 한다.']))
        self.assertEqual(o['fields']['계약시작일']['status'],'needs_review')
    def test_mid_error_does_not_override_final_success(self):
        o=self.get(fixture(['2025-01-01 01:00:00 Job JOB_A started','2025-01-01 01:01:00 ERROR BKP-E1042: temporary','2025-01-01 01:05:00 Job JOB_A finished. Result: SUCCESS'],kind='log',name='test.log'))
        self.assertEqual(o['fields']['실행결과']['value'],'성공');self.assertEqual(o['fields']['오류코드']['value'],'BKP-E1042')
    def test_incomplete_log_has_no_end_or_result(self):
        o=self.get(fixture(['2025-01-01 01:00:00 Job JOB_A started','2025-01-01 01:01:00 ERROR BKP-E1042: stopped'],kind='log',name='test.log'))
        self.assertIsNone(o['fields']['로그종료']['value']);self.assertIsNone(o['fields']['실행결과']['value'])
    def test_explicit_completed_with_warnings(self):
        o=self.get(fixture(['2025-01-01 01:01:00 WARN FS-W0087: usage 87%','2025-01-01 01:05:00 Job: [ROTATE] completed with the following status: [COMPLETED_WITH_WARNINGS]'],kind='log',name='test.log'))
        self.assertEqual(o['fields']['실행결과']['value'],'경고');self.assertEqual(o['fields']['오류코드']['value'],'FS-W0087')
        self.assertEqual(o['fields']['로그종료']['value'],'2025-01-01 01:05')
    def test_structured_diagram_header_date(self):
        o=self.get(fixture(['MES 서버 구성도','사업: MES 전환 | 설치 위치: 서울 | 2025-03-03'],name='서버구성_MES.docx'))
        self.assertEqual(o['fields']['문서일자']['value'],'2025-03-03')
    def test_conflicting_clients_are_not_overwritten_by_path(self):
        o=self.get(fixture(['고객사: 다온물류']))
        self.assertEqual(o['fields']['거래처']['status'],'needs_review')
    def test_unrelated_final_phrase_not_document_status(self):
        o=self.get(fixture(['최종 검수 완료 후 지급한다.']))
        self.assertIsNone(o['fields']['상태']['value'])
    def test_system_does_not_use_body_integration_partner(self):
        o=self.get(fixture(['MES 서버 구성 현황','mes-if01 ERP 연동 서버'],name='서버구성_MES.docx'))
        self.assertEqual(o['fields']['대상시스템']['value'],'MES')
    def test_no_contract_type_inference(self):
        o=self.get(fixture(['유지보수 사업 계약서','을이 유지보수 업무를 수행한다.'],name='유지보수 계약서.docx'))
        self.assertIsNone(o['fields']['계약유형']['value'])
    def test_claims_not_extraction_input(self):
        r=fixture(['일반 문단'])
        b=r['blocks'][0];b['evidence']=[{'evidence_id':'e1','kind':'literal','loc':b['loc'],'quote':'일반 문단'}]
        b['claims']=[{'claim_id':'c1','text':'계약금액: KRW 99999','status':'inferred','evidence_ids':['e1']}]
        base=self.get(r)
        self.assertIsNone(base['fields']['금액']['value'])
    def test_design_example_rejected(self):
        r=copy.deepcopy(RECORDS['D-005']);r['record_kind']='design_example'
        with self.assertRaises(ValueError):self.get(r)
    def test_forged_evidence_rejected(self):
        r=fixture(['계약번호: CT-2025-1234']);o=self.get(r)
        o['fields']['계약번호']['evidence'][0]['quote']='계약번호: CT-2025-9999'
        self.assertTrue(enrich.check_output(o,r))
    def test_repeatable_without_model_or_network(self):
        with patch('socket.create_connection',side_effect=AssertionError('network is forbidden')):
            a=self.get(RECORDS['D-005']);b=self.get(RECORDS['D-005'])
        self.assertEqual(a,b);self.assertEqual(enrich.check_output(a,RECORDS['D-005']),[])
    def test_pending_counts_as_unresolved_not_true_negative(self):
        o=self.get(RECORDS['D-044']);g={f:'N/A' for f in enrich.FIELDS};g['금액']='100'
        rows=evaluation.compare(o,g);money=next(x for x in rows if x['field']=='금액')
        self.assertEqual(money['verdict'],'unresolved_present')
        vat=next(x for x in rows if x['field']=='VAT');self.assertEqual(vat['verdict'],'unresolved_absence')
        m=evaluation.aggregate([money,vat]);self.assertIsNone(m['filled_value_precision']);self.assertEqual(m['gold_value_recall'],0)
    def test_evaluation_does_not_mutate_prediction(self):
        o=self.get(RECORDS['D-005']);before=enrich.canonical(o)
        evaluation.compare(o,{f:'N/A' for f in enrich.FIELDS})
        self.assertEqual(before,enrich.canonical(o))

if __name__=='__main__':unittest.main()
