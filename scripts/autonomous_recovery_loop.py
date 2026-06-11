#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Autonomous Pick-and-Place Monitor with Recovery Loop v2
=======================================================
State machine based on observable reality:
  NOT_HELD ⇄ HELD  (two stable states, transitions are grasp/release)

Anomalies:
  - Flip-flop: rapid oscillation without enough stable frames
  - Stuck: same state too long when expecting transition
  - UNCERTAIN: ambiguity for too many consecutive frames

Recovery: CV gate → anomaly detected → Gemini Vision → recovery plan
"""
import base64
import cv2
import os
import requests
import time
import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════
VIDEO_PATH = "/mnt/c/Users/Research/Documents/Robot/logs/camera_recordings/camera_recording_20260608_175717_stable_reverse_preclose_v5_override_1_20260608_dual_motion_dual.mp4"
OPENROUTER_MODEL = "google/gemini-2.5-flash"
FRAME_STEP = 5
DEBOUNCE_FRAMES = 3        # consecutive frames to confirm state change
MAX_UNCERTAIN_FRAMES = 4   # consecutive UNCERTAIN → anomaly

# CV gate thresholds
ORANGE_LOWER = (10, 100, 100)
ORANGE_UPPER = (25, 255, 255)
BLUE_LOWER = (85, 35, 35)
BLUE_UPPER = (135, 255, 255)
ORANGE_FLOOR = 100
ORANGE_THRESHOLD = 500
BLUE_THRESHOLD = 5000

# ═══════════════════════════════════════════════════════
# CV Gate
# ═══════════════════════════════════════════════════════
def largest_blob(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return max([cv2.contourArea(c) for c in contours]) if contours else 0

def cv_detect(hsv_frame):
    orange = largest_blob(cv2.inRange(hsv_frame, ORANGE_LOWER, ORANGE_UPPER))
    blue = largest_blob(cv2.inRange(hsv_frame, BLUE_LOWER, BLUE_UPPER))
    
    if orange < ORANGE_FLOOR:
        return "NOT_HELD", orange, blue
    if orange > ORANGE_THRESHOLD:
        return "HELD", orange, blue
    if blue < BLUE_THRESHOLD:
        return "NOT_HELD", orange, blue
    return "UNCERTAIN", orange, blue

# ═══════════════════════════════════════════════════════
# Gemini Recovery
# ═══════════════════════════════════════════════════════
def get_env_key(name):
    env_path = os.path.expanduser("~/.hermes/.env")
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return None

def ask_gemini(image_bgr, anomaly_type, context):
    api_key = get_env_key("OPENROUTER_API_KEY")
    if not api_key:
        return "ERROR: No API key"
    
    tmp_path = "/tmp/anomaly_frame.jpg"
    cv2.imwrite(tmp_path, image_bgr)
    with open(tmp_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    
    prompt = f"""Robot wrist camera. Orange tape = cup marker. Yellow/pink = gripper tips.

ANOMALY: {anomaly_type}
Context: {context}

Analyze the image:
1. Where is the cup? State (upright/fallen/missing)?
2. Specific recovery plan for the robot.

Concise. Korean or English."""
    
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": prompt}
            ]}],
            "max_tokens": 300
        }, timeout=30)
    
    if resp.status_code == 200:
        return resp.json()["choices"][0]["message"]["content"]
    return f"API ERROR {resp.status_code}"

# ═══════════════════════════════════════════════════════
# Improved State Machine
# ═══════════════════════════════════════════════════════
@dataclass
class PickPlaceMonitor:
    state: str = "NOT_HELD"
    pending_state: str = None
    pending_count: int = 0
    stable_count: int = 0
    uncertain_count: int = 0
    
    # History
    transitions: list = field(default_factory=list)  # (frame, from, to)
    anomalies: list = field(default_factory=list)
    
    # Recovery state
    recovery_mode: bool = False
    recovery_source_state: str = None
    
    # Stats
    held_frames: int = 0
    not_held_frames: int = 0
    uncertain_frames: int = 0
    total_frames: int = 0

    def update(self, verdict, frame_idx):
        """Returns: None (stable) or anomaly description string."""
        self.total_frames += 1
        
        # Count states
        if verdict == "HELD":
            self.held_frames += 1
        elif verdict == "NOT_HELD":
            self.not_held_frames += 1
        else:
            self.uncertain_frames += 1
        
        # ── UNCERTAIN handling ──
        if verdict == "UNCERTAIN":
            self.uncertain_count += 1
            if self.uncertain_count >= MAX_UNCERTAIN_FRAMES:
                self._record_anomaly(frame_idx, f"UNCERTAIN for {self.uncertain_count} frames")
                self.uncertain_count = 0
                return f"UNCERTAIN too long ({MAX_UNCERTAIN_FRAMES}+ frames)"
            return None  # still waiting for clarity
        
        self.uncertain_count = 0  # got clear verdict
        
        # ── SAME as current state → stable ──
        if verdict == self.state:
            self.stable_count += 1
            self.pending_state = None
            self.pending_count = 0
            return None
        
        # ── DIFFERENT from current state → debounce ──
        if self.pending_state == verdict:
            self.pending_count += 1
        else:
            self.pending_state = verdict
            self.pending_count = 1
        
        # Need DEBOUNCE_FRAMES consecutive to confirm transition
        if self.pending_count < DEBOUNCE_FRAMES:
            return None
        
        # ── Transition confirmed ──
        old = self.state
        self.state = verdict
        self.pending_state = None
        self.pending_count = 0
        self.stable_count = 1
        
        # Check if this is a valid transition
        valid = (old == "NOT_HELD" and verdict == "HELD") or \
                (old == "HELD" and verdict == "NOT_HELD")
        
        event = f"{'NORMAL' if valid else 'UNEXPECTED'}: {old} → {verdict}"
        self.transitions.append((frame_idx, old, verdict, valid))
        
        if not valid:
            self._record_anomaly(frame_idx, event)
        
        return event

    def _record_anomaly(self, frame_idx, reason):
        self.anomalies.append({"frame": frame_idx, "reason": reason, "state": self.state})

    @property
    def is_normal(self):
        """Check if the pattern looks like a normal pick-and-place."""
        if len(self.transitions) == 0:
            return False
        # Normal: exactly 2 transitions (NOT_HELD→HELD, HELD→NOT_HELD)
        if len(self.transitions) == 2:
            t1, t2 = self.transitions
            return t1[3] and t2[3]  # both valid
        # Multiple cycles also OK if all valid
        return all(t[3] for t in self.transitions)


# ═══════════════════════════════════════════════════════
# Live Camera Reader (Windows shared dir)
# ═══════════════════════════════════════════════════════
LIVE_FRAME_DIR = "/mnt/c/Users/Research/Documents/Robot/live_frames"
LIVE_FRAME_FILE = "aux_latest.jpg"

def live_frame_reader(frame_dir=LIVE_FRAME_DIR):
    """Generator: yield (frame, frame_idx) from live frame directory."""
    frame_path = Path(frame_dir) / LIVE_FRAME_FILE
    idx = 0
    last_mtime = 0
    while True:
        if frame_path.exists():
            mtime = frame_path.stat().st_mtime
            if mtime > last_mtime:
                last_mtime = mtime
                frame = cv2.imread(str(frame_path))
                if frame is not None:
                    yield frame, idx
                    idx += 1
        time.sleep(0.1)


# ═══════════════════════════════════════════════════════
# Main Loop
# ═══════════════════════════════════════════════════════
def main(video_path=VIDEO_PATH, use_camera=False, camera_id=1):
    if use_camera:
        # Live mode: read from Windows Python stream
        frame_iter = live_frame_reader()
        total = float('inf')
        fps = 8.0
    else:
        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
    
    print(f"{'CAMERA' if use_camera else 'VIDEO'}: {video_path if not use_camera else f'device {camera_id}'}")
    print(f"FPS: {fps:.1f}  Debounce: {DEBOUNCE_FRAMES} frames  Step: {FRAME_STEP}")
    print()
    
    monitor = PickPlaceMonitor()
    recovery_plans = []
    frame_idx = 0
    gemini_calls = 0
    max_gemini_calls = 3
    
    while True:
        if use_camera:
            frame, current_idx = next(frame_iter)
            aux = frame  # already aux-only from Windows script
        else:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            aux = frame[:, 640:, :] if w == 1280 else frame
            current_idx = frame_idx
            frame_idx += FRAME_STEP
            if frame_idx >= total:
                break
        
        hsv = cv2.cvtColor(aux, cv2.COLOR_BGR2HSV)
        verdict, orange, blue = cv_detect(hsv)
        event = monitor.update(verdict, current_idx)
        
        # Heartbeat every 20 frames
        if monitor.total_frames % 20 == 0 and not event:
            print(f"[{current_idx:5d}] heartbeat | {verdict} | orange={orange:6.0f} blue={blue:6.0f}", flush=True)
        
        if event:
            is_anomaly = "UNEXPECTED" in event or "UNCERTAIN" in event
            tag = "⚠️ " if is_anomaly else "✓ "
            print(f"[f{frame_idx:5d}] {tag}{event} | orange={orange:6.0f} blue={blue:6.0f}")
            
            if is_anomaly and gemini_calls < max_gemini_calls:
                gemini_calls += 1
                print(f"         → Gemini recovery #{gemini_calls}...")
                recovery = ask_gemini(aux, event, 
                    f"State was {monitor.state}, held={monitor.held_frames} not_held={monitor.not_held_frames}")
                recovery_plans.append({"frame": frame_idx, "event": event, "plan": recovery})
                print(f"         → {recovery[:150]}...")
                print()
        
        if not use_camera:
            time.sleep(0.1)
    
    if not use_camera:
        cap.release()
    
    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"SUMMARY: {monitor.total_frames} frames processed")
    print(f"  HELD: {monitor.held_frames}  NOT_HELD: {monitor.not_held_frames}  UNCERTAIN: {monitor.uncertain_frames}")
    print(f"  Transitions: {len(monitor.transitions)}")
    for f, old, new, valid in monitor.transitions:
        print(f"    f{f}: {old} → {new} {'✓' if valid else '⚠️'}")
    print(f"  Anomalies: {len(monitor.anomalies)}")
    print(f"  Recovery plans: {len(recovery_plans)}")
    print(f"  Pattern normal: {monitor.is_normal}")
    
    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "source": str(video_path) if not use_camera else f"camera_{camera_id}",
        "state_machine": {
            "held_frames": monitor.held_frames,
            "not_held_frames": monitor.not_held_frames,
            "uncertain_frames": monitor.uncertain_frames,
            "transitions": [{"frame": f, "from": o, "to": n, "valid": v} for f, o, n, v in monitor.transitions],
            "is_normal": monitor.is_normal,
        },
        "anomalies": monitor.anomalies,
        "recovery_plans": recovery_plans,
    }
    out_path = "/tmp/autonomous_recovery_v2_report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--video", default=VIDEO_PATH)
    p.add_argument("--camera", type=int, default=0, help="Camera device ID (0=default)")
    p.add_argument("--live", action="store_true", help="Use live camera instead of video")
    args = p.parse_args()
    main(video_path=args.video, use_camera=args.live, camera_id=args.camera)
