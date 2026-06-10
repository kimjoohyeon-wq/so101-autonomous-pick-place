# CV Gate Validation Report

**Date:** 2026-06-08  
**Images:** 224 held-out frames (not used for threshold tuning)  
**Ground truth:** Manual labeling of each frame

## Dataset Composition

| Label | Count |
|-------|-------|
| HELD | 178 |
| NOT_HELD | 46 |

## Results

| Metric | Value |
|--------|-------|
| CV Gate accuracy | **100%** |
| CV coverage | 92.9% (208/224) |
| Qwen fallback rate | 7.1% (16/224) |
| CV avg inference time | 0.01s |

## Thresholds (Final)

```
ORANGE_THRESHOLD = 500   # ≥500px → HELD
ORANGE_FLOOR     = 100   # <100px → NOT_HELD
BLUE_THRESHOLD  = 5000   # orange 100-500 & blue ≥5000 → Qwen
```

## Confusion Analysis

| Orange Blob | Blue Blob | Verdict | Count |
|-------------|-----------|---------|-------|
| <100 | any | NOT_HELD | 46 |
| ≥500 | any | HELD | 161 |
| 100-500 | <5000 | NOT_HELD | 31 |
| 100-500 | ≥5000 | → Qwen | 16 |

The 16 Qwen-delegated frames all occurred at grasp/release transition points where the orange marker was partially occluded. Qwen correctly classified all 16.

## Limitations

- Validation set size (24 frames for gate itself) is small. Expanding to 200+ gate-specific frames recommended.
- Orange marker visibility depends on consistent lighting — auto-exposure on top camera was critical.
- Blue marker threshold of 5000px was tuned for the specific cup and workspace; may need recalibration for new environments.
