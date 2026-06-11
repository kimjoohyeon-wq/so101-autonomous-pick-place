# SPDX-License-Identifier: MIT
"""Windows-side aux camera streamer for the WSL monitor."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2


DEFAULT_OUT_DIR = Path(r"C:\Users\Research\Documents\Robot\live_frames")


def write_latest_frame(path: Path, frame) -> bool:
    """Write through a temporary file, then replace the latest frame atomically."""
    tmp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    if not cv2.imwrite(str(tmp_path), frame):
        return False
    tmp_path.replace(path)
    return True


def stream_camera(camera_id: int, out_dir: Path, width: int, height: int, fps: float, snapshot_every: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"CAMERA {camera_id} NOT FOUND", flush=True)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    delay = 1.0 / fps if fps > 0 else 0.125
    latest_path = out_dir / "aux_latest.jpg"

    print(f"CAPTURING camera {camera_id} -> {out_dir}", flush=True)
    frame_count = 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(delay)
                continue

            write_latest_frame(latest_path, frame)

            if snapshot_every > 0 and frame_count % snapshot_every == 0:
                snap_path = out_dir / f"aux_{frame_count:06d}.jpg"
                cv2.imwrite(str(snap_path), frame)

            frame_count += 1
            time.sleep(delay)
    except KeyboardInterrupt:
        print("STOPPED", flush=True)
        return 0
    finally:
        cap.release()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture aux camera frames for the SO-101 live monitor.")
    parser.add_argument("--camera", type=int, default=1, help="Camera device ID")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Directory for aux_latest.jpg")
    parser.add_argument("--width", type=int, default=640, help="Capture width")
    parser.add_argument("--height", type=int, default=480, help="Capture height")
    parser.add_argument("--fps", type=float, default=8.0, help="Capture frames per second")
    parser.add_argument("--snapshot-every", type=int, default=40, help="Save periodic numbered snapshots; 0 disables")
    args = parser.parse_args()

    return stream_camera(
        camera_id=args.camera,
        out_dir=args.out_dir,
        width=args.width,
        height=args.height,
        fps=args.fps,
        snapshot_every=args.snapshot_every,
    )


if __name__ == "__main__":
    sys.exit(main())
