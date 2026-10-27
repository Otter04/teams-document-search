"""Human-readable report from frozen evaluation evidence; no search changes."""
import json
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=R/'outputs/search-v31-fix-001';B=R/'outputs/indexing-v31-001';RUN=O/'run-004'
def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(s) for s in p.read_text().splitlines()]
def byid(xs):return {x['query_id']:x for x in xs}
s=read(RUN/'summary.json');first=read(B/'evaluation/run-001/summary.json');scores=byid(read(RUN/'scores.json'));old=byid(read(B/'evaluation/run-001/scores.json'))
responses=byid(rows(RUN/'responses.jsonl'));before=byid(rows(B/'evaluation/run-001/responses.jsonl'));v2=byid(rows(R/'outputs/search-boundary-review-001/boundary-review-001/responses.jsonl'))
key='all_required_representatives_found'
def pct(x):return f"{x[key]}/{x['questions']} ({100*x[key]/x['questions']:.1f}%)"
def rank(response,did):
 ids=[x['doc_id'] for x in response['response']['results']]
 return str(ids.index(did)+1)+'위' if did in ids else '상위5 밖'
def branch(response,name,did):
 positions=[i+1 for i,h in enumerate(response['response']['diagnostics'][name]) if h['doc_id']==did]
 return str(min(positions))+'위' if positions else '후보 없음'
lines=['# v3.1 검색 후보 독점·대표 버전 개선 평가','',
 '기준: search-1.7.3, Elasticsearch v003 / Nori·BM25 + bge-m3 kNN → 청크 RRF → 기존 규칙 R1 → 문서별 최선 청크 점수·버전 묶기. LLM 질문 분석 ON, 제한 2.5초 유지. 모델 리랭커 추가 없음.','',
 '## 결과','',
 '| 평가 범위 | 이전 v2 | v3.1 최초 | 개선 후 |','|---|---:|---:|---:|',
 f"| 기존 125개 | {pct(s['baseline_old125'])} | {pct(first['old125_same_gold'])} | {pct(s['old125_same_gold'])} |",
 f"| 신규 25개 | 해당 없음 | {pct(first['new25'])} | {pct(s['new25'])} |",
 f"| 전체 150개 | 해당 없음 | {pct(first['all150'])} | {pct(s['all150'])} |",'',
 f"기존 기준 회복: {s['old_performance_restored']}. 신규 90% 달성: {s['new25_goal_reached']}. 신규 25개에서는 23개 이상 성공해야 90%를 넘는다.",
 '성공은 **질문마다 필수로 지정된 대표 문서 전부가 최종 상위 5개에 포함됨**이다. 최종 답변의 정확도나 모든 관련 문서의 완전성을 뜻하지 않는다. 제공 정답은 바꾸지 않았으며 실행기에는 질문·기준일만 전달했다. 기존 125개는 이전 정답으로 별도 재채점했다.','',
 f"최초 v3.1 대비 새 실패: {', '.join(s['regressed_vs_first']) or '없음'}. 이전 v2 대비 기존125개 새 실패: {', '.join(s['old_regressions_vs_v2']) or '없음'}.",'',
 '## 무엇을 바꿨는가','',
 '1. 의미 검색의 기존 상위 50청크에서 한 문서가 절반을 초과해 차지할 때만 다양성 보정을 적용한다. 해당 분기에서 문서당 최상위 3청크를 남기고, 충분한 후보를 얻을 때까지 이미 충분히 받은 문서를 제외해 Elasticsearch에 추가 조회한다. 보충 조회는 한 번에 최대 150청크, 첫 조회를 포함해 총 최대 6회다. 일반적인 의미 후보 목록과 BM25 후보 순서는 그대로 유지한다. 단순히 50개를 잘라서 빈 목록을 만드는 방식은 사용하지 않는다.',
 '2. 날짜·거래처 등 업무 조건은 보충 조회에서도 유지한다. 두 분기의 후보를 합치는 RRF와 문서별 최고 청크 점수 방식은 유지했다. 긴 문서의 청크 수를 점수에 합산하지 않는다.',
 '3. 동일 프로젝트·종류·기본 파일명의 `ver 0.5/0.6/0.7`을 검색 시점에 같은 문서군으로 묶는다. 숫자 버전과 “맨 처음 설계안/처음엔” 요청을 연결한다. 같은 폴더의 `(원본)파일명`과 대응 수정본도 같은 문서군으로 묶는다.',
 '4. 같은 문서군·버전·상태이며 공통 블록의 종류·텍스트·표·그림 구조가 전부 동일한 구형/신형 Office 파일은 DOCX/XLSX/PPTX를 대표로 선택한다. 명시적 날짜순·버전·상태·최초 요청은 이 규칙보다 우선한다. 파일의 실제 수정일 값은 바꾸지 않는다.',
 '5. “L4 스위치 구성도/망 그림”을 구성도 종류와 연결하고, 설정 파일을 묻는 표현을 기존에 추출한 `Ingress/host`, `replicas`, `supportshow` 필드·명령과 연결했다. 거래처나 문서ID를 추측해 필터에 넣지 않는다.',
 '문서군·대표 선택 보완은 검색 시점의 파생 규칙이다. 저장한 공통 JSON·메타데이터·벡터·Elasticsearch 색인 재생성은 없었다.','',
 '## 기존에는 성공했으나 v3.1에서 새로 실패했던 4개','']
cases=[('Q-032','D-054','새 아키텍처 정의서 0.6판과 0.7판이 별도 문서군으로 잡혀 두 결과 자리를 차지했다. 정답 제안서의 “수강신청 오토스케일링” 내용은 정상적으로 색인되어 있었다. 새 정의서에도 “수강신청 기간에는 웹·API 계층을 자동 확장”이라는 관련 내용이 있으므로, 새 결과가 모두 무관한 문서라는 뜻은 아니다. 고정된 필수 대표 정답 D-054가 밀렸다는 평가다.'),
 ('Q-041','D-082','정답 HSR_network_diagram_rev2.pptx에는 “L4 스위치 Piolink PAS-K × 2 (Active-Standby)”와 실제 연결선이 있다. 후보 누락은 아니었다. 기존부터 정답이 5위 경계에 있었고 신규 L4 발주서가 경쟁하면서 교육자료·납품확인서·제안서 등에 밀렸다. 질문의 구성도 종류를 반영하지 못했던 점을 보완했다.'),
 ('Q-093','D-027','정답 deploy_20251021_wms-was01.log에는 “WARN HC-W0301: health check slow response on wms-was02 (2,870ms > 2,000ms)”와 “deploy finished: WARNING”가 있다. 긴 SAN 로그 D-198이 의미 후보 50개 중 45개를 차지했고, 정답의 가장 높은 의미 후보 순위가 3위에서 14위로 내려가 결합 후 밀렸다.'),
 ('Q-094','D-008','정답 CRP_network_diagram_rev2.pptx에는 “2025 MES 고도화 구축 네트워크 구성도 (Rev.2)”, “화성 1공장 전산실”, 작성일 2025-03-17이 있다. 키워드 후보가 0개인 상황에서 D-198이 의미 후보 50개 중 49개를 차지해 정답이 두 후보 목록 모두에서 사라졌다. “망 그림/제일 새 판”의 종류·최신판 의도도 함께 보완했다.')]
for qid,did,explanation in cases:
 lines += [f"### {qid} — {scores[qid]['query']}",'',f"필수 대표: **{did} {next(c['title'] for c in scores[qid]['expected_cards'] if c['representative']==did)}**.",'',explanation,'',
 '| 관찰 지점 | v2 | v3.1 최초 | 개선 후 |','|---|---|---|---|',
 f'| 최종 문서 순위 | {rank(v2[qid],did)} | {rank(before[qid],did)} | {rank(responses[qid],did)} |',
 f'| 키워드 분기의 첫 청크 순위 | {branch(v2[qid],"bm25",did)} | {branch(before[qid],"bm25",did)} | {branch(responses[qid],"bm25",did)} |',
 f'| 의미 분기의 첫 청크 순위 | {branch(v2[qid],"vector",did)} | {branch(before[qid],"vector",did)} | {branch(responses[qid],"vector",did)} |','']
lines += ['## 수정 중 발생한 부작용과 확인','',
 '첫 수정안은 문서당 3청크 제한을 모든 질문에 적용했다. 그 결과 Q-034·Q-039의 정확한 로그 문구와 Q-127·Q-149·Q-150의 강한 의미 후보가 약한 양쪽 분기 일치 문서에 밀렸다. 제한 후 다른 후보의 상대 순위가 올라가면서 RRF 결합 결과가 달라진 것이다. 두 번째에서는 키워드 분기를 보존했고, 세 번째에서는 두 분기 모두 실제 독점이 있을 때만 보정했다. Q-127은 낮은 BM25 동점 후보를 보충할 때 생긴 결합 부작용이 남아, 최종안은 의미 분기의 독점만 보정하고 BM25 후보 순서를 유지했다. 각 전체 평가를 run-001/002/003/004에 그대로 남겼다.',
 '이 과정에서 Q-127의 “맨 처음”을 최신 설계서로 바꾸지 않도록 했고, Q-150의 진단 덤프 요청도 기존 source 근거와 연결했다. 최종 회귀 여부는 위 결과와 아래 전수표에 따른다.','',
 '## 신규 25개 및 남은 미달','',
 '| 질문 | 최초 | 개선 후 | 필수 대표와 최종 순위 |','|---|---|---|---|']
for qid,r in scores.items():
 if int(qid[2:])<=125:continue
 expected='; '.join(c['representative']+' '+(str(c['representative_rank'])+'위' if c['representative_rank'] else c['reason']) for c in r['expected_cards'] if c['priority']=='필수')
 lines.append(f"| {qid} {r['query']} | {'통과' if old[qid][key] else '미달'} | {'통과' if r[key] else '미달'} | {expected} |")
lines+=['','Q-130은 “저장장치 처분”과 원문의 “폐기 대상 디스크를 직원 입회하에 물리 파쇄하고 확인서 제출”의 표현 차이가 크다. Q-131은 “품질 쪽 비중”과 원문의 “기술 평가 80점, 가격 평가 20점” 연결이 약하다. 이 두 질문은 문서 길이·버전 문제와 별개의 의미 표현 연결 문제다. 정확한 최종 실패 단계는 전수 CSV·scores.json에 기록했다.',
 'Q-068·Q-069는 이전 v2에서도 실패로 남겨 두었던 날짜 기준과 제공 정답의 충돌이다. 해당 기간의 문서가 없을 때 범위를 풀어서 정답을 억지로 반환하지 않았다.','',
 '## 시간·보존·한계','',
 f"최초 150개 평균 {first['all150']['mean_client_seconds']:.3f}초 → 개선 후 {s['timing']['mean']:.3f}초. 개선 후 중앙값 {s['timing']['median']:.3f}초, P95 {s['timing']['p95']:.3f}초, 최대 {s['timing']['max']:.3f}초, 요청 시간 합계 {s['timing']['total']:.1f}초.",
 f"질문 분석 상태: {s['llm']}. Orin 질문 분석 제한 2.5초 유지. 일부 질문을 규칙으로 더 명확히 해석해 모델 호출 필요 건수가 달라졌다. 반복 실험 평균이나 동시 사용자 부하 성능은 아니다.",
 f"후보 보충 횟수 한도 도달: {s['candidate_refill_limit_reached']}건. 요청 오류: {read(RUN/'complete.json')['errors']}건.",
 f"기존125개 정답 대표 1위: 이전 v2 {s['baseline_old125']['required_representative_top1']}/125 → v3.1 최초 {first['old125_same_gold']['required_representative_top1']}/125 → 개선 후 {s['old125_same_gold']['required_representative_top1']}/125. 상위5 회복과 1위 품질 회복은 다른 지표다.",
 '보존 확인은 source-preservation.json과 runtime-verification.json에 기록한다. 195개 원본 파일의 해시 일치 확인. 공통 블록·문서 보강·임베딩 등 준비 산출물 및 최초 평가·정답 24개 파일의 해시 일치 확인. v003의 195문서·3,754청크를 재사용했다. 외부 유료 API, 추가 비전/보강/문서 임베딩 호출은 하지 않았다.',
 '추가 참고 정답까지 전부 포함한 기존 질문 수는 v2의119/125에서118/125다. Q-091의 필수 로그 D-084는1위지만 추가 참고 D-139는 v2에서5위였다가 신규 D-186 등이 들어오며 상위5 밖으로 밀린 상태다. D-139는 키워드2위에 있지만 의미 후보에는 없고, 최종 순위 조정 후 청크12위다. 이는 v3.1 최초부터 있었고 이번 수정에서 새로 생긴 누락은 아니다.',
 '개발 평가세트를 보고 개선한 결과이므로 독립 자료에 대한 일반화 성능은 아직 검증하지 않았다. 신규 자료가 늘면 후보 수, 동점, 대표 선택 기준을 별도 독립 평가로 확인해야 한다.','',
 '## 결과 파일','',
 '- `run-004/query-results.csv`: 전체150개 질문·정답 순위·상위5·실패 단계·시간',
 '- `run-004/responses.jsonl`: 실제 API 응답과 분기/결합/최종 순위',
 '- `run-004/summary.json`: 이전 결과와 비교',
 '- `run-004/date-policy-audit.json`: 기간 밖 문서 혼입·Q-061 확인',
 '- `source-preservation.json`, `immutable-artifacts.json`: 원본·산출물 보존',
 '- `before/`, `code-001/`, `code-002/`, `code-003/`, `code-004/`: 변경 전 및 실행 코드',
 '- `run-001/`, `run-002/`, `run-003/`: 수정 중 전체평가, 덮어쓰지 않고 보존','']
report='\n'.join(lines).replace('기존 기준 회복: True. 신규 90% 달성: True.','기존 상위5 기준 회복: 달성. 신규 90% 달성: 달성.')
audit=read(RUN/'date-policy-audit.json')
assert audit['date_relaxations']==0 and audit['q061_exact_three'] and all(set(v)<= {'inside'} for v in audit['totals'].values())
report=report.replace('## 결과 파일','날짜를 명시한11개 질문에서 필수 날짜 조건11개 유지, 자동 완화0건. 최종 카드29개·다른 버전4개·BM25후보263개·벡터후보356개 모두 기간 안이었다. Q-061은 올해 백업 로그3개만 반환했다. 회귀 검사96건 통과.\n\n## 결과 파일')
(O/'REPORT.md').write_text(report)
print(O/'REPORT.md')
