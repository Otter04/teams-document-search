"""Offline, lossless transfer policy. Detection stays strict; admission is graded.

No network, gold labels, correction, deduplication or changes to frozen v1/v2.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('frozen_quality_v2', HERE.parent / 'rag-vision-v2/quality.py')
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)
base = v2.base
VERSION = 'vision-quality-3.0.0'
ADMITTED = {'candidate', 'candidate_with_warnings'}
# Preserve every detection. Only issues that can be represented without losing
# content are advisory. Unknown/new rules fail closed until assigned a policy.
WARNING_CODES = {
    'DUPLICATE_LITERAL', 'DUPLICATE_TABLE', 'DUPLICATE_CLAIM',
    'DUPLICATE_RELATION', 'DUPLICATE_SOURCE_LITERAL_REVIEW',
    'SOURCE_LITERAL_ONLY_IN_CLAIMS', 'COMPLETE_WITH_UNREADABLE_CELL',
    'KNOWN_CELL_EMPTY', 'UNREADABLE_CELL_WITH_TEXT', 'UNREADABLE_PAGE_WITH_TEXT',
}

def apply_policy(issues):
    return [{**i, 'original_severity': i['severity'],
             'severity': 'warning' if i['code'] in WARNING_CODES else i['severity'],
             'blocks_transfer': i['code'] not in WARNING_CODES} for i in issues]

def check_quality(w, native_context=None):
    return apply_policy(v2.check_quality(w, native_context))

def validate_response(response, item, expected_model):
    result = v2.validate_response(response, item, expected_model)
    result['previous_v2_decision'] = result['decision']
    result['validator_version'] = VERSION
    result['issues'] = apply_policy(result['issues'])
    blocked = bool(result['baseline_errors']) or any(i['blocks_transfer'] for i in result['issues'])
    result['decision'] = ('reject' if blocked else
                          'candidate_with_warnings' if result['issues'] else 'candidate')
    result['transfer_allowed'] = result['decision'] in ADMITTED
    result['review_required'] = bool(result['issues'])
    # Even an internally consistent response is not verified against the image.
    result['meaning_accuracy_verified'] = False
    return result

def convert_checked(record, item, response, model):
    assessment = validate_response(response, item, model)
    if not assessment['transfer_allowed']:
        raise ValueError('quality gate ' + assessment['decision'])
    doc = base.convert(record, item, assessment['data'], model)
    if assessment['issues']:
        unit = next(u for u in doc['coverage']['units'] if u['unit_id'] == item['unit_id'])
        codes = sorted({i['code'] for i in assessment['issues']})
        # Common schema uses pending for review; populated block_ids still
        # preserve the extraction. Never turn a contradictory report into a
        # completed/known reading or silently relocate literal/claim fields.
        unit.update(status='pending', reason=VERSION + ': transferred with warnings; source review required: ' + ', '.join(codes))
        tags = [VERSION + ':' + c for c in codes]
        for block in doc['blocks']:
            if block['block_id'] in unit['block_ids']:
                block['warnings'].extend(tags)
        doc['warnings'].extend(item['unit_id'] + ': ' + tag for tag in tags)
    errors = base.common.check(doc)
    if errors:
        raise ValueError('; '.join(errors[:8]))
    return doc, assessment
