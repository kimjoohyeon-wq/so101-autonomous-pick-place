# SO-101 Gripper Calibration Reference

## Grip Strength Convention (CRITICAL — Boss Correction 2026-06-09)

**`gripper.pos` 값이 낮을수록 더 강하게 닫힌다.**

| gripper.pos | 상태 | 비고 |
|-------------|------|------|
| 0.0 | 완전 열림 | 최대 개방 |
| ~5-15 | 강한 그립 | 컵 파지 가능 범위 |
| 20.3 | 최대 폐쇄 | 하드웨어 한계 |
| 70-80 | 중간 | 접근 시 gripper 열린 상태 |

## Offset 방향 (헷갈리지 말 것)

```
+offset (양수) → gripper.pos 증가 → 더 약한 그립 (열리는 방향)
-offset (음수) → gripper.pos 감소 → 더 강한 그립 (닫히는 방향)
```

**실수 이력:** 2026-06-09 이전까지 모든 테스트에서 +offset을 사용해 grip을 약화시키고 있었음.
보스 지적으로 수정. 이후 -15 offset에서 최적 성능 확인.

## Leader vs Follower Calibration 차이

| | Leader Arm (COM4) | Follower Arm (COM3) |
|---|---|---|
| Closed grip 값 | 1.0 ~ 2.0 | 20.3 |
| Open grip 값 | ~70 | ~70-78 |
| 녹화된 trajectory 호환 | grip offset +20~30 필요 | 기본값 |

**Leader로 녹화한 trajectory를 follower에서 replay할 때:**
- Leader grip 값(1-2)에 +20~30 offset을 더해야 follower에서 같은 grip 상태가 됨
- v12, v3 trajectory는 leader 녹화 → follower replay 시 grip 너무 약함

## v11 Trajectory Grip 최적값

v11은 follower에서 직접 replay 가능 (leader 녹화 아님).
최적 offset: **-15.0** → gripper.pos 약 5~15 범위에서 작동

## 기록된 실험 데이터

| Offset | gripper.pos (추정) | held_ratio | 결과 |
|--------|-------------------|------------|------|
| +0 | 20.3 | 0.71 | grip 약함, 컵 자주 떨어짐 |
| +8 | 28.3 | 0.91 | boss: "gripper가 컵을 치고 지나감" |
| -10 | 10.3 | 0.90 | 양호 |
| **-15** | **5.3** | **0.93** | **최적** |
| -20 | 0.3 | 0.82 | 너무 빨리 닫혀서 접근 방해 |

## 교훈

1. Actuator 특성은 가정하지 말고 직접 실험으로 확인
2. 부호(sign) 방향을 반대로 이해하면 모든 후속 작업이 무효화됨
3. Leader-follower calibration 차이는 문서화하고 모든 trajectory에 적용
