"""Offline independent checks and report. No imports of API runners."""
from pathlib import Path
import json,hashlib,math,statistics,collections
O=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text())
manifest=read(O/'manifest.json');qs=read(O/'inputs.json');labels={x['query_id']:x for x in read(O/'labels.json')}
rows=[read(O/'queries'/q['query_id']/'result.json') for q in qs];assert len(rows)==82
for r in rows:
 qid=r['id'];d=O/'queries'/qid;label=labels[qid]
 for stage in ('keyword','semantic','rrf','reranker'):
  hh=r[stage];assert len(hh)<=50 and len(hh)==len({h['chunk_id'] for h in hh})
  ranks={h['chunk_id']:i for i,h in enumerate(hh,1)}
  answer=[min((ranks[c] for c in g if c in ranks),default=None) for card in label['cards'] for g in card['anchor_groups']]
  rank=max(answer) if all(v is not None for v in answer) else None
  assert r['metrics'][stage]['anchor_ranks']==answer and r['metrics'][stage]['complete_rank']==rank
  for n in (10,20,50):assert r['metrics'][stage]['at'][str(n)]==(rank is not None and rank<=n)
 scores=collections.defaultdict(float)
 for stage,weight in [('keyword',1),('semantic',2)]:
  for i,h in enumerate(r[stage],1):scores[h['chunk_id']]+=weight/(60+i)
 expected=sorted(scores,key=lambda cid:(-scores[cid],cid))[:50]
 assert expected==[h['chunk_id'] for h in r['rrf']]
 assert all(h['score']==scores[h['chunk_id']] for h in r['rrf'])
 raw=[read(p) for p in sorted(d.glob('rerank-attempt[1234].json')) if not read(p).get('error')];assert len(raw)==1
 raw=raw[0];assert raw['request']['query']==r['query'] and raw['request']['model']=='Qwen/Qwen3-Reranker-8B' and len(raw['request']['documents'])==50
 ss={x['index']:x['relevance_score'] for x in raw['response']['results']};assert set(ss)==set(range(50))
 inds=sorted(ss,key=lambda i:(-ss[i],i+1,r['rrf'][i]['chunk_id']))
 assert [r['rrf'][i]['chunk_id'] for i in inds]==[h['chunk_id'] for h in r['reranker']]
 assert r['metrics']['rrf']['at']['50']==r['metrics']['reranker']['at']['50']
 assert len(list(d.glob('rewrite-attempt*.json')))>0 and not list(d.glob('*second*'))
 assert sum(v for k,v in r['timings'].items() if k!='total')<=r['timings']['total']+.01
for p,h in manifest['source_hashes'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
summary=read(O/'summary.json');all82=summary['metrics']['all82'];names={'keyword':'키워드 Nori/BM25','semantic':'의미 검색 A·B','rrf':'RRF 결합 상위50','reranker':'8B 리랭커'}
lines=['# 2차 Qwen 없이 전체 검색 82질문 새 API 평가','2026-11-11. Qwen A·B 재작성 → bge-m3 질문 임베딩 → 키워드/의미 검색 → RRF → 8B 리랭커 전체를 새로 실행했다. 2차 Qwen, 요구 추출/충족 판정, Min-max는 사용하지 않았다. 문서·버전 묶기 이전의 청크 순위 평가다.','## 전체 82질문 단계별 결과','성공 기준: 등록된 필수 정답 근거 묶음이 모두 상위 N청크 안에 있음. 한 정답 문서의 아무 청크가 있다는 뜻이 아니다. 이전 rrf50-paired-api-20261110과 같은 정답을 고정했다.','| 단계 | 상위10 | 상위20 | 상위50 | 상위50 미발견 |','|---|---:|---:|---:|---:|']
for k,name in names.items():
 x=all82['stages'][k];lines.append('| '+name+' | '+' | '.join(f"{x['at'][str(n)]}/82 ({100*x['at'][str(n)]/82:.2f}%)" for n in (10,20,50))+f" | {x['missing50']} |")
lines+=['## 실행 조건','- 문서 195개·기존 토큰 청크와 벡터 3,022개 재사용. 색인/문서 보강/원본 변경 없음.','- 1차: OpenRouter qwen/qwen3.6-35b-a3b, 기존 A·B 재작성 전용 프롬프트, temperature0·최대300토큰·엄격 JSON 스키마 요청. document/content 요구 추출 프롬프트 아님.','- 질문 임베딩: OpenRouter baai/bge-m3, DeepInfra 고정·대체 공급자 없음. A·B 각 벡터 정규화 후 50:50 결합.','- 키워드: 원문 질문·명사 중심 Nori·사용자/확장 사전 없음·전체 필드 최소일치20%·본문/파일명/표머리글1·문맥2. 검색용 문맥의 파일명 중복 제거 유지.','- 두 분기 각각 최대50. RRF 상수60·키워드:의미1:2. RRF 상위50을 SiliconFlow Qwen/Qwen3-Reranker-8B에 원문 질문과 함께 전달.','- 모델 계산은 모두 API. Elasticsearch 검색·점수 결합·기록과 집계는 로컬 코드. 후보 다양성 등 기존 검색 설정 유지.','- 같은82 질문 중 확인 필요8개도 진단용으로 검색했다. 서비스 자동 답변 성공률과 구분한다.','## 일반 질문74개 / 확인 필요8개','| 집단·단계 | 상위10 | 상위20 | 상위50 |','|---|---:|---:|---:|']
for group in ('normal74','clarify8'):
 x=summary['metrics'][group]
 for k,name in names.items():lines.append('| '+group+' · '+name+' | '+' | '.join(f"{x['stages'][k]['at'][str(n)]}/{x['n']}" for n in (10,20,50))+' |')
lines+=['## 시간과 API 호출','질문별 첫 Qwen 호출 직전부터 최종 리랭커 청크 순위 직후까지의 실측이다. 초기화·작업 대기열·정답 채점·최종 문서 묶기는 제외한다. 요청/응답 저장, JSON 검증, 재시도가 있었다면 실패와 대기 시간은 포함한다. 중단 후 이어진 질문은 최초 시작부터 완료까지 중단 구간도 포함하며, 해당 질문의 재사용된 단계 시간은 새 호출 지연으로 해석하지 않는다. 초기 최대3질문, 빠른 완료 요청 뒤 추가2작업으로 최대5질문을 동시 실행했으므로 독립 단일 사용자 부하에서의 고정 지연은 아니다.','| 구간 | 평균초 | P95초 | 최대초 |','|---|---:|---:|---:|']
for k in ('rewrite','embedding','keyword','semantic','fusion','reranker','total'):
 t=summary['seconds'][k];lines.append(f"| {k} | {t['mean']:.3f} | {t['p95']:.3f} | {t['max']:.3f} |")
lines+=['호출 집계: `'+json.dumps(summary['api_calls'],ensure_ascii=False)+'`','재작성 원문 복귀: `'+json.dumps(summary['rewrite_fallbacks'],ensure_ascii=False)+'`','중단 없이 끝난 질문의 시간: `'+json.dumps(summary.get('uninterrupted_timing'),ensure_ascii=False)+'` · 이어서 처리한 질문: `'+json.dumps(summary.get('resumed_questions'),ensure_ascii=False)+'`','## 검증','82질문 네 단계 정답 근거 순위와 RRF 점수·8B 응답 인덱스를 독립 재계산했다. RRF50과 리랭커50의 후보 집합 및 상위50 성공은 동일함을 확인했다. 기존 입력 해시와 Elasticsearch 원문·벡터 전후 일치를 확인했다. 추가 조건 튜닝, 서비스 배포, 2차 Qwen 호출은 없다.','[질문별 순위·시간](questions.csv) · [설정](manifest.json) · [요약](summary.json)']
text=lines[0]
for prev,line in zip(lines,lines[1:]):text+=('\n' if prev.startswith('|') and line.startswith('|') else '\n\n')+line
(O/'REPORT.md').write_text(text+'\n')
(O/'verification.json').write_text(json.dumps({'questions':82,'stage_metrics_independently_recomputed':328,'rrf_recomputed':82,'reranker_mapping_verified':82,'source_hashes_preserved':True,'second_qwen_calls':0},indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
