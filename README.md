# SO-101 Autonomous Pick-and-Place with Hybrid AI Vision

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Lint](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/actions/workflows/lint.yml/badge.svg)](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/actions/workflows/lint.yml)
[![Issues](https://img.shields.io/github/issues/kimjoohyeon-wq/so101-autonomous-pick-place)](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues)

SO-101 로봇 팔을 위한 **CV + VLM 하이브리드 비전 파이프라인**.  
Classical CV로 92.9%를 0.01초 처리하고, 모호한 케이스만 VLM에 위임하는 2단계 cascade.

> 🎯 **목표:** 퇴근 후 무인 자율 pick-and-place + 컵 넘어짐/이탈 시 스스로 복구  
> 📍 **현재:** CV+VLM 비전 모니터링 + 텍스트 리포트 (실제 로봇 제어 파이프라인은 로드맵 단계)

---

## 현재 상태 vs 목표

| 기능 | 상태 | 설명 |
|------|------|------|
| CV 게이트 (HSV blob) | ✅ 구현 | 결정론적 3단계 threshold + blue 2차 필터 |
| 상태 머신 (debounce + anomaly) | ✅ 구현 | PickPlaceMonitor dataclass, 3프레임 debounce |
| VLM 복구 계획 생성 (Gemini) | ✅ 구현 | anomaly 감지 → Gemini Vision → 텍스트 복구 계획 |
| VLM 복구 계획 **실행** | ❌ 미구현 | 텍스트 → 서보 명령 매핑 레이어 0줄 |
| 실시간 로봇 제어 파이프라인 | ❌ 미구현 | 시리얼 통신, gripper 제어, trajectory 실행 전무 |
| ACT 모방학습 | ❌ 미구현 | LeRobot 데이터셋 포맷은 호환, 학습 파이프라인 없음 |
| 설정 파일 분리 | ❌ 미구현 | HSV 임계값 7개 소스코드에 하드코딩 |
| 에러 복원력 | ❌ 미구현 | API 호출 try/except 없음, 재시도 로직 없음 |
| 라이브 카메라 원자성 | ❌ 미구현 | atomic rename 없음, partial frame read 위험 |

---

## 핵심 아이디어

```
CV Gate (0.01초, 결정론적)   → 자신 있는 케이스 즉시 판정 (92.9%)
    ↓ (7.1% 모호한 케이스만)
VLM / GPT (2~3초)           → 공간 추론 + 복구 계획 텍스트 생성
    ↓ (실행부 TODO)
로봇 제어                    → 복구 계획 → 서보 명령 → gripper 동작
```

**왜 이 방식인가?**
- NVIDIA LiteVLM(2025)과 같은 철학: "싼 필터로 거르고, 비싼 모델은 꼭 필요할 때만"
- CV는 결정론적이고 검증 가능 → 물리적 안전 보장
- VLM은 유연한 공간 추론 → 예외 상황 대응

## CV Gate 동작 방식

```
orange 마커 blob 면적 검출
  ├─ < 100px          → NOT_HELD (확정)
  ├─ > 500px          → HELD (확정)  
  └─ 100~500px (경계)
       ├─ blue < 5000px  → NOT_HELD (노이즈/반사 — 진짜 컵 아님)
       └─ blue ≥ 5000px  → Qwen2-VL 호출 (진짜 모호한 케이스)
```

## 성능 (현재 검증 범위)

| 지표 | 결과 | 비고 |
|------|------|------|
| CV 게이트 정확도 | 100% (24장) | 결정론적 threshold 기반. 1000+ 프레임 스트레스 테스트 필요 [#1](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/1) |
| CV 커버리지 | 92.9% (224프레임) | 조명/각도/마커 마모에 따라 변동 가능 |
| CV 처리 속도 | **0.01초** / 프레임 | 실시간 제어에 무리 없음 |
| VLM 호출 비율 | 7.1% | 전환점/이상 상황만 |
| 복구 루프 | ⚠️ 텍스트 생성만 | Gemini 분석 → 복구 계획 텍스트 출력. 실행부 미구현 [#3](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/3) |

## 데모

**CV 게이트 + 상태 머신 실시간 pick-and-place 모니터링:**

![Demo](docs/demo.mp4)

- 🟢 초록 바 = HELD (컵 파지) / 🔴 빨간 바 = NOT_HELD
- 🟡 노란 윤곽 = orange 마커 검출 / 🔵 파란 윤곽 = blue 마커 검출
- 55프레임, 0 anomaly, 정상 pick-and-place 사이클

## 시스템 구성

```
📁 so101-autonomous-pick-place/
├── scripts/
│   ├── aux_hybrid_detector.py       # CV+VLM 하이브리드 검출기 (오프라인/배치)
│   ├── autonomous_recovery_loop.py  # 상태 머신 + Gemini 복구 루프
│   └── aux_camera_stream.py         # Windows 카메라 → WSL 공유 디렉토리 스트리밍
├── bridge/                           # Codex ↔ Hermes 협업 브릿지 (프로토콜 정의)
├── docs/
│   ├── codex_oss_application_draft.md
│   ├── skills/                       # gripper calibration + SO-101 실행 문서
│   └── demo.mp4
├── reports/                          # 샘플 실행 리포트
├── logs/                             # 샘플 JSONL 실행 로그
└── .github/workflows/lint.yml        # ruff lint (테스트 없음)
```

## 설치

```bash
git clone https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place.git
cd so101-autonomous-pick-place
pip install -r requirements.txt
```

## 빠른 시작

### 1. CV 게이트 검출기 (오프라인 모드)

```bash
python scripts/aux_hybrid_detector.py --image cup_scene.jpg
# → HELD | cv_held | orange=5230 blue=8198

# 배치 모드 (CSV)
python scripts/aux_hybrid_detector.py --csv labels.csv --out report.json
```

### 2. 자율 복구 루프 (비디오 파일)

```bash
python scripts/autonomous_recovery_loop.py --video path/to/recording.mp4
# CV gate → anomaly 감지 → Gemini 분석 → 복구 계획 텍스트 → JSON 리포트
```

### 3. 라이브 카메라 모드

```bash
# Windows에서 카메라 스트리밍 시작
python scripts/aux_camera_stream.py

# WSL에서 실시간 모니터링
python scripts/autonomous_recovery_loop.py --live --camera 1
```

### 요구사항
- Python 3.10+
- OpenCV, NumPy, requests
- (선택) 로컬 GPU + Qwen2-VL 서버
- (선택) OpenRouter API 키 (Gemini 2.5 Flash)

## 기술 스택

| 계층 | 기술 | 상태 |
|------|------|------|
| CV Gate | OpenCV, HSV 블롭 검출 | ✅ |
| 로컬 VLM | Qwen2-VL-2B (RTX 3080) | ✅ |
| 클라우드 VLM | Gemini 2.5 Flash (OpenRouter) | ✅ |
| 상태 머신 | Python dataclass 기반 이벤트 드리븐 | ✅ |
| 로봇 제어 | SO-101 (LeRobot 호환) | ❌ 파이프라인 미구현 |
| ACT 학습 | LeRobot 데이터셋 포맷 | ❌ 학습 파이프라인 미구현 |

## 로드맵

**완료:**
- [x] CV 게이트 (3단계 threshold + blue 2차 필터)
- [x] 상태 머신 (debounce + anomaly 감지)
- [x] Gemini 복구 계획 **텍스트 생성**
- [x] 라이브 카메라 스트리밍 + 모니터링

**진행 예정:**
- [ ] 복구 계획 → 서보 명령 **실행 레이어** ([#3](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/3))
- [ ] 실시간 로봇 제어 파이프라인
- [ ] CV Gate 1000+ 프레임 스트레스 테스트 ([#1](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/1))
- [ ] HSV 임계값 config 파일 분리 ([#6](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/6))
- [ ] API 에러 복원력 + 재시도 로직 ([#9](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/9))
- [ ] 라이브 카메라 atomic write ([#8](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/8))
- [ ] SRP: state machine / vision / io 모듈 분리 ([#5](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/5))
- [ ] VLM 호출 타임아웃 + 안전 정지 ([#2](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/2))
- [ ] YOLO 학습 데이터셋 공개
- [ ] ACT 모방학습 파이프라인 ([#4](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues/4))
- [ ] 다중 로봇 플랫폼 지원

## 기여

이슈와 PR 환영합니다. [Issues](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/issues)에서 `good first issue` 태그로 시작하기 좋은 항목을 확인하세요.

현재 가장 시급한 기여 포인트:
1. **복구 계획 실행 레이어** — VLM 텍스트 출력 → SO-101 서보 명령 매핑
2. **CV Gate 벤치마크 확장** — 1000+ 프레임 스트레스 테스트
3. **설정 파일 분리** — 하드코딩된 HSV 임계값 → config.yaml

## 라이선스

MIT License — 상업적 사용, 수정, 배포 자유롭게 가능.

---

**Maintainer:** [@kimjoohyeon-wq](https://github.com/kimjoohyeon-wq)  
**Built with:** Hermes Agent + Codex + Gemini + DeepSeek
