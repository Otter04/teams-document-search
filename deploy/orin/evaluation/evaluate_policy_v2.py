"""Offline before/after replay; source responses/gold remain frozen."""
import argparse
from datetime import datetime, timezone
from adapter import *
from evaluate import enrichment_row, integrity
from enrichment_policy_v2 import assess, VERSION
from jsonschema import Draft202012Validator

REPLAY = ROOT/'outputs/enrichment-delivery-policy-v2'
# Exact 17-document scope in the user's previous progress question.
PRIOR17 = ['D-005','H-001','H-002','D-044','D-102','D-002','H-006','H-007',
           'H-016','H-011','H-015','H-020','H-021','H-022','H-023','D-007','H-018']


def metadata_audit(candidate, gold, packet):
    """Offline gold-only safeguard; never used by normalization or model requests.

    A different, potentially valid evidence location remains pending review.
    Missing values are counted in recall; they are not fabricated to make a pass.
    Summary semantics are ALWAYS separate and remain unreviewed here.
    """
    fields = ec.score_fields(candidate, gold, packet, valid=True)
    errors = []
    for field in fields:
        name = field['field']
        if field['predicted_value'] is not None:
            if not field['value_match']:
                errors.append(name + ':wrong_or_unresolved_value')
            elif not field['correct_supported_value']:
                errors.append(name + ':metadata_evidence_review_required')
    return errors


def row(env, gold, packet):
    before = enrichment_row(env, gold, packet)
    after = assess(env, packet)
    shape = after['candidate'] is not None and not list(
        Draft202012Validator(ec.schema()).iter_errors(after['candidate']))
    audit = metadata_audit(after['candidate'], gold, packet) if shape else ['no_valid_candidate']
    contract_valid = not after['errors']
    return {'doc_id': gold['doc_id'], 'response_sha256': digest(env),
            'before_valid': before['delivery_valid'], 'before_errors': before['delivery_errors'],
            'after_contract_valid': contract_valid, 'after_errors': after['errors'],
            'corrections': after['corrections'],
            'metadata_audit_errors': audit,
            'metadata_audited_candidate': contract_valid and not audit,
            'summary_semantics': 'pending_separate_source_review',
            'value_matches': before['value_matches'], 'needed': before['needed'],
            'filled': before['filled'], 'strict_json': before['strict_json'],
            'normalized_candidate': after['candidate'] if after['corrections'] else None}


def aggregate(rows):
    return {'documents': len(rows), 'before_valid': sum(r['before_valid'] for r in rows),
            'after_contract_valid': sum(r['after_contract_valid'] for r in rows),
            'metadata_audited_candidates': sum(r['metadata_audited_candidate'] for r in rows),
            'corrected_documents': sum(bool(r['corrections']) for r in rows),
            'corrections': sum(len(r['corrections']) for r in rows),
            'newly_contract_valid': [r['doc_id'] for r in rows if r['after_contract_valid'] and not r['before_valid']],
            'regressions': [r['doc_id'] for r in rows if r['before_valid'] and not r['after_contract_valid']],
            'strict_json': sum(r['strict_json'] for r in rows),
            'value_matches': sum(r['value_matches'] for r in rows),
            'needed': sum(r['needed'] for r in rows),
            'filled': sum(r['filled'] for r in rows)}


def evaluate(ids=None):
    gold = {g['doc_id']: g for g in read(PREP/'private/gold.json')}
    ids = ids if ids is not None else [d for d in gold if (OUT/'results/enrichment'/d/'envelope.json').exists()]
    groups = {'orin': [], 'openrouter': []}
    for did in ids:
        packet = read(PREP/'public/inputs'/f'{did}.json')
        for name, path in [('orin', OUT/'results/enrichment'/did/'envelope.json'),
                           ('openrouter', BASE_ENRICH/'responses'/MODEL/f'{did}.json')]:
            groups[name].append(row(read(path), gold[did], packet))
    result = {'version': VERSION, 'created_at': datetime.now(timezone.utc).isoformat(),
              'scope': ids, 'new_model_calls': 0, 'original_responses_modified': False,
              'summary_review_complete': False,
              'normalization_uses_gold': False, 'metadata_audit_uses_gold': True,
              'records': groups, 'summary': {k: aggregate(v) for k,v in groups.items()},
              'previous_17': {k: aggregate([r for r in v if r['doc_id'] in PRIOR17]) for k,v in groups.items()}}
    return result


def snapshot_paths(ids):
    paths = [PREP/'private/gold.json', PREP/'contract.py']
    for did in ids:
        paths.extend([OUT/'results/enrichment'/did/'envelope.json',
                      BASE_ENRICH/'responses'/MODEL/f'{did}.json',
                      PREP/'public/inputs'/f'{did}.json'])
    return paths


def markdown(result):
    lines = ['# 근거 표기 검증 기준 v2 재평가', '',
             '기존 응답만 재평가했다. 새 모델 호출 0건. 원응답·정답·프롬프트는 변경하지 않았다.', '',
             '## 같은 문서 집합의 전후 비교', '',
             '| 범위 | 응답 제공 환경 | 문서 수 | 기존 전달 기준 | 표기 정리 후 전달 기준 | 값·메타데이터 근거 대조까지 통과한 후보 |',
             '|---|---|---:|---:|---:|---:|']
    for label, group in [('앞서 안내한 17문서', result['previous_17']), ('이번 저장 응답 전체', result['summary'])]:
        for name, s in group.items():
            lines.append(f"| {label} | {name} | {s['documents']} | {s['before_valid']} | {s['after_contract_valid']} | {s['metadata_audited_candidates']} |")
    lines += ['', '메타데이터 값·근거 대조는 기존 검수 정답을 사용하는 오프라인 평가다. 운영 검증기가 정답 없이 모든 의미 오류를 알아낸다는 뜻이 아니다. 요약 의미 검수는 별도 대기이며, 위 후보를 운영 색인에 자동 반영하지 않는다.', '',
              '## 적용 범위', '',
              '- `kind=source`이며 파일명을 명확히 가리키는 `file_name`, `source.file_name`, `document.source.file_name`만 정규화한다.',
              '- `file_name:` 또는 `파일명:` 등 허용된 설명 접두어를 뺀 나머지가 입력의 **전체 파일명과 일치할 때만** 제거한다. 유니코드 NFC와 양끝 공백만 정리하며 파일명 내부 공백·문장부호는 보존한다.',
              '- 본문 인용, 숫자, 부정 표현, 실제 값, 날짜 역할, 상태는 고치지 않는다. 다른 파일·없는 참조·잘못된 인용은 계속 차단한다.',
              '- 잘린 출력·HTTP 오류·JSON 문법 오류는 복구해 통과시키지 않는다. 후보 근거와 요약 근거도 동일 규칙을 적용한다.',
              '- 원응답은 보존하고 정리 전후와 위치를 별도 기록한다. 기존 문서 전체 판정은 유지하되 안전한 표기 차이는 더 이상 실패 원인이 되지 않는다.', '',
              '## 문서별 변화', '', '| 환경 | 문서 | 기존 → 표기 정리 후 | 정리 횟수 | 남은 자동 전달 오류 수 |', '|---|---|---|---:|---:|']
    for name, rows in result['records'].items():
        for r in rows:
            lines.append(f"| {name} | {r['doc_id']} | {'통과' if r['before_valid'] else '보류'} → {'통과' if r['after_contract_valid'] else '보류'} | {len(r['corrections'])} | {len(r['after_errors'])} |")
    lines += ['', 'H-001은 값 13/13을 그대로 유지하면서 파일명 인용의 `file_name:` 접두어만 제거해 통과한다. D-102의 잘못된 거래처·인용, H-007의 작성일/표지일 상태 모순은 그대로 보류한다.', '',
              '이전 17문서 Orin 값 일치는 156/161로 유지된다. 전달률 상승은 모델 정확도 향상이 아니라 같은 응답의 안전한 표기 정리 효과다.', '',
              '근거: [상세 재평가](evaluation.json), [고정 평가 범위와 원본 해시](snapshot.json), [기존 원본 보존](../orin-evaluation-run-001/integrity.json).']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.live:
        result = evaluate()
        write(OUT/'enrichment-policy-v2.json', result)
    else:
        snapshot_path = REPLAY/'snapshot.json'
        if snapshot_path.exists():
            snapshot = read(snapshot_path)
        else:
            ids = [g['doc_id'] for g in read(PREP/'private/gold.json') if (OUT/'results/enrichment'/g['doc_id']/'envelope.json').exists()]
            snapshot = {'created_at': datetime.now(timezone.utc).isoformat(), 'doc_ids': ids,
                        'hashes': {str(p): filehash(p) for p in snapshot_paths(ids)}}
            write(snapshot_path, snapshot)
        assert all(filehash(p)==h for p,h in snapshot['hashes'].items()), 'Frozen replay inputs changed'
        result = evaluate(snapshot['doc_ids'])
        write(REPLAY/'evaluation.json', result)
        (REPLAY/'README.md').write_text(markdown(result))
        integrity()
    print(json.dumps({'summary': result['summary'], 'previous_17': result['previous_17']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
