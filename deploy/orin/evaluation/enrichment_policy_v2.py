"""Bounded evidence notation repair. No gold, network, value inference or mutation."""
import copy
import re
import unicodedata
from adapter import ec
from jsonschema import Draft202012Validator

VERSION = 'enrichment-evidence-notation-v2'
FILE_REFS = {'file_name', 'source.file_name', 'document.source.file_name'}
PREFIX = re.compile(r'^(?:file_name|source\.file_name|document\.source\.file_name|파일명)\s*[:：]\s*')


def filename_text(value):
    # Internal spaces and punctuation can distinguish filenames; preserve them.
    return unicodedata.normalize('NFC', value).strip()


def evidence_slots(candidate):
    for name, field in candidate['fields'].items():
        for i, evidence in enumerate(field['evidence']):
            yield f'fields.{name}.evidence[{i}]', evidence
        for j, option in enumerate(field['candidates']):
            for i, evidence in enumerate(option['evidence']):
                yield f'fields.{name}.candidates[{j}].evidence[{i}]', evidence
    for j, sentence in enumerate(candidate['summary']):
        for i, evidence in enumerate(sentence['evidence']):
            yield f'summary[{j}].evidence[{i}]', evidence


def normalize(candidate, packet):
    result = copy.deepcopy(candidate)
    changes = []
    # No salvaging malformed JSON/schema; caller must also require a normal stop.
    if list(Draft202012Validator(ec.schema()).iter_errors(result)):
        return result, changes
    if result['doc_id'] != packet['document']['doc_id']:
        return result, changes
    filename = packet['document']['source'].get('file_name')
    if not isinstance(filename, str) or not filename.strip():
        return result, changes
    for path, evidence in evidence_slots(result):
        if evidence['kind'] != 'source' or evidence['ref'] not in FILE_REFS:
            continue
        quote = evidence['quote']
        # Keep a literal source quote untouched, even if the real filename starts
        # with a label-like string. Alias repair requires the FULL filename.
        if filename_text(quote) == filename_text(filename):
            cleaned = quote
        else:
            match = PREFIX.match(quote)
            if not match or filename_text(quote[match.end():]) != filename_text(filename):
                continue
            cleaned = filename
        if evidence['ref'] == 'file_name' and cleaned == quote:
            continue
        before = copy.deepcopy(evidence)
        evidence.update(ref='file_name', quote=cleaned)
        changes.append({'path': path, 'code': 'exact_filename_notation',
                        'before': before, 'after': copy.deepcopy(evidence)})
    return result, changes


def assess(env, packet):
    errors = []
    response = env.get('response', {})
    if env.get('http_status', 200) != 200 or response.get('error'):
        errors.append('api_error')
    choices = response.get('choices') or []
    if len(choices) != 1:
        return {'candidate': None, 'corrections': [], 'errors': errors + ['missing_or_multiple_choices']}
    if choices[0].get('finish_reason') != 'stop':
        errors.append('not_normal_stop')
    try:
        candidate = ec.loads(choices[0].get('message', {}).get('content'))
    except (ValueError, TypeError):
        return {'candidate': None, 'corrections': [], 'errors': errors + ['invalid_json']}
    # Transport/finish failures cannot produce a reusable normalized candidate.
    if errors:
        return {'candidate': None, 'corrections': [], 'errors': errors}
    candidate, corrections = normalize(candidate, packet)
    errors.extend(ec.validate(candidate, packet))
    return {'candidate': candidate, 'corrections': corrections, 'errors': errors}
