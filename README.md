# SO-101 Autonomous Pick-and-Place with Hybrid AI Vision

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

SO-101 로봇 팔을 위한 **CV + VLM 하이브리드 비전 파이프라인**.  
Classical CV로 92.9%를 0.01초 처리하고, 모호한 케이스만 VLM에 위임하는 2단계 cascade 아키텍처.

> 🎯 **목표:** 퇴근 후 무인 자율 pick-and-place + 컵 넘어짐/이탈 시 스스로 복구

---

## 핵심 아이디어

```
CV Gate (0.01초)          → 자신 있는 케이스 즉시 판정
    ↓ (7.1% 모호한 케이스만)
VLM / GPT (2~3초)         → 공간 추론 + 복구 계획 생성
```

**왜 이 방식인가?**
- NVIDIA LiteVLM(2025)과 같은 철학: "싼 필터로 거르고, 비싼 모델은 꼭 필요할 때만"
- CV는 결정론적이고 검증 가능 → 물리적 안전 보장
- VLM은 유연한 공간 추론 → 예외 상황 대응

## 성능

| 지표 | 결과 |
|------|------|
| CV 게이트 정확도 | **100%** (24장 검증) |
| CV 커버리지 | 92.9% (224프레임 신규 검증) |
| CV 처리 속도 | **0.01초** / 프레임 |
| VLM 호출 비율 | 7.1% (전환점/이상 상황만) |
| 복구 루프 테스트 | ✅ Gemini 2.5 Flash 연동 완료 |

## 시스템 구성

```
📁 so101-autonomous-pick-place/
├── scripts/
│   ├── aux_hybrid_detector.py    # CV+VLM 하이브리드 검출기
│   └── autonomous_recovery_loop.py # 자율 복구 루프
├── bridge/                        # Codex ↔ Hermes 협업 브릿지
├── docs/
│   └── codex_oss_application_draft.md
├── reports/
└── logs/
```

## 빠른 시작

### 1. CV 게이트 검출기

```bash
python scripts/aux_hybrid_detector.py --image cup_scene.jpg
# → HELD | cv_held | orange=5230 blue=8198
```

### 2. 자율 복구 루프

```bash
python scripts/autonomous_recovery_loop.py
# CV gate monitors → anomaly detected → Gemini analyzes → recovery plan
```

### 요구사항
- Python 3.10+
- OpenCV, NumPy, requests
- (선택) 로컬 GPU + Qwen2-VL 서버
- (선택) OpenRouter API 키 (Gemini 2.5 Flash)

## 기술 스택

| 계층 | 기술 |
|------|------|
| CV Gate | OpenCV, HSV 블롭 검출 |
| 로컬 VLM | Qwen2-VL-2B (transformers, RTX 3080) |
| 클라우드 VLM | Gemini 2.5 Flash / GPT-5 (Codex) |
| 로봇 제어 | SO-101 (LeRobot 호환) |
| 상태 머신 | Python 기반 이벤트 드리븐 |

## 로드맵

- [x] CV 게이트 100% 정확도
- [x] 224프레임 신규 검증
- [x] 자율 복구 루프 프로토타입
- [ ] Codex GPT-5 vision 통합
- [ ] 실시간 로봇 제어 파이프라인
- [ ] YOLO 학습 데이터셋 공개
- [ ] 다중 로봇 플랫폼 지원

## 라이선스

MIT License — 상업적 사용, 수정, 배포 자유롭게 가능.

---

**Maintainer:** [@kimjoohyeon-wq](https://github.com/kimjoohyeon-wq)  
**Built with:** Hermes Agent + Codex + Gemini + DeepSeek
