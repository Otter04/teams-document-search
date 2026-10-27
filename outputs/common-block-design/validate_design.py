"""Validate the proposed block contract, not parsing/model quality.

Run: python validate_design.py
Dependency: jsonschema==4.25.1
"""
import copy
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'common-block.schema.json').read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


def check(doc):
    errors = [f"schema:{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in VALIDATOR.iter_errors(doc)]
    if errors:
        return errors

    def need(condition, message):
        if not condition:
            errors.append(message)

    def unique(items, field, name):
        values = [item[field] for item in items]
        need(len(values) == len(set(values)), f'duplicate {name}')
        return {item[field]: item for item in items}

    blocks = unique(doc['blocks'], 'block_id', 'block_id')
    assets = unique(doc['assets'], 'asset_id', 'asset_id')
    runs = unique(doc['runs'], 'run_id', 'run_id')
    unique(doc['coverage']['units'], 'unit_id', 'unit_id')
    orders = [b['order'] for b in doc['blocks']]
    need(len(orders) == len(set(orders)), 'duplicate reading order')
    for run in runs.values():
        need(set(run['input_asset_ids']) <= assets.keys(), 'unknown input asset')
    if doc['record_kind'] == 'design_example':
        need(doc['coverage']['scope'] == 'excerpt', 'design example must be excerpt')
        need(all(r['method'] == 'manual_design' for r in runs.values()), 'example must not impersonate model run')
    if doc['record_kind'] == 'template':
        need(doc['coverage']['scope'] == 'template', 'template must have template scope')
    for unit in doc['coverage']['units']:
        need(set(unit['block_ids']) <= blocks.keys(), 'unknown unit block')
        if unit['status'] in ('failed', 'excluded'):
            need(bool(unit['reason']), 'failed/excluded unit requires reason')

    def walk(value):
        if isinstance(value, dict):
            if 'kind' in value and value['kind'] in ('pdf', 'pptx', 'docx', 'xlsx', 'txt', 'log'):
                need(value['kind'] == doc['source']['format'], 'location format mismatch')
                if 'line_start' in value:
                    need(value['line_start'] <= value['line_end'], 'reversed line range')
            if 'frame_asset_id' in value:
                aid = value['frame_asset_id']
                need(aid in assets, 'unknown bbox frame')
                need(value['x0'] < value['x1'] and value['y0'] < value['y1'], 'reversed/empty bbox')
                if aid in assets:
                    need(assets[aid]['kind'] != 'region_image', 'bbox must use full source frame, not crop frame')
            if isinstance(value.get('bbox'), dict) and value['bbox']['frame_asset_id'] in assets:
                frame = assets[value['bbox']['frame_asset_id']]['loc']
                for key in ('kind', 'page', 'slide', 'sheet', 'media_part'):
                    if key in frame and key in value:
                        need(frame[key] == value[key], 'bbox/source location mismatch')
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(doc)

    for block in blocks.values():
        bid = block['block_id']
        parent = block['parent_id']
        need(parent is None or parent in blocks, 'unknown parent')
        need(block['run_ref'] in runs, 'unknown extraction run')
        need(set(block['context_ids'] + block['content_refs']) <= blocks.keys(), 'unknown block reference')
        need(bid not in block['context_ids'] + block['content_refs'], 'self block reference')
        seen = {bid}
        ancestor = parent
        while ancestor in blocks:
            if ancestor in seen:
                errors.append('parent cycle')
                break
            seen.add(ancestor)
            ancestor = blocks[ancestor]['parent_id']
        ev = unique(block['evidence'], 'evidence_id', 'evidence_id')
        unique(block['claims'], 'claim_id', 'claim_id')
        for claim in block['claims']:
            need(set(claim['evidence_ids']) <= ev.keys(), 'unknown claim evidence')
        if block['content_refs']:
            need(block['text'] == '', 'referencing content must not duplicate literal text')
        if block['type'] == 'table_row':
            need(parent in blocks and blocks[parent]['type'] == 'table', 'table row requires table parent')
            need(len({c['row'] for c in block['cells']}) == 1, 'mixed anchor rows in table row')
            need(block['text'] == '\t'.join(c['text'] for c in sorted(block['cells'], key=lambda c:c['column'])),
                 'row text must serialize its anchor cells once')
        if block['type'] == 'figure':
            nodes = unique(block['visual']['nodes'], 'node_id', 'node_id')
            unique(block['visual']['relations'], 'relation_id', 'relation_id')
            for node in nodes.values():
                need(set(node['evidence_ids']) <= ev.keys(), 'unknown node evidence')
            for relation in block['visual']['relations']:
                need(relation['from_node'] in nodes and relation['to_node'] in nodes, 'unknown relation endpoint')
                need(set(relation['evidence_ids']) <= ev.keys(), 'unknown relation evidence')
        if block['type'] == 'table':
            t = block['table']
            need(all(r <= t['row_count'] for r in t['header_rows']), 'header outside table')
            if t['continued_from'] is not None:
                need(t['continued_from'] in blocks and t['continued_from'] != bid and blocks[t['continued_from']]['type']=='table',
                     'invalid continued table reference')
            slots = set()
            for child in blocks.values():
                if child['parent_id'] != bid:
                    continue
                need(child['type'] == 'table_row', 'table child must be table_row')
                for cell in child.get('cells', []):
                    occupied = {(r,c) for r in range(cell['row'],cell['row']+cell['row_span'])
                                for c in range(cell['column'],cell['column']+cell['column_span'])}
                    need(not slots & occupied, 'overlapping table cells')
                    need(all(r<=t['row_count'] and c<=t['column_count'] for r,c in occupied), 'cell outside table')
                    slots.update(occupied)
            need(slots == {(r,c) for r in range(1,t['row_count']+1) for c in range(1,t['column_count']+1)},
                 'unrepresented table cells')
    return errors


def main():
    result = {'scope':'schema_and_reference_integrity_only', 'model_called':False,
              'vision_quality_evaluated':False, 'documents':[], 'negative_checks':[]}
    fixtures = {}
    for folder in ('examples', 'templates'):
        for path in sorted((ROOT/folder).glob('*.json')):
            doc = json.loads(path.read_text())
            fixtures[path.stem] = doc if folder=='examples' else fixtures.get(path.stem,doc)
            errors = check(doc)
            result['documents'].append({'path':str(path.relative_to(ROOT)), 'valid':not errors, 'errors':errors})
    for path in sorted((ROOT/'assets').glob('*.png')):
        for doc in fixtures.values():
            for asset in doc['assets']:
                if asset['path'] == str(path.relative_to(ROOT)):
                    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset['sha256']

    # These check distinct contract failures, not model accuracy.
    base = fixtures['pdf-diagram-D-069']
    def negative(name, original, mutate):
        doc = copy.deepcopy(original)
        mutate(doc)
        found = check(doc)
        result['negative_checks'].append({'case':name,'rejected':bool(found),'errors':found})
    negative('missing_required_text',base,lambda d:d['blocks'][1].pop('text'))
    negative('invented_direction_enum',base,lambda d:d['blocks'][1]['visual']['relations'][0].update(direction='downward'))
    negative('dangling_node',base,lambda d:d['blocks'][1]['visual']['relations'][0].update(to_node='absent'))
    negative('dangling_evidence',base,lambda d:d['blocks'][1]['claims'][0].update(evidence_ids=['absent']))
    negative('parent_cycle',base,lambda d:d['blocks'][1].update(parent_id=d['blocks'][1]['block_id']))
    negative('bbox_reversed',base,lambda d:d['blocks'][1]['loc']['bbox'].update(x0=.99,x1=.1))
    negative('bbox_wrong_page',base,lambda d:d['blocks'][1]['loc'].update(page=2))
    negative('missing_model_identity',base,lambda d:d['runs'][0].update(method='vision_llm'))
    negative('example_marked_production',base,lambda d:d.update(record_kind='run_result'))
    negative('overlapping_cells',fixtures['pdf-scan-table-D-044'],lambda d:d['blocks'][1]['cells'][1].update(column=1))
    negative('table_cell_omission',fixtures['pdf-scan-table-D-044'],lambda d:d['blocks'][1]['cells'].pop())
    negative('unknown_unit_block',base,lambda d:d['coverage']['units'][0].update(block_ids=['absent']))
    negative('duplicate_block_id',base,lambda d:d['blocks'][1].update(block_id=d['blocks'][0]['block_id']))
    negative('reversed_lines',fixtures['txt-D-052'],lambda d:d['blocks'][0]['loc'].update(line_start=4,line_end=1))
    result['passed'] = all(x['valid'] for x in result['documents']) and all(x['rejected'] for x in result['negative_checks'])
    (ROOT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'documents':len(result['documents']),
                      'negative_checks':len(result['negative_checks']),'vision_quality_evaluated':False}))
    if not result['passed']:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
