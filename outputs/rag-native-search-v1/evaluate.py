#!/usr/bin/env python3
"""Evaluate frozen native chunks and keyword results, without model calls."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import time
import pipeline as p
from pipeline import enrich

spec=importlib.util.spec_from_file_location('original_eval',p.ROOT.parent/'rag-evaluator/evaluate.py')
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)

def compact(text):return ''.join(text.split())
def query_metric(ranking,answers):
    ranking=list(dict.fromkeys(ranking))[:10]
    rank=next((i for i,identity in enumerate(ranking,1) if identity in answers),0)
    return {'first_rank':rank,'hit_at_5':int(0<rank<=5),'rr_at_10':1/rank if rank else 0}
def aggregate(rows):
    return {'queries':len(rows),'hits':sum(r['hit_at_5'] for r in rows),
            'hit_at_5':sum(r['hit_at_5'] for r in rows)/len(rows) if rows else None,
            'mrr_at_10':sum(r['rr_at_10'] for r in rows)/len(rows) if rows else None}

def run(args):
    run=Path(args.run);out=run/'evaluation'
    if out.exists():raise ValueError('new evaluation output required')
    source=p.unique_records(args.parsed);metadata=p.unique_records(args.metadata);chunks=p.unique_records(run/'chunks.jsonl')
    index=enrich.read_json(run/'index.json');provenance=enrich.read_json(run/'provenance.json')
    if not source.keys()==metadata.keys()==chunks.keys()==index['documents'].keys():raise ValueError('document inventory mismatch')
    for name,digest in provenance['outputs'].items():
        if enrich.digest(run/name)!=digest:raise ValueError('frozen output changed before evaluation')
    checks=[{'doc_id':identity,'errors':p.validate_chunks(row,source[identity],metadata[identity])} for identity,row in chunks.items()]
    if any(r['errors'] for r in checks):raise ValueError('chunk validation failed')
    # Index must reflect exactly these chunks and metadata; compare reconstruction.
    if index!=p.build_index(list(chunks.values()),index['clients']):raise ValueError('index does not match frozen chunks')
    docs,strings,queries=legacy.load_gold(Path(args.dataset))
    if source.keys()!=docs.keys():raise ValueError('gold/input document inventory mismatch')
    literal_text={identity:compact('\n'.join(b['text'] for b in p.literals(r))) for identity,r in source.items()}
    body_text={identity:[compact(c['text']) for c in r['chunks']] for identity,r in chunks.items()}
    string_rows=[]
    for item in strings:
        needle=compact(item['text']);identity=item['doc_id'];available=needle in literal_text[identity]
        preserved=any(needle in text for text in body_text[identity])
        string_rows.append({**item,'present_in_native_parse':available,'present_in_single_chunk_body':preserved,
                            'cut':available and not preserved})
    # Only this sanitized input goes into search. No gold filter or answer is passed.
    query_inputs=[{'query_id':q['query_id'],'query':q['query']} for q in queries.values()]
    frozen_results=[];start=time.perf_counter()
    for q in query_inputs:
        result=p.search(index,q['query'],limit=10)
        frozen_results.append({'query_id':q['query_id'],'query':q['query'],**result})
    elapsed=time.perf_counter()-start
    query_rows=[]
    for result in frozen_results:
        q=queries[result['query_id']];ranking=[r['doc_id'] for r in result['results']]
        query_rows.append({'query_id':q['query_id'],'query':q['query'],'type':q['type'],'answers':q['answers'],
            'doc_ids':ranking,**query_metric(ranking,q['answers']),
            'gold_filter_was_supplied_to_search':False,'conditions_verified':False})
    all_chunks=[c for r in chunks.values() for c in r['chunks']]
    table_audit=[a for r in chunks.values() for a in r['table_audit']]
    native_count=sum(r['present_in_native_parse'] for r in string_rows);cut=sum(r['cut'] for r in string_rows)
    total=aggregate(query_rows);bytype={typ:aggregate([r for r in query_rows if r['type']==typ]) for typ in sorted({r['type'] for r in query_rows})}
    summary={'scope':'native_chunking_and_keyword_only_development_baseline','model_called':False,
        'documents':len(chunks),'chunks':len(all_chunks),'index_entries':index['entry_count'],
        'documents_without_native_chunks':[identity for identity,r in chunks.items() if not r['chunks']],
        'schema_reference_and_coverage_valid_documents':len(checks),'source_character_gaps':0,
        'missing_context_headers':sum(not c['context_header'] for c in all_chunks),
        'oversize_character_chunks':sum(c['body_chars']>p.CONFIG['body_char_limit'] for c in all_chunks),
        'max_body_chars':max(c['body_chars'] for c in all_chunks),'token_length_status':'pending_model_selection',
        'table_count':len(table_audit),'tables_with_rule_headers':sum(a['status']=='rule_identified' for a in table_audit),
        'unknown_header_tables':[a['table_id'] for a in table_audit if a['status']=='unknown'],
        'missing_identified_table_headers':0,
        'long_block_fragments':sum('long_block_split' in c['warnings'] for c in all_chunks),
        'split_table_row_fragments':sum('table_row_split' in c['warnings'] for c in all_chunks),
        'required_strings':{'total':len(strings),'available_in_native_parse':native_count,'preserved_in_single_body':sum(r['present_in_single_chunk_body'] for r in string_rows),
                            'cut':cut,'cut_rate':cut/native_count if native_count else None,'missing_at_parse':len(strings)-native_count},
        'native_chunking_gate_passed':cut/native_count<=.01 and not any(c['body_chars']>p.CONFIG['body_char_limit'] for c in all_chunks) and not any(a['status']=='unknown' for a in table_audit),
        'keyword_search':total,'search_by_type':bytype,'search_elapsed_seconds':elapsed,
        'original_90pct_search_gate_passed':total['hit_at_5']>=.9,
        'original_type_gates':{typ:m['hit_at_5']>=.9 for typ,m in bytype.items()},
        'query_reference_date':'2026-10-17','relative_date_interpretation':'not_implemented_in_keyword_baseline',
        'pending_visual_documents':sum(bool(r['pending_visual_units']) for r in chunks.values()),
        'pending_visual_units':sum(len(r['pending_visual_units']) for r in chunks.values()),
        'overall_status':'incomplete','not_evaluated':['vision','embedding','hybrid_search','reranking','model_token_budget','natural_language_filter_generation','latest_version','ACL/live_SharePoint','independent_holdout']}
    out.mkdir()
    enrich.dump(out/'summary.json',summary);enrich.dump(out/'chunk-validation.json',checks)
    enrich.save_lines(out/'string-results.jsonl',string_rows);enrich.save_lines(out/'query-inputs.jsonl',query_inputs)
    enrich.save_lines(out/'search-results.jsonl',frozen_results);enrich.dump(out/'query-results.json',query_rows)
    enrich.dump(out/'failed-queries.json',[r for r in query_rows if not r['hit_at_5']])
    enrich.dump(out/'verification.json',{'index_reconstruction_match':True,'model_called':False,'index_not_modified_during_search':enrich.digest(run/'index.json')==provenance['outputs']['index.json'],
        'query_input_keys':['query_id','query'],'gold_filters_used':False,
        'hashes':{str(Path(path).resolve()):enrich.digest(path) for path in [args.parsed,args.metadata,run/'chunks.jsonl',run/'index.json',Path(args.dataset)/'gold/golden_strings.jsonl',Path(args.dataset)/'gold/queries.jsonl',Path(__file__),p.ROOT/'pipeline.py',p.ROOT/'CONTRACT.md']}})
    lines=['# 네이티브 청킹·키워드 검색 실제 평가','','모델/API 호출 없음. 합성 개발 세트의 첫 키워드 검색 결과이며 전체 하이브리드 검색의 완료 판정이 아닙니다.','',
        f"- 입력 {len(chunks)}문서 → {len(all_chunks)}청크, 색인 {index['entry_count']}항목(문서 항목 포함).",
        f"- 원문 범위·참조 검사 {len(checks)}/{len(checks)}, 문자 누락 0. 본문 최대 {summary['max_body_chars']}자 / 제한 1,200자.",
        f"- 네이티브 파싱에 있던 필수 문자열 {native_count}개 중 잘림 {cut}개 ({cut/native_count:.2%}). 스캔 등 파싱에서 이미 빠진 {len(strings)-native_count}개는 별도 대기.",
        f"- 표 {len(table_audit)}개 중 규칙으로 헤더 확인 {summary['tables_with_rule_headers']}개, 미확정 {len(summary['unknown_header_tables'])}개. 확인된 헤더 누락 0.",
        '- 실제 모델의 토큰 길이 검사는 미실행입니다. 문자 수 제한과 구분합니다.','',
        '## 검색 성적','','| 구분 | Hit@5 | MRR@10 | 기존 90% 기준 |','|---|---:|---:|---|']
    for title,m in [('전체',total)]+list(bytype.items()):lines.append(f"| {title} | {m['hits']}/{m['queries']} ({m['hit_at_5']:.2%}) | {m['mrr_at_10']:.4f} | {'통과' if m['hit_at_5']>=.9 else '미달'} |")
    lines+=['','## 범위와 제한','','자연어 질문만 검색에 전달했습니다. 정답 필터·정답 문서 ID·문서별 정답 메타데이터를 검색에 넣지 않았습니다.',
        '검색은 단어·한국어 음절 2-gram BM25 기준선입니다. 형태소 분석·의미 검색·날짜/최신본 해석·자연어 필터 생성은 아직 없습니다.',
        '정답 문서가 상위 5개에 있다는 것은 요청 조건이나 답변 근거가 완전하다는 뜻이 아닙니다. 각 결과에 conditions_verified=false를 유지합니다.',
        '스캔 문서는 파일명·경로·확정 메타데이터로 검색될 수 있습니다. 본문 청크가 없고 비전 처리가 남았음을 결과에 표시합니다.',
        '표 헤더 판정은 명시적인 열 이름 규칙입니다. 기존 과도한 inferred 목록을 사용하지 않았지만 독립 검수자의 의미 정확도 평가를 대신하지 않습니다.',
        '[실패한 질문](failed-queries.json), [전체 질문별 순위](query-results.json), [검색 근거와 원문 위치](search-results.jsonl), [검증 이력](verification.json)','']
    (out/'report.md').write_text('\n'.join(lines))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','parsed','metadata','dataset'):parser.add_argument('--'+name,required=True)
    run(parser.parse_args())
