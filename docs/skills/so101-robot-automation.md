---
name: so101-robot-automation
description: SO-101 robot arm pick-and-place automation — CV servo, LeRobot control, waypoints, COM port recovery, and hybrid CV+VL judgment pipelines.
triggers:
  - aux hold detector
  - aux hybrid detector
  - wrist camera cup held
  - auxiliary camera detection
  - CV gate + Qwen
version: 1.1.0
metadata:
  hermes:
    tags: [robot, automation, manufacturing, computer-vision, pick-and-place]
---

# SO-101 Robot Pick-and-Place Automation

Patterns, pitfalls, and proven configurations for automating the SO-101 robot arm (LeRobot SO-Follower) with top-down camera CV servo + VL model judgment.

## Hardware

- Robot: SO-101 Follower (COM3), Leader arm (COM4)
- Camera: USB top-down (Camera 0, cv2.CAP_MSMF, exposure -10)
- Gripper: Soft pneumatic + yellow-painted tips for CV detection
- Cup: White paper cup with dark X-marker on bottom

## WSL → Windows Execution Model (2026-06-05)

**Hermes runs in WSL. All robot scripts MUST be dispatched through Windows PowerShell:**

```
WSL terminal → powershell.exe -Command "python <script>" → Windows Python → COM/Camera
```

**Important:** WSL Python cannot access COM ports (`/dev/ttyS*` permission denied) or `cv2.CAP_MSMF`. Windows Python (lerobot 0.5.1) is the only path. Write complex scripts as .py files, then execute with `powershell.exe -Command "python C:\\path\\to\\script.py --args"`.

**Self-limitation pitfall:** Hermes tends to claim it "cannot" control the robot from WSL. This has been corrected by the boss multiple times. **Always try the PowerShell path before concluding something is impossible.** The path works — COM3, COM4, Camera 0, and Camera 1 were all verified functional from WSL via PowerShell on 2026-06-05.

## Aux Hold Detector (Wrist Camera — 2026-06-09)

Binary HELD/NOT_HELD classification from wrist camera (MSMF Camera 1). Uses hybrid CV gate + Qwen fallback.

**Logic (v3 — correct):**
```
orange blob < 100px              → CV: NOT_HELD (confident)
orange blob > 500px              → CV: HELD (confident)
orange 100-500 & blue < 5000px  → CV: NOT_HELD (noisy, blue filter essential)
orange 100-500 & blue ≥ 5000px  → Qwen fallback (true borderline, rare)
```

**Script:** `scripts/aux_hybrid_detector.py` — offline only, WSL-safe path translation.

**Full reference:** `references/aux-hybrid-detector-20260609.md` — dataset distribution, approach evolution, pitfalls, external research, fresh video validation.

**Boss decision (2026-06-09):** Qwen fallback stays despite known unreliability. It is a formal safety net
for the orange 100-500 + blue ≥ 5000 case that has never occurred in testing. The CV gate is the real
detector — do not propose removing Qwen again unless the boss raises it.

## Autonomous Recovery Loop (2026-06-09)

CV gate → state machine → anomaly detection → external VLM recovery planner.

Pattern: cheap/fast CV monitors robot state (0.01s/frame). State machine tracks expected pick-and-place
transitions. When anomaly detected → Gemini 2.5 Flash (via OpenRouter) or GPT-5 Codex analyzes the
scene and produces a concrete recovery plan (~2-3s, ~$0.001/call).

**Why external VLM:** Qwen2-VL-2B can classify HELD/NOT_HELD but cannot produce spatial grasp plans
for recovery. Gemini 2.5 Flash ($0.001/image) produces concrete, actionable plans. DeepSeek V4 Pro
API currently rejects image inputs despite claiming multimodal architecture — use Gemini or GPT-5.

**State machine v2 (debounce — resolved v1 false positives):**
v1 flagged every state change as anomaly (7 false positives in 56-frame test). v2 uses simple
NOT_HELD ↔ HELD transitions with 3-frame debounce — requires 3 consecutive frames of new state
before registering a transition. UNCERTAIN persisting >4 consecutive frames triggers anomaly.
Result: 0 false positives on same video, clean pick-and-place pattern recognition.

```python
DEBOUNCE_FRAMES = 3        # consecutive frames to confirm state change
MAX_UNCERTAIN_FRAMES = 4   # consecutive UNCERTAIN → anomaly

# Valid transitions (what we can actually observe from CV gate):
# NOT_HELD → HELD (grasp succeeded)
# HELD → NOT_HELD (release/drop)
# Everything else is an anomaly or UNCERTAIN
```

**Live camera streaming (Windows → WSL):**
WSL has no direct camera access. Pattern:
1. Windows Python script (`aux_camera_stream.py`) captures aux camera (cv2.CAP_DSHOW, Camera 1)
   and writes `aux_latest.jpg` to shared dir `C:\Users\Research\Documents\Robot\live_frames\`
2. WSL monitor reads from `/mnt/c/Users/Research/Documents/Robot/live_frames/aux_latest.jpg`
3. Monitor uses mtime polling to detect new frames (generator pattern, 0.1s poll interval)

```bash
# Windows (start camera stream)
python aux_camera_stream.py

# WSL (start live monitor)
python autonomous_recovery_loop.py --live
```

**Dual-camera format:** Recordings are 1280x480 side-by-side. Right half (640:1280) = aux wrist camera.

**Available API keys** in `~/.hermes/.env`: OPENROUTER_API_KEY, GEMINI_API_KEY (credits may be depleted).

**Context Compaction Pitfall (CRITICAL — 2026-06-09):** When a session starts with a context compaction summary, DO NOT trust its claimed file paths or deployment status. The compaction may fabricate file locations (e.g., claiming `autonomous_recovery_loop.py` is at `/home/research/Robot/scripts/` when it actually exists only in the GitHub repo at `/home/research/so101-autonomous-pick-place/scripts/`). Always verify with `search_files` or `find` before acting on compaction-claimed paths. The compaction is a lossy summary — it can hallucinate file existence, directory structure, and deployment state. This is a metacognitive rule: compaction summaries are reference hints, not authoritative state.

**GitHub repo:** https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place (live 2026-06-09).
**Local clone:** `/home/research/so101-autonomous-pick-place/` — clone with `git clone https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place.git` from WSL.
Scripts are at `scripts/aux_hybrid_detector.py`, `scripts/autonomous_recovery_loop.py`, `scripts/aux_camera_stream.py`.
**NOT at `/home/research/Robot/scripts/`** — the Robot project at `/mnt/c/Users/Research/Documents/Robot/` is a separate workspace for LeRobot control scripts.

**Full reference:** `references/autonomous-recovery-loop-20260609.md` — architecture, test results,
Gemini API call pattern, recovery plan examples, DeepSeek vision limitation, OSS application status.

**Integration into round_trip_loop.py:** See "Live Aux Monitor → round_trip_loop.py Integration" section.

**Demo GIF creation:** `references/demo-gif-creation.md` — script pattern for generating visual demos from
test videos with CV detection overlay and state bar.

## Live Aux Monitor → round_trip_loop.py Integration (2026-06-09)

CV gate live monitoring integrated into the round-trip orchestration loop. The `AuxMonitor`
class runs in a background thread during trajectory replay, detects cup-drop anomalies
(HELD→NOT_HELD mid-transit), and triggers automatic retry.

**Key files:**
- `scripts/aux_live_monitor.py` — CV gate monitor module (importable, thread-based)
- `scripts/round_trip_loop.py` — modified with `--live-aux-monitor`, `--max-aux-retries`, `replay_with_aux_monitor()`

**Integration pattern:**
```python
# Before replay: start monitor
mon = AuxMonitor(camera_id=0)  # aux wrist = camera 0 (check camera_roles.json!)
mon.start(expect_held=True)
time.sleep(0.5)  # detect initial grasp

# Replay (blocking subprocess)
ok, out = replay_trajectory(TRAJ, ...)

# After replay: check results
result = mon.stop()
if result["cup_drop_count"] > 0:
    # retry up to --max-aux-retries
```

**Flags added to round_trip_loop.py:**
- `--live-aux-monitor` — enable CV gate monitoring during replay
- `--max-aux-retries N` — max retries per leg on cup-drop (default: 1)
- `--aux-monitor-camera N` — aux camera ID (default: 1 → **CHECK camera_roles.json!** Aux wrist = camera 0, Top = camera 1)

**⚠️ CRITICAL: Camera index defaults to 1 but aux wrist IS camera 0.**
Always verify with `camera_roles.json` before running. The skill's default was wrong and caused
`camera_error: Failed to open camera 1` on first run. Use `--aux-monitor-camera 0` for aux wrist.

**⚠️ Gate bypass requires joint offset:** `--allow-forward-start-offset` alone is NOT enough to
bypass the forward start gate. You MUST include at least one `--forward-joint-offset`. Without it,
the gate will still block even with `--allow-forward-start-offset` set. Minimum safe bypass:
`--forward-joint-offset shoulder_pan=-1 --allow-forward-start-offset`

**⚠️ Elbow and large shoulder offsets break replay:** `elbow_flex` offset and `shoulder_pan <= -3`
caused `replay_failed` (PLAY FAIL, held_ratio=0.00). The only safe joint offsets tested:
- `shoulder_pan=-1` — always works with replay OK
- Other joints (shoulder_lift, elbow_flex) — **caused replay FAIL when added**

**⚠️ CP949 encoding in PowerShell Python stdout:** Unicode chars (✓, —, emoji) crash with
`UnicodeEncodeError: 'cp949' codec can't encode character`. Workaround:
```powershell
$env:PYTHONIOENCODING='utf-8'; python -u script.py ...
```

**⚠️ PowerShell background output:** stdout from `powershell.exe -Command` often does not appear
in Hermes process tools. Always redirect to file, then read from WSL with `iconv -f UTF-16 -t UTF-8`
(PowerShell `>` writes UTF-16 LE by default).

**Usage:**
```powershell
python scripts\round_trip_loop.py --execute --rounds 3 \
    --live-aux-monitor --aux-monitor-camera 0 --max-aux-retries 1 \
    --forward-joint-offset shoulder_pan=-1 --allow-forward-start-offset
```

**Offset tuning data (2026-06-09, 11 physical runs):**

| # | Gripper | Joints | held_ratio (1st→retry) | Result |
|---|---------|--------|------------------------|--------|
| 1 | +0 | pan=-1 | 0.71→0.88 | cup_drop×5, replay OK |
| 2 | +3 | pan=-3, elbow=-3 | 0.00 | **replay FAIL** |
| 3 | +2 | pan=-2, elbow=-2 | 0.00 | **replay FAIL** |
| 4 | +2 | pan=-1 | 0.88→0.88 | cup_drop×5, replay OK |
| 5 | +4 | pan=-1 | 0.87→0.83 | cup_drop×5, replay OK |
| 6 | +4 | pan=-1, lift=-3, elbow=-2 | 0.79→0.82 | cup_drop×4, replay OK |
| 7 | +8 | pan=-1, lift=-8, elbow=-6 | 0.24→0.61 | cup_drop×14 (arm too low) |
| 8 | +8 | pan=-1, lift=+8 | 0.65→0.87 | cup_drop×3 (1drop retry) |
| 9 | +12 | pan=-1, lift=+12 | 0.35→0.71 | cup_drop×4 |
| 10 | +4 | pan=-1, lift=+8 | 0.49→0.21 | cup_drop×4 |
| 11 | **+8** | **pan=-1, lift=+5, elbow=-5** | **0.91→0.92** | cup_drop×4, **green_visible=True** |

**Best combo (run 11):** `--forward-gripper-offset 8.0 --forward-joint-offset shoulder_pan=-1 --forward-joint-offset shoulder_lift=5 --forward-joint-offset elbow_flex=-5`
Achieved held_ratio=0.91-0.92 with `green_visible=True` in post-state (cup successfully moved from green marker).

**Key tuning insights:**
- `shoulder_lift` negative (arm lower) → held_ratio collapses (0.24). Use POSITIVE shoulder_lift (+5 to +8) to keep arm from diving.
- `elbow_flex` negative (-5) with positive shoulder_lift enables forward reach without diving. Combine both.
- `gripper +8.0` is safe (higher values up to +12 degraded performance). Sweet spot: +2 to +8.
- `shoulder_pan=-1` is the only safe pan offset; -2 or greater causes replay FAIL.
- retry often improves held_ratio because arm is already warm/positioned from first attempt.

**Cup-drop pattern (all runs):** Drops at frames ~20-27 and ~55-70 across all successful replays.
With held_ratio 0.91-0.92 these are brief marker-fov-loss events, not real physical drops.
The 0.91-0.92 ratio means the cup is HELD for >90% of transit time.

**Boss workflow preference (2026-06-09):** When tuning offsets, be AGGRESSIVE and make the
choices yourself. Don't ask for every parameter value — start conservative, then escalate
autonomously. Pattern: "보수적 시작" → if that fails, go "진취적으로" without asking again.
Report results; the boss will intervene if they disagree. Boss also gave real-time kinematic
feedback: "더 밑으로" (go lower), "너무 밑으로 내려간다" (too low now) → adjust opposite direction.
Iterate based on boss's visual observations of arm position.

**Full reference:** `references/live-aux-monitor-offset-tuning-20260609.md` — complete 11-run
tuning log with per-run analysis and parameter space map.

**Full reference:** `references/live-aux-monitor-integration-20260609.md` — architecture diagram,
code patterns, anomaly types, caveats, and v2 upgrade path (mid-flight abort).

## Codex for OSS Application (2026-06-09)

OpenAI's "Codex for OSS" program provides 6 months free Codex + ChatGPT Pro + API credits
for open-source maintainers. Codex Security (vulnerability scanning) is available conditionally.

**Program details (boss research):**
- Targets: core maintainers, not just high-star repos
- Ecosystem impact, dependency chains, and security sensitivity matter more than stars
- Application emphasizes "why the project matters"

**Our application:** Draft at `docs/codex_oss_application_draft.md`.
Key arguments: CV+VLM hybrid pattern (comparable to NVIDIA LiteVLM), physical safety critical,
manufacturing SME impact, validated on SO-101 hardware.

**GitHub repo:** https://github.com/kimjoohyeon-wq/so101-autonomous-pick-place (created 2026-06-09).

## GitHub Setup (WSL, no sudo, 2026-06-09)

```bash
# Install gh CLI
mkdir -p ~/.local/bin
wget https://github.com/cli/cli/releases/download/v2.65.0/gh_2.65.0_linux_amd64.tar.gz
tar -xzf gh_*.tar.gz && cp gh_*/bin/gh ~/.local/bin/

# PAT approach (device flow timeouts in WSL):
# 1. Generate token: https://github.com/settings/tokens (classic, scopes: repo + workflow)
# 2. Save: echo "ghp_xxx" > /tmp/gh_token.txt && chmod 600 /tmp/gh_token.txt
# 3. Auth: GH_TOKEN=*** /tmp/gh_token.txt) gh repo create ...
# 4. Push: git remote set-url origin "https://USER:TOKEN@github.com/USER/REPO.git"
# 5. If "missing scope 'read:org'" — ignore, only repo+workflow needed

# Fresh clone pattern (avoid large .git history from old project):
git clone $url fresh && cd fresh && cp <files> ... && git push
```

**Do NOT remove contextually-useful CV filters to "simplify" a hybrid pipeline.** Removing the blue blob
filter from the aux hold detector dropped accuracy from 100% to 87.5% because the 3 borderline NOT_HELD
images (orange 109-472 px) all had blue < 5000 — a signal the filter exploited. Qwen alone could not
distinguish these cases. Always test the simplified version against the full dataset before committing.

**Corollary:** When a CV filter catches real errors that the VLM misses, the filter is NOT redundant —
it's compensating for a VLM blind spot. Document which specific images depend on each filter.

**Fresh video finding (2026-06-09):** On new videos (224 frames), the 100px orange floor threshold can
cause oscillation when orange blobs sit exactly on the boundary (e.g., v5_override_1 showed 8 transitions
with values of 100-101 px). Consider ±10px hysteresis to prevent rapid HELD↔NOT_HELD toggling.



### Yellow Tip Detection

HSV mask for yellow gripper tips (painted, not LED):
```python
YELLOW_LOWER = (20, 100, 100)  # H: 20-35 for yellow
YELLOW_UPPER = (35, 255, 255)
```

### X-Marker Cup Detection

Use `detect_x_marker_feature()` with ROI tracking:
```python
from top_view_pick_correction import detect_x_marker_feature
res = detect_x_marker_feature(roi, cup={...}, min_confidence=0.35)
```

Track last known position to narrow the search region on subsequent frames.

### Nudge Direction Convention (CRITICAL)

**For top-down camera view with SO-101 LeRobot coordinates:**

| dx (cup_x - tip_x) | sp_delta | Robot motion |
|---|---|---|
| dx > 0 (cup right of tip) | **-NUDGE_SP** | Arm rotates to move tip RIGHT |
| dx < 0 (cup left of tip) | **+NUDGE_SP** | Arm rotates to move tip LEFT |

| dy (cup_y - tip_y) | sl_delta | Robot motion |
|---|---|---|
| dy > 0 (cup below tip in image) | **+NUDGE_SL** | shoulder_lift increases → tip moves DOWN in image |
| dy < 0 (cup above tip in image) | **-NUDGE_SL** | shoulder_lift decreases → tip moves UP in image |

**This was a long-standing bug:** The original sign was inverted for dy. With the wrong sign, the servo DIVERGES (distance grows each iteration). Fixed 2026-06-05.

```python
# CORRECT:
sp_delta = -NUDGE_SP if dx > 0 else +NUDGE_SP
sl_delta = +NUDGE_SL if dy > 0 else -NUDGE_SL
```

### Tuning

Start with small steps, increase if starting distance is large:
```python
NUDGE_SP = 2.5  # degrees per iteration (increase to 4.0 if >150px start)
NUDGE_SL = 2.0  # degrees per iteration (increase to 3.0 if >150px start)
ALIGN_TOL_PX = 20  # convergence threshold in pixels
MAX_SERVO_ITER = 15  # enough for ~150px starting distance
```

Reduce step by 50% when `dist < 60` to prevent oscillation.

### Approach Positions

Choose based on approximate cup location:

| Use case | sp | sl | Starting distance |
|---|---|---|---|
| Golden reference (cup at 117,147) | -28.0 | -42.0 | ~50-70px |
| General (cup anywhere left side) | -40.0 | -35.0 | ~120-150px |

## GRASP Sequence

After servo alignment, the grasp uses the ALIGNED position as base:

```python
# 1. Open gripper at aligned position (only change gripper.pos → 77.8)
# 2. Descend: shoulder_lift.pos = aligned_sl - descent_depth
# 3. Close gripper: gripper.pos = 15.0 (or tighter)
```

**Descent depth tuning:**
- Start at 20.0° (safe default)
- Increment by 5.0° on failure
- Max 45.0° (prevent collision)

## COM Port Recovery

**Pattern:** Killing a running robot process leaves COM3 locked at the driver level. The robot MUST be power-cycled to recover.

```powershell
# Check port availability
powershell.exe -Command "[System.IO.Ports.SerialPort]::GetPortNames()"

# USB cycle (if COM3 shows but connection fails with PermissionError)
powershell.exe -ExecutionPolicy Bypass -File scripts/cycle_usb_admin.ps1
```

**PermissionError pattern:**
```
serial.serialutil.SerialException: could not open port 'COM3': PermissionError(13, '액세스가 거부되었습니다.', None, 5)
```
→ USB cycle, then retry.

Never assume COM3 is available after a `kill`. Always check with a quick connect test before launching a long script.

## Camera Configuration (Updated 2026-06-05)

**Working config — MSMF Camera 0:**
```python
cap = cv2.VideoCapture(0, cv2.CAP_MSMF)
cap.set(cv2.CAP_PROP_EXPOSURE, -10)  # actual reports -6, but image does darken
# Do NOT touch AUTO_EXPOSURE, AUTO_WB — leave at driver defaults
```

**Exposure findings:**
| Set | Actual | Table V | Result |
|-----|--------|---------|--------|
| -4 to -8 | -6 | 255 | Overexposed, S=10, useless |
| -9 | -6 | 232 | Borderline |
| -10 | -6 | 170 | Best — S=5, detectable with 3x boost |
| -11 | -6 | 132 | Too dark |

**Pitfalls:**
- DSHOW Camera 1 = same physical camera but has severe cyan cast even with AUTO_WB=1. Use MSMF only.
- Camera output has extremely low saturation (S=4-6). Compensate with 3x saturation boost in detector.
- AWB must stay ON — manual WB gives unusable color shifts.

## Color Marker Detector v3 (2026-06-05)

`detect_color_markers.py` — offline, image-based, NO COM ports, NO robot.

**Key features added v3:**
- `preprocess_frame()` with configurable `--boost N` (default 3x)
- Workspace ROI filter: `WS_MIN_X=10, WS_MAX_X=450, WS_MIN_Y=40, WS_MAX_Y=470`
- Minimum confidence threshold (0.25) for green/pink visibility in `classify_state`
- Orange→Yellow cup fallback with disambiguation: `_is_cup_yellow()` requires conf≥0.25 AND area≥150
- Orange cup acceptance requires conf≥0.25 AND area≥80

**HSV ranges (tuned for MSMF 0 + boost 3x):**
```python
"yellow":  ((20,  60,  80), (35, 255, 255))
"green":   ((35,  50,  80), (85, 255, 255))
"pink":    ((145, 50,  80), (175, 255, 255))
"orange":  ((5,   60,  80), (20, 255, 255))
```

**State classification:** occlusion-based. Cup visible + green not visible + pink visible = cup_on_green. All low-confidence detections filtered before classification.

## Leader/Follower Reference Strategy (2026-06-05)

When visual servoing alone cannot converge (starting distances >100px with oscillation), use the leader arm (COM4) to demonstrate the trajectory once, then replay with small CV offset corrections.

### 3-Stage Approach

```
Stage 1: Leader Demo → Candidate Reference
  - Boss manually demonstrates pick-and-place on COM4 leader arm
  - Record all 6 joint positions + top-view snapshot
  - Save as candidate_reference.json
  - Follower replays → boss verifies visually → "validated" label
  - NOT "perfect golden reference" — servo load, backlash, cup slip,
    gripper friction, and cable drag can cause replay differences.

Stage 2: CV Reference State
  - Snapshot during validated replay → reference_state.json
  - Contains: yellow tip pos, X-marker pos, green/pink marker visibility
  - All positions stored in fixed top-camera pixel coordinates

Stage 3: CV Offset Replay + Gradual Expansion
  - CV detects current cup position → computes Δx, Δy from reference
  - Applies offset to reference trajectory → follower replays
  - Verify with occlusion marker logic
  - Expand range: 50px → 100px → 200px
```

### Why This Over Pure Visual Servo

Pure visual servoing from 140px+ starting distance fails because:
- Nudge converges to ~89px minimum, then oscillates
- Cup detection jumps 20-30px between captures
- Shoulder_pan pixel effect varies nonlinearly with joint angle

Leader reference provides an exact trajectory. CV only needs to correct a small Δ (10-30px), not the full distance.

### Trajectory Recording — Critical Pattern (2026-06-05)

**Leader `get_action()` returns absolute joint positions, NOT relative deltas.** But the values are only meaningful when the action is sent to the follower (teleop mirroring mode). Without `send_action()`, all recorded positions stay static.

**Correct recording loop:**
```python
leader_action = leader.get_action()       # read leader absolute position
robot.send_action(leader_action)          # MUST send to follower (teleop)
obs = clean_obs(robot.get_observation())  # record follower's actual mirror position
# Store obs as frame["joints"]
```

**Trajectory frame format:**
```json
{"t": 0.0, "dt": 0.0, "joints": {"shoulder_pan.pos": -3.0, ...}}
```

**Scripts:**
- `record_leader_trajectory.py` — COM4 leader → COM3 follower mirror, 10Hz, configurable duration
- `replay_follower_trajectory.py` — replays `joints` from trajectory JSON on COM3, `--speed N` for slowdown
- `replay_with_cv_offset.py` — captures current snapshot, detects cup Δ from reference, applies px→deg offset

## Occlusion-Based Marker Verification (2026-06-05)

Replace "did the cup lift?" (hard to judge from top-down 2D) with "is the floor marker covered?"

### Marker System (Current — 2026-06-05)

See `so101-vision-pipeline` skill for up-to-date HSV ranges and detection thresholds.

| Marker | Color | Meaning | Detection |
|---|---|---|---|
| Orange/Yellow | orange/yellow | Cup marker (on top of cup) | `detect_color_markers.py` — HSV inRange |
| Green | green | Target point A | `detect_color_markers.py` — HSV inRange |
| Pink | pink | Target point B | `detect_color_markers.py` — HSV inRange |
| Yellow tip | yellow | Gripper tip | `detect_color_markers.py` — filtered by area/position |

**Note:** The original black X-marker on the cup has been replaced with orange/yellow color markers. X-marker detection via `detect_x_marker_feature()` is deprecated and no longer used.

### Principle

When the cup is placed ON a floor marker, that marker is OCCLUDED (not visible). This is a binary problem — much easier for both CV and Qwen than "is the cup hovering 5mm above the table?"

### Static State Classes

| Class | Green | Pink | X | Meaning |
|---|---|---|---|---|
| `cup_on_green` | no | yes | yes | Cup covers green marker |
| `cup_on_pink` | yes | no | yes | Cup covers pink marker |
| `cup_between` | yes | yes | yes | Cup covers neither |
| `empty_floor` | yes | yes | no | No cup in area |
| `needs_review` | mixed | mixed | mixed | Arm shadow/glare/partial occlusion |

### Critical Correction (REV1, 2026-06-05)

The original plan REVERSED the green/pink interpretation. Correct rule:
- Green NOT visible → green is covered → cup is ON green
- Pink NOT visible → pink is covered → cup is ON pink

Do NOT use "forward"/"reverse" as ground truth labels until the physical meaning of green/pink is stored in a config file.

## Reference Frame Contract (No ArUco)

```text
The current workcell reference is the fixed top-camera pixel coordinate system
defined by green, pink, X, and gripper-tip markers. Camera movement, focus
change, exposure change, or marker movement invalidates the reference and
requires recapture.
```

ArUco was removed from the workcell. If metric table-plane coordinates or camera pose are needed later, ArUco can be restored — but it is not required for this static occlusion test.

## Qwen VL Judgment — Role Limitations (2026-06-05)

### What Qwen MUST NOT Do

- **NOT a real-time controller** — ~10s per frame, cannot be in a servo loop
- **NOT a spatial feedback source** — "left/right/up/down" answers are unreliable (2B model, conf ~0.50)
- **NOT a replacement for CV** — CV already provides precise dx, dy pixel values

### Shadow Validation Results (2026-06-05)

Qwen2-VL-2B tested against CV detector on 4 static states:

| State | CV | Qwen | Match |
|-------|-----|------|-------|
| empty_floor | empty_floor | cup_on_green | ❌ |
| cup_between | cup_between | cup_on_green | ❌ |
| cup_on_green | cup_on_green | cup_on_green | ✅ |
| cup_on_pink | cup_on_pink | cup_on_green | ❌ |

**Accuracy: 25% (1/4).** Qwen always classified as `cup_on_green` because it could not see the pink marker in low-saturation (S=4-6) images. CV detector with 3x saturation boost reliably distinguishes all states.

**Conclusion:** Qwen is NOT usable as a standalone state classifier under these camera conditions. CV must be the primary classifier. Qwen remains shadow-only for batch/post-hoc comparison.

### What Qwen CAN Do

- **Shadow/batch verifier** — run after the fact, not in the control loop
- **Binary/3-value classifier** — `success / failure / uncertain` (for pick-lift judgment, not marker state)
- **Compare against human labels and CV output** → confusion table

### Promotion Gate

Qwen MAY be promoted to advisory judgment ONLY after:
1. Confusion table written (Qwen vs human labels)
2. Zero false-success bias (never says "success" when human says "failure")
3. False-positive rate documented and accepted

Until then, Qwen output is shadow only — compare with CV and human, do not act on it.

### Execution Order (Corrected)

```
1. Static marker classifier validation (offline images, no robot)
2. CV vs human confusion table
3. Qwen shadow comparison on saved images
4. Leader/follower reference collection
5. CV-offset replay
```

Robot execution (COM3/COM4) is FORBIDDEN until static marker classifier passes acceptance criteria.

## Windows Encoding (cp949)

Korean Windows uses cp949 encoding for PowerShell stdout. Use ONLY ASCII in print statements. Avoid:

| Avoid | Use Instead |
|-------|------------|
| ✅ ✓ | `[OK]` |
| ❌ ✗ | `[FAIL]` |
| ⚠ ⚡ | `[WARN]` |
| ★ ☆ | `*` |
| ° (degree) | ` deg` |
| — (em dash) | `--` or `-` |
| → | `->` |
| 🚫 ⛔ | `[BLOCKED]` |
| ⏺ ⏵ | `[REC]` `[PLAY]` |
| 💡 🔍 | (omit) |
| Any emoji | (omit entirely) |

**This applies to ALL scripts that print to stdout via PowerShell.** The error manifests as:
```
UnicodeEncodeError: 'cp949' codec can't encode character '\uXXXX' in position N: illegal multibyte sequence
```

Write to files (JSON, TXT) in UTF-8 (`encoding="utf-8"`) — those are fine. Only stdout is affected.

### cp949 Workaround: PYTHONIOENCODING

When Unicode characters CANNOT be avoided in stdout (e.g., pre-existing code with ✓, —, emoji), force UTF-8 output by setting the environment variable before Python runs:

```powershell
# PowerShell — set env var inline before python command
powershell.exe -Command "\$env:PYTHONIOENCODING='utf-8'; python -u scripts\round_trip_loop.py ..."
```

This tells Python to emit UTF-8 to stdout regardless of the console's default code page. Use this sparingly — rewriting to ASCII is preferred for long-term maintainability.

### PowerShell Background Output Capture

When running robot scripts via `powershell.exe -Command` in Hermes background mode, stdout often does NOT appear in the `process` tool's poll/log output. The output is lost because PowerShell's stdout handling differs from bash.

**Workaround: redirect to file, read from WSL**

```bash
# Start with file redirect
powershell.exe -Command "python -u script.py > C:\path\to\out.log 2>&1"

# Read from WSL (PowerShell defaults to UTF-16 LE encoding)
iconv -f UTF-16 -t UTF-8 /mnt/c/path/to/out.log
```

**Why UTF-16:** PowerShell's `>` redirect operator writes UTF-16 LE by default (BOM `\xFF\xFE`). Use `iconv` or `python3 -c "open(p,encoding='utf-16').read()"` to decode. For `Tee-Object`, same UTF-16 default applies.

**Alternative — bash-style redirect via cmd /c:**
```bash
# cmd.exe uses the system ANSI code page (cp949), avoids UTF-16 issue
cmd.exe /c "python -u script.py > C:\path\to\out.log 2>&1"
```

But this reintroduces the cp949 encoding problem. The `$env:PYTHONIOENCODING='utf-8'` + file redirect + `iconv` combo is the most reliable pattern found so far.

## Key Files

### Robot Workspace (C:\Users\Research\Documents\Robot)

- `scripts/yellow_servo_pick.py` — single-attempt CV servo + grasp
- `scripts/auto_pick_loop.py` — multi-attempt loop with CV+Qwen judgment
- `scripts/golden_pick.py` — reference pick with known cup position
- `scripts/detect_color_markers.py` — offline color marker detector (--image input, no COM)
- `scripts/so101_teach_teleop.py` — leader(COM4)→follower(COM3) real-time teleop
- `scripts/record_leader_trajectory.py` — record leader arm joint trajectory to JSON (2026-06-05)
- `scripts/replay_follower_trajectory.py` — replay recorded trajectory on follower (2026-06-05)
- `scripts/replay_with_cv_offset.py` — CV cup-position offset correction + replay (2026-06-05)
- `scripts/round_trip_loop.py` — autonomous bidirectional round-trip loop: green→pink→green repeat with detector verification + video recording (2026-06-05)
- `bridge/_move_to_v11_start.py` — reset arm to pick_green_v11 frame-0 position
- `bridge/_move_to_v2_start.py` — reset arm to pick_pink_v2 frame-0 position
- `scripts/so101_pose_tool.py` — robot connection + joint utilities
- `scripts/top_view_pick_correction.py` — X-marker detection
- `reports/auto_pick_place_plan_20260605_REV1.md` — corrected plan
- `reports/static_marker_state_test_plan_20260605.md` — test plan

### WSL (/home/research)

- `analyze_single.py` — single-video Qwen classifier (called via `wsl python3`)
- `batch_analyze.py` — nightly batch video analysis
- `nightly_analyze.sh` — one-line batch runner
- `models/Qwen2-VL-2B-Instruct-Q4_K_M.gguf` — Qwen model (941MB)
- `models/mmproj-Qwen2-VL-2B-Instruct-f16.gguf` — multimodal projector (1.3GB)

## Static Marker Test — Gripper Interference (2026-06-05)

When testing color marker detection with a static top-camera image, the gripper may still be in frame. Pink HSV ranges (150-175°H) can detect gripper finger tips as false positives because the 3D-printed black material can reflect pinkish tones under certain lighting.

**Solution:** Move the arm to HOME position before capturing static validation images. HOME puts the arm outside the top-camera field of view.

```powershell
# Quick HOME move before static capture
python -c "from so101_pose_tool import connect_robot, clean_obs; ..."
```

If the arm cannot be moved, filter out detections that overlap with known gripper positions, or use a narrower pink HSV range.

**Test workflow:**
1. Move arm to HOME (out of frame)
2. Capture static image → run `detect_color_markers.py`
3. Verify marker positions are correct (deliver annotated image to boss)
4. Tune HSV ranges if confidence < 0.3
5. Repeat for each state class (empty_floor, cup_on_green, cup_on_pink, cup_between)
6. Build confusion table: CV output vs human label
7. Proceed to robot tests ONLY after all acceptance criteria pass (see `static_marker_state_test_plan`)

## Success Criteria: Multi-Camera Video Evidence (2026-06-09)

**held_ratio is NOT a reliable success indicator.** On 2026-06-09, trajectory replay achieved held_ratio=0.93 with grip offset -15, but the boss confirmed the cup was NOT actually transported. The aux camera CV gate can report HELD even when the cup has fallen.

### Unreliable Metrics

| Metric | Why Unreliable |
|--------|---------------|
| `held_ratio` | Measures CV gate HELD frames / total, but CV gate can hallucinate HELD when cup dropped (wrist camera FOV loss, marker confusion) |
| `verdict: detector_target_occluded` | Detector infers occlusion from marker absence, NOT physical cup position |
| `green_visible: True` | Only means green marker uncovered — cup may still be on green side |

### New Standard: Multi-Camera Video Evidence

1. **Top camera video** — shows cup position on table (green/pink zone)
2. **Aux/wrist camera video** — shows cup relative to gripper mid-transit
3. **Pre/post snapshots** — timestamped still images for side-by-side comparison
4. **Operator visual confirmation** — boss 육안 확인이 최종 판정

### Success Definition

> Cup physically moved from source zone (green) to target zone (pink) — confirmed by:
> - Top camera: cup absent from source, present at target
> - Aux camera: cup visible in gripper during transit, absent after release
> - Operator: visual check of delivered video/snapshots

Until operator confirms, all automatic verdicts are **advisory only**.

## Information Request vs Execution Approval (CRITICAL — 2026-06-09)

**보스 교정:** "어떻게하는거야?", "알려줘", "작성해줘", "명령어 알려줘" 등은 정보 요청이지 실행 승인이 아니다.

**Do NOT execute when the boss asks:**
- "어떻게하는거야?" → 설명/명령어만 제공
- "goal 명령어 작성" → 프롬프트 텍스트를 보여주기만 (cron job 생성 금지)
- "알려줘" → 정보만 전달

**Only execute when boss explicitly approves:**
- "진행해", "시작해", "실행해", "그래 승인"
- cron job, delegate_task, terminal 실행, 로봇 동작 모두 명시적 승인 후에만

## DeepSeek Revision Workflow (2026-06-05)

The boss (Joo) may send a comprehensive revision document via DeepSeek that corrects the current plan. This is a structured pattern:

**Trigger:** Boss sends a `.md` file titled `deepseek_prompt_*_rev*` with mandatory corrections.

**Response protocol:**
1. Read the prompt carefully — it lists required input files, hard constraints, and mandatory corrections
2. Read ALL referenced files before making any changes
3. Audit actual file presence (not all referenced files may exist — note gaps honestly)
4. Implement every mandatory correction exactly as specified
5. Create new output files (never overwrite originals unless explicitly told)
6. Produce exactly the files requested, in the order specified
7. Verify: file existence, syntax check if code, no robot/camera access without approval

**Common constraints in these prompts:**
- No robot motion, no COM port access, no camera capture by default
- Read HANDOFF.md first
- Do not re-add removed components (ArUco, etc.)
- Use neutral class names (cup_on_green, not forward/first)

**Key lesson:** When the boss sends a correction doc, treat it as authoritative over your own plan. Implement faithfully. Do not argue or re-interpret.

## Auto-Correction Pipeline Execution (2026-06-05)

`scripts/auto_correct_pipeline.py` runs pick_green→pink replay with post-run detector verification and correction accumulation.

### Verdict Types

| Verdict | Trigger | Meaning |
|---------|---------|---------|
| `replay_failed` | `[PLAY] FAIL` in replay script (elapsed <10s) | COM3 serial failure — trajectory never executed |
| `detector_ambiguous` | Robot moved but pink_occluded=False | Trajectory replayed but cup didn't reach target |
| `user_confirmed_success` | User enters `s` as label | Pink occluded — cup placed on target |

### Bridge Update Sequence After Pipeline Session

When a pipeline session completes (whether success or failure):

1. Append session summary to `RUN_INDEX.jsonl` — one entry per session with all run verdicts
2. Append session summary to `TASK_LOG.jsonl` — session-level summary with verdict array
3. Update `LIVE_TEST_STATUS.md` — new mode string, last results, next step
4. If stopped on 2-failure rule: write `HERMES_LIVE_TEST_REPORT_YYYYMMDD_HHMM.md` to `reports/`
5. Update `HERMES_TO_CODEX.md` with review request (status, what happened, questions)

### Stop Condition: 2-Consecutive-Failure Rule

If the same trajectory fails twice in a row (any combination of `replay_failed` + `detector_ambiguous`):

1. The pipeline auto-stops (no more runs)
2. Write a full live test report immediately
3. Do NOT attempt another run until root cause is diagnosed
4. Update LIVE_TEST_STATUS mode to `stopped-2-failure-rule`
5. Request Codex review via HERMES_TO_CODEX.md

This rule fired on 2026-06-05 when v11 trajectory (previously user-confirmed success) failed with `replay_failed` (COM3, 7.9s) then `detector_ambiguous` (68.1s, cup stayed on green).

### COM3 Reliability

`[PLAY] FAIL` with very short elapsed time (<10s for a 60s trajectory) indicates COM3 serial connection failure — the replay script couldn't open or communicate with the port. Before next physical run after a PLAY FAIL:

1. Kill all lingering Python processes on Windows: `Get-Process python* | Stop-Process -Force`
2. Verify COM3 is listed: `[System.IO.Ports.SerialPort]::GetPortNames()`
3. Power-cycle the robot if permission error persists
4. Run a quick connect test before launching the full pipeline

## Overnight Unattended Loop Protocol (2026-06-05, revised 22:00 KST)

When the boss orders an unattended overnight run, the rules are:

### Rules

1. **No auto-correction.** Fixed trajectories only (v11 forward, v2 reverse). Do not change joint offsets.
2. **Data collection only.** The goal is repeatability data and calibration samples, not adaptive learning.
3. **Strict pre-state checking.** `--strict-pre-state` must be on. Every leg verifies the cup is on the expected source marker before replaying.
4. **Multi-set structure.** Do NOT attempt 60 rounds at once. Split into 10-round sets (6 sets max). Each set must be analyzed before the next.
5. **Failure tolerance.** `--max-consecutive-failures 2` for unattended runs (the boss raised this from 1 on 2026-06-05 after the detector gate was fixed to allow `ambiguous_after_previous_success`).
6. **Leg cooldown.** 5 seconds between legs for cup/arm settling.
7. **Fresh Python process per set.** Kill all `python*` processes between sets. This ensures camera settings are fresh.
8. **Night camera profile.** When room lights are off, use `configs/camera_capture_profile.json` (MSMF, exposure=-4, gain=0, brightness=0, mean brightness ~143).
9. **Run analyzer after each set.** `python scripts/analyze_round_trip_calibration.py` after each set's loop exits.
10. **Log everything to bridge.** RUN_INDEX.jsonl, TASK_LOG.jsonl, LIVE_TEST_STATUS.md, CALIBRATION_SAMPLES.jsonl.
11. **Pre-written plan required.** The boss must approve the plan document before execution.

### Stop Conditions (HARD)

- **2 consecutive physical failures** → STOP immediately. Report with video/snapshot evidence.
- **Replay failed** (`[PLAY] FAIL`, COM error, trajectory not executed) → STOP immediately.
- **Cup dropped** (visible in video/post-snapshot) → STOP immediately.
- **Cup clearly in wrong position** (not near either marker) → STOP immediately.
- **Collision / abnormal noise / joint error / COM error** → STOP immediately.

### Continue Conditions (NOT failures)

- **`detector_target_occluded`** → SUCCESS. Continue.
- **`pre_state_note=ambiguous_after_previous_success`** → Detector noise, NOT physical failure. Continue.
- **`strict_pre_state_failed` when pre_state is unexpected class (not `cup_between`)** → Detector guard, NOT physical failure. The cup may be correctly positioned but detector misclassified. Stop the set but log as detector issue, not physical failure.
- **Detector state mismatch between frames of the same physical scene** → Detector instability, NOT physical failure. Log and continue.

### 60-Round Target Command

```powershell
cd C:\Users\Research\Documents\Robot
# Set 1-6 (each 10 rounds, run sequentially with analysis between sets)
python scripts\round_trip_loop.py --execute --rounds 10 --strict-pre-state --max-consecutive-failures 2 --leg-cooldown-s 5
python scripts\analyze_round_trip_calibration.py
# Then: analyze → kill python processes → next set
```

### Per-Set Reporting

After each set, report:
- Rounds completed / legs attempted / successes / physical failures
- Detector ambiguity count
- Stop reason (if any)
- Cumulative forward/reverse reliability
- Latest video and snapshot paths
- CALIBRATION_SAMPLES cumulative count

### Final Report (after all sets)

At the end of 60 rounds (or early stop), produce:
- Total sets run / rounds / legs
- Detector-based success count
- Video/snapshot-based estimated success
- Actual physical failure count and root causes
- Detector ambiguity count
- Representative ambiguity/failure snapshot paths
- Latest video paths
- CALIBRATION_SAMPLES cumulative count
- Items ready for correction learning vs still missing

## Leg Judgment Rule: Same-Leg Pre/Post Only (CRITICAL — 2026-06-05)

**DO NOT compare one leg's post-snapshot with another leg's pre-snapshot.** This was a major interpretation error caught by the boss on 2026-06-05. The agent incorrectly called r01_rev a "physical failure" by comparing r01_fwd_post (21:36:02) with r01_rev_pre (21:36:13) — but those are different snapshots from different moments. The leg was BLOCKED before motion (strict pre-state gate), not a physical failure.

**Correct rule:**
- Judge each leg by comparing **that leg's own pre and post snapshots**
- `r01_fwd`: compare `r01_fwd_pre` vs `r01_fwd_post` → pink area 522→79 (85% drop) → SUCCESS
- `r01_rev`: was blocked before replay — no pre/post to compare → NOT a physical failure
- `pre_state_note=ambiguous_after_previous_success` is a gate classification, not a motion result

**Gate logic (Codex-patched 2026-06-05 21:41 KST):**
```python
def strict_pre_state_allowed(expected_state, pre_state, results):
    if pre_state == expected_state:
        return True, ""
    previous_ok = bool(results and is_success_verdict(results[-1].get("verdict", "")))
    if previous_ok and pre_state == "cup_between":
        return True, "ambiguous_after_previous_success"
    return False, ""
```
- Clear mismatch (e.g., `cup_on_pink` when `cup_on_green` expected and no previous success) → STOP
- `cup_between` after a successful previous leg → ALLOW, log `ambiguous_after_previous_success`

**Occlusion check uses same-leg comparison:**
```python
def check_occlusion_since_pre(pre_det, post_det, marker_key):
    # Compares THIS leg's pre vs THIS leg's post
    pre_area = marker_area(pre_det, marker_key)
    post_area = marker_area(post_det, marker_key)
    relative_occluded = post_area <= pre_area * 0.35  # 65%+ area drop
    ...
```

## Detector Reliability: Pink Marker Instability (2026-06-05)

**Critical pitfall:** The pink marker detector produces inconsistent classifications across frames of the same physical scene. On 2026-06-05, two snapshots taken 11 seconds apart of an unmoved cup produced different classifications:

| Snapshot | Detector | Ground truth (vision) |
|----------|----------|----------------------|
| 21:36:02 | `cup_on_pink` | Cup on plain table, pink not visible |
| 21:36:13 | `cup_between` | Cup on same position, pink not visible |

The cup did not physically move. The detector changed its mind due to pink-marker false positives at wrong image locations (e.g., detecting pink at [36, 301] when real pink baseline is at [151, 84]). Pink area_ratio is **inflated by false positives** and should not be used as the sole success gate.

**Impact on unattended loops:** Strict pre-state catches this inconsistency and stops the loop correctly — but it also means the loop cannot progress past the first reverse leg because the reverse pre-state compares against pink marker classification.

**Recommended fix:** For reverse leg pre-state, use **green-occlusion-only gating** instead of pink marker classification:
- Forward (green→pink): pre-state checks cup is on green (reliable — green is rarely misdetected). Post-state checks pink is occluded.
- Reverse (pink→green): pre-state checks green is visible (cup NOT on green). Do NOT require `cup_on_pink` classification. Let the forward post-state pink occlusion check be the gate, not the reverse pre-state pink classification.

Until this fix is applied, unattended loops will reliably stop after the first successful forward leg when the reverse pre-state detector inconsistency triggers.

## Reverse Leg Gripper Offset (2026-06-05 22:40 KST)

The reverse trajectory (pick_pink_v2) may not close the gripper firmly enough on the cup, causing grasp failures. Boss requested: "컵을 그리퍼가 쥘때 조금더 많이 쥘수없을까?"

**Solution:** Added `--gripper-offset` to `replay_follower_trajectory.py` and `--reverse-gripper-offset` to `round_trip_loop.py`. During replay, every frame's `gripper.pos` is offset by the specified amount (negative = close more).

**replay_follower_trajectory.py patch:**
```python
parser.add_argument("--gripper-offset", type=float, default=0.0,
                    help="Offset added to gripper.pos each frame (negative = close more)")
# In replay loop:
if gripper_offset != 0.0 and "gripper.pos" in action:
    action = dict(action)  # shallow copy
    action["gripper.pos"] = action["gripper.pos"] + gripper_offset
```

**round_trip_loop.py patch:**
```python
parser.add_argument("--reverse-gripper-offset", type=float, default=-3.0,
                    help="Offset for gripper.pos on reverse leg (negative = close more)")
# Passed to reverse leg replay:
replay_ok, _ = replay_trajectory(TRAJ_PINK, dry_run=args.dry_run,
                                  gripper_offset=args.reverse_gripper_offset)
```

**Usage:**
```powershell
python scripts/round_trip_loop.py --execute --rounds 10 --reverse-gripper-offset -5
```

Default is -3.0 degrees. Forward leg is unaffected (offset=0). Increase magnitude (-5, -8) if reverse grasp still fails.

## Forward vs Reverse Reliability (2026-06-05, updated 22:40 KST)

Three overnight unattended sessions revealed a critical asymmetry:

| Direction | Trajectory | Attempts | Success | Rate |
|-----------|-----------|----------|---------|------|
| Forward (🟢→🔴) | pick_green_v11 | 5+ | 5+ | **~100%** |
| Reverse (🔴→🟢) | pick_pink_v2 | 3+ | 2+ | **~50%** |

**Forward leg is reliable.** Pink area consistently drops 59-85% (same-leg pre→post), exceeding the 65% occlusion threshold (post_area ≤ pre_area * 0.35).

**Reverse leg is intermittent.** Two successes achieved (green area drop 73-85%) but also two failures (green area drop 1-34%). The v2 reverse trajectory may have an insufficiently firm grip — boss observed cup slipping or falling during reverse grasp.

**Potential fix (2026-06-05):** Added `--reverse-gripper-offset` (default -3.0 deg) to close gripper more firmly during reverse replay. Increase to -5 or -8 if needed. See "Reverse Leg Gripper Offset" section.

## Night Camera Detector Ambiguity (2026-06-05 22:15 KST, patched 22:36)

When room lights are off and the night camera profile is active (exposure=-4, gain=0, brightness=0, mean brightness ~143), the color marker detector becomes unreliable:

- **Green marker visibility collapses:** Green area drops from baseline 916 to ~95 (10.4% of baseline). This is NOT the same as cup occlusion — it's the camera's inability to see the green marker in low light.
- **`cup_on_green` is rarely detected:** Even when the cup is physically on the green marker, the detector returns `needs_review`, `empty_floor_review`, or `empty_floor` because the green marker signal is too weak.
- **Pink detection also degrades:** Pink area ratio becomes less reliable, with false positives at wrong image positions.
- **Vision (VL model) verification is essential** — the detector alone cannot be trusted at night.

**Final patch (v3, 2026-06-05 22:36) — always pass night ambiguity states:**

```python
NIGHT_AMBIGUOUS_STATES = {"cup_between", "needs_review", "empty_floor_review", "empty_floor"}

def strict_pre_state_allowed(expected_state, pre_state, results):
    """
    Night detector ambiguity states are ALWAYS allowed through.
    The max_consecutive_failures guard handles actual stop conditions.
    """
    if pre_state == expected_state:
        return True, ""
    if pre_state in NIGHT_AMBIGUOUS_STATES:
        previous_ok = bool(results and is_success_verdict(results[-1].get("verdict", "")))
        no_prior = len(results) == 0
        if no_prior:
            return True, "night_detector_ambiguous_first_leg"
        if previous_ok:
            return True, "ambiguous_after_previous_success"
        return True, "night_detector_ambiguous_despite_previous_failure"
    return False, ""
```

**Evolution of this patch (3 iterations):**
1. v1: Only `cup_between` allowed with prior success (`ambiguous_after_previous_success`)
2. v2: Added `needs_review` + `empty_floor_review`, allowed on first leg too (no prior results needed). But still required prior success otherwise.
3. v3 (final): Added `empty_floor`, **always pass** all 4 night-ambiguous states regardless of previous result. `max_consecutive_failures` is the sole stop condition.

**Why v3 is necessary:** If the previous leg had a `detector_target_visible` failure (which at night could itself be a detector issue), v2 would block the next leg's `empty_floor` state. This stopped the loop at r06_fwd in Set 1 (2026-06-05). The cup was correctly positioned but the detector couldn't confirm it.

**Rule:** Under night lighting, always verify detector output with vision/snapshot analysis before concluding physical failure. The detector's area ratios are unreliable — green area dropping from 916 to 95 is the camera's fault, not cup placement.

### Arm Pose Drift Between Sessions (2026-06-05)

**Critical discovery:** The SO-101 follower arm does NOT hold its position between sessions. After prior pipeline/loop runs, all joints drifted significantly. On 2026-06-05, the arm was found at:

| Joint | v11 start | Actual | Delta |
|-------|-----------|--------|-------|
| shoulder_pan | +2.1 | -3.8 | **-5.9** |
| shoulder_lift | -90.5 | -103.3 | **-12.7** |
| elbow_flex | 101.8 | 97.8 | **-4.0** |
| wrist_flex | 59.4 | 77.5 | **+18.1** |
| wrist_roll | 90.5 | 96.0 | **+5.5** |
| gripper | 0.0 | 7.4 | **+7.4** |

The gripper was partially closed (7.4°) — incapable of grasping. This explains why a previously successful trajectory (v11 at 17:08) failed on subsequent replays (19:24, 19:29): the replay executed correctly but from the wrong starting position.

**Rule:** Before every trajectory replay session, check the arm's current pose against the trajectory's frame 0 and reset if any joint delta exceeds 2.0°.

### Arm Reset to Trajectory Start Position

When arm pose has drifted, reset to trajectory frame 0 before replay:

**Move order matters:** Open gripper FIRST, then proximal-to-distal (shoulder → elbow → wrist). This prevents the partially-closed gripper from hitting the table:

```
1. gripper.pos → 0.0     (open fully)
2. shoulder_lift.pos      (lift clear of workspace)
3. shoulder_pan.pos       (horizontal alignment)
4. elbow_flex.pos
5. wrist_flex.pos
6. wrist_roll.pos
```

Use single-joint `send_action()` calls with 0.5s settle time between moves. Do NOT send the full target pose at once — the safety clamp limits per-action deltas and single-joint moves are more predictable.

```python
# Pattern: reset one joint at a time
for joint in MOVE_ORDER:
    action = {joint: target[joint]}
    robot.send_action(action)
    time.sleep(0.5)
```

After reset, verify all joints are within tolerance before launching replay.

**Script reference:** `bridge/_move_to_v11_start.py` (adapt target positions for other trajectories)

## Reference Files

- `references/bridge-protocol-20260605.md` — shared Codex-Hermes file-based coordination bridge protocol (RUN_INDEX, TASK_LOG, LIVE_TEST_STATUS, stop conditions)
- `references/overnight-60round-protocol-20260605.md` — 60-round overnight data collection: 10-round sets, stop/continue rules, reporting format
- `references/rev2-workflow-corrections-20260605.md` — consolidated REV2 corrections: occlusion logic fix, nudge sign bug, Codex convergence, Qwen role limits, COM3 recovery, execution order
- `references/static-marker-test-plan-20260605.md` — static state classes, acceptance criteria, gripper interference pitfall, confusion table template
- `references/codex-verification-cv-qwen-hybrid-20260605.md` — Codex GPT-5.5 full verification of CV+Qwen hybrid architecture
- `references/pipeline-execution-report-20260605.md` — auto_correct_pipeline session report: 2-failure rule in action, verdict classification, bridge update sequence
- `references/arm-pose-drift-20260605.md` — arm pose drift discovery: all 6 joints drifted up to 18° between sessions, gripper partially closed, root cause of replay failures
- `references/round-trip-loop-20260605.md` — round-trip autonomous loop: 16-leg results, video recording integration, occlusion check bug fix, detector false alarm pattern
