"""Human-readable comparison; does not turn pending jobs/reviews into successes."""
from adapter import *
from evaluate import vision, enrichment, integrity
from evaluate_policy_v2 import evaluate as evaluate_policy_v2
import fcntl

def fraction(n,d):return f'{n}/{d} ({100*n/d:.2f}%)' if d else '미집계'
def seconds(x):return f'{x:.2f}초' if x is not None else '미집계'

def main():
    v=vision();e=enrichment();iv=integrity()
    policy=evaluate_policy_v2([r['doc_id'] for r in e['records']])
    write(OUT/'enrichment-policy-v2.json',policy)
    ps,pb=policy['summary']['orin'],policy['summary']['openrouter']
    vs,bs=v['orin'],v['openrouter_same_inputs'];es,eb=e['orin'],e['openrouter_same_inputs']
    done=v['complete'] and e['complete']
    run_status=read(OUT/'run-status.json') if (OUT/'run-status.json').exists() else {}
    state_label='전체 생성 응답 수집 완료' if done else '진행 중 — 전체 평가 결과 아님'
    if not done and run_status.get('status')=='waiting_for_server':state_label='캐시 수정 후 서버 준비 대기 — 평가 응답 없음'
    elif not done and run_status.get('status','').startswith('blocked'):state_label='실행 중단 — 상태 기록 확인 필요'
    failure_note=''
    if not done and run_status.get('status')=='blocked_server_initialization':
        state_label='평가 시작 전 중단 — 서버 초기화 실패'
        failure_note='\n서버 초기화 실패로 대기 실행기가 정지했다. 최근 발생 시각과 오류는 [확인 기록](run-status.json), 시도별 원인은 [캐시 수정 기록](cache-fix.json)을 참조한다. 모델 생성 응답이 없으면 정확도·시간 비교는 불가능하다.\n'
    text=f'''# Orin 로컬 모델과 기존 OpenRouter 비교

상태: **{state_label}**. 비전 {v['received']}/132장, 문서 보강 {e['received']}/20문서.
{failure_note}

## 비교 조건

- 선정 모델 Qwen3.6-35B-A3B를 비교한다. 기존 결과는 OpenRouter → DeepInfra FP8, 이번 결과는 사내 Orin AWQ 4비트다.
- 기존 원본 이미지, 네이티브 문맥, 시스템 프롬프트, JSON 스키마와 요청별 생성 설정을 유지했다. 메시지와 요청 해시 대조 기록이 있다.
- 원래 출력 상한 16,384토큰을 유지한다. 가장 긴 보강 입력은 31,628토큰이므로 사용자 승인으로 서버 문맥을 49,152토큰으로 확대했다. 자동 캐시 26.81GiB 할당 실패 후 캐시를 8GiB로 직접 지정했다. 이 직접 지정이 80% 기반 캐시 자동 계산보다 우선한다. 입력을 자르거나 요약해서 넣지 않았다.
- `/tokenize`와 이미지 생성 요청 사이의 미러 캐시 불일치를 우회하기 위해 이미지 전처리 재사용 캐시를 껐다(`mm_processor_cache_gb=0`). 모델 입력과 이미지 해상도는 그대로다. 생성 전 HTTP 500으로 실패한 첫 요청은 `history/mm-cache-failure/`에 보존하며 재시도 완료 응답과 중복 집계하지 않는다. 준비 실패는 운영 오류이며 내용 정확도와 분리한다.
- `skip_mm_profiling`으로 초기 최대 크기 가상 이미지 메모리 점검을 생략한다. 실제 이미지 입력과 비전 추론은 유지하며 실제 요청의 성공·메모리 상태로 확인한다. 최초 요청에는 필요한 연산 준비 시간이 포함될 수 있다.
- API 모델 이름과 제공자 라우팅, 비추론 옵션의 표현만 로컬 API 방식으로 변환했다. 원응답에는 실제 로컬 모델 ID를 보존하며 DeepInfra 응답으로 가장하지 않는다.
- 비전은 기존 전체 132장 실험의 원래 프롬프트를 사용했다. 후속 7장 프롬프트 수정 실험을 섞지 않는다.
- 보강은 기존 검수된 공통 입력 20개로 별도 비교한다. 이번 비전 출력을 보강 입력에 섞지 않아 두 단계의 오류를 분리한다. 연쇄 처리 전체의 평가와는 다르다.
- 기존 결과는 한 번의 저장된 실행이다. 하드웨어, 양자화, 실행기 및 JSON 생성 제약 구현이 달라 순수 모델 또는 양자화 하나의 효과를 분리할 수 없다.
- 새 유료 API 호출은 0건. OpenRouter 키를 읽거나 새로 요청하지 않았다.

## 비전 — 완료된 동일 자료끼리 비교

| 지표 | 기존 OpenRouter Qwen3.6 | Orin Qwen3.6 |
|---|---|---|
| 원문 항목 보존 | {fraction(bs['all']['compatible'],bs['all']['total'])} | {fraction(vs['all']['compatible'],vs['all']['total'])} |
| 스캔·시각 전사 대상 항목 보존 | {fraction(bs['scan']['compatible'],bs['scan']['total'])} | {fraction(vs['scan']['compatible'],vs['scan']['total'])} |
| 완결 JSON | {fraction(bs['json_complete'],bs['images'])} | {fraction(vs['json_complete'],vs['images'])} |
| v3 검증 후 공통 블록 전달 | {fraction(bs['transferred'],bs['images'])} | {fraction(vs['transferred'],vs['images'])} |
| 경고를 동반한 전달 | {bs['warning_images']}장 | {vs['warning_images']}장 |
| 표 셀 내용·행열 구조 회수 | {fraction(bs['table_structure']['correct'],bs['table_structure']['expected'])} | {fraction(vs['table_structure']['correct'],vs['table_structure']['expected'])} |
| 구성도 연결 관계 회수 | {fraction(bs['graph_edges']['correct'],bs['graph_edges']['expected'])} | {fraction(vs['graph_edges']['correct'],vs['graph_edges']['expected'])} |
| 원문 문구 중복 감지 | {bs['duplicate_images']}장 | {vs['duplicate_images']}장 |
| 요청 전체 시간 중앙값 | {seconds(v['timing']['openrouter_same_inputs']['median_seconds'])} | {seconds(v['timing']['orin']['median_seconds'])} |
| 보고된 입력 토큰 합계 | {v['timing']['openrouter_same_inputs']['input_tokens']} | {v['timing']['orin']['input_tokens']} |
| 보고된 출력 토큰 합계 | {v['timing']['openrouter_same_inputs']['output_tokens']} | {v['timing']['orin']['output_tokens']} |

원문 항목 보존은 기존 평가기의 공백·일부 표기 정규화 기준을 그대로 사용한다. 잘린 JSON에서 읽을 수 있는 접두 내용도 내용 진단에는 포함하지만, 공통 블록 전달에는 사용하지 않는다. 네이티브 문맥이 제공된 126장과 원문 시각 전사 참조 6장을 구분한다. 이 참조는 AI 검수 개발 자료이며 독립 사람 정답이 아니다. 경고 전달은 내용 정확도 승인과 다르다.

## 문서 보강 — 완료된 동일 자료끼리 비교

| 지표 | 기존 OpenRouter Qwen3.6 | Orin Qwen3.6 |
|---|---|---|
| 필요한 메타데이터 값 일치 | {fraction(eb['value_only']['matches'],eb['value_only']['needed'])} | {fraction(es['value_only']['matches'],es['value_only']['needed'])} |
| 채운 메타데이터 값 정확도 | {fraction(eb['value_only']['matches'],eb['value_only']['filled'])} | {fraction(es['value_only']['matches'],es['value_only']['filled'])} |
| 엄격 JSON 파싱 | {fraction(eb['strict_json'],eb['documents'])} | {fraction(es['strict_json'],es['documents'])} |
| 기존 v1 상태·근거 형식 전달 기준 | {fraction(eb['delivery_valid'],eb['documents'])} | {fraction(es['delivery_valid'],es['documents'])} |
| 요청 전체 시간 중앙값 | {seconds(e['timing']['openrouter_same_inputs']['median_seconds'])} | {seconds(e['timing']['orin']['median_seconds'])} |

값 일치 진단과 전체 전달 합격은 별개다. 근거 ID, 인용, 필드 상태가 틀린 응답은 값이 맞아도 자동 전달 합격으로 간주하지 않는다. 요약의 의미상 사실성·핵심 내용 포함률은 실제 요약을 원문과 별도 검수하기 전에는 점수를 부여하지 않는다.

## 근거 표기 정리 v2 — 동일 응답 재평가

| 지표 | 기존 OpenRouter 응답 | Orin 응답 |
|---|---|---|
| 기존 v1 전달 기준 | {fraction(pb['before_valid'],pb['documents'])} | {fraction(ps['before_valid'],ps['documents'])} |
| v2 파일명 표기 정리 후 전달 기준 | {fraction(pb['after_contract_valid'],pb['documents'])} | {fraction(ps['after_contract_valid'],ps['documents'])} |
| 기존 정답으로 값·메타데이터 근거까지 확인한 후보 | {fraction(pb['metadata_audited_candidates'],pb['documents'])} | {fraction(ps['metadata_audited_candidates'],ps['documents'])} |

전체 파일명과 정확히 일치할 때만 `file_name:` 같은 접두어와 명확한 source 경로 별칭을 정리한다. 값·본문 인용·날짜 역할·상태·JSON 오류는 수정하지 않는다. 원응답·정답·프롬프트는 보존하며 재평가를 위한 모델 호출은 없다. 값 정확도와 생성 시간은 바뀌지 않는다.

마지막 행은 정답이 있는 평가 자료의 오프라인 추가 검사다. 정답이 없는 운영 자료의 모든 의미 오류를 자동 검출한다는 뜻이 아니다. 다른 근거 위치는 검토 대기로 남긴다. 요약 의미 검수와 실제 색인 반영은 별도이며, 형식 통과를 운영 승인으로 간주하지 않는다.

[v2 상세 결과](enrichment-policy-v2.json) · [변경 시점의 고정 전후 비교](../enrichment-delivery-policy-v2/README.md) · [검증 기준과 재사용 범위](../../docs/ENRICHMENT_DELIVERY_POLICY.md)

## 시간 해석과 보존

시간은 요청 전송부터 전체 응답 수신까지다. 서버 시작 시간은 제외하며 전처리·대기·생성·통신 시간을 포함한다. Orin 평가 실행기는 Orin 내부의 루프백 주소로 요청하므로 Mac과 VPN 통신 시간은 제외한다. 기존 OpenRouter 시간에는 외부 네트워크 통신이 포함된다. 출력 길이도 함께 보존한다. 동일 원본 이미지와 메시지를 전송해도 제공자의 내부 이미지 전처리나 사용량 집계 방식이 달라 보고된 입력 토큰 수가 같다는 보장은 없다. 차이 원인을 확인하지 않고 해상도 또는 비용 차이라고 단정하지 않는다. Orin은 한 번에 한 요청을 보내며, 다른 기존 서비스가 있는 장비다. 과거 클라우드 실행과 완전히 통제된 속도 실험은 아니다.

기존 파일 {iv['checked_files']}개 해시 검사: 변경 {len(iv['changed'])}개. 기존 정답·응답·평가 결과를 수정하지 않았다.

- [요청과 실행 범위](manifest.json), [진행 상태](progress.json), [실행 로그](progress.log)
- [비전 상세 점수](vision-evaluation.json), [보강 상세 점수](enrichment-evaluation.json)
- `results/`: 실제 요청 해시·원응답·시간·시도 기록. 자동 재호출 없음.
- `vision-common-blocks/`: 기존 네이티브 블록을 보존하고 v3 판정을 통과한 로컬 비전 결과만 추가한 평가용 공통 블록 사본. 운영 색인에 자동 반영하지 않았다.
- [요약 검수 준비](semantic-review.template.json), [기존 파일 보존 검사](integrity.json)
'''
    (OUT/'README.md').write_text(text)
    print('Report updated:',v['received'],e['received'])

if __name__=='__main__':
    # Heartbeat/manual refresh and the existing watcher must not race on outputs.
    with (OUT/'.report.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        main()
