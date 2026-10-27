"""Score supplied expected cards after evaluation; never modifies search or labels."""
import argparse,collections,csv,json
from pathlib import Path

def members(card):
    return {card['representative']}|{x['doc_id'] for x in card['other_versions']+card['same_file_copies']}

def score_one(gold,row,docs):
    response=row.get('response',{});cards=response.get('results',[]);ids=[x['doc_id'] for x in cards]
    diag=response.get('diagnostics',{});branches={name:{r['doc_id'] for r in diag.get(name,[])} for name in ['bm25','vector']}
    combined={r['doc_id'] for r in diag.get('rrf_top30',[])}
    expected=[]
    for c in gold['expected_cards']:
        group=members(c);found=[d for d in ids if d in group];rep=c['representative']
        rank=ids.index(rep)+1 if rep in ids else None
        if rank:cause='representative_found'
        elif found:cause='different_version'
        elif 'error' in row:cause='request_error'
        elif response.get('status')=='needs_clarification':cause='clarification_requested'
        elif not group&(branches['bm25']|branches['vector']):cause='outside_both_candidate_lists'
        elif not group&combined:cause='outside_combined_top30'
        else:cause='lost_after_combination'
        expected.append({'priority':c['priority'],'family':c['family'],'representative':rep,'title':c['representative_file'],
          'representative_rank':rank,'family_rank':min([ids.index(d)+1 for d in found],default=None),'shown_family_members':found,
          'linked_as_other_version':any(rep==v['doc_id'] for a in cards for v in a.get('other_versions',[])),
          'candidate_branches':[name for name,found_ids in branches.items() if group&found_ids],
          'in_combined_top30':bool(group&combined),'reason':cause})
    required=[c for c in expected if c['priority']=='필수'];assert required
    answer_ids=set(gold['answer_doc_ids']);answer_ranks=[i+1 for i,d in enumerate(ids) if d in answer_ids]
    expected_reps=[c['representative'] for c in expected]
    return {'query_id':gold['query_id'],'query':gold['query'],'origin':gold['origin'],'type':gold['type'],'test_focus':gold['test_focus'],
      'status':response.get('status','request_error'),'top5':[{'rank':i+1,'doc_id':d,'title':docs[d]['file_name']} for i,d in enumerate(ids)],
      'expected_cards':expected,'answer_any_hit':bool(answer_ranks),'mrr_at5':1/min(answer_ranks) if answer_ranks else 0,
      'all_required_families_found':all(c['family_rank'] is not None for c in required),
      'all_required_representatives_found':all(c['representative_rank'] is not None for c in required),
      'all_expected_representatives_found':all(c['representative_rank'] is not None for c in expected),
      'exact_representative_set':set(ids)==set(expected_reps),'exact_representative_order':ids==expected_reps,
      'required_representative_top1':bool(ids) and ids[0] in {c['representative'] for c in required},
      'query_plan':response.get('query_plan',{}),'relaxed_conditions':response.get('relaxed_conditions',[]),
      'seconds':row['client_seconds'],'error':row.get('error')}

def summarize(rows):
    keys=['answer_any_hit','all_required_families_found','all_required_representatives_found',
          'all_expected_representatives_found','exact_representative_set','exact_representative_order','required_representative_top1']
    return {'questions':len(rows),**{k:sum(r[k] for r in rows) for k in keys},
      'mrr_at5':sum(r['mrr_at5'] for r in rows)/len(rows),
      'status':dict(collections.Counter(r['status'] for r in rows)),
      'required_card_failure_reasons':dict(collections.Counter(c['reason'] for r in rows for c in r['expected_cards']
        if c['priority']=='필수' and c['representative_rank'] is None)),
      'failed_required_representative_queries':[r['query_id'] for r in rows if not r['all_required_representatives_found']],
      'mean_client_seconds':sum(r['seconds'] for r in rows)/len(rows)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--gold',type=Path,required=True);ap.add_argument('--run',type=Path,required=True);args=ap.parse_args()
    assert (args.run/'complete.json').exists(),'Score only a completed run'
    gold=[json.loads(s) for s in args.gold.read_text().splitlines() if s.strip()]
    responses={r['query_id']:r for r in map(json.loads,(args.run/'responses.jsonl').read_text().splitlines())}
    assert len(gold)==len(responses) and all(q['query_id'] in responses for q in gold)
    docs=json.loads((Path(__file__).resolve().parents[2]/'outputs/search-service-001/documents.json').read_text())
    scores=[score_one(q,responses[q['query_id']],docs) for q in gold]
    summary={'all':summarize(scores),'by_origin':{o:summarize([r for r in scores if r['origin']==o]) for o in sorted({r['origin'] for r in scores})},
      'new30_by_focus':{f:summarize([r for r in scores if r['origin']=='애매형' and r['test_focus']==f]) for f in sorted({r['test_focus'] for r in scores if r['origin']=='애매형'})}}
    for name,value in [('scores.json',scores),('summary.json',summary)]:
        (args.run/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    with (args.run/'query-results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['질문ID','구분','질문','필수 정답 대표 문서와 실제 순위','실제 상위5','정답 하나 이상','필수 문서군 모두','필수 대표문서 모두','목록 완전일치','상태','실패 단계'])
        for r in scores:
            req=[c for c in r['expected_cards'] if c['priority']=='필수']
            w.writerow([r['query_id'],r['origin'],r['query'],'; '.join(c['representative']+' '+(str(c['representative_rank'])+'위' if c['representative_rank'] else '없음') for c in req),
              '; '.join(str(c['rank'])+'위 '+c['doc_id']+' '+c['title'] for c in r['top5']),r['answer_any_hit'],r['all_required_families_found'],r['all_required_representatives_found'],r['exact_representative_set'],r['status'],
              '; '.join(c['representative']+': '+c['reason'] for c in req if c['representative_rank'] is None)])
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
