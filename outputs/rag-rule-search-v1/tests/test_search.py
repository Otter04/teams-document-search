import copy
from datetime import date
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import search as s
RULES=s.base.enrich.read_json(s.ROOT/'rules.json')

def concept_ids(text):return {h['concept'] for h in s.concepts(text,RULES)}
def field_filter(q,field,op='gte',as_of='2026-10-17'):
    return next(f['value'] for f in s.plan(q,as_of)['filters'] if f['field']==field and f['op']==op)

class RuleTests(unittest.TestCase):
    def test_autoscale_same_concept(self):self.assertIn('autoscale',concept_ids('오토스케일링'));self.assertIn('autoscale',concept_ids('SCHOOL_AUTOSCALE_TEST'))
    def test_generic_conversion_is_not_database_switchover(self):
        for text in ('클라우드 전환 제안','서비스 전환 작업','화면 전환'):
            self.assertNotIn('switchover',concept_ids(text))
        self.assertIn('switchover',concept_ids('Data Guard 전환 훈련'))
    def test_particle_suffix(self):self.assertIn('test',concept_ids('테스트에서'));self.assertIn('error',concept_ids('오류가 났다'))
    def test_english_substring_not_alias(self):self.assertNotIn('test',concept_ids('contest'));self.assertNotIn('database',concept_ids('adblock'))
    def test_guarded_abbreviation(self):self.assertNotIn('dataguard',concept_ids('DG artist'));self.assertIn('dataguard',concept_ids('DG_SWITCHOVER_DRILL'))
    def test_concept_does_not_invent_source_text(self):
        x='SCHOOL_FAILOVER_TEST';self.assertIn('failover',concept_ids(x));self.assertEqual(x,'SCHOOL_FAILOVER_TEST')
    def test_technical_identifier_and_components(self):
        t=s.tokens('SERVICE_RELEASE_7.4.2 CT-2099-001 ORA-01555',[],RULES)
        for term in ('w:service_release_7.4.2','w:7.4.2','w:ct-2099-001','w:ora-01555'):self.assertIn(term,t)
    def test_calendar_leap_year(self):self.assertEqual(s.interval('2024년 2월',date(2026,10,17)),(date(2024,2,1),date(2024,2,29)))
    def test_last_month_year_boundary(self):self.assertEqual(s.interval('지난달',date(2026,1,2)),(date(2025,12,1),date(2025,12,31)))
    def test_yesterday_year_boundary(self):self.assertEqual(s.interval('어제',date(2026,1,1)),(date(2025,12,31),date(2025,12,31)))
    def test_reference_year_changes(self):
        self.assertEqual(field_filter('작년 12월 백업 로그','로그시작',as_of='2027-01-01'),'2026-12-01 00:00')
    def test_absolute_log_month(self):
        self.assertEqual(field_filter('2025년 9월 실패한 로그','로그시작'),'2025-09-01 00:00')
        self.assertEqual(field_filter('2025년 9월 실패한 로그','로그시작','lte'),'2025-09-30 23:59')
        self.assertEqual(field_filter('2025년 9월 실패한 로그','실행결과','eq'),'실패')
    def test_partial_date_expression_not_silently_truncated(self):
        for q in ('2025년 9월과 10월 로그','2025년 1분기 로그','2025년 9월말 로그','2025년 9월 3일과 4일 로그'):
            x=s.plan(q,'2026-10-17');self.assertFalse(x['filters']);self.assertTrue(x['warnings'])
    def test_explicit_log_end_role(self):
        self.assertEqual(field_filter('로그 종료 시각이 어제인 자료','로그종료'),'2026-10-16 00:00')
    def test_document_date_role(self):self.assertEqual(field_filter('작성일 2024-02-29 보고서','문서일자'),'2024-02-29')
    def test_contract_end_role(self):self.assertEqual(field_filter('계약 종료일 올해 계약서','계약종료일'),'2026-01-01')
    def test_ambiguous_contract_year_abstains(self):
        x=s.plan('2025년 유지보수 계약','2026-10-17');self.assertFalse(x['filters']);self.assertIn('ambiguous_date_role',x['warnings'])
    def test_invalid_date_abstains(self):
        x=s.plan('2025년 2월 30일 로그','2026-10-17');self.assertFalse(x['filters']);self.assertIn('invalid_calendar_date',x['warnings'])
    def test_multiple_dates_abstain(self):self.assertFalse(s.plan('2024년 또는 2025년 로그','2026-10-17')['filters'])
    def test_unsupported_negation_and_comparison_abstain(self):
        for q in ('작년 제외 로그','2025년 이전 로그','올해 실패하지 않은 로그','작년 말고 올해 로그'):self.assertFalse(s.plan(q,'2026-10-17')['filters'])
    def test_missing_year_abstains(self):self.assertFalse(s.plan('9월 백업 로그','2026-10-17')['filters'])
    def test_error_does_not_imply_failed_job(self):self.assertFalse(s.plan('오류 난 배치 로그','2026-10-17')['filters'])
    def test_conflicting_status_abstains(self):self.assertFalse(s.plan('실패한 성공한 로그','2026-10-17')['filters'])
    def test_success_warning_not_forced_success(self):self.assertFalse(s.plan('경고로 완료된 로그','2026-10-17')['filters'])
    def test_identifier_not_date_filter(self):
        for query in ('CT-2025-0402','Q-2504-02 로그','version_2025-09 로그','ID-2025-09-02 로그'):
            result=s.plan(query,'2026-10-17');self.assertFalse(result['filters']);self.assertFalse(result['warnings'])
    def test_no_mutation_and_unknown_filter_exclusion(self):
        original=s.base.enrich.read_json(s.ROOT.parent/'native-search-run-002/index.json')
        before=copy.deepcopy(original);ix=s.build_index(original,RULES)
        self.assertEqual(before,original);self.assertEqual(ix['documents'],original['documents'])
        for eid,e in ix['entries'].items():
            for field in ('text','source_refs','context_refs','context_header','table_header_text'):self.assertEqual(e[field],original['entries'][eid][field])
        result=s.search(ix,'2099년 백업 로그','2026-10-17');self.assertEqual(result['results'],[]);self.assertTrue(result['query_plan']['filters'])
    def test_query_plan_keeps_remaining_meaning(self):
        x=s.plan('작년 12월 DB 백업 로그','2026-10-17');self.assertIn('DB 백업 로그',x['lexical_query']);self.assertFalse(x['conditions_verified'])
if __name__=='__main__':unittest.main()
