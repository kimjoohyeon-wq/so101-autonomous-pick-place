# Contributing to SO-101 Autonomous Pick-and-Place

환영합니다! 이 프로젝트는 실제 로봇 하드웨어에서 검증된 AI 비전 파이프라인을 오픈소스로 제공합니다.

## 시작하기

```bash
git clone https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place.git
cd so101-autonomous-pick-place
pip install -r requirements.txt
```

## 작동 방식

1. **CV 게이트** — HSV 블롭 검출로 0.01초 만에 컵 파지 상태 판정
2. **VLM 캐스케이드** — 모호한 케이스만 VLM에 위임 (현재 Gemini 2.5 Flash, 향후 Codex GPT-5)
3. **자율 복구 루프** — 이상 감지 → VLM 분석 → 복구 계획 생성

## 기여 방법

1. 이슈 생성: 버그 리포트, 기능 제안, 질문 모두 환영
2. PR 제출: 작은 PR이 더 좋습니다. 큰 변경은 먼저 이슈로 논의해주세요
3. 코드 스타일: `flake8` 또는 `ruff` 린트 통과 필수

## 안전 주의사항

이 코드는 실제 로봇 하드웨어를 제어할 수 있습니다. PR 제출 시:
- 물리적 안전에 영향을 주는 변경은 반드시 명시
- 새로운 동작은 시뮬레이션/드라이런으로 먼저 테스트

## 라이선스

MIT — 기여한 코드도 MIT로 제공됩니다.
