# SO-101 Autonomous Pick-and-Place with Hybrid AI Vision

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Lint](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/actions/workflows/lint.yml/badge.svg)](https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place/actions/workflows/lint.yml)

A **CV + VLM hybrid vision pipeline** for the SO-101 robot arm.  
Classical CV handles 92.9% of frames in **0.01 seconds**; ambiguous cases cascade to a VLM for spatial reasoning and recovery planning.

> 🎯 **Goal:** Lights-out autonomous pick-and-place with self-recovery on cup drops and anomalies.

[한국어 README](README.ko.md)

---

## Core Idea

```
CV Gate (0.01s)           → confident cases decided immediately
    ↓ (7.1% ambiguous only)
VLM / GPT (2–3s)          → spatial reasoning + recovery plan generation
```

**Why this architecture?**
- Same philosophy as NVIDIA LiteVLM (2025): "cheap filter first, expensive model only when needed"
- CV is deterministic and verifiable → guarantees physical safety
- VLM provides flexible spatial reasoning → handles edge cases

## Performance

| Metric | Result |
|--------|--------|
| CV Gate accuracy | **100%** (24-frame validation) |
| CV coverage | 92.9% (224-frame held-out test) |
| CV inference speed | **0.01s** / frame |
| VLM invocation rate | 7.1% (transition points & anomalies only) |
| Recovery loop | ✅ Gemini 2.5 Flash integrated |

## Demo

**CV Gate + state machine real-time pick-and-place monitoring:**

![Demo](docs/demo.mp4)

- 🟢 Green bar = HELD (cup grasped) / 🔴 Red bar = NOT_HELD
- 🟡 Yellow contour = orange marker detected / 🔵 Blue contour = blue marker detected
- 55 frames, 0 anomalies, normal pick-and-place cycle

## System Overview

```
📁 so101-autonomous-pick-place/
├── scripts/
│   ├── aux_hybrid_detector.py       # CV+VLM hybrid detector
│   └── autonomous_recovery_loop.py  # Autonomous recovery loop
├── bridge/                          # Codex ↔ Hermes collaboration bridge
├── docs/
│   └── codex_oss_application_draft.md
├── reports/
└── logs/
```

## Quick Start

### 1. CV Gate Detector

```bash
python scripts/aux_hybrid_detector.py --image cup_scene.jpg
# → HELD | cv_held | orange=5230 blue=8198
```

### 2. Autonomous Recovery Loop

```bash
python scripts/autonomous_recovery_loop.py
# CV gate monitors → anomaly detected → Gemini analyzes → recovery plan
```

### Requirements
- Python 3.10+
- OpenCV, NumPy, requests
- (Optional) Local GPU + Qwen2-VL server
- (Optional) OpenRouter API key (Gemini 2.5 Flash)

## Tech Stack

| Layer | Technology |
|-------|------------|
| CV Gate | OpenCV, HSV blob detection |
| Local VLM | Qwen2-VL-2B (transformers, RTX 3080) |
| Cloud VLM | Gemini 2.5 Flash / GPT-5 (Codex) |
| Robot Control | SO-101 (LeRobot-compatible) |
| State Machine | Python event-driven |

## Roadmap

- [x] CV Gate 100% accuracy
- [x] 224-frame held-out validation
- [x] Autonomous recovery loop prototype
- [ ] Codex GPT-5 vision integration
- [ ] Real-time robot control pipeline
- [ ] YOLO training dataset release
- [ ] Multi-robot platform support

## License

MIT License — free for commercial use, modification, and redistribution.

---

**Maintainer:** [@kimjoohyeon-wq](https://github.com/kimjoohyeon-wq)  
**Built with:** Hermes Agent + Codex + Gemini + DeepSeek
