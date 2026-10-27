"""Score the frozen 150 questions, preserve all responses, and explain changed ranks."""
import collections
import csv
import html
import json
import statistics
import sys
from pathlib import Path
from prepare import ROOT, OUT, rows, sha, write
sys.path.insert(0, str(ROOT/'deploy/search'))
from score_dataset import score_one, summarize

def stage_ranks(response, did):
    diag = response.get('diagnostics', {})
    result = {}
    for name in ['bm25','vector','rrf_top30','rerank_candidates','ranked_top30']:
        result[name] = next((i for i,r in enumerate(diag.get(name,[]),1) if r['doc_id']==did), None)
    result['final'] = next((i for i,r in enumerate(response.get('results',[]),1) if r['doc_id']==did), None)
    return result

def main():
    gold_path = ROOT/'outputs/indexing-v31-001/evaluation/gold-v31.jsonl'
    gold = rows(gold_path); assert len(gold) == 150
    docs = json.loads((OUT/'search-data/documents.json').read_text())
    scored, responses, summaries, freezes = {}, {}, {}, {}
    for name in ['baseline','candidate']:
        run = OUT/'evaluation'/name
        assert json.loads((run/'complete.json').read_text())['completed'] == 150
        freezes[name] = json.loads((run/'freeze.json').read_text())
        responses[name] = {r['query_id']:r for r in rows(run/'responses.jsonl')}
        assert len(responses[name]) == 150
        scored[name] = [score_one(q, responses[name][q['query_id']], docs) for q in gold]
        summaries[name] = {'all':summarize(scored[name]),
                           'old125':summarize(scored[name][:125]),'new25':summarize(scored[name][125:])}
        write(run/'scores.json', scored[name]); write(run/'summary.json', summaries[name])
    a,b = freezes['baseline'],freezes['candidate']
    for k in ['inputs_sha256','use_llm','filter_mode','reranker']:
        assert a[k] == b[k], k
    for k in ['config','embedding_fingerprint','documents','query_analysis_model']:
        assert a['health'][k] == b['health'][k], k
    success = lambda r: r['all_required_representatives_found']
    old = {r['query_id']:r for r in scored['baseline']}
    new = {r['query_id']:r for r in scored['candidate']}
    regressions = [q for q in old if success(old[q]) and not success(new[q])]
    improvements = [q for q in old if not success(old[q]) and success(new[q])]
    changed = [q for q in old if [x['doc_id'] for x in old[q]['top5']] != [x['doc_id'] for x in new[q]['top5']]]
    details = []
    for q in gold:
        qid = q['query_id']
        if qid not in changed and success(new[qid]):
            continue
        expected = []
        for card in q['expected_cards']:
            if card['priority'] != '필수':
                continue
            did = card['representative']
            expected.append({'doc_id':did,'title':docs[did]['file_name'],
                             **{name:stage_ranks(responses[name][qid].get('response',{}),did) for name in responses}})
        details.append({'query_id':qid,'query':q['query'],'regression':qid in regressions,
                        'before_top5':old[qid]['top5'],'after_top5':new[qid]['top5'],'expected':expected,
                        'after_failure_reasons':[c['reason'] for c in new[qid]['expected_cards'] if c['priority']=='필수' and c['representative_rank'] is None]})
    def plan_without_elapsed(row):
        plan = json.loads(json.dumps(row.get('response',{}).get('query_plan',{})))
        plan.get('llm',{}).pop('elapsed_seconds', None)
        return plan
    # Preserve the raw plans; ignore only measured elapsed time in this equality test.
    plan_changes = [q for q in responses['baseline'] if plan_without_elapsed(responses['baseline'][q]) != plan_without_elapsed(responses['candidate'][q])]
    plans_equal = not plan_changes
    verification = json.loads((OUT/'structural-verification.json').read_text())
    hashes = verification['baseline_hashes']
    assert all(sha(ROOT/p)==h for p,h in hashes.items()), 'Preserved baseline file changed'
    latency = {}
    for name, rs in responses.items():
        seconds = sorted(r['client_seconds'] for r in rs.values())
        llm = [r['response']['query_plan'].get('llm',{}) for r in rs.values()]
        latency[name] = {'mean':statistics.mean(seconds),'median':statistics.median(seconds),
                         'p95':seconds[142],'maximum':max(seconds),
                         'llm_attempted':sum(bool(x.get('attempted')) for x in llm),
                         'llm_used':sum(bool(r['response']['query_plan'].get('used_llm')) for r in rs.values()),
                         'llm_statuses':dict(collections.Counter(str(x.get('status',x.get('reason','not_attempted'))) for x in llm))}
    result = {'scope':'195 v3.1 documents; original 150 development questions; source review OFF',
              'summaries':summaries,'regressions':regressions,'improvements':improvements,
              'changed_top5_queries':changed,'query_plans_identical':plans_equal,'query_plan_equality_ignores_only':'llm.elapsed_seconds','query_plan_changes':plan_changes,
              'latency':latency,'details':details,'baseline_files_unchanged':True,'gold_sha256':sha(gold_path),
              'same_search_configuration':True,'default_service_replaced':False}
    write(OUT/'comparison.json', result)
    with (OUT/'question-comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w = csv.writer(f); w.writerow(['질문 ID','질문','기존 성공','새 청크 성공','필수 정답 문서: 기존→새 순위','기존 상위5','새 상위5','실패 단계'])
        for q in gold:
            qid = q['query_id']; ranks = []
            for c in q['expected_cards']:
                if c['priority']=='필수':
                    did=c['representative']; values=[stage_ranks(responses[n][qid]['response'],did)['final'] for n in ['baseline','candidate']]
                    ranks.append(f'{did}: {values[0]} → {values[1]}')
            w.writerow([qid,q['query'],success(old[qid]),success(new[qid]),'; '.join(ranks),
                        ' / '.join(x['doc_id'] for x in old[qid]['top5']),' / '.join(x['doc_id'] for x in new[qid]['top5']),
                        ', '.join(c['reason'] for c in new[qid]['expected_cards'] if c['priority']=='필수' and c['representative_rank'] is None)])
    report = ['# 전체 문서 토큰 재청킹 비교 — 2026-10-27', '',
      '195개 문서의 기존 파싱·비전·문서 보강 결과를 재사용했다. 기존 v003 색인과 기본 검색 화면은 보존했다. 새 후보는 v004-rechunk / Orin 8023이다.', '',
      '**성공 기준:** 질문에 지정된 필수 정답 대표 문서가 모두 최종 상위 5개에 포함되어야 한다. 질문 하나에 정답이 여러 개이면 전부 필요하다. 개발용 150개 재평가이며 독립 평가·답변 생성 정확도가 아니다.', '',
      '| 범위 | 기존 v003 | 토큰 재청킹 |', '|---|---:|---:|']
    for label,key,n in [('전체','all',150),('기존 125개','old125',125),('v3.1 신규 25개','new25',25)]:
        vals=[summaries[x][key]['all_required_representatives_found'] for x in ['baseline','candidate']]
        report.append(f'| {label} | {vals[0]}/{n} ({vals[0]/n:.1%}) | {vals[1]}/{n} ({vals[1]/n:.1%}) |')
    report += ['',f'- 새 실패: {", ".join(regressions) or "없음"}. 새 성공: {", ".join(improvements) or "없음"}.',
       f'- 정답 문서 1위: {summaries["baseline"]["all"]["required_representative_top1"]}/150 → {summaries["candidate"]["all"]["required_representative_top1"]}/150.',
       f'- 상위 5개 문서 순서가 달라진 질문: {len(changed)}개. 질문 분석 결과 동일 여부: {plans_equal}.',
       '- 검색 설정 동일: search-1.7.4, BM25/Nori + bge-m3, RRF + R1, 문서 대표 선택·날짜 필수 조건 유지. 질문 LLM ON/2.5초, Qwen 원문 대조 OFF.',
       '- 질문 분석의 실제 결정은 150개 모두 동일했다(측정 소요시간 제외). 양쪽 모두 LLM 분석 51회 시도·0회 채택으로 규칙 대체가 적용됐다.',
       '- 필수 문서군 기준은 148/150 → 146/150이다. 지정 대표 파일 기준의 4개 회귀 중 2개는 같은 문서군의 PDF 대신 PPTX가 대표로 선택된 사례이고, 나머지 2개는 정답 문서군이 상위 5개 밖으로 밀렸다.', '',
       '## 새 실패 4개를 쉽게 설명하면', '',
       '| 질문 | 실제 변화 | 확인된 원인 |', '|---|---|---|',
       '| Q-023: 스토리지 300TB 늘리는 제안 | 정답 D-040 PDF 1위 → 같은 제안서 D-039 PPTX 1위 | 정답 PDF 청크는 여전히 키워드 1위·의미 2위에 있다. 다만 문서군에서 점수가 더 높은 PPTX가 대표로 선택됐다. 원문 정보가 사라진 실패가 아니다. |',
       '| Q-079: 한 대 고장 나도 쇼핑몰 운영이 계속되는 제안 | 정답 D-075 PDF 1위 → 같은 제안서 D-074 PPTX 1위 | 키워드 후보는 양쪽 모두 0개. 묶인 청크의 의미 순위에서 PPTX가 PDF보다 앞서면서 대표 파일이 바뀌었다. |',
       '| Q-083: 3억 조금 넘는 예비 전산실 제안 | D-064 5위 → 상위 5개 밖 | 금액 표를 일정·인력·총액과 함께 묶자 D-064의 첫 의미 후보는 8→9위, R1 청크 순위는 7→9위가 됐다. 주변 문맥은 늘었지만 금액 중심 질문에서 다른 제안서를 이기지 못했다. 두 실행 모두 키워드 후보가 없다. |',
       '| Q-097: 교육기관 고객 서버 스펙 정리표 | D-061 1위 → 상위 5개 밖 | 의미 검색에서는 여전히 D-061이 1위다. 합쳐진 다른 청크에 교육·고객·서버 등의 표현이 같이 들어가면서 키워드 후보가 0→14개로 늘었다. 두 검색에 함께 잡힌 제안서들이 결합에서 앞서고, 의미 검색에만 잡힌 D-061 청크는 결합 13위로 밀렸다. |', '',
       '**결론:** 구조적 청킹 개선과 검색 순위 개선은 별개다. 90% 목표는 넘었지만 기존 성공 4개를 잃었으므로, 기본 검색 화면을 새 색인으로 자동 교체하지 않았다. 정답표·대표 선택·결합 가중치를 이번 결과에 맞춰 바꾸지 않았다.', '',
       '| 청킹 검사 | 결과 |','|---|---:|',
       f'| 원문 청크 | {verification["source_chunks_before"]} → {verification["source_chunks_after"]} |',
       f'| 기존 의미 보강 청크 | {verification["semantic_chunks_unchanged"]}개 유지 |',
       f'| 전체 색인 청크 | 3,754 → {verification["total_embedding_inputs"]:,} |',
       f'| 원문 청크 400~600토큰 | {verification["within_400_600"]:,}개 |',
       f'| 원문 청크 400 미만 | {verification["below_400"]:,}개 |',
       f'| 600 초과 / 입력 잘림 | {verification["above_600"]} / 0 |',
       f'| 제목 단독 | {verification["title_only_before"]} → {verification["title_only_after"]} |',
       f'| 페이지·슬라이드를 연결한 청크 | {verification["multi_page_chunks"]}개 |',
       '| 원문 위치 범위·본문 재구성 | 195문서 전수 통과 |', '',
       '토큰 수에는 문서 정보·제목·표 머리글·본문·특수 토큰이 포함된다. 짧은 조항·시트·독립 구역·로그 시간 구간·마지막 잔여 구간은 400토큰에 못 미쳐도 유지한다. 기존 의미 보강 31개는 길이를 늘리지 않았다. 400~600토큰 청크 대부분은 긴 RTF 진단 덤프이며, 분포 자체를 모든 문서의 의미 경계 품질로 해석하면 안 된다.', '',
       '## 처리 시간', '', '| 구분 | 기존 | 재청킹 |', '|---|---:|---:|']
    for label,key in [('평균','mean'),('중앙값','median'),('95백분위','p95'),('최대','maximum')]:
        report.append(f'| {label} | {latency["baseline"][key]:.3f}초 | {latency["candidate"][key]:.3f}초 |')
    manifest = json.loads((OUT/'prepared/embedding-manifest.json').read_text())
    report += ['', '순차 단일 실행 시간이며 동시 부하 검증이 아니다. 재청킹·임베딩 시간과 질의 시간을 혼합하지 않았다.',
               f'새 임베딩 작업은 {manifest["elapsed_seconds"]:.2f}초였다. {manifest["cache_hits"]}개 입력의 벡터를 재사용하고 {manifest["vectors"]-manifest["cache_hits"]}개를 새로 계산했다. 두 서버의 평가 벽시계 시간은 각각 약 191초·195초였다.', '', '## 실패 및 순위 변경 근거', '']
    for d in details:
        if not d['after_failure_reasons'] and not d['regression']:
            continue
        report += [f'### {d["query_id"]}: {d["query"]}', '',
                   '- 기존: '+', '.join(x['doc_id'] for x in d['before_top5']),
                   '- 재청킹: '+(', '.join(x['doc_id'] for x in d['after_top5']) or '결과 없음'),
                   '- 필수 정답 문서에서 나온 **청크**의 단계별 최초 등장 순위(최종 `final`만 문서 순위):']
        for e in d['expected']:
            report.append(f'  - {e["doc_id"]} {e["title"]}: `{e["baseline"]}` → `{e["candidate"]}`')
        report += ['','단계별 순위의 없음(None)은 해당 후보 목록에 없음을 뜻한다. Q-068·Q-069는 기존과 동일하게 명시 날짜 조건을 자동 완화하지 않는 정책과 원래 정답표가 충돌하는 사례다.' if d['query_id'] in ['Q-068','Q-069'] else '후보 단계와 결합 이후의 탈락을 구분한 실제 응답 기록이다. 검색 규칙을 결과에 맞춰 추가 수정하지 않았다.', '']
    report += ['## 보존·검증과 한계', '',
       '- 원문 블록·메타데이터·요약·문서군·버전 정책·Nori 설정 보존. 기존 파일 해시 재확인.',
       '- 새 ES 저장 레코드 3,217개(문서 195 + 청크 3,022) 전수 대조 및 기존 v001/v002/v003 건수 보존 확인은 `search-data/index-verification.json`.',
       '- 날짜 조건 11개는 양쪽 모두 잠금 유지, 자동 완화 0건, 기간 밖·날짜 미확인 혼입 0건. Q-061의 올해 백업 로그 3개도 그대로다. 각 실행의 `date-policy-audit.json` 참조.',
       '- 로컬 bge-m3 토큰 수와 Orin 입력 토큰 수 전수 일치. 새 외부 API·비전·문서 보강 호출 없음. 검색 평가의 기존 질문 분석 요청만 유지.',
       '- 원문 범위 보존은 의미 이해의 완전성을 증명하지 않는다. 표 행·제목·원문 위치·대표 문서 사례를 구조적으로 검사했다. 임의의 새 자료와 자유 표현은 별도 평가가 필요하다.',
       '- [150개 질문 전수 비교](question-comparison.csv) · [기계 판독 결과](comparison.json) · [청킹 검사](structural-verification.json) · [규칙과 실행 방법](../../deploy/rechunk/README.md)', '']
    (OUT/'REPORT.md').write_text('\n'.join(report))
    # Small standalone view: all 150 scores plus concrete D-001/D-002 chunk contents.
    view = ['<!doctype html><html lang="ko"><meta charset="utf-8"><title>전체 재청킹 비교</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#182333}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left}pre{white-space:pre-wrap;background:#f4f6f8;padding:16px}summary{cursor:pointer} .bad{background:#fff1ed}</style><h1>전체 문서 재청킹 비교</h1>',
            '<p>기존 색인 보존 · 후보 v004-rechunk · 원문 대조 OFF · 150개 개발 질문</p>',
            f'<p>필수 정답 상위 5개: {summaries["baseline"]["all"]["all_required_representatives_found"]}/150 → {summaries["candidate"]["all"]["all_required_representatives_found"]}/150</p>',
            '<p><a href="REPORT.md">상세 보고서</a> · <a href="question-comparison.csv">전체 질문 CSV</a></p><table><tr><th>질문</th><th>기존 성공</th><th>새 성공</th><th>새 상위 5개</th></tr>']
    for q in gold:
        qid=q['query_id'];view.append(f'<tr class="{"bad" if qid in regressions else ""}"><td>{qid} {html.escape(q["query"])}</td><td>{success(old[qid])}</td><td>{success(new[qid])}</td><td>{", ".join(x["doc_id"] for x in new[qid]["top5"])}</td></tr>')
    view.append('</table><h2>D-001 · D-002 실제 새 청크</h2>')
    for r in rows(OUT/'prepared/chunks.jsonl'):
        if r['doc_id'] in ['D-001','D-002']:
            for c in r['chunks']:
                view.append(f'<details><summary>{r["doc_id"]} · {html.escape(" / ".join(c["heading_path"]))} · {c["token_count"]}토큰</summary><pre>{html.escape(c["context_header"]+chr(10)+c["text"])}</pre></details>')
    (OUT/'comparison.html').write_text('\n'.join(view))
    print(json.dumps({k:result[k] for k in ['summaries','regressions','improvements','query_plans_identical','latency']},ensure_ascii=False))

if __name__ == '__main__':
    main()
