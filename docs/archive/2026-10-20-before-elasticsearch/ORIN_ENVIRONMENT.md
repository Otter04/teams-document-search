# Orin 서빙 모델·설정 및 환경 점검 기록

## 2026-10-20 추가 인덱싱 실행

- 기존 Qwen3.6 AWQ4 서버로 제안서 13개·메모/메일 4개의 의미 보강 17건을 실행했다. 출력은 원문 구절 선택 방식이며 결과와 어시스턴트 교정을 분리 보존했다. 생성 합계 309.19초.
- 사용자가 지정한 기존 `/media/sdcard/models/bge-m3`를 읽기 전용으로 사용했다. 별도 일회성 컨테이너 `rag-bge-m3-index-001`은 기존 vLLM 이미지를 재사용하고 네트워크를 차단했다. 1,089개 입력을 Orin GPU에서 CLS pooling·L2 정규화·FP16 연산으로 처리했고 FP32 1,024차원 벡터를 저장했다. 총 107.15초, 종료 코드 0.
- 임베딩 토큰 최대 563, 한도 8,192, 잘림 0건. Qwen 서버 설정·기존 모델 파일은 변경하지 않았다. bge-m3는 별도 API 서버로 상시 서빙한 것이 아니라 파일을 로딩해 일괄 처리했다.
- Mac에서 FAISS 파일을 만들고 재로드·전체 벡터 재구성을 검증했다. 검색·답변 요청은 실행하지 않았다.

[최종 산출물·모델 해시·복사 기록](../outputs/indexing-110-semantic-vector-001/README.md). 아래 전체 비교 설명은 이전 실행 기록이며 45응답에서 중단한 비교를 재개한 것이 아니다.

## 실제 서빙한 모델과 최종 기록 설정

기록일: **2026-10-20**. 선정 모델 계열은 Qwen3.6-35B-A3B이며, **Orin에 실제로 올린 모델 파일은 `Qwen3.6-35B-A3B-AWQ-4bit`**다. Orin에 이미 저장되어 있던 4비트 양자화 가중치를 Docker 안의 vLLM으로 불러와 Orin에서 직접 추론한다. 이 로컬 평가의 요청을 OpenRouter로 보내는 구조가 아니다.

| 항목 | 기록된 적용 값 |
|---|---|
| 모델 역할 | 파싱 단계의 이미지·스캔 비전 처리, 문서 보강 단계의 메타데이터·요약 생성 |
| Orin 모델 파일 경로 | `/media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit` |
| 양자화 | AWQ 4비트; 실행 시 `awq_marlin` 사용 |
| Docker 컨테이너 | `rag-qwen36` |
| 컨테이너 내부 모델 경로 | `/models/qwen36`, 원본 모델 폴더를 읽기 전용으로 연결 |
| 실행 도구 | vLLM |
| API 모델 이름 | `qwen3.6-35b-a3b` — 요청에서 사용하는 별칭 |
| 전체 문맥 한도 | **49,152토큰**, 입력과 출력의 합계 |
| 평가 요청의 최대 출력 | **16,384토큰**, 문맥 확대 후에도 유지 |
| GPU 메모리 비율 인자 | `0.80` |
| KV 캐시 예산 | **8GiB 직접 지정**; 이 값이 메모리 비율에 따른 자동 캐시 계산보다 우선함 |
| 동시 처리 | 최대 1개 시퀀스 |

4비트 양자화는 모델 가중치를 더 적은 비트로 저장하는 방식이다. 모든 연산과 캐시까지 4비트라는 뜻은 아니다. 저장된 실행 설정의 `dtype`은 `half`, 캐시 자료형은 `auto`다.

기존 OpenRouter 비교는 DeepInfra **FP8** 조건이었고, Orin은 **AWQ 4비트** 조건이다. 모델 계열은 같지만 양자화·장비·실행 환경이 달라 품질과 처리 시간을 다시 비교하고 있다. 이를 양자화만의 효과로 해석하지 않는다. 최종 운영 장비는 DGX Spark 예정이며, 현재 Orin은 로컬 실행 검증 환경이다.

처음에는 문맥 16,384토큰으로 텍스트·이미지 기본 요청을 검증했고, 이후 전체 평가를 위해 49,152토큰으로 늘렸다. 캐시 할당 문제 처리 후 서버 준비와 실제 평가 응답을 확인했다. **이 절은 저장된 배포·실행 기록이며, 문서를 읽는 시점의 서버 생존이나 전체 평가 완료를 보증하지 않는다.**

근거: [서빙 명령](../deploy/orin/serve-local-model.sh), [평가 실행 설정](../outputs/orin-evaluation-run-001/serving-conditions.json), [초기 기본 요청 검증](../outputs/orin-serving-run-001/README.md), [전체 평가 기록](../outputs/orin-evaluation-run-001/README.md), [캐시 오류 처리](../outputs/orin-evaluation-run-001/CACHE_FIX.md).

## 최초 환경 점검 기록 — 2026-10-19

확인 시점: 2026-10-19 17:31–17:33 KST. 사용자 VPN 및 Mac 기본 터미널의 인증된 SSH 연결로 직접 확인했다. **아래는 서버 시작 전의 과거 기록**이다. ‘아직 하지 않았다’와 ‘다음 검증’도 이 점검 시점을 기준으로 하며, 이후 서빙 결과는 위 절을 참고한다.

## 확인 결과

| 항목 | 관측값 |
|---|---|
| 접속 | `ubuntu@192.168.60.40`, SSH 연결 재사용 성공 |
| 장비 | NVIDIA Jetson AGX Orin Developer Kit, aarch64 |
| 메모리 | OS 표시 총 61GiB, 사용 가능 약 57GiB; 시점에 따라 변동 |
| Swap | 약 30GiB, 점검 시 사용량 0 |
| 운영체제 | Ubuntu 22.04.5 LTS |
| Jetson Linux / L4T | 36.4.7, `nvidia-l4t-core=36.4.7-20250918154033` |
| JetPack | `nvidia-jetpack` 메타 패키지 버전은 조회되지 않음. JetPack 버전을 확정하지 않음 |
| 호스트 CUDA SDK | 12.6.11, `/usr/local/cuda-12.6` |
| Docker | 29.0.2, NVIDIA 컨테이너 런타임 등록 확인 |
| 작업 저장소 | `/media/sdcard`, ext4, 전체 469GiB / 여유 약 158GiB, ubuntu 쓰기 가능 |
| 루트 저장소 | 전체 57GiB / 여유 약 18GiB |
| Docker 데이터 | `/media/sdcard/docker` |
| 전력 모드 | `MAXN`, 모드 번호 0; 변경하지 않음 |

## 기존 컨테이너

- `test`: `ghcr.io/nvidia-ai-iot/vllm:latest-jetson-orin`, NVIDIA 런타임, bridge 네트워크, bind mount 없음, 포트 게시 없음.
- `timesfm-test`: `dustynv/pytorch:2.7-r36.4.0`, NVIDIA 런타임, host 네트워크.
- `sdp-api`: 실행 중 및 healthy, 호스트 8000 포트를 사용 중.

컨테이너를 재시작하거나 설정을 바꾸지 않았다. `test` 안에서 패키지 버전과 PyTorch GPU 인식만 점검했다.

## 기존 vLLM 환경

- Python 3.10.19
- PyTorch 2.10.0, 빌드 CUDA 12.6
- vLLM 0.19.0+cu126
- Transformers 4.57.3
- `torch.cuda.is_available() = True`, GPU 이름 `Orin`, compute capability `(8, 7)`
- vLLM 모델 레지스트리에 `Qwen3_5MoeForConditionalGeneration` 존재
- tegrastats 약 2초 관측에서 GPU 사용률 0%. 장시간 부하 상태를 의미하지 않는다.

## 이미 저장된 선정 모델

경로: `/media/sdcard/models/Qwen3.6-35B-A3B-AWQ-4bit`

- 로컬 설정의 architecture: `Qwen3_5MoeForConditionalGeneration`
- 로컬 설정의 model_type: `qwen3_5_moe`
- `vision_config` 존재. tokenizer, chat template, 이미지 및 비디오 전처리 설정 파일 존재.
- 양자화: AWQ, 4비트, group_size 32, version `gemm`; 일부 모듈은 양자화 제외 목록에 포함된다.
- safetensors 인덱스가 참조하는 가중치 파일 6개 모두 존재.
- 가중치 파일 합계 24,969,808,408바이트: 약 25.0GB 또는 23.3GiB. 이는 실행 시 전체 메모리 사용량과 다르다.
- 해당 모델 폴더에서 `.incomplete` 파일은 발견하지 못했다.

폴더명과 로컬 설정을 확인한 것이며, 원 배포처·리비전 대조, 전체 해시 검증 및 실제 로딩은 아직 하지 않았다. 파일 존재만으로 정상 추론을 보증하지 않는다.

## 다음 검증

1. 로컬 모델 출처와 양자화 구성을 확인하고, Orin에서 해당 AWQ·MoE·비전 연산을 실행할 수 있는지 점검한다.
2. 기존 서비스를 유지하면서 별도 RAG 실행 공간과 모델 서버를 구성한다. 현재 `test`에는 모델 디렉터리 mount가 없으므로 그대로 호스트 모델 경로를 읽을 수 있다고 가정하지 않는다. 8000 포트는 이미 사용 중이다.
3. 모델 로딩, 텍스트 1건, 이미지 1건으로 기본 동작과 메모리 사용량을 확인한다.
4. 기존 비전 파싱·문서 보강 평가 입력으로 로컬 모델 결과를 검증한다. OpenRouter 비교 때와 양자화·실행 환경이 다르므로 기존 점수가 그대로 유지된다고 가정하지 않는다.

이번 점검에서는 모델 다운로드·설치·추론, 유료 API 호출, 기존 서비스 변경을 수행하지 않았다.

## 연결 유지

Mac의 VPN과 SSH 터미널을 유지해야 한다. 현재 공유 소켓은 `/Users/kangdongkyoon/.ssh/rag-orin.sock`이다. 비밀번호와 개인키 내용은 이 문서에 저장하지 않는다.
