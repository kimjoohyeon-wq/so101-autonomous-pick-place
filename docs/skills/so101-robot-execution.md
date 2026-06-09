---
name: so101-robot-execution
description: Execute SO-101 physical robot commands from WSL via Windows PowerShell. Load FIRST before any robot run — contains control path, stop procedure, safety rules, pipeline patterns, yellow-tip visual servo close/lift workflow, and common pitfalls. Covers autonomous pick-and-place, data collection loops, auto-correction workflow, and camera-guided pre-grasp alignment.
category: manufacturing
---

# SO-101 Robot Execution (WSL → Windows)

## Critical Path

```
WSL (Hermes) → PowerShell → Windows Python → COM3/COM4 + Cam0/Cam1
```

**Do NOT try to use `/dev/ttyS*` from WSL Python.** Those are motherboard serial ports, not Windows COM ports.

## Execution Template

```bash
/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -Command "cd C:\Users\Research\Documents\Robot; python <script> <args>"
```

**PowerShell `-File` only works with `.ps1` files. Use `-Command` for `.py` scripts.**

## Stopping The Robot (CRITICAL - READ FIRST)

**Background process kill does NOT stop child Python processes on Windows.** The robot will keep moving. Use:

```powershell
Get-Process python* | Stop-Process -Force
```

Never rely on Hermes `process(action='kill')` for Windows robot processes. It kills the shell wrapper but leaves Python running with the COM port held.

## Environment

- lerobot 0.5.1 (Windows Python 3.12)
- OpenCV with CAP_MSMF backend
- COM3 = follower arm, COM4 = leader arm
- Camera 0 = top_external (640x480), Camera 1 = aux_wrist (640x480)
- Camera roles config: `configs/camera_roles.json`

## Pre-Flight Checklist (MANDATORY)

Before ANY physical run:
1. Kill stale processes: `Get-Process python* | Stop-Process -Force`
2. Check `logs/nudge_status.json` (running=false, blocked=false)
3. Read `bridge/LIVE_TEST_STATUS.md` for current state
4. **Verify arm pose vs trajectory start** — see [Pre-Replay Pose Verification](#pre-replay-pose-verification) below
5. Dry-run first: `--dry-run` or `--help`
6. Confirm user approved physical step
7. Single run before loop — never jump straight to `while True`

**If pose delta exceeds 2° on any joint (ESPECIALLY gripper), do NOT replay.** Fix pose first.

## Safe Pipeline Pattern

Every autonomous loop MUST follow this pattern (enforced by Codex review):

1. `--execute` flag REQUIRED (default is no-op or dry-run)
2. `--max-runs` defaults to 1 (not unlimited)
3. `--require-user-label` pauses after each run for user input
4. User label is ground truth — detector is advisory only
5. Correction offsets only updated on user-confirmed success
6. 2 consecutive failures → auto-stop
7. Every run produces: pre-snapshot + video + replay + post-snapshot + detector + JSON episode
8. Camera index from `configs/camera_roles.json`, not hardcoded
9. After completion: append TASK_LOG, update LIVE_TEST_STATUS

## Pre-Replay Pose Verification

**The arm drifts between sessions.** A trajectory that worked yesterday will fail today if the arm starts from a different position. Gripper state is especially critical — a partially-closed gripper cannot grasp the cup.

### Check script

Use `bridge/_check_pose.py` (or the older `scripts/check_pose_vs_trajectory.py`) to compare current arm position against trajectory frame 0. For detailed drift data and reset procedure, see `references/arm-pose-drift-v11-reset.md`.

```powershell
python bridge\_check_pose.py
```

### Reset scripts

After checking, if pose delta exceeds threshold, use the appropriate reset script:

| Trajectory | Reset Script |
|-----------|-------------|
| v11 (green→pink) | `bridge/_move_to_v11_start.py` |
| v2 (pink→green) | `bridge/_move_to_v2_start.py` |

For new trajectories, create a reset script following the template: read frame 0 from trajectory JSON, connect COM3, send target joint positions in order: gripper → lift → pan → elbow → wrist_flex → wrist_roll.

### Thresholds

- **Any joint delta > 2°**: replay will likely fail — fix pose first
- **Gripper delta > 1°**: gripper no longer at recorded state — will mis-grasp or miss
- **PLAY FAIL in <10s**: strong indicator of severe pose mismatch (normal replay is ~65s for 596 frames)

Each cycle must collect:
- **Pre-snapshot**: verify cup at expected start position (detector)
- **Video**: full run recording (MP4, FPS matched to trajectory)
- **Replay**: trajectory execution with accumulated correction offsets
- **Post-snapshot**: verify cup at expected target position (detector)
- **Episode JSON**: all metadata + detector output + correction state
- **RUN_INDEX**: append one JSONL line per run

Never run blind replay without recording and verification.

## Yellow-Tip Visual Servo (Close + Lift Workflow)

The preferred workflow for supervised cup pickup. Runs through a persistent
nudge session (`so101_nudge_session.py`) that reads commands from
`logs/nudge_command.json`.

### Step-by-Step

1. **Kill stale + start nudge session**:
```powershell
Get-Process python* | Stop-Process -Force
```
```bash
powershell.exe -Command "cd C:\Users\Research\Documents\Robot; python scripts\so101_nudge_session.py --port COM3 --duration 600 --gripper-limit 60 --body-limit 15"
```

2. **Wait for session ready** — check `logs/nudge_status.json` for `running=true`.

3. **Move to golden pre-grasp pose** via `move_pose` command:
```python
# Write to logs/nudge_command.json:
{"command": "move_pose", "pose": "golden_pregrasp_reference", ...}
```

4. **Dual gate precheck** — verify camera view matches golden:
```powershell
python scripts\check_dual_golden_pregrasp.py --capture --tag <name>
```

5. **Visual servo nudge** if gate says `hold_or_correct`:
```powershell
python scripts\yellow_tip_servo_pregrasp.py --capture --execute-nudge --max-iterations 5 --max-step-deg 1.5 --gain-x 0.06 --gain-y 0.06 --tag <name>
```
— Only nudges `shoulder_pan` (X) and `shoulder_lift` (Y).
— Does NOT close, lift, transfer, place, or park.

6. **Close gripper** (write nudge command directly to `logs/nudge_command.json`):
```python
{"command": "nudge", "deltas": {"gripper.pos": -48.0}, ...}
```

7. **Tiny lift**:
```python
{"command": "nudge", "deltas": {"shoulder_lift.pos": -6.0, "gripper.pos": -5.0}, ...}
```

8. **Capture post-lift snapshots**, deliver to user for visual confirmation.

9. **Stop nudge session**: `{"command": "stop"}` or kill PowerShell process.

### Golden Reference Files

- `configs/yellow_tip_visual_servo_reference.golden.json` — target `tip_minus_cup_px`
- `configs/so101_poses.json` → `golden_pregrasp_reference` — target joint angles
- `configs/dual_golden_pregrasp_gate.json` — tolerance thresholds

### Key Scripts (Yellow-Tip)

| Script | Purpose |
|--------|---------|
| `scripts/so101_nudge_session.py` | Persistent robot session, polls `nudge_command.json` |
| `scripts/send_nudge_command.py` | Write nudge/stop commands to `nudge_command.json` |
| `scripts/yellow_tip_servo_pregrasp.py` | Visual servo loop (camera + nudge) |
| `scripts/check_dual_golden_pregrasp.py` | Dual camera gate (top + aux) |
| `scripts/yellow_tip_visual_servo_scene.py` | Offline orange/yellow detector |

### Pitfalls (Yellow-Tip)

18. **Golden reference joint pose ≠ golden camera view**: Moving the arm to the
    golden joint angles may NOT reproduce the golden camera image. If the cup,
    camera, or lighting has changed since the golden reference was captured,
    expect large initial errors. The servo loop can correct X (shoulder_pan) but
    Y errors >20px may not converge with shoulder_lift alone — elbow_flex also
    affects tip-cup Y offset and may need manual adjustment.

19. **Dual gate is advisory**: `ok_to_close_candidate` is helpful but not
    required. Codex's first confirmed lift succeeded with BOTH gates failing
    (`cup_or_tip_missing` after close). User visual confirmation is the ground
    truth. Do not block indefinitely on gate pass.

20. **Aux gate may never pass**: If the physical camera setup differs from when
    the golden reference was captured, the aux gate Y error will be persistently
    large (-100 to -150px). The aux gate tolerance is only 45px. Accept that
    aux gate will fail and proceed based on top gate + user visual confirm.

21. **Gain sign matters for Y**: The default `gain-y=0.06` with negative errors
    produces negative shoulder_lift deltas, which moves the gripper tip UP in
    the image (wrong direction for correcting tip-below-cup offset). If Y error
    keeps getting more negative, try `gain-y` with opposite sign.

22. **Nudge command file must be atomically written**: Use temp-file + rename
    pattern. `send_nudge_command.py` already does this. Direct writes to
    `nudge_command.json` can cause the session to read partially-written JSON.

23. **`max_below_cup_px` hardcoded to 8.0 breaks tip detection**: In
    `check_dual_golden_pregrasp.py:96`, `pick_gripper_tip(yellow, cup,
    min_above_px=3.0, max_below_cup_px=8.0)` silently rejects yellow blobs
    more than 8px below the cup center. If `yellow_candidates_count` is >0 but
    `gripper_yellow_tip` is null, bump `max_below_cup_px` to 25.0. Fixed
    2026-06-06 after golden v2 cup shift revealed the bug.
    See `references/visual-servo-debug-20260606.md` for full debug log.

24. **Gripper drift after lift**: The gripper slowly loses grip over time.
    After a confirmed close + tiny lift, the cup will eventually slip and fall
    back to the table. Deliver results and capture snapshots immediately after
    lift — do not wait or run additional checks.

25. **Don't over-optimize servo**: If X error stays below ~12px after 8
    iterations, proceed to close/lift. Running 20+ iterations for perfect
    convergence wastes time. The gain limits mean some positions simply won't
    converge below the tolerance floor.

26. **Gripper stuck closed after close/lift with no nudge session**: When the
    nudge session (`so101_nudge_session.py`) has exited (killed, timed out, or
    crashed), you cannot write to `nudge_command.json` to open the gripper.
    Use direct COM3 connection instead — `bridge/_open_gripper.py` connects,
    opens gripper, and disconnects. The correct API is
    `SOFollower(SOFollowerRobotConfig(port="COM3"))` →
    `robot.connect(calibrate=False)` → `robot.send_action({'gripper.pos': 0.0})`.
    Always `robot.disconnect()` after. See `references/open-gripper-direct.md`.

27. **Per-attempt golden reference capture**: Cup position drifts between
    trials (even small bumps shift it by 25+ px). The golden reference
    (`tip_minus_cup_px`) captured in one attempt becomes stale for the next.
    Always recapture golden reference before each servo cycle — never reuse
    a previous attempt's reference. The workflow: capture live →
    compute new tip_minus_cup_px → update reference JSON → servo against
    new reference.

28. **정보 요청 ≠ 실행 승인 (CRITICAL — 보스 Correction 2026-06-09).** "어떻게하는거야?", "작성해줘", "알려줘" 등은 정보 요청이지 실행 승인이 아니다. 보스가 cron job 생성, 스크립트 실행, 로봇 동작 등을 명시적으로 승인("진행해", "시작해", "실행해")하기 전까지는 **텍스트/설명만 제공**하고 절대 실행하지 말 것. "goal 명령어 작성" = 프롬프트 텍스트를 보여달라는 뜻이지 cron job을 만들라는 뜻이 아니다. 크론잡, delegate_task, terminal 실행은 명시적 승인 후에만.

## Verdict Classification

Clear distinction between failure modes:
- `replay_failed` — script crashed, COM port error, robot didn't move
- `detector_failure` — robot moved but detector says cup not at target
- `detector_ambiguous` — detector uncertain (needs_review)
- `user_confirmed_success` — user visually confirmed (OVERRIDES detector)
- `user_confirmed_failure` — user visually confirmed failure

Trust hierarchy: `user visual label > full-view evidence > detector state > embedded old JSON`

## Key Scripts

| Script | Purpose | Safe? |
|---|---|---|
| `scripts/auto_correct_pipeline.py` | Auto-correction pick-and-place with recording | ✅ Safe (--execute required) |
| `scripts/round_trip_loop.py` | Autonomous round-trip loop (green→pink→green repeat). Supports `--live-aux-monitor` for CV gate anomaly detection. | ✅ Safe (--execute required) |
| `scripts/aux_live_monitor.py` | Live CV gate aux-camera monitor (threaded, detects cup-drop mid-transit) | ✅ Safe (camera only) |

**Full reference:** `references/gripper-calibration.md` — gripper.pos 값-강도 관계, offset 방향, leader-follower calibration 차이, v11 최적값, 실험 데이터.\n\n## Live Aux CV Gate Monitor (2026-06-09)

`scripts/aux_live_monitor.py` — threaded CV gate monitor that runs during trajectory replay.
Detects cup-drop anomalies (HELD → NOT_HELD mid-transit) and triggers automatic retry.

**Key features:**
- CV gate: orange+blue blob detection on aux wrist camera (640×480, DirectShow)
- State machine: NOT_HELD ↔ HELD with debounce (3 frames)
- Anomaly types: `cup_drop` (cup fell mid-transit), `cup_lost` (UNCERTAIN 8+ frames)
- Runs in background thread via `AuxMonitor(camera_id).start()` / `.stop()`

**Standalone test:**
```powershell
cd C:\Users\Research\Documents\Robot
$env:PYTHONIOENCODING='utf-8'
python scripts\aux_live_monitor.py --camera 0 --timeout 30
```

**CRITICAL: Camera roles** — aux_wrist = camera 0, top_external = camera 1 (verify in `configs/camera_roles.json`). Using wrong camera ID crashes the monitor with `Failed to open camera`.

**PYTHONIOENCODING:** Always set `$env:PYTHONIOENCODING='utf-8'` before running round_trip_loop.py from PowerShell. cp949 default crashes on Unicode characters (✓, —).

**Integration with round_trip_loop.py:**
```powershell
$env:PYTHONIOENCODING='utf-8'
python scripts\round_trip_loop.py --execute --rounds 1 `
    --dual-camera-evidence --auto-aux-hold-label `
    --live-aux-monitor --aux-monitor-camera 0 --max-aux-retries 1 `
    --forward-joint-offset shoulder_pan=-1 `
    --forward-joint-offset shoulder_lift=5 `
    --forward-joint-offset elbow_flex=-5 `
    --forward-gripper-offset 8.0 `
    --allow-forward-start-offset
```

**Gate bypass gotcha:** `--allow-forward-start-offset` REQUIRES at least one `--forward-joint-offset`. Without it, the gate blocks even with the flag set. Always pair them.

**Pre-state with cup covering marker:** `--strict-pre-state` will block when pre-state is `needs_review` (cup covers green marker, normal). Remove `--strict-pre-state` when cup is correctly placed — `needs_review` from occlusion is expected, not a failure.

**Flow during replay:**
1. `AuxMonitor.start(expect_held=True)` — begin monitoring aux camera
2. `replay_trajectory()` — robot executes trajectory (blocking)
3. `AuxMonitor.stop()` — returns {held_ratio, anomalies, cup_drop_count}
4. If `cup_drop_count > 0`: retry up to `--max-aux-retries` times
5. If retries exhausted: leg marked as failure

**Function reference:** `replay_with_aux_monitor()` in `round_trip_loop.py` wraps the above flow.

**Common issues:**
- **Camera conflict:** `aux_live_monitor.py` opens the aux wrist camera (camera 0) via DirectShow. Kill any other Python process using that camera first (`Get-Process python* | Stop-Process -Force`).
- **WRONG CAMERA ID:** aux_wrist = camera 0, top_external = camera 1 (see `configs/camera_roles.json`). Using camera 1 for aux monitor crashes with `Failed to open camera`.
- **PYTHONIOENCODING:** Set `$env:PYTHONIOENCODING='utf-8'` before ALL PowerShell robot commands. Windows cp949 default crashes on ✓ and — in round_trip_loop.py output.
- **Gate bypass:** `--allow-forward-start-offset` REQUIRES at least one `--forward-joint-offset`. Without it, the flag is silently ignored and the gate blocks.
- **Cup-drop false positives:** If orange marker briefly becomes invisible (lighting, camera angle), the debounce mechanism absorbs it. Only sustained HELD→NOT_HELD transitions trigger anomalies. Drops clustered at trajectory frames ~20-25 and ~55-65 are likely camera FOV losses, not real drops.
- **Initial grasp delay:** Monitor starts 0.5s before replay to detect the initial grasp. If grasp happens after replay begins, the first few frames may show NOT_HELD before the transition.

Full integration reference: `references/live-aux-monitor-integration.md`.
Joint offset tuning results: `references/forward-leg-joint-tuning-20260609.md`.

For unattended 60-round data collection
and set-based execution (10 rounds × 6 sets), see `references/overnight-data-collection.md`.

Key rules:
- Same-leg pre/post comparison for success judgment (never cross-leg)
- Night detector ambiguity (`needs_review`, `empty_floor`, etc.) is NOT a physical failure
- PowerShell exit ≠ loop complete — check `Get-Process python*`
- Fixed trajectories only, no auto-correction
| `scripts/replay_follower_trajectory.py` | Replay trajectory on follower | ⚠️ Direct use ok for single run |
| `scripts/record_leader_trajectory.py` | Record leader demo (COM4→COM3 mirror) | ✅ Safe (human-operated) |
| `bridge/_check_pose.py` | Verify arm pose matches trajectory start | ✅ Safe (no robot motion) |
| `bridge/_move_to_v11_start.py` | Reset arm to v11 (green→pink) start pose | ⚠️ Moves robot |
| `bridge/_move_to_v2_start.py` | Reset arm to v2 (pink→green) start pose | ⚠️ Moves robot |
| `scripts/detect_color_markers.py` | Offline marker detection | ✅ Safe (no robot) |
| `scripts/record_camera.py` | Record camera video | ✅ Safe (no robot) |
| `scripts/yellow_tip_servo_pregrasp.py` | Visual servo pre-grasp alignment (camera-only) | ✅ Safe (--capture default) |
| `scripts/check_dual_golden_pregrasp.py` | Dual camera golden gate check | ✅ Safe (no robot) |
| `scripts/so101_nudge_session.py` | Persistent robot control session (COM3) | ⚠️ Keeps arm at target |
| `scripts/send_nudge_command.py` | Write nudge command for session | ✅ Safe (writes file only) |

## Visual Servo Pre-Grasp Pipeline

Camera-first pre-close alignment for paper-cup POC. The `yellow_tip_servo_pregrasp.py` script never closes, lifts, transfers, places, or parks.

### Architecture

```
so101_nudge_session.py (persistent, polls nudge_command.json)
  ├─ yellow_tip_servo_pregrasp.py writes nudge commands
  └─ direct nudge_command.json writes for close/lift
```

### Workflow

1. Start nudge session: `python scripts\so101_nudge_session.py --port COM3 --gripper-limit 60 --body-limit 15`
2. Move to golden: `move_pose` command to `golden_pregrasp_reference`
3. Run servo: `python scripts\yellow_tip_servo_pregrasp.py --capture --execute-nudge --max-iterations 6 --gain-x 0.06 --gain-y 0.03`
4. After servo converges (or close enough), send close: `send_nudge_command.py gripper.pos=-48.0`
5. Send tiny lift: `send_nudge_command.py shoulder_lift.pos=-6.0 gripper.pos=-5.0`
6. Stop session: `send_nudge_command.py --stop`

### Golden Reference

When the cup position changes, the old golden reference (`configs/yellow_tip_visual_servo_reference.json`) becomes invalid. Create a new one:
- Manually compute `tip_minus_cup_px` from live capture data (cup center vs yellow tip center)
- Update `target_tip_minus_cup_px` in the reference JSON
- Set `user_verified: true`

### Nudge Session Commands

Write directly to `logs/nudge_command.json` (atomic write via temp file):
- `move_pose`: move to saved pose by name
- `nudge`: apply joint deltas to current position
- `save`: save current pose with name
- `stop`: end session

## Trajectory Library

| Name | Direction | Frames | Replays | Verified |
|------|-----------|--------|---------|----------|
| `20260605_170823_pick_green_v11.json` | green→pink | 596 | 8 | ✅ 7/8 user-confirmed |
| `20260605_195740_pick_pink_v2.json` | pink→green | 596 | 5 | ✅ 5/5 user-confirmed |

**Reliability:** Combined 12/13 success across 8 rounds of round-trip testing (2026-06-05). Only r03 forward was a detector false negative (pink fully invisible but area_ratio=None → bug; since fixed). Single r05 forward was borderline (pink 60% occluded, area_ratio 0.403 vs 0.30 threshold).

Round-trip loop validation data and false-negative analysis: `references/round-trip-validation-20260605.md`.

## Detector Quick Reference

```bash
# Baseline REQUIRED for cup states. Without baseline → only empty_floor_review/needs_review.
python scripts\detect_color_markers.py --image <path> --baseline configs\marker_baseline.json --json-only
```

## Bridge Protocol

Every work unit leaves a record:
- Physical run → `bridge/RUN_INDEX.jsonl`
- Code/report/offline → `bridge/TASK_LOG.jsonl`
- Current state → `bridge/LIVE_TEST_STATUS.md`
- Codex review needed → `bridge/HERMES_TO_CODEX.md`
- Codex feedback → `bridge/CODEX_TO_HERMES.md`

## Common Pitfalls

1. **Self-limiting**: "I can't control the robot from WSL" — FALSE. Use PowerShell path.
2. **Skipping dry-run**: Always validate trajectory before physical execution.
3. **No recording**: Blind replay without video = wasted run. Always record.
4. **No pre-check**: Always verify cup position before starting replay.
6. **No success judgment**: Detector output alone is not a verdict. User label required.
7. **Unbounded loops**: `while True` without safety gates. Always use --max-runs.
8. **cp949 encoding**: Non-ASCII characters in print/argparse break on Windows. Use ASCII only. Specifically: em-dash (`—`) → `--`, degree sign (`°`) → `deg`, checkmark (`✓`) → `OK`. Both `detect_color_markers.py` and `auto_correct_pipeline.py` had em-dash crashes (6 instances each). Scan with `grep -Pn '[^\\x00-\\x7F]' *.py`.
9. **Port conflicts**: Always kill stale Python before connecting. Add delay between runs.
10. **Background kill**: `process(action='kill')` leaves child Python alive. Use Stop-Process.
11. **Arm pose drift**: The arm does NOT return to a fixed home position between sessions. A trajectory recorded hours ago may fail because the arm is now in a completely different pose. ALWAYS run check_pose_vs_trajectory.py before replaying. Gripper state drift is the most common silent failure — a partially-closed gripper produces valid-looking motion but cannot grasp.
12. **Short gripper hold during recording**: During leader demo recording, the gripper must stay closed for the ENTIRE transport phase. Releasing mid-motion drops the cup. v1 failed with 5s hold; v2 succeeded with 22s hold. See `references/reverse-trajectory-recording.md` for detailed timeline.
13. **Detector green occlusion is NOT a failure**: When replaying pink→green, the green marker will be hidden under the cup. Detector correctly reports `green.visible=false` + `state=cup_on_green` + `needs_review=true`. The `needs_review` here is informational — the detector infers cup-on-green from green marker absence. Do NOT treat this as a rejection or failure signal. Confirm with vision or user label.
14. **Occlusion check MUST test BOTH area_ratio AND marker visibility**: When a marker is fully occluded, `area_ratio` is `None` (no detection → no ratio). Testing only `area_ratio < 0.30` returns `False` for `None`, producing a false negative. Always add `marker_not_visible` fallback: `is_occluded = (ratio is not None and ratio < 0.30) or not marker.get("visible", True)`. This bug was found in `round_trip_loop.py` forward leg (r03_fwd pink fully invisible but classified as failure) and the same fix was applied to the reverse leg's green check. See `references/detector-occlusion-check.md`.
15. **Detector false positive locations**: When the real pink marker is occluded, the detector may find noise at an entirely different position (e.g., pink at (23,350) instead of (151,84)) with low confidence. The noise detection's area_ratio is meaningless. If pink center is >50px from expected position and confidence <0.30, it's noise — treat as fully occluded.
16. **PowerShell wrapper exits before Python finishes**: `powershell.exe -Command "python script.py"` returns immediately after spawning Python. Hermes background process notification fires on PowerShell exit, not Python completion. The loop may still be running. Always check `Get-Process python*` to confirm actual state.
17. **Night detector false negatives**: Under night lighting (exposure=-4), green marker area drops from ~916 to ~95 (10% of baseline). The detector returns `needs_review`/`empty_floor`/`empty_floor_review` even when the cup is correctly placed. These are detector ambiguity, NOT physical failure. The `strict_pre_state_allowed` gate in `round_trip_loop.py` must include `NIGHT_AMBIGUOUS_STATES = {cup_between, needs_review, empty_floor_review, empty_floor}`.
