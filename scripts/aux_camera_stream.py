# SPDX-License-Identifier: MIT
"""Windows-side: capture aux camera frames to shared dir for WSL monitor."""
import cv2
import time
import sys
from pathlib import Path

CAMERA_ID = 1  # aux camera
OUT_DIR = Path(r"C:\Users\Research\Documents\Robot\live_frames")
OUT_DIR.mkdir(parents=True, exist_ok=True)

cap = cv2.VideoCapture(CAMERA_ID, cv2.CAP_DSHOW)
if not cap.isOpened():
    print(f"CAMERA {CAMERA_ID} NOT FOUND", flush=True)
    sys.exit(1)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 8)

print(f"CAPTURING camera {CAMERA_ID} → {OUT_DIR}", flush=True)

frame_count = 0
while True:
    ok, frame = cap.read()
    if not ok:
        time.sleep(0.1)
        continue
    
    # Write latest frame (overwrite)
    path = OUT_DIR / "aux_latest.jpg"
    cv2.imwrite(str(path), frame)
    
    # Also save periodic snapshot
    if frame_count % 40 == 0:
        snap = OUT_DIR / f"aux_{frame_count:06d}.jpg"
        cv2.imwrite(str(snap), frame)
    
    frame_count += 1
    time.sleep(0.125)  # ~8 fps
