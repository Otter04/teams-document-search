"""Question-only planning: no corpus vocabulary, aliases or query expansion.

Text is passed unchanged to Elasticsearch's Nori analyzer. Calendar, explicit
date-role, version and status syntax affect filters/grouping, never add terms.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from query import DATE_RX, SEASON_RX, NEGATION, calendar_range, identifiers


def plan_literal(query, reference=None, ref_date=None):
    query = unicodedata.normalize('NFC', query).strip()
    ref = date.fromisoformat(ref_date) if ref_date else datetime.now(ZoneInfo('Asia/Seoul')).date()
    p = dict(query=query, semantic=query, keywords=query, conditions={}, condition_evidence={},
             boost={}, exact=[], identifiers=identifiers(query), concepts=[], relaxable=[],
             reference_date=ref.isoformat(), used_llm=False,
             llm={'attempted':False, 'status':'disabled', 'reason':'nori_literal_policy'},
             warnings=[], requires_clarification=False, sort=None, requested_version=None,
             requested_version_order=None, date_interpretation=None, lexical_expansions=[],
             client_candidates=[], search_policy='nori_literal')

    def add(field, value, evidence):
        p['conditions'][field] = value
        p['condition_evidence'][field] = evidence

    # Generic document-state/version syntax. No entity, document-type or system list.
    for state in ('서명본', '초안'):
        if state in query:
            add('status', state, state)
    if re.search(r'최신|최종본|최종\s*견적|(?:제일|가장)\s*새\s*(?:판|버전)', query):
        p['boost']['latest_version'] = True
    version = re.search(r'(?<![a-z0-9])(?:v|rev)(\d+(?:\.\d+)*)', query, re.I)
    if version:
        p['requested_version'] = 'v' + version[1]
    if re.search(r'첫\s*(?:견적|제안|버전|작성본)|최초|초기\s*(?:견적|제안|버전|작성본)|처음\s*(?:뽑은|작성한|만든)|(?:맨\s*)?처음\s*설계안|처음엔|처음에는', query):
        p['requested_version_order'] = 'earliest'

    role = 'document_date'
    if re.search(r'표지\s*(날짜|일자|일)', query):
        role = 'cover_date'
    elif re.search(r'작성\s*(일자|일)|작성된', query):
        role = 'written_date'
    elif '수정' in query:
        role = 'file_modified_at'
    elif re.search(r'로그|(?<![A-Za-z])logs?(?![A-Za-z])', query, re.I):
        role = 'log_start'
    elif re.search(r'계약', query) and re.search(r'유지보수|관리\s*계약|계약\s*기간|(?:적용|유효)\s*(?:중인|되는|한)?\s*계약', query) and not re.search(r'작성|표지|수정|체결|맺|서명|문서\s*(일자|날짜)|계약일', query):
        role = 'contract_period'
        p['date_role_note'] = '계약의 관리·유지보수·적용 기간은 원문에 명시된 시작일·종료일과 요청 기간의 겹침으로 확인합니다.'
    if role in ('file_modified_at', 'written_date', 'cover_date') and re.search(r'최근|최신|마지막|내림차순|오름차순|오래된', query):
        p['sort'] = {'field':role, 'direction':'asc' if re.search(r'오름차순|오래된', query) else 'desc'}

    dates = list(DATE_RX.finditer(query))
    if len(dates) == 1:
        try:
            bounds = calendar_range(dates[0][0], ref)
            if role == 'file_modified_at':
                lo = date.fromisoformat(bounds['gte'])
                hi = date.fromisoformat(bounds['lte']) + timedelta(days=1)
                bounds = {'gte':lo.isoformat()+'T00:00:00+09:00', 'lt':hi.isoformat()+'T00:00:00+09:00'}
            add(role, bounds, dates[0][0])
        except ValueError:
            p['warnings'].append('invalid_calendar_date')
            p['requires_clarification'] = True
    elif len(dates) > 1:
        p['warnings'].append('multiple_date_ranges')
        p['requires_clarification'] = True
    if re.search(r'(?<!\d)\d{1,2}\s*(?:월|일)', DATE_RX.sub(' ', query)):
        p['warnings'].append('unsupported_calendar_expression')
        p['requires_clarification'] = True
        p['conditions'].pop(role, None)
    season = SEASON_RX.search(query)
    if season and len(dates) == 1 and role in p['conditions'] and not re.search(r'\d\s*월', dates[0][0]):
        p['date_interpretation'] = {'policy':'explicit_year_only', 'expression':season[0],
            'field':role, 'bounds':p['conditions'][role],
            'message':'“'+season[0]+'”의 정확한 월 범위는 확정하지 않고, 명시한 연도 안에서만 검색합니다.'}
        p['warnings'].append('approximate_season_year_only')
    p['unresolved_date'] = bool(re.search(r'분기|월말|월초|최근\s*\d|지난달|이번달', query)) or bool(season and not p['date_interpretation'])
    if p['unresolved_date']:
        p['requires_clarification'] = True
    if NEGATION.search(query):
        p['warnings'].append('unsupported_negation')
        p['requires_clarification'] = True
    # Explicit period constraints are never relaxed, even with zero lexical hits.
    p['relaxable'] = ['status'] if 'status' in p['conditions'] else []
    return p
