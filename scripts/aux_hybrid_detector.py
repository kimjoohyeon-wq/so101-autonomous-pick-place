#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hybrid aux hold detector: CV gate (orange/blue blob) + local GPU Qwen2-VL.

Offline-only: reads images, calls local GPU server. Never opens cameras/COM ports.

Pipeline (CV-confident fast path, Qwen only for genuinely ambiguous):
  1. CV: largest orange/blob contour area
  2. orange < 100px → NOT_HELD (confident)
  3. orange > 500px → HELD (confident)
  4. orange in [100, 500]:
     - blue < 5000px → NOT_HELD (noise/reflection, not a real cup)
     - blue ≥ 5000px → Qwen (genuinely ambiguous, rare)
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests

API = "http://127.0.0.1:8081/v1/chat/completions"
ORANGE_LOWER = np.array([10, 100, 100])
ORANGE_UPPER = np.array([25, 255, 255])
BLUE_LOWER = np.array([85, 35, 35])
BLUE_UPPER = np.array([135, 255, 255])
ORANGE_THRESHOLD = 500
ORANGE_FLOOR = 100  # below this, blue is noise — NOT_HELD
BLUE_THRESHOLD = 5000

QWEN_PROMPT = (
    "This is a wrist camera view from a robot arm. "
    "If you see a white paper cup clearly held between gripper fingers, say HELD. "
    "If the gripper is empty or you see only floor/work surface, say NOT_HELD. "
    "Answer with exactly one word: HELD or NOT_HELD."
)

def largest_blob(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return max([cv2.contourArea(c) for c in contours]) if contours else 0


def detect(img_path, api_url=API):
    """Return (verdict, method, orange_blob, blue_blob, qwen_raw)."""
    # Windows -> WSL path
    if img_path.startswith("C:") and not os.path.exists(img_path):
        img_path = "/mnt/c" + img_path[2:].replace("\\", "/")
    img = cv2.imread(str(img_path))
    if img is None:
        return ("ERROR", "read_failed", 0, 0, None)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    orange_blob = largest_blob(cv2.inRange(hsv, ORANGE_LOWER, ORANGE_UPPER))
    blue_blob = largest_blob(cv2.inRange(hsv, BLUE_LOWER, BLUE_UPPER))

    if orange_blob < ORANGE_FLOOR:
        return ("NOT_HELD", "cv_not_held", orange_blob, blue_blob, None)
    if orange_blob > ORANGE_THRESHOLD:
        return ("HELD", "cv_held", orange_blob, blue_blob, None)

    # Borderline orange in [100, 500]:
    #   - low blue → NOT_HELD (noise/reflection, not a real cup)
    #   - high blue → Qwen (genuinely ambiguous)
    if blue_blob < BLUE_THRESHOLD:
        return ("NOT_HELD", "cv_not_held_borderline", orange_blob, blue_blob, None)

    # Truly ambiguous — ask Qwen
    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    resp = requests.post(
        api_url,
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        {"type": "text", "text": QWEN_PROMPT},
                    ],
                }
            ],
            "max_tokens": 10,
            "temperature": 0.0,
        },
        timeout=30,
    )
    raw = resp.json()["choices"][0]["message"]["content"].strip().upper()
    if "NOT" in raw:
        verdict = "NOT_HELD"
    elif "HELD" in raw or "HOLD" in raw:
        verdict = "HELD"
    else:
        verdict = f"UNKNOWN({raw[:30]})"
    return (verdict, "qwen", orange_blob, blue_blob, raw)


def batch_from_csv(csv_path, out_path=None, api_url=API):
    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    results = []
    ok = total = cv_count = qwen_count = 0
    for row in rows:
        img_path = row["image"].strip('"')
        # Windows -> WSL path
        if img_path.startswith("C:") and not os.path.exists(img_path):
            img_path = "/mnt/c" + img_path[2:].replace("\\", "/")
        if not os.path.exists(img_path):
            print(f"MISSING: {img_path}")
            continue
        actual = "HELD" if row.get("actual_held_cup", "").strip() == "True" else "NOT_HELD"
        verdict, method, ob, bb, raw = detect(img_path, api_url=api_url)
        correct = (verdict == actual)
        ok += int(correct)
        total += 1
        if method.startswith("cv_"):
            cv_count += 1
        else:
            qwen_count += 1

        results.append({
            "image": img_path,
            "actual": actual,
            "predicted": verdict,
            "correct": correct,
            "method": method,
            "orange_blob": int(ob),
            "blue_blob": int(bb),
            "qwen_raw": raw
        })
        mark = "OK" if correct else "ERR"
        print(f"[{mark}] {verdict:8s} | {method:7s} | orange={int(ob):5d} blue={int(bb):5d} | {Path(img_path).name[:50]}")

    print(f"\nAccuracy: {ok}/{total} = {ok/total*100:.1f}%" if total else "No images")
    print(f"CV gate: {cv_count} | Qwen: {qwen_count}")

    if out_path:
        report = {
            "schema": "aux_hybrid_detector_v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "total": total, "correct": ok,
            "accuracy": round(ok/total, 4) if total else 0,
            "cv_gate_count": cv_count, "qwen_count": qwen_count,
            "results": results
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report saved: {out_path}")

    return results


def main():
    p = argparse.ArgumentParser(description="Hybrid aux hold detector (CV+Qwen GPU)")
    p.add_argument("--csv", help="CSV with image paths (label_priority_pack format)")
    p.add_argument("--image", action="append", help="Single image path (repeatable)")
    p.add_argument("--out", help="JSON report output path")
    p.add_argument("--api-url", default=os.environ.get("QWEN_API_URL", API), help="Local VLM chat-completions endpoint")
    args = p.parse_args()

    if args.csv:
        batch_from_csv(args.csv, args.out, api_url=args.api_url)
    elif args.image:
        for img in args.image:
            verdict, method, ob, bb, raw = detect(img, api_url=args.api_url)
            print(f"{verdict} | {method} | orange={int(ob)} blue={int(bb)} | {img}")
    else:
        p.print_help()


if __name__ == "__main__":
    main()
