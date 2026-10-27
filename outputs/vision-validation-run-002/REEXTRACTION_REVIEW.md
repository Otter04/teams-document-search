# 원문 재확인·재추출 목록

추가 호출은 실행하지 않았다. 아래 항목은 검증기만으로 정답을 만들 수 없다. 사람의 원본 대조 수정 또는 향후 모델 재추출이 필요하다. 재호출이 유일한 방법이거나 성공이 보장된다는 뜻은 아니다.

구절 단위는 이전 AI 검수 초안을 유지했다. possible_misread_or_rewrite / missing_or_unmatched는 근접 문자열 유사도 0.7 기준의 분류 보조이며, 최종 원인 확정은 원문 대조가 필요하다. 기존 검수에서 확인한 오독 예시는 README에 적었다.

## qwen3.6-35b-a3b

### 원문 재확인 또는 향후 재추출: 23항목

#### D-044-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-044/page-1.png>) · 새 검증 결과: candidate

- 원문 기준: 의료법인 새봄의료재단(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)은 「PACS 스토리지 증설」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.
  - 가까운 출력: 의료법인 새봄의료재단(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)는 「PACS 스토리지 증설」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.
  - 분류 보조: possible_misread_or_rewrite
- 원문 기준: 양 당사자는 본 계약의 이행 과정에서 알게 된 상대방의 영업상·기술상 정보를 계약 종료 후 3년간 제3자에게 누설하지 아니한다.
  - 가까운 출력: 당 당사자는 본 계약의 이행 과정에서 알게 된 상대방의 영업상·기술상 정보를 계약 종료 후 3년간 제3자에게 누설하지 아니한다.
  - 분류 보조: possible_misread_or_rewrite

#### D-069-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-069/page-1.png>) · 새 검증 결과: reject

- 원문 기준: 범례: 실선 = 1G/10G 이더넷 | (주)도담캐피탈 전산 담당자 검토 필요
  - 가까운 출력: 범례 : 실선 ≈ 1G/10G 이더넷 | (주) 도담캐피탈 전산 담당자 검토 필요
  - 분류 보조: possible_misread_or_rewrite

#### D-102-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-102/page-1.png>) · 새 검증 결과: reject

- 원문 기준: 온새미시 도시공사(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)은 「시설관리시스템 노후 서버 교체」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.
  - 가까운 출력: 은새미시 도시공사(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)은 「시설관리시스템 노후 서버 교체」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.
  - 분류 보조: possible_misread_or_rewrite
- 원문 기준: 본 계약의 기간은 2025년 11월 3일부터 2025년 12월 19일까지로 한다.
  - 가까운 출력: 본 계약의 기간은 2025년 11월 3일부터 2025년 12월 19일까지 한다.
  - 분류 보조: possible_misread_or_rewrite
- 원문 기준: 갑은 계약 체결 후 선금으로 계약금액의 30%를, 최종 검수 완료 후 30일 이내에 잔금 70%를 지급한다.
  - 가까운 출력: 갑은 계약 체결 후 선급으로 계약금액의 30%를, 최종 검수 완료 후 30일 이내에 잔금 70%를 지급한다.
  - 분류 보조: possible_misread_or_rewrite
- 원문 기준: 을이 수행하는 업무의 범위는 서버 4대 교체, Windows Server 2022 전환, 조달청 우수제품 구매 절차 준수로 하며, 세부 내용은 별첨 과업내용서에 따른다.
  - 가까운 출력: 을이 수행하는 업무의 범위는 서버 4대 교체, Windows Server 2022 전환, 조달청 우수제품 구매 절차 준수하며, 세부 내용은 별첨 과업내용서에 따른다.
  - 분류 보조: possible_misread_or_rewrite
- 원문 기준: 을은 검수 완료일로부터 1년간 납품물의 하자에 대하여 무상으로 보수한다.
  - 가까운 출력: 을은 검수 완료일로부터 1년간 납품물의 하자에 대하여 무료로 보수한다.
  - 분류 보조: possible_misread_or_rewrite
- 원문 기준: 일방 당사자가 본 계약을 위반하고 서면 시정 요구를 받은 날로부터 14일 이내에 시정하지 아니하는 경우 상대방은 본 계약을 해지할 수 있다.
  - 가까운 출력: 일방 당사자가 본 계약을 위반하고 서면 시정을 받은 날로부터 14일 이내에 시정하지 아니하는 경우 상대방은 본 계약을 해지할 수 있다.
  - 분류 보조: possible_misread_or_rewrite

#### D-102-vision-page2

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-102/page-2.png>) · 새 검증 결과: reject

- 원문 기준: 제11조(분쟁 해결)
  - 가까운 출력: 주소: (생략)
  - 분류 보조: missing_or_unmatched
- 원문 기준: 본 계약과 관련하여 분쟁이 발생한 경우 양 당사자는 협의하여 해결하며, 협의가 이루어지지 않을 때에는 서울중앙지방법원을 관할 법원으로 한다.
  - 가까운 출력: 주소: 서울특별시 구로구 디지털로 000, 7층
  - 분류 보조: missing_or_unmatched
- 원문 기준: 본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하여 갑과 을이 기명날인한 후 각 1부씩 보관한다.
  - 가까운 출력: 대표이사: 최도윤 (인)
  - 분류 보조: missing_or_unmatched
- 원문 기준: 2025년 10월 24일
  - 가까운 출력: 주소: 서울특별시 구로구 디지털로 000, 7층
  - 분류 보조: missing_or_unmatched

#### H-020-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/additional-parsing-run-001/assets/H-020/page-1.png>) · 새 검증 결과: reject

- 원문 기준: 온라인몰 반품분류 견적서
  - 가까운 출력: 분류 카메라
  - 분류 보조: missing_or_unmatched
- 원문 기준: 거래처: 푸른리테일
  - 가까운 출력: 항목
  - 분류 보조: missing_or_unmatched
- 원문 기준: 대상 시스템: 온라인몰
  - 가까운 출력: 분류 카메라
  - 분류 보조: missing_or_unmatched
- 원문 기준: 문서상태: 최종
  - 가까운 출력: 항목
  - 분류 보조: missing_or_unmatched
- 원문 기준: 작성일: 2026-09-18
  - 가까운 출력: 400000
  - 분류 보조: missing_or_unmatched
- 원문 기준: 견적번호: QT-26-PR-88
  - 가까운 출력: 2
  - 분류 보조: missing_or_unmatched
- 원문 기준: 견적유효기간: 2026-10-18
  - 가까운 출력: 400000
  - 분류 보조: missing_or_unmatched
- 원문 기준: 견적금액: KRW 7,000,000 (VAT 별도)
  - 가까운 출력: 400000
  - 분류 보조: missing_or_unmatched
- 원문 기준: 반품 봉투의 훼손 위치를 확인하고 자동 분류 결과를 검수한다. 이 문서는 스캔 이미지로만 보관한다.
  - 가까운 출력: 검수 교육
  - 분류 보조: missing_or_unmatched
- 원문 기준: 합성 평가 자료 - 실제 계약이나 고객 정보를 나타내지 않음
  - 가까운 출력: 항목
  - 분류 보조: missing_or_unmatched

### 기존 응답 claims에서 필드 배치 검수 가능: 0항목

### 네이티브 원문 복구 검수 가능: 0항목

## qwen3-vl-30b-a3b-instruct

### 원문 재확인 또는 향후 재추출: 21항목

#### D-044-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-044/page-1.png>) · 새 검증 결과: reject

- 원문 기준: 의료법인 새봄의료재단(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)은 「PACS 스토리지 증설」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.
  - 가까운 출력: 의료법인 새봄의료재단(이하 "갑"이라 한다)과 라움정보기술 주식회사(이하 "을"이라 한다)는 「PACS 스토리지 증설」(이하 "본 사업"이라 한다)에 관하여 다음과 같이 계약을 체결한다.
  - 분류 보조: possible_misread_or_rewrite

#### D-044-vision-page2

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-044/page-2.png>) · 새 검증 결과: reject

- 원문 기준: 본 계약과 관련하여 분쟁이 발생한 경우 양 당사자는 협의하여 해결하며, 협의가 이루어지지 않을 때에는 서울중앙지방법원을 관할 법원으로 한다.
  - 가까운 출력: 을
상호: 라움정보기술 주식회사
대표이사: 정태오 (인)
주소: 서울특별시 구로구 디지털로 000, 7층
  - 분류 보조: missing_or_unmatched
- 원문 기준: 본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하여 갑과 을이 기명날인한 후 각 1부씩 보관한다.
  - 가까운 출력: 갑
상호: 의료법인 새봄의료재단
대표이사: 류정원 (인)
주소: (생략)
  - 분류 보조: missing_or_unmatched
- 원문 기준: 2025년 3월 22일
  - 가까운 출력: 을
상호: 라움정보기술 주식회사
대표이사: 정태오 (인)
주소: 서울특별시 구로구 디지털로 000, 7층
  - 분류 보조: missing_or_unmatched

#### D-069-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-069/page-1.png>) · 새 검증 결과: reject

- 원문 기준: 여신관리시스템 DR 구축 네트워크 구성도 (Rev.1)
  - 가까운 출력: DR 서버팜
10.65.110.0/24
  - 분류 보조: missing_or_unmatched
- 원문 기준: 설치 위치: 여의도 본사 IDC | 작성일: 2025-08-27 | 작성: 라움정보기술 기술지원팀
  - 가까운 출력: 본사 -DR 전용회선 1Gbps × 2
  - 분류 보조: missing_or_unmatched
- 원문 기준: 범례: 실선 = 1G/10G 이더넷 | (주)도담캐피탈 전산 담당자 검토 필요
  - 가까운 출력: 방화벽
FortiGate 600F × 2 (본사) / FortiGate 400F × 2 (DR)
  - 분류 보조: missing_or_unmatched

#### D-102-vision-page2

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-102/page-2.png>) · 새 검증 결과: reject

- 원문 기준: 제11조(분쟁 해결)
  - 가까운 출력: 갑
상호: 온새미시 도시공사
대표이사: 최도윤 (인)
주소: (생략)
  - 분류 보조: missing_or_unmatched
- 원문 기준: 본 계약과 관련하여 분쟁이 발생한 경우 양 당사자는 협의하여 해결하며, 협의가 이루어지지 않을 때에는 서울중앙지방법원을 관할 법원으로 한다.
  - 가까운 출력: 을
상호: 라움정보기술 주식회사
대표이사: 정태오 (인)
주소: 서울특별시 구로구 디지털로 000, 7층
  - 분류 보조: missing_or_unmatched
- 원문 기준: 본 계약의 성립을 증명하기 위하여 계약서 2부를 작성하여 갑과 을이 기명날인한 후 각 1부씩 보관한다.
  - 가까운 출력: 갑
상호: 온새미시 도시공사
대표이사: 최도윤 (인)
주소: (생략)
  - 분류 보조: missing_or_unmatched
- 원문 기준: 2025년 10월 24일
  - 가까운 출력: 을
상호: 라움정보기술 주식회사
대표이사: 정태오 (인)
주소: 서울특별시 구로구 디지털로 000, 7층
  - 분류 보조: missing_or_unmatched

#### H-020-vision-page1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/additional-parsing-run-001/assets/H-020/page-1.png>) · 새 검증 결과: reject

- 원문 기준: 온라인몰 반품분류 견적서
  - 가까운 출력: 분류 카메라
  - 분류 보조: missing_or_unmatched
- 원문 기준: 거래처: 푸른리테일
  - 가까운 출력: 항목 수량 금액
  - 분류 보조: missing_or_unmatched
- 원문 기준: 대상 시스템: 온라인몰
  - 가까운 출력: 분류 카메라
  - 분류 보조: missing_or_unmatched
- 원문 기준: 문서상태: 최종
  - 가까운 출력: 항목 수량 금액
  - 분류 보조: missing_or_unmatched
- 원문 기준: 작성일: 2026-09-18
  - 가까운 출력: 400000
  - 분류 보조: missing_or_unmatched
- 원문 기준: 견적번호: QT-26-PR-88
  - 가까운 출력: 2
  - 분류 보조: missing_or_unmatched
- 원문 기준: 견적유효기간: 2026-10-18
  - 가까운 출력: 400000
  - 분류 보조: missing_or_unmatched
- 원문 기준: 견적금액: KRW 7,000,000 (VAT 별도)
  - 가까운 출력: 400000
  - 분류 보조: missing_or_unmatched
- 원문 기준: 반품 봉투의 훼손 위치를 확인하고 자동 분류 결과를 검수한다. 이 문서는 스캔 이미지로만 보관한다.
  - 가까운 출력: 검수 교육
  - 분류 보조: missing_or_unmatched
- 원문 기준: 합성 평가 자료 - 실제 계약이나 고객 정보를 나타내지 않음
  - 가까운 출력: 항목 수량 금액
  - 분류 보조: missing_or_unmatched

### 기존 응답 claims에서 필드 배치 검수 가능: 66항목

#### D-001-vision-slide4

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-001/slide-4.png>) · 새 검증 결과: reject

- 원문 기준: 제안 목표
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 목표 1
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 설비 데이터 1초 단위 실시간 수집
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 목표 2
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: ERP 생산실적 자동 연동
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 목표 3
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: MES 서버 가상화 전환
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched

#### D-001-vision-slide5

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-001/slide-5.png>) · 새 검증 결과: reject

- 원문 기준: 제안 아키텍처
  - 가까운 출력: 보안·네트워크 FortiGate 200F × 2 (HA)
  - 분류 보조: missing_or_unmatched
- 원문 기준: 설치 위치: 화성 1공장 전산실
  - 가까운 출력: MES 애플리케이션 mes-app01
  - 분류 보조: missing_or_unmatched

#### D-002-vision-page9

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-002/page-9.png>) · 새 검증 결과: reject

- 원문 기준: 회사 소개
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 라움정보기술 주식회사
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 주요 사업
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 임직원
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 인프라 구축 · 운영 , 시스템
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 2009 년
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 142 명
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: ISO 27001, ISO 9001
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched

#### D-008-vision-slide1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-008/slide-1.png>) · 새 검증 결과: reject

- 원문 기준: 2025 MES 고도화 구축 네트워크 구성도 (Rev.2)
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 설치 위치: 화성 1공장 전산실  |  작성일: 2025-03-17  |  작성: 라움정보기술 기술지원팀
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 범례: 실선 = 1G/10G 이더넷 | ㈜청람정밀 전산 담당자 검토 필요
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: Internet / 전용회선
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 방화벽
FortiGate 200F × 2 (HA)
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 코어 스위치
Cisco C9500-24Y4C × 2
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: OT망 방화벽 FortiGate 100F
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 설비망 L2 스위치 × 6
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 서버팜
10.21.10.0/24
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: OT 설비망
10.21.50.0/24
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 관리망
10.21.99.0/24
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched

#### D-020-vision-slide4

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-020/slide-4.png>) · 새 검증 결과: reject

- 원문 기준: 제안 목표
  - 가까운 출력: 목표 1
PDA 기반 입고 검수
  - 분류 보조: missing_or_unmatched

#### D-031-vision-slide4

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-031/slide-4.png>) · 새 검증 결과: reject

- 원문 기준: 제안 목표
  - 가까운 출력: 목표 2
무중단 전환 (주말 작업)
  - 분류 보조: missing_or_unmatched

#### D-040-vision-page9

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-040/page-9.png>) · 새 검증 결과: reject

- 원문 기준: 회사 소개
  - 가까운 출력: 주요 사업
인프라 구축 · 운영 , 시스템
통합
  - 분류 보조: missing_or_unmatched
- 원문 기준: 라움정보기술 주식회사
  - 가까운 출력: 주요 사업
인프라 구축 · 운영 , 시스템
통합
  - 분류 보조: missing_or_unmatched

#### D-054-vision-page3

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-054/page-3.png>) · 새 검증 결과: reject

- 원문 기준: 사업 이해
  - 가까운 출력: 현황 1
수강신청 기간 동시 접속 3 만 명에서 응답 지연
  - 분류 보조: missing_or_unmatched
- 원문 기준: 미르내대 학사정보시스템 현황과 개선 과제
  - 가까운 출력: 현황 2
온프레미스 서버 노후
  - 분류 보조: missing_or_unmatched

#### D-074-vision-slide3

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-074/slide-3.png>) · 새 검증 결과: reject

- 원문 기준: 사업 이해
  - 가까운 출력: 현황 2
블랙프라이데이 트래픽 3배 증가
  - 분류 보조: missing_or_unmatched
- 원문 기준: 해솔유통㈜ 온라인몰 현황과 개선 과제
  - 가까운 출력: 현황 1
단일 웹서버 장애 시 온라인몰 전체 중단
  - 분류 보조: missing_or_unmatched

#### D-074-vision-slide4

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-074/slide-4.png>) · 새 검증 결과: reject

- 원문 기준: 제안 목표
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 목표 1
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: L4 스위치 Active-Standby 이중화
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 목표 2
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 웹·WAS 각 2대 이상
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 목표 3
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: DB 복제 구성
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched

#### D-074-vision-slide9

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-074/slide-9.png>) · 새 검증 결과: reject

- 원문 기준: 회사 소개
  - 가까운 출력: 주요 사업
인프라 구축 · 운영,
시스템 통합
  - 분류 보조: missing_or_unmatched
- 원문 기준: 라움정보기술 주식회사
  - 가까운 출력: 주요 사업
인프라 구축 · 운영,
시스템 통합
  - 분류 보조: missing_or_unmatched

#### D-075-vision-page9

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-075/page-9.png>) · 새 검증 결과: reject

- 원문 기준: 회사 소개
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 라움정보기술 주식회사
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 주요 사업
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 임직원
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 인프라 구축 · 운영 , 시스템
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 2009 년
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 142 명
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: ISO 27001, ISO 9001
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched

#### D-082-vision-slide1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-082/slide-1.png>) · 새 검증 결과: reject

- 원문 기준: 온라인몰 인프라 이중화 네트워크 구성도 (Rev.2)
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 설치 위치: 판교 IDC  |  작성일: 2025-02-17  |  작성: 라움정보기술 기술지원팀
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 범례: 실선 = 1G/10G 이더넷 | 해솔유통㈜ 전산 담당자 검토 필요
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: Internet / 전용회선
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 방화벽
FortiGate 400F × 2
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 코어 스위치
Arista 7050X3 × 2
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: L4 스위치 Piolink PAS-K × 2 (Active-Standby)
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: DMZ 웹서버 2대
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: DMZ
10.76.20.0/24
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 서버팜
10.76.10.0/24
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched
- 원문 기준: 관리망
10.76.99.0/24
  - 가까운 출력: 없음
  - 분류 보조: missing_or_unmatched

#### D-098-vision-slide9

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-098/slide-9.png>) · 새 검증 결과: reject

- 원문 기준: 회사 소개
  - 가까운 출력: 주요 사업
인프라 구축 · 운영,
시스템 통합
  - 분류 보조: missing_or_unmatched
- 원문 기준: 라움정보기술 주식회사
  - 가까운 출력: 주요 사업
인프라 구축 · 운영,
시스템 통합
  - 분류 보조: missing_or_unmatched

### 네이티브 원문 복구 검수 가능: 5항목

#### D-045-vision-slide1

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-045/slide-1.png>) · 새 검증 결과: reject

- 원문 기준: PACS 스토리지 300TB
  - 가까운 출력: PACS 스토리지 증설 네트워크 구성도 (Rev.1)
  - 분류 보조: missing_or_unmatched
- 원문 기준: SAN
FC Fabric A/B
  - 가까운 출력: SAN 스위치 Brocade G720 × 2
  - 분류 보조: missing_or_unmatched
- 원문 기준: 관리망
10.43.99.0/24
  - 가까운 출력: 의료영상망
10.43.20.0/24
  - 분류 보조: possible_misread_or_rewrite

#### D-064-vision-slide8

[원본 이미지](</Users/kangdongkyoon/Documents/Codex/2026-10-14/rag/outputs/parsing-run-003/assets/D-064/slide-8.png>) · 새 검증 결과: reject

- 원문 기준: 제안 금액
  - 가까운 출력: 금액
  - 분류 보조: missing_or_unmatched
- 원문 기준: 총 제안금액: ₩315,600,000 (부가가치세 별도)
  - 가까운 출력: 94,680,000
  - 분류 보조: missing_or_unmatched
