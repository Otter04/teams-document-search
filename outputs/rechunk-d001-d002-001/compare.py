"""Isolated two-document rechunking pilot. No model inference or index writes.

Run with the bundled Python and PYTHONPATH=work/rechunk-tokenizer-deps.
The four section groups are a reviewed outline for these two documents only,
not a new production routing algorithm. Every original chunk is retained once.
"""
import copy
import hashlib
import html
import json
from pathlib import Path
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = ROOT / 'outputs/indexing-v31-001/prepared'
DOCS = ('D-001', 'D-002')
GROUPS = [
    ([1, 2], '문서 개요와 목차', '문서 식별 정보와 목차. 다른 주제를 붙여 분량을 늘리지 않음.'),
    ([3, 4, 5], '현황·목표·제안 아키텍처', '동일 MES 사업의 문제·개선 목표·구성 방안을 함께 유지.'),
    ([6, 7, 8], '추진 일정·투입 인력·제안 금액', '동일 사업의 수행 계획. 표 제목·행·총액·부가세 조건을 함께 유지.'),
    ([9], '회사 소개', '제안 업체의 소개이며 사업의 기술 내용과 구분. 독립 정보로 유지.'),
]
TITLE_ONLY = {'투입 인력', '제안 금액'}

def read(path):
    return json.loads(Path(path).read_text())

def lines(path):
    with open(path) as stream:
        return [json.loads(line) for line in stream if line.strip()]

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()

def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def page(chunk):
    loc = chunk['source_refs'][0]['loc']
    return loc.get('slide', loc.get('page'))

def main():
    baseline_files = [BASE / name for name in [
        'parsed.jsonl', 'indexing-records.jsonl', 'enriched.jsonl', 'chunks.jsonl',
        'semantic-chunks.jsonl', 'document-index.jsonl', 'embedding-inputs.jsonl',
        'embedding-manifest.json', 'token-budget.json',
    ]] + [ROOT / 'outputs/indexing-v31-001/search-data' / name
          for name in ['chunks.ndjson', 'documents.json', 'chunks-mapping.json']]
    hashes_before = {str(p.relative_to(ROOT)): sha(p) for p in baseline_files}
    tokenizer_path = OUT / 'tokenizer/tokenizer.json'
    expected_hash = read(BASE / 'embedding-manifest.json')['model_hashes']['tokenizer.json']
    assert sha(tokenizer_path) == expected_hash
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    tokenizer.no_padding()
    tokenizer.no_truncation()
    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=True).ids)

    inputs = lines(BASE / 'embedding-inputs.jsonl')
    budget = read(BASE / 'token-budget.json')
    assert sha(BASE / 'embedding-inputs.jsonl') == budget['input_file_sha256']
    assert len(inputs) == len(budget['counts'])
    input_map = {r['chunk_id']: r for r in inputs}
    selected_inputs = [(r, n) for r, n in zip(inputs, budget['counts']) if r['doc_id'] in DOCS]
    assert len(selected_inputs) == 28
    assert all(count(r['text']) == n for r, n in selected_inputs)
    records = {r['doc_id']: r for r in lines(BASE / 'chunks.jsonl') if r['doc_id'] in DOCS}
    sources = {r['doc_id']: r for r in lines(BASE / 'indexing-records.jsonl') if r['doc_id'] in DOCS}
    sem = {r['doc_id']: r for r in lines(BASE / 'semantic-chunks.jsonl') if r['doc_id'] in DOCS}
    comparisons = []
    after_inputs = []
    for did in DOCS:
        record = records[did]
        blocks = {b['block_id']: b for b in sources[did]['blocks']}
        before = []
        for old in record['chunks']:
            item = copy.deepcopy(old)
            item.update(embedding_text=input_map[old['chunk_id']]['text'],
                        input_tokens=count(input_map[old['chunk_id']]['text']),
                        title_only=old['text'].strip() in TITLE_ONLY)
            before.append(item)
        new = []
        for ordinal, (positions, title, reason) in enumerate(GROUPS, 1):
            selected = [c for c in record['chunks'] if page(c) in positions]
            assert selected
            pieces, body_refs = [], []
            for old in selected:
                start = len('\n\n'.join(pieces)) + (2 if pieces else 0)
                pieces.append(old['text'])
                body_refs.append({'original_chunk_id': old['chunk_id'],
                                  'body_start': start, 'body_end': start + len(old['text']),
                                  'source_refs': copy.deepcopy(old['source_refs'])})
            body = '\n\n'.join(pieces)
            meta = record['filter_metadata']
            pos_label = 'slide' if record['source']['format'] == 'pptx' else 'page'
            position = str(positions[0]) if len(positions) == 1 else f'{positions[0]}-{positions[-1]}'
            context = ' | '.join([record['source']['file_name']] +
                                 [f'{f}={meta[f]}' for f in ['거래처', '문서종류', '문서일자']] +
                                 [title, f'{pos_label}={position}'])
            text = context + '\n' + body
            tokens = count(text)
            assert tokens <= 600, 'This pilot requires an outline review rather than automatic text cutting'
            tables = [{'table_id': c['table_id'], 'header': c['table_header_text'],
                       'header_status': c['table_header_status'],
                       'context_refs': c['context_refs'], 'original_chunk_id': c['chunk_id']}
                      for c in selected if c.get('table_id')]
            item = {'doc_id': did, 'chunk_id': f'{did}-PILOT-{ordinal:02d}',
                    'kind': 'reviewed_section_group', 'section': title, 'positions': positions,
                    'text': body, 'context_header': context, 'embedding_text': text,
                    'input_tokens': tokens, 'body_tokens_with_special_tokens': count(body),
                    'target_status': 'within_400_600' if tokens >= 400 else 'short_coherent_exception',
                    'grouping_reason': reason,
                    'short_reason': reason if tokens < 400 else None,
                    'title_only': body.strip() in TITLE_ONLY,
                    'source_sha256': record['source']['sha256'],
                    'source_refs': [ref for c in selected for ref in c['source_refs']],
                    'original_parts': body_refs, 'tables': tables,
                    'filter_metadata': meta, 'overlap_applied': False,
                    'new_text_generated': False, 'body_deduplicated': False}
            for part in body_refs:
                old = next(c for c in selected if c['chunk_id'] == part['original_chunk_id'])
                assert body[part['body_start']:part['body_end']] == old['text']
                reconstructed = '\n'.join(blocks[ref['block_id']]['text'][ref['start']:ref['end']]
                                          for ref in part['source_refs'])
                assert reconstructed == old['text']
                assert all(blocks[ref['block_id']]['loc'] == ref['loc'] for ref in part['source_refs'])
            new.append(item)
            after_inputs.append({k: item[k] for k in ['doc_id', 'chunk_id', 'embedding_text', 'input_tokens']})
        assigned = [p['original_chunk_id'] for c in new for p in c['original_parts']]
        assert assigned == [c['chunk_id'] for c in record['chunks']]
        assert not any(c['title_only'] for c in new)
        technical = next(c for c in new if c['positions'] == [3, 4, 5])
        assert all(n in {ref['loc'].get('slide', ref['loc'].get('page')) for ref in technical['source_refs']}
                   for n in [3, 4, 5])
        normalized = ''.join(technical['text'].split())
        assert '5분' in normalized and '1초' in normalized
        delivery = next(c for c in new if c['positions'] == [6, 7, 8])
        assert len(delivery['tables']) == 3
        assert all(s in ''.join(delivery['text'].split()) for s in ['265,400,000', '부가가치세별도'])
        preserved_semantic = copy.deepcopy(sem[did])
        preserved_semantic.update(embedding_text=input_map[sem[did]['chunk_id']]['text'],
                                  input_tokens=count(input_map[sem[did]['chunk_id']]['text']),
                                  pilot_action='preserved_without_rechunking')
        doc = {'doc_id': did, 'source': record['source'], 'before': before,
               'after': new, 'semantic_chunk_unchanged': preserved_semantic}
        comparisons.append(doc)
        write(f'{did}-comparison.json', doc)
    hashes_after = {str(p.relative_to(ROOT)): sha(p) for p in baseline_files}
    assert hashes_before == hashes_after
    verification = {
        'scope': list(DOCS), 'target_input_tokens': [400, 600],
        'count_includes': ['context', 'body including table headers', 'special tokens'],
        'tokenizer_sha256': expected_hash, 'tokenizer_matches_existing_model': True,
        'historical_token_counts_reproduced': len(selected_inputs),
        'source_chunks_before': 26, 'source_chunks_after': 8,
        'semantic_chunks_preserved': 2,
        'title_only_chunks_before': sum(c['title_only'] for d in comparisons for c in d['before']),
        'title_only_chunks_after': sum(c['title_only'] for d in comparisons for c in d['after']),
        'within_target': sum(c['target_status'] == 'within_400_600' for d in comparisons for c in d['after']),
        'short_coherent_exceptions': sum(c['input_tokens'] < 400 for d in comparisons for c in d['after']),
        'over_600': 0, 'source_text_lost_or_rewritten': False,
        'all_26_original_chunks_preserved_once': True, 'source_reference_validation': 'passed',
        'both_documents_have_problem_goal_and_architecture_in_one_chunk': True,
        'all_six_tables_with_titles_and_source_rows_preserved': True,
        'new_inference_calls': 0, 'embeddings_generated': 0, 'production_index_changed': False,
        'search_evaluation_performed': False, 'baseline_hashes_unchanged': True,
        'baseline_hashes': hashes_after,
        'limitations': ['Reviewed outline for two documents only; no generalized production chunker.',
                       '400-token lower bound is not met for all coherent source sections.',
                       'Existing PDF extraction repetitions are preserved, not silently deduplicated.',
                       'No search quality claim follows from structural checks alone.'],
    }
    write('verification.json', verification)
    write('embedding-inputs-candidate.json', after_inputs)
    # A reviewable, standalone comparison. It does not access the running search UI.
    esc = html.escape
    page_html = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>D-001·D-002 청킹 비교</title>',
      '<style>body{font:16px/1.65 -apple-system,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#182333;background:#fafbfc}h1,h2{line-height:1.3}table{border-collapse:collapse;width:100%;background:white;margin:20px 0}td,th{border:1px solid #dbe2ea;padding:10px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f0f3f8;padding:16px;font:14px/1.65 monospace}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}.box{border:1px solid #dbe2ea;border-radius:10px;padding:16px;margin:12px 0;background:white}summary{cursor:pointer;font-weight:600}.good{color:#08795d}.short{color:#9a5900}@media(max-width:800px){.grid{grid-template-columns:1fr}}</style>',
      '<h1>D-001·D-002 재청킹 비교</h1><p>격리된 로컬 실험입니다. 기존 자료·운영 색인 보존. 임베딩·LLM·검색 재평가 없음.</p>',
      '<p><b>목표: 전체 입력 400~600토큰.</b> bge-m3 토크나이저의 기존 모델 해시 일치, 기존 28개 입력의 토큰 수 재현. 관련 없는 구역을 붙여 최소 길이를 채우지 않았습니다.</p>',
      '<p>원문 청크 26→8개. 제목 단독 4→0개. 새 원문 청크 2개는 목표 범위, 6개는 짧은 예외입니다. 의미 보강 2개는 그대로 유지합니다.</p>']
    report = ['D-001·D-002 재청킹 실험 — 기존 결과 보존',
              '목표: bge-m3 전체 입력 400~600토큰. 실제로 목표 2/8, 짧은 예외 6/8.',
              '기존 26개 원문 청크 → 8개. 기존 의미 보강 2개는 변경 없음.',
              '제목 단독 4→0. 기존 텍스트·원문 위치 보존 검사 통과.', '']
    for d in comparisons:
        did = d['doc_id']
        page_html.append(f'<h2>{did} · {esc(d["source"]["file_name"])}</h2><p>원문 13→4개, 의미 보강 1개 유지. 전체 14→5개.</p>')
        page_html.append('<table><tr><th>새 구역</th><th>출처</th><th>전체 입력 토큰</th><th>판정</th></tr>')
        for c in d['after']:
            status = '목표 범위' if c['input_tokens'] >= 400 else '짧은 예외'
            page_html.append(f'<tr><td>{esc(c["section"])}</td><td>{c["positions"]}</td><td>{c["input_tokens"]}</td><td>{status}</td></tr>')
            report.append(f'{did} {c["section"]}: {c["input_tokens"]}토큰 ({status}) / {c["grouping_reason"]}')
        page_html.append('</table><div class="grid"><section><h3>기존: 원문 청크 13개</h3>')
        for c in d['before']:
            page_html.append(f'<details class="box"><summary>{esc(c["text"][:35])} · {c["input_tokens"]}토큰</summary><p>{esc(c["chunk_id"])}</p><pre>{esc(c["embedding_text"])}</pre></details>')
        page_html.append('</section><section><h3>재청킹: 원문 청크 4개</h3>')
        for c in d['after']:
            page_html.append(f'<details class="box" open><summary>{esc(c["section"])} · {c["input_tokens"]}토큰</summary><p>{esc(c["grouping_reason"])}</p><pre>{esc(c["embedding_text"])}</pre><p>연결된 기존 청크: {len(c["original_parts"])}개 · 표: {len(c["tables"])}개</p></details>')
        page_html.append('</section></div>')
        s = d['semantic_chunk_unchanged']
        page_html.append(f'<details class="box"><summary>변경하지 않은 의미 보강 청크 · {s["input_tokens"]}토큰</summary><pre>{esc(s["embedding_text"])}</pre></details>')
    page_html.append('<h2>검증 범위와 한계</h2><p>각 원문 구절의 문자 범위와 슬라이드·페이지 위치를 검사했습니다. 3~5페이지/슬라이드가 같은 청크에 들어가 5분 현황과 1초 목표를 함께 확인할 수 있습니다. 표 제목·행·총액·부가세 조건도 보존됩니다. 모든 내용의 의미적 완전성 또는 검색 성능 향상을 입증한 것은 아닙니다.</p><p>D-002의 기존 중복 추출 구절은 보존했습니다. 중복은 분량을 늘리기 위해 추가한 것이 아니며, PDF 중복 제거는 별도 검토 대상입니다.</p><p><a href="verification.json">검증 JSON</a> · <a href="D-001-comparison.json">D-001 전체 JSON</a> · <a href="D-002-comparison.json">D-002 전체 JSON</a></p></html>')
    (OUT / 'comparison.html').write_text(''.join(page_html))
    (OUT / 'REPORT.txt').write_text('\n'.join(report) + '\n')
    print(json.dumps({k: v for k, v in verification.items() if k not in ['baseline_hashes', 'limitations']}, ensure_ascii=False))
    print('\n'.join(report))

if __name__ == '__main__':
    main()
