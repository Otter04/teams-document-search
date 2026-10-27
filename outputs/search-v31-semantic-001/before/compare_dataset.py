"""Compare completed runs offline, including regressions and every supplied question."""
import argparse,collections,hashlib,json,math,statistics
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',type=Path,required=True)
    ap.add_argument('--after',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--focus',nargs='+',default=['Q-075','Q-081','Q-082','Q-084','Q-099'])
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    def read(run,name):return json.loads((run/name).read_text())
    before=read(args.before,'scores.json');after=read(args.after,'scores.json')
    assert len(before)==len(after)==99
    assert all(a['query_id']==b['query_id'] and a['query']==b['query'] for a,b in zip(before,after))
    for run in [args.before,args.after]:assert read(run,'complete.json')['errors']==0
    gold=Path('datasets/search-gold-v2/search_gold.jsonl')
    expected_hash='cfe07b187b4f76c8db5d64ce701ae02dfecc850c835c13032b46cf3c221788d0'
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==expected_hash
    assert read(args.before,'freeze.json')['inputs_sha256']==read(args.after,'freeze.json')['inputs_sha256']
    bs=read(args.before,'summary.json');as_=read(args.after,'summary.json')
    keys=['answer_any_hit','all_required_families_found','all_required_representatives_found']
    change={k:{'improved':[b['query_id'] for a,b in zip(before,after) if not a[k] and b[k]],
               'regressed':[b['query_id'] for a,b in zip(before,after) if a[k] and not b[k]]} for k in keys}
    change['top5_order_identical']=[b['query_id'] for a,b in zip(before,after) if a['top5']==b['top5']]
    change['gold_sha256']=expected_hash;change['before']=str(args.before);change['after']=str(args.after)
    def runtime(run):
        rows=list(map(json.loads,(run/'responses.jsonl').read_text().splitlines()))
        times=sorted(r['client_seconds'] for r in rows)
        return {'mean_seconds':statistics.mean(times),'p95_seconds':times[math.ceil(len(times)*.95)-1],
          'llm_statuses':dict(collections.Counter(r['response']['query_plan']['llm'].get('status','not_called') for r in rows))}
    change['runtime']={'before':runtime(args.before),'after':runtime(args.after)}
    (args.output/'comparison.json').write_text(json.dumps(change,ensure_ascii=False,indent=2)+'\n')
    lines=['# 99개 검색 평가: 보완 전후 비교','',
      '같은 질문·정답·기준일(2026-10-14), B/R1로 Orin 실제 API를 호출한 결과다. 정답은 검색 서버에 전달하지 않았다.',
      '110문서·1,089청크·bge-m3 벡터를 재사용했고 검색 규칙과 후보 전달·대표 버전 선택만 바꿨다.',
      '', '| 평가 범위 | 정답 하나 이상: 이전 → 이후 | 필수 대표 문서 모두: 이전 → 이후 |',
      '|---|---|---|']
    for label,key in [('기존 61','기존'),('조건 점검 8','추가'),('새 간접 표현 30','애매형'),('전체 99',None)]:
        a=bs['by_origin'][key] if key else bs['all'];b=as_['by_origin'][key] if key else as_['all'];n=b['questions']
        def pair(k):return f"{a[k]}/{n} ({a[k]/n:.2%}) → **{b[k]}/{n} ({b[k]/n:.2%})**"
        lines.append(f"| {label} | {pair('answer_any_hit')} | {pair('all_required_representatives_found')} |")
    lines+=['','필수 대표 문서 모두: 정답에서 필수로 지정한 문서가 실제 상위 5개 카드에 모두 표시돼야 통과한다. 다른 버전 목록에 접혀 있는 것은 통과로 세지 않는다. 이 지표는 반환 목록 전체가 정답 목록과 동일하다는 뜻은 아니다.',
      '', '## 개선 대상 '+str(len(args.focus))+'개', '', '| 질문 | 목표 문서 | 이전 | 이후 |', '|---|---|---|---|']
    for qid in args.focus:
        a=next(r for r in before if r['query_id']==qid);b=next(r for r in after if r['query_id']==qid)
        for card in [c for c in b['expected_cards'] if c['priority']=='필수']:
            old=next(c for c in a['expected_cards'] if c['representative']==card['representative'])
            lines.append(f"| {qid} {b['query']} | {card['representative']} · {card['title']} | {old['representative_rank'] or old['reason']} | {str(card['representative_rank'])+'위' if card['representative_rank'] else card['reason']} |")
    lines+=['', '## 회귀와 남은 실패', '']
    for k,v in change.items():
        if isinstance(v,dict) and 'regressed' in v:lines.append(f"- {k}: 새 성공 {', '.join(v['improved']) or '없음'}, 성공→실패 {', '.join(v['regressed']) or '없음'}")
    lines+=['', '상위 5개 문서와 순서가 같은 질문: '+str(len(change['top5_order_identical']))+'/99. 정확도 유지와 순서 불변은 다르다.',
      '', '| 남은 실패 | 질문 | 필수 정답의 실제 위치 |', '|---|---|---|']
    for r in after:
        if r['all_required_representatives_found']:continue
        details='; '.join(c['representative']+': '+(str(c['representative_rank'])+'위' if c['representative_rank'] else c['reason']) for c in r['expected_cards'] if c['priority']=='필수')
        lines.append(f"| {r['query_id']} | {r['query']} | {details} |")
    lines+=['','## 시간·보존·한계','']
    for label,t in change['runtime'].items():
        lines.append(f"- {label}: 평균 {t['mean_seconds']:.3f}초, p95 {t['p95_seconds']:.3f}초, LLM 상태 {t['llm_statuses']}")
    lines+=['- 오류 없는 99응답을 확인했다. 외부 유료 API는 사용하지 않았다.',
      '- 원본 정답 SHA256: `'+expected_hash+'`. 이전 응답과 점수도 보존했다.',
      '- 개발 질문을 보고 개선한 뒤 재평가한 성적이다. 별도 독립 운영 자료에서의 성능을 보장하지 않는다.',
      '- LLM 시간 초과 뒤 규칙 처리는 LLM 조건 분석 성공이 아니다. 요청한 정답이 1위라는 뜻도 아니다.',
      '- [99개 개별 결과](ALL_RESULTS.md) · [최종 점수 JSON](../'+args.after.name+'/scores.json) · [CSV](../'+args.after.name+'/query-results.csv)',
      '- [날짜 처리와 검색 설계](../../docs/SEARCH_DESIGN.md)']
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    lines=['# 99개 질문의 실제 결과','', '| 질문 | 필수 정답: 이전 → 이후 순위 | 이후 상위 5개 | 통과 |','|---|---|---|---|']
    for a,b in zip(before,after):
        old={c['representative']:c['representative_rank'] for c in a['expected_cards']}
        exp='; '.join(f"{c['representative']}: {old[c['representative']] or '없음'} → {c['representative_rank'] or '없음'}" for c in b['expected_cards'] if c['priority']=='필수')
        actual='<br>'.join(f"{c['rank']}. {c['doc_id']} {c['title']}" for c in b['top5'])
        lines.append(f"| {b['query_id']} {b['query']} | {exp} | {actual} | {'성공' if b['all_required_representatives_found'] else '실패'} |")
    (args.output/'ALL_RESULTS.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(change,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
