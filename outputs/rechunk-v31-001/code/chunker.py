"""Source-grounded token chunking. No question, gold, LLM, or vector dependencies.

Uses reviewed common-block references, not the old character-sized text slices,
as atomic units. The old boundaries are only hints for headings and table identity.
Token counts include the actual embedding prefix and special tokens.
"""
import copy
import hashlib
import json
import re
from functools import lru_cache

VERSION = 'token-context-1.0'
CONFIG = {'version': VERSION, 'target_min': 400, 'max_input_tokens': 600,
          'tokenizer': 'installed bge-m3 tokenizer.json', 'log_window_minutes': 5,
          'overlap': 'headings and table headers as context; no fixed character overlap',
          'short_policy': 'retain independent sections, clauses, sheets, and final remainders'}
ROLES = [
    ('front', r'^(목\s*차|문서\s*개요|개요 및 목차)$'),
    ('technical', r'^(사업\s*이해|현황(?:과 개선 과제)?|제안\s*목표|추진\s*목표|제안\s*아키텍처|시스템\s*아키텍처)$'),
    ('delivery', r'^(추진\s*일정|투입\s*인력|제안\s*금액|사업\s*일정|수행\s*일정)$'),
    ('company', r'^(회사\s*소개|업체\s*소개)$'),
]

def unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result

def position(c):
    loc = c['source_refs'][0]['loc']
    return next(((k, loc[k]) for k in ('slide', 'page', 'sheet') if k in loc), ('body', None))

def heading(c):
    if c.get('heading_path'):
        return c['heading_path'][-1]
    line = c['text'].splitlines()[0].strip() if c['text'] else ''
    return line if len(line) <= 40 and not re.search(r'[\t。.!?:：]|\d{4}[-.]', line) else ''

def title_only(c):
    text = c['text'].strip()
    return bool(text and len(text) <= 80 and '\n' not in text and '\t' not in text
                and (text in c.get('heading_path', []) or any(re.match(rx, text) for _, rx in ROLES)))

class Chunker:
    def __init__(self, tokenizer, max_tokens=600, min_tokens=400):
        self.tokenizer = tokenizer
        self.maximum, self.minimum = max_tokens, min_tokens

    @lru_cache(maxsize=8192)
    def count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=True).ids)

    def groups(self, record, blocks):
        """Conservative structural boundaries; cross-page joins need source evidence."""
        groups, current, last_key = [], [], None
        fmt = record['source']['format']
        frame_head = {}
        for c in record['chunks']:
            frame_head.setdefault(position(c), heading(c))
        bucket = None
        for c in record['chunks']:
            frame = position(c)
            h = frame_head[frame] if frame[0] in ('page', 'slide') else heading(c)
            role = next((role for role, rx in ROLES if re.match(rx, h)), None)
            if frame[0] in ('page', 'slide'):
                proposal = record['filter_metadata'].get('문서종류') == '제안서'
                if proposal and frame[1] == 1 and role is None:
                    role = 'front'
                # A repeated heading (including its explicit continuation marker)
                # can connect neighboring pages. Unknown headings keep page boundaries.
                normalized = re.sub(r'\s*\(?계속\)?\s*$', '', h)
                key = ('page-section', role or normalized or frame)
            elif frame[0] == 'sheet':
                key = frame
            elif fmt in ('rtf', 'txt', 'ini', 'yaml', 'xml', 'json', 'jmx', 'no_extension'):
                key = ('source-stream', tuple(c.get('heading_path', [])))
            else:
                key = ('section', tuple(c.get('heading_path', [])))
            for ref in c['source_refs']:
                b = blocks[ref['block_id']]
                assert b['loc'] == ref['loc']
                text = b['text'][ref['start']:ref['end']]
                assert 0 <= ref['start'] <= ref['end'] <= len(b['text'])
                if fmt == 'log':
                    m = re.match(r'(\d{4}-\d\d-\d\d)[ T](\d\d):(\d\d)', text)
                    if m:
                        bucket = (m[1], m[2], int(m[3]) // 5)
                    key = ('log-window', bucket)
                if key != last_key and current:
                    groups.append(current)
                    current = []
                last_key = key
                current.append({'text': text, 'ref': copy.deepcopy(ref), 'old_id': c['chunk_id'],
                                'old': c, 'heading': h, 'group_key': key,
                                'is_heading': b.get('type', b.get('block_type')) == 'heading'
                                  or text.strip() in c.get('heading_path', [])
                                  or (text.strip() == h and len(text) < 81),
                                'split_reason': None})
        if current:
            groups.append(current)
        # A cover title, draft-status banner, or section heading is context for
        # the following content, even when that content starts another heading.
        joined, pending_titles = [], []
        for group in groups:
            if all(u['is_heading'] for u in group) and sum(len(u['text']) for u in group) <= 120:
                pending_titles.extend(group)
                continue
            joined.append(pending_titles + group)
            pending_titles = []
        if pending_titles:
            if joined:
                joined[-1].extend(pending_titles)
            else:
                joined.append(pending_titles)  # A source containing only a title is not invented content.
        return joined

    def context(self, units):
        old = unique([u['old'] for u in units])
        if len(old) == 1:
            prefix = old[0]['context_header']
        else:
            pieces = old[0]['context_header'].split(' | ')
            prefix = ' | '.join([pieces[0]] + [p for p in pieces[1:] if '=' in p and not re.match(r'(page|slide|sheet|line_start)=', p)])
            headings = unique([u['heading'] for u in units if u['heading']])
            if headings:
                prefix += ' | ' + ' · '.join(headings)
            positions = unique([position(c) for c in old])
            if positions[0][0] != 'body':
                prefix += ' | ' + positions[0][0] + '=' + ','.join(str(p[1]) for p in positions)
        # Attach a table header when its row has moved to an earlier chunk.
        body = '\n'.join(u['text'] for u in units)
        headers = unique([u['old'].get('table_header_text', '') for u in units
                          if u['old'].get('table_header_text')])
        missing = [h for h in headers if h not in body]
        if missing:
            prefix += '\n' + '\n'.join(missing)
        return prefix

    def embedding_text(self, units):
        return self.context(units) + '\n' + '\n'.join(u['text'] for u in units)

    def split_large(self, unit):
        if self.count(self.embedding_text([unit])) <= self.maximum:
            return [unit]
        # Prefer full lines/sentences. A single oversized row/line is the only
        # fallback that may be divided; preserve exact Unicode character offsets.
        text, parts, start = unit['text'], [], 0
        boundaries = [m.end() for m in re.finditer(r'\n|(?<=[.!?。])\s+|(?<=다\.)\s+', text)]
        boundaries += [len(text)]
        while start < len(text):
            def fragment(end):
                u = dict(unit, text=text[start:end], ref=copy.deepcopy(unit['ref']), split_reason='oversized_source_block')
                u['ref']['start'] = unit['ref']['start'] + start
                u['ref']['end'] = unit['ref']['start'] + end
                return u
            lo, hi = start+1, len(text)
            fit = start
            while lo <= hi:
                mid = (lo+hi)//2
                if self.count(self.embedding_text([fragment(mid)])) <= self.maximum:
                    fit, lo = mid, mid+1
                else:
                    hi = mid-1
            assert fit > start, 'Metadata/header alone exceeds the token budget'
            preferred = [b for b in boundaries if start < b <= fit]
            if preferred:
                fit = preferred[-1]
            elif fit < len(text):
                whitespace = [m.end()+start for m in re.finditer(r'\s+', text[start:fit])]
                if whitespace:
                    fit = whitespace[-1]
            parts.append(fragment(fit)); start = fit
        return parts

    def pack(self, group):
        units = [part for u in group for part in self.split_large(u)]
        packs, pending = [], []
        for u in units:
            if pending and self.count(self.embedding_text(pending + [u])) > self.maximum:
                # A heading must travel with the following content if it fits.
                headings = []
                while len(pending) > 1 and pending[-1]['is_heading']:
                    headings.insert(0, pending.pop())
                packs.append(pending); pending = headings
                if pending and self.count(self.embedding_text(pending + [u])) > self.maximum:
                    # Overlarge following block already has its heading in context.
                    packs[-1].extend(pending); pending = []
            pending.append(u)
        if pending:
            packs.append(pending)
        # Balance the final remainder using whole source units, never characters.
        if len(packs) > 1:
            while len(packs[-2]) > 1 and self.count(self.embedding_text(packs[-1])) < self.minimum:
                prev, tail = packs[-2], packs[-1]
                if self.count(self.embedding_text(prev[:-1])) < self.minimum:
                    break
                if self.count(self.embedding_text([prev[-1]] + tail)) > self.maximum:
                    break
                tail.insert(0, prev.pop())
        assert all(self.count(self.embedding_text(p)) <= self.maximum for p in packs)
        return packs

    def run(self, record, blocks):
        result = copy.deepcopy(record)
        result['config'] = CONFIG
        result['chunks'] = []
        groups = self.groups(record, blocks)
        for group_no, group in enumerate(groups, 1):
            packs = self.pack(group)
            for n, units in enumerate(packs, 1):
                refs = [u['ref'] for u in units]
                text = '\n'.join(u['text'] for u in units)
                prefix = self.context(units)
                tokens = self.count(prefix + '\n' + text)
                olds = unique([u['old'] for u in units])
                c = copy.deepcopy(olds[0])
                tables = unique([{'table_id': o.get('table_id'), 'header': o.get('table_header_text', ''),
                                  'context_refs': o.get('context_refs', []), 'header_status': o.get('table_header_status')}
                                 for o in olds if o.get('table_id')])
                reason = ('independent_structural_section' if len(packs) == 1 else 'whole_source_units_remainder') if tokens < self.minimum else None
                c.update(text=text, context_header=prefix, source_refs=refs,
                         kind=olds[0]['kind'] if len({o['kind'] for o in olds}) == 1 else 'context_group',
                         context_refs=unique([r for o in olds for r in o.get('context_refs', [])]),
                         table_header_text='\n'.join(unique([t['header'] for t in tables if t['header']])),
                         table_id=tables[0]['table_id'] if len(tables) == 1 else None,
                         heading_path=unique([u['heading'] for u in units if u['heading']]),
                         body_chars=len(text), token_count=tokens, token_budget_status='validated_bge_m3_no_truncation',
                         original_chunk_ids=unique([u['old_id'] for u in units]), tables=tables,
                         chunking={'version': VERSION, 'group': group_no, 'part': n, 'parts': len(packs),
                                   'boundary': units[0]['group_key'], 'short_reason': reason,
                                   'oversized_block_splits': sum(bool(u['split_reason']) for u in units),
                                   'overlap_body_chars': 0})
                identity = json.dumps([VERSION, record['source']['sha256'], refs, prefix], ensure_ascii=False, sort_keys=True)
                c['chunk_id'] = record['doc_id'] + '-T-' + hashlib.sha256(identity.encode()).hexdigest()[:16]
                result['chunks'].append(c)
        return result
