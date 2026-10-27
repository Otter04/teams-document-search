# Orin 캐시 오류 처리 기록

2026-10-20. **서버 준비 및 첫 전체 평가 이미지 성공, 전체 평가 진행 중.**

## 확인된 원인과 범위

- 초기 서버는 KV 캐시를 자동으로 26.81GiB로 계산했다. 실제 할당 직전에 `NvMapMemAllocInternalTagged ... error 12`가 반복됐고, 이후 PyTorch의 NVML 내부 단언 오류로 종료됐다. Docker의 OOMKilled=false는 GPU 메모리 할당 성공을 뜻하지 않는다.
- KV 캐시 8GiB 직접 지정은 한 번 정상 초기화됐지만, 다음 재시작에서는 다시 할당 실패했다. 크기 축소만으로 해결됐다고 볼 수 없다.
- 모델 파일의 읽기 캐시가 남아 있었다. 해당 6개 safetensors 파일에만 읽기 캐시 반환을 요청하자 MemFree는 3,628,864kB에서 27,958,644kB로 늘었고, MemAvailable은 약 31,340,000kB로 거의 같았다. 반환된 파일 캐시는 약 23GiB다. 통합 메모리에서 즉시 빈 공간과 회수 가능 공간의 차이가 중요한 원인으로 확인됐다. 메모리 단편화의 영향은 별도로 분리 측정하지 않았다.
- 다른 오류: `/tokenize`로 이미지 토큰을 계산한 뒤 생성 요청에서 미러 이미지 캐시의 항목이 맞지 않아 HTTP 500이 발생했다. 응답 생성 이전 오류이며 원본 기록은 history/mm-cache-failure에 보존했다.

## 적용한 조치

1. KV 캐시를 8GiB로 직접 지정. 기존 80% 인자는 남아 있지만 캐시 크기 계산은 이 직접 지정이 우선한다.
2. 이미지 전처리 재사용 캐시를 0으로 지정해 미러 캐시 불일치를 우회.
3. 초기 최대 크기 가상 이미지 점검을 생략. 실제 비전 처리와 원본 해상도는 유지하고 실제 요청에서 메모리를 확인.
4. 가중치 로딩 후 해당 모델 파일의 읽기 캐시만 `POSIX_FADV_DONTNEED`로 반환. 모델 파일을 수정하거나 시스템 전체 캐시를 비우지 않았고 기존 다른 서비스를 재시작하지 않았다.

문맥 49,152·출력 한도 16,384, 모델 가중치·정밀도·요청 메시지·평가 기준은 유지했다. 단일 변경의 독립 효과를 분리한 실험은 아니며 조합으로 복구를 확인했다.

## 실제 검증

- 11:35 KST 서버 준비, 모델 API와 health 응답 정상.
- D-044-vision-page2: HTTP 200, 정상 종료, 1,275 출력 토큰, 217.047초.
- 동일 문서 기존 OpenRouter: 19.159초, 1,244 출력 토큰.
- 기존 항목 보존 기준은 양쪽 11/11, 표 셀 내용·구조는 8/8. 양쪽 모두 완결 JSON 및 경고 동반 전달이다. Orin 응답은 읽은 표 셀을 unreadable로 표시하는 모순이 있어 자동 확정 성공과 구분한다.
- OpenRouter 입력 사용량은 1,553토큰, 로컬은 4,093토큰으로 보고됐다. 같은 이미지·메시지이지만 제공자 내부 전처리/사용량 계산 차이를 분리하지 못했으므로 순수 장비 속도만의 비교로 해석하지 않는다.
- 전체 132장·20문서 비교, 장시간 안정성 및 재시작 재현 검증은 이 한 건으로 완료 처리하지 않는다.

## 실행과 기록

Orin에서 전체 평가가 독립 실행되고 응답을 저장한다. Mac의 수집기가 연결돼 있는 동안 새 응답을 가져와 같은 기준으로 채점하고 README를 갱신한다. VPN이 끊겨도 Orin 생성은 계속되지만 Mac 보고서는 마지막 동기화 상태에 머물 수 있다. 요약 의미 검수는 별도이며 자동 채점 완료로 간주하지 않는다.

- [현재 평가 결과](README.md)
- [캐시 반환 측정](model-file-cache-release.json)
- [서버 준비 상태](server-ready-state.txt)
- [실행 설정](serving-conditions.json)
- [최초 실패 로그](server-startup-49152.log)
- [이미지 캐시 실패 로그](server-cache8-mm-failure.log)
- [8GiB 재시작 실패 로그](server-cache8-mmoff-startup-failure.log)
- [복구한 서버 로그](server-cache-fixed-startup.log)

공식 설정 의미: [vLLM 0.19 실행 인자](https://docs.vllm.ai/en/v0.19.0/configuration/engine_args/). NVML 오류 보고 경로 참고: [PyTorch allocator](https://github.com/pytorch/pytorch/blob/v2.10.0/c10/cuda/CUDACachingAllocator.cpp). 설치된 Jetson 빌드와 upstream의 줄 번호는 다르다.
