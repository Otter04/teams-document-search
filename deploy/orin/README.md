# Orin 기존 모델 서빙 명령

2026-10-20 갱신. **현재 명령은 문맥 49,152토큰·직접 지정 캐시 8GiB다.** 이전 16,384토큰 명령의 [기본 요청 성공](../../outputs/orin-serving-run-001/README.md)과 구분한다. 전체 평가 확장 시 자동 캐시 26.81GiB 할당에 실패해 모델 파일 읽기 캐시 반환 등을 포함한 현재 설정으로 서버 준비와 첫 평가 이미지 응답을 확인했다. 전체 평가는 진행 중이다. [전체 평가 상태](../../outputs/orin-evaluation-run-001/README.md)가 현재 실행 근거다. 같은 이름의 컨테이너가 있으면 다시 생성하지 않는다.

## 실행 위치와 경로

`serve-local-model.sh`는 **Orin 호스트**에서 실행한다. Mac이나 기존 `test` 컨테이너 내부에서 실행하지 않는다.

| 목적 | 호스트 | 새 컨테이너 |
|---|---|---|
| 기존 모델 | `/media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit` | `/models/qwen36`, 읽기 전용 |
| 실행 캐시 | `/media/sdcard/rag-runtime/cache` | `/root/.cache`, 쓰기 가능 |
| API | `127.0.0.1:8001` | `0.0.0.0:8000` |

`serve /models/qwen36`가 마운트된 로컬 모델을 직접 읽는다. `--pull never`는 Docker 이미지 다운로드를 막고, Hugging Face 오프라인 환경 변수는 모델 다운로드를 막는다. 누락 파일이 있으면 자동 다운로드 대신 실패하게 된다. 네트워크 자체를 완전히 차단하는 설정은 아니다.

기존 `test` 컨테이너에는 bind mount가 없으므로 별도 `rag-qwen36` 컨테이너를 만든다. 기존 컨테이너를 삭제하거나 재시작하지 않는다. 현재 호스트 8000은 `sdp-api`가 사용하므로 새 서비스는 8001을 사용한다. 이름이나 포트가 이미 사용 중이면 자동 제거·덮어쓰기를 하지 않고 충돌 원인을 확인한다.

확인한 이미지: `ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin`, ID `sha256:410a4d96365aaad0a062c0e73d5fbf25841c671df21f244a1f31c10051fe7e28`. 현재 태그는 이 로컬 이미지에 해당한다. 나중에 태그를 갱신하면 같은 환경이라는 보장은 없다.

## 초기 설정의 의미

현재 변경: 긴 입력 31,628토큰과 기존 출력 상한 16,384토큰을 함께 수용하도록 문맥을 49,152로 늘렸다. `--kv-cache-memory-bytes 8589934592`로 캐시를 8GiB로 지정한다. 이 옵션이 있으면 `--gpu-memory-utilization 0.80`에 기반한 캐시 자동 계산을 사용하지 않으므로 "실제 80% 사용"으로 해석하면 안 된다. 이미지 토큰 사전 계산 후 재사용 캐시 불일치를 우회하기 위해 `--mm-processor-cache-gb 0`도 적용했다. 가중치, 캐시 dtype, 이미지 해상도, 프롬프트, 출력 상한은 바꾸지 않았다. 아래 16,384토큰 설명은 최초 기본 요청 검증 이력이다.

- AWQ 구성은 로컬 `config.json`에서 자동 감지하도록 두었다. `--dtype half`는 비양자화 연산의 FP16 선택이며, 저장된 AWQ 가중치를 FP16 전체 모델로 다시 다운로드한다는 뜻이 아니다.
- 사용자 요청에 따라 메모리 비율을 0.80으로 올리고, 문맥은 기존의 두 배인 16,384토큰으로 설정했다. 문맥 한도는 입력·이미지 토큰·생성 출력이 함께 사용한다. 전체 평가에서 긴 입력이 있으면 확대 검토가 필요하다.
- 동시 요청 1개, 요청당 이미지 최대 1장·비디오 0개로 첫 구동을 확인한다. 여러 페이지는 우선 페이지별 요청으로 처리한다.
- 메모리 이용 비율 0.80은 vLLM의 메모리 예산 설정이다. GPU 연산 사용률을 80%로 제한한다는 뜻이 아니다. Orin은 CPU와 GPU가 메모리를 공유하므로 실제 모델 로딩 시 여유 메모리를 확인해야 한다. 실제 사용량이나 다른 프로세스와의 무충돌을 보증하지 않는다.
- `--enforce-eager`로 CUDA graph/컴파일 최적화 경로를 줄여 첫 구동을 단순화한다. 최종 속도 튜닝 결과는 아니다.
- 기본 요청은 `enable_thinking=false`로 하여 이전 문서 보강 비교의 비추론 설정에 맞춘다. 개별 요청에서 덮어쓸 수 있다. `reasoning-parser`는 모델 출력의 추론 구분을 위한 옵션이며 그 자체로 추론을 켜는 옵션이 아니다.
- temperature·top_p·출력 길이 등의 평가 조건은 평가 요청에서 명시한다. 이 서버 명령만으로 이전 OpenRouter 평가 조건이 재현되는 것은 아니다.

## 실행 후 확인 명령 — Orin 호스트

```bash
docker logs -f --tail 100 rag-qwen36
```

로그 보기는 Ctrl+C로 종료해도 컨테이너를 중지하지 않는다. 컨테이너 ID가 반환된 것만으로 모델 준비 완료를 판단하지 않는다. 다른 터미널에서 준비 상태를 확인한다.

```bash
curl --fail http://127.0.0.1:8001/health
curl --fail http://127.0.0.1:8001/v1/models
curl --fail http://127.0.0.1:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-35b-a3b","messages":[{"role":"user","content":"한국어로 짧게 인사해 주세요."}],"max_tokens":64,"temperature":0.2,"chat_template_kwargs":{"enable_thinking":false}}'
```

텍스트 응답 확인과 이미지 추론 확인은 별개다. 이미지 요청은 기존 평가 이미지의 base64 data URL로 별도 검증한다.

## Mac에서 접속

서버가 준비된 뒤 **Mac에서** 현재 인증된 SSH 연결에 터널을 추가한다.

```bash
ssh -S /Users/kangdongkyoon/.ssh/rag-orin.sock \
  -O forward -L 127.0.0.1:18001:127.0.0.1:8001 \
  ubuntu@192.168.60.40

curl --fail http://127.0.0.1:18001/v1/models
```

Mac RAG 실행기의 API 주소는 `http://127.0.0.1:18001/v1`, 모델 이름은 `qwen3.6-35b-a3b`이다. VPN과 SSH 연결을 유지해야 한다. Orin의 API 포트는 외부 인터페이스에 공개하지 않았다.

## 근거와 검증 범위

- [직접 확인한 Orin 환경](../../docs/ORIN_ENVIRONMENT.md)
- [NVIDIA Jetson AI Lab의 Orin AWQ 실행 예시](https://github.com/NVIDIA-AI-IOT/jetson-ai-lab/blob/main/src/content/models/qwen3-6-35b-a3b.md): 최초 제안은 AWQ 경로, 문맥 8192 및 메모리 비율 0.7을 참고했다. 현재는 사용자 요청으로 문맥 16384, 메모리 비율 0.80을 적용했고 실제 구동과 기본 요청 테스트를 완료했다. 이 예시의 일반 최신 이미지 다운로드·host 네트워크·MTP 설정을 그대로 적용하지 않았다. 해당 페이지는 텍스트 예시이므로 비전 성공의 근거로 사용하지 않았다.
- [AWQ 배포 모델 카드](https://huggingface.co/cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit): 비전 인코더 모델이라는 설명 참고. 로컬 파일과 현재 온라인 리비전의 완전 동일성을 검증한 것은 아니다.

Orin에서 실제 AWQ-Marlin 모델 로딩, 텍스트 요청, 계약서 이미지 요청이 성공했다. API 요청에서 `"response_format":{"type":"json_object"}`를 주면 이번 테스트에서는 코드블록 없이 JSON이 반환됐다. 이 옵션은 서버 실행 인자가 아니라 요청 본문에 넣는다. 전체 공통 블록 규격 검증은 별도로 필요하다.
