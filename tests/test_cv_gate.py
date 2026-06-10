# SPDX-License-Identifier: MIT
"""Unit tests for CV gate (cv_detect) and state machine (PickPlaceMonitor).

These are deterministic, pure functions — ideal for unit testing.
Tests use synthetic HSV frames constructed via numpy to exercise every branch.
"""

import numpy as np
import pytest

# Import the module under test (add repo root to path)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from autonomous_recovery_loop import cv_detect, PickPlaceMonitor, largest_blob


# ═══════════════════════════════════════════════════════
# Helpers: synthetic HSV frames
# ═══════════════════════════════════════════════════════

def make_hsv(orange_px=0, blue_px=0):
    """Create a 480x640 HSV frame with controlled orange/blue pixel counts.

    Orange: H=15, S=200, V=200 (center of ORANGE_LOWER/ORANGE_UPPER)
    Blue:   H=110, S=150, V=150 (center of BLUE_LOWER/BLUE_UPPER)
    Background: H=0, S=0, V=0 (black — below both HSV ranges)

    Pixels are laid out as compact 2D blocks (not thin lines) so that
    cv2.contourArea() returns meaningful values.
    """
    frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def fill_region(arr, px, color, row_start=0, col_start=0):
        """Fill pixels as compact 2D block starting at (row_start, col_start).
        Returns the next available row after filling."""
        if px <= 0:
            return row_start
        # Use a square-ish block: width = min(640, sqrt(px) * 2) to ensure thickness
        width = min(640, max(10, int(px ** 0.5) * 2))
        rows_needed = (px + width - 1) // width
        for r in range(rows_needed):
            if row_start + r >= 480:
                break
            cols_this_row = min(width, px - r * width)
            arr[row_start + r, col_start:col_start + cols_this_row] = color
        return row_start + rows_needed

    next_row = fill_region(frame, orange_px, [15, 200, 200], 0, 0)
    fill_region(frame, blue_px, [110, 150, 150], min(next_row, 479), 0)
    return frame


# ═══════════════════════════════════════════════════════
# cv_detect tests
# ═══════════════════════════════════════════════════════

class TestCVDetect:
    """Test the CV gate decision tree: 4 branches."""

    def test_orange_below_floor_returns_not_held(self):
        """orange < 100 → NOT_HELD (sure it's not held)"""
        frame = make_hsv(orange_px=50)  # well below ORANGE_FLOOR=100
        verdict, _, _ = cv_detect(frame)
        assert verdict == "NOT_HELD"

    def test_orange_zero_returns_not_held(self):
        """No orange at all → NOT_HELD"""
        frame = make_hsv(orange_px=0, blue_px=0)
        verdict, _, _ = cv_detect(frame)
        assert verdict == "NOT_HELD"

    def test_orange_above_threshold_returns_held(self):
        """orange > 500 → HELD (sure it's held)"""
        frame = make_hsv(orange_px=600)  # above ORANGE_THRESHOLD=500
        verdict, _, _ = cv_detect(frame)
        assert verdict == "HELD"

    def test_orange_well_above_threshold_returns_held(self):
        """Strong orange signal → HELD"""
        frame = make_hsv(orange_px=5000)
        verdict, _, _ = cv_detect(frame)
        assert verdict == "HELD"

    def test_borderline_low_blue_returns_not_held(self):
        """orange in [100,500] + blue < 5000 → NOT_HELD (noise/reflection)"""
        frame = make_hsv(orange_px=300, blue_px=1000)  # blue below BLUE_THRESHOLD=5000
        verdict, _, _ = cv_detect(frame)
        assert verdict == "NOT_HELD"

    def test_borderline_high_blue_returns_uncertain(self):
        """orange in [100,500] + blue >= 5000 → UNCERTAIN (genuinely ambiguous)"""
        frame = make_hsv(orange_px=300, blue_px=6000)  # blue above BLUE_THRESHOLD=5000
        verdict, _, _ = cv_detect(frame)
        assert verdict == "UNCERTAIN"

    def test_borderline_exact_floor_high_blue_returns_uncertain(self):
        """orange contourArea in [100,500] + blue >= 5000 → UNCERTAIN.
        Note: cv2.contourArea() < pixel count due to boundary discretization,
        so we request ~200px to get contourArea ~166 (above floor=100)."""
        frame = make_hsv(orange_px=200, blue_px=6000)
        verdict, _, _ = cv_detect(frame)
        assert verdict == "UNCERTAIN"

    def test_borderline_at_threshold_returns_held(self):
        """orange contourArea > 500 → HELD.
        Note: cv2.contourArea() < pixel count; ~700px gives contourArea ~640."""
        frame = make_hsv(orange_px=700)
        verdict, _, _ = cv_detect(frame)
        assert verdict == "HELD"

    def test_borderline_just_below_threshold_low_blue(self):
        """orange at 499 (just below threshold), low blue → NOT_HELD"""
        frame = make_hsv(orange_px=499, blue_px=100)
        verdict, _, _ = cv_detect(frame)
        assert verdict == "NOT_HELD"

    def test_returns_pixel_counts(self):
        """cv_detect returns (verdict, orange_px, blue_px)"""
        frame = make_hsv(orange_px=200, blue_px=3000)
        verdict, orange, blue = cv_detect(frame)
        assert verdict == "NOT_HELD"  # borderline + low blue
        assert orange > 0
        assert blue > 0

    def test_only_orange_no_blue(self):
        """Only orange markers, no blue → works"""
        frame = make_hsv(orange_px=800, blue_px=0)
        verdict, orange, blue = cv_detect(frame)
        assert verdict == "HELD"
        assert blue == 0

    def test_only_blue_no_orange(self):
        """Only blue markers, no orange → NOT_HELD (orange < floor)"""
        frame = make_hsv(orange_px=0, blue_px=8000)
        verdict, orange, blue = cv_detect(frame)
        assert verdict == "NOT_HELD"
        assert orange == 0
        assert blue > 0


# ═══════════════════════════════════════════════════════
# PickPlaceMonitor tests
# ═══════════════════════════════════════════════════════

class TestPickPlaceMonitor:
    """Test the state machine: debounce, transitions, anomalies."""

    def test_initial_state_is_not_held(self):
        monitor = PickPlaceMonitor()
        assert monitor.state == "NOT_HELD"
        assert monitor.total_frames == 0

    def test_same_verdict_repeated_is_stable(self):
        """Same verdict as current state → returns None (stable)"""
        monitor = PickPlaceMonitor()
        result = monitor.update("NOT_HELD", frame_idx=0)
        assert result is None
        assert monitor.state == "NOT_HELD"
        assert monitor.stable_count == 1
        assert monitor.total_frames == 1

    def test_different_verdict_once_does_not_transition(self):
        """One different frame → not enough for debounce → returns None"""
        monitor = PickPlaceMonitor()
        monitor.update("NOT_HELD", 0)  # establish base
        result = monitor.update("HELD", 1)  # 1st different
        assert result is None  # debounce not met (need 3)
        assert monitor.state == "NOT_HELD"  # still NOT_HELD
        assert monitor.pending_state == "HELD"
        assert monitor.pending_count == 1

    def test_different_verdict_twice_same_does_not_transition(self):
        """Two consecutive different → still not enough"""
        monitor = PickPlaceMonitor()
        monitor.update("NOT_HELD", 0)
        monitor.update("HELD", 1)
        result = monitor.update("HELD", 2)
        assert result is None  # need 3, got 2
        assert monitor.state == "NOT_HELD"

    def test_three_consecutive_different_confirms_transition(self):
        """DEBOUNCE_FRAMES=3 → transition confirmed on 3rd consecutive"""
        monitor = PickPlaceMonitor()
        monitor.update("NOT_HELD", 0)
        monitor.update("HELD", 1)
        monitor.update("HELD", 2)
        result = monitor.update("HELD", 3)
        # Transition should be confirmed
        assert monitor.state == "HELD"
        assert "NORMAL" in result
        assert "NOT_HELD → HELD" in result
        assert len(monitor.transitions) == 1
        assert monitor.transitions[0][3] is True  # valid transition

    def test_held_to_not_held_is_valid_transition(self):
        """HELD → NOT_HELD is a normal release"""
        monitor = PickPlaceMonitor(state="HELD")
        monitor.update("HELD", 0)
        monitor.update("NOT_HELD", 1)
        monitor.update("NOT_HELD", 2)
        result = monitor.update("NOT_HELD", 3)
        assert monitor.state == "NOT_HELD"
        assert "NORMAL" in result

    def test_held_to_held_direct_is_not_transition(self):
        """HELD → HELD is not a transition (but also not unexpected — 
        you can't transition to same state; the debounce logic only kicks in
        when verdict != current state)."""
        monitor = PickPlaceMonitor(state="HELD")
        result = monitor.update("HELD", 0)
        assert result is None
        assert monitor.state == "HELD"

    def test_held_to_held_with_not_held_interrupt(self):
        """HELD → NOT_HELD (1 frame) → HELD → should not confirm NOT_HELD
        because debounce requires 3 consecutive. The NOT_HELD interrupt
        starts pending but then HELD matches current state → resets pending."""
        monitor = PickPlaceMonitor(state="HELD")
        monitor.update("HELD", 0)
        # NOT_HELD starts pending — different from state, count=1
        monitor.update("NOT_HELD", 1)
        assert monitor.pending_state == "NOT_HELD"
        # HELD matches current state → resets pending (stable branch)
        result = monitor.update("HELD", 2)
        assert result is None
        assert monitor.state == "HELD"
        assert monitor.pending_state is None  # reset by stable branch

    def test_uncertain_below_max_is_silent(self):
        """1-3 UNCERTAIN frames → returns None (waiting for clarity)"""
        monitor = PickPlaceMonitor()
        assert monitor.update("UNCERTAIN", 0) is None
        assert monitor.update("UNCERTAIN", 1) is None
        assert monitor.update("UNCERTAIN", 2) is None
        assert monitor.uncertain_count == 3

    def test_uncertain_at_max_triggers_anomaly(self):
        """4 consecutive UNCERTAIN → anomaly returned"""
        monitor = PickPlaceMonitor()
        monitor.update("UNCERTAIN", 0)
        monitor.update("UNCERTAIN", 1)
        monitor.update("UNCERTAIN", 2)
        result = monitor.update("UNCERTAIN", 3)
        assert result is not None
        assert "UNCERTAIN too long" in result
        assert len(monitor.anomalies) == 1
        assert monitor.uncertain_count == 0  # reset after anomaly

    def test_uncertain_resets_on_clear_verdict(self):
        """UNCERTAIN count resets when a clear verdict arrives"""
        monitor = PickPlaceMonitor()
        monitor.update("UNCERTAIN", 0)
        monitor.update("UNCERTAIN", 1)
        monitor.update("HELD", 2)  # clear verdict
        assert monitor.uncertain_count == 0

    def test_held_and_not_held_frame_counters(self):
        """State counters increment correctly"""
        monitor = PickPlaceMonitor()
        for _ in range(5):
            monitor.update("NOT_HELD", _)
        assert monitor.not_held_frames == 5
        assert monitor.held_frames == 0

        # Transition to HELD
        monitor.update("HELD", 5)
        monitor.update("HELD", 6)
        monitor.update("HELD", 7)
        assert monitor.held_frames > 0

    def test_is_normal_zero_transitions_returns_false(self):
        monitor = PickPlaceMonitor()
        assert monitor.is_normal is False

    def test_is_normal_two_valid_transitions_returns_true(self):
        monitor = PickPlaceMonitor()
        # Simulate a full pick-and-place cycle: NOT_HELD → HELD → NOT_HELD
        # Transition to HELD
        monitor.update("NOT_HELD", 0)
        monitor.update("HELD", 1); monitor.update("HELD", 2)
        monitor.update("HELD", 3)
        assert monitor.state == "HELD"

        # Transition back to NOT_HELD
        monitor.update("NOT_HELD", 4); monitor.update("NOT_HELD", 5)
        monitor.update("NOT_HELD", 6)
        assert monitor.state == "NOT_HELD"

        assert len(monitor.transitions) == 2
        assert monitor.is_normal is True

    def test_is_normal_with_one_bad_transition_returns_false(self):
        """If any transition is invalid, is_normal is False"""
        monitor = PickPlaceMonitor()
        # Force an invalid transition: NOT_HELD → NOT_HELD is not possible in
        # normal flow, but we can fake it by directly manipulating
        monitor.transitions.append((0, "NOT_HELD", "NOT_HELD", False))
        assert monitor.is_normal is False

    def test_multiple_cycles_all_valid_returns_true(self):
        """3 pick-and-place cycles, all valid → is_normal True"""
        monitor = PickPlaceMonitor()
        for cycle in range(3):
            base = cycle * 10
            # NOT_HELD → HELD
            monitor.state = "NOT_HELD"
            monitor.pending_state = None; monitor.pending_count = 0
            for i in range(4):
                monitor.update("HELD", base + i)
            assert monitor.state == "HELD"
            # HELD → NOT_HELD
            for i in range(4):
                monitor.update("NOT_HELD", base + 4 + i)
            assert monitor.state == "NOT_HELD"

        assert len(monitor.transitions) == 6
        assert monitor.is_normal is True

    def test_total_frames_accurate(self):
        monitor = PickPlaceMonitor()
        for i in range(50):
            monitor.update("NOT_HELD", i)
        assert monitor.total_frames == 50

    def test_recorded_transitions_have_frame_and_validity(self):
        """Each recorded transition has (frame_idx, from_state, to_state, valid)"""
        monitor = PickPlaceMonitor()
        monitor.update("NOT_HELD", 0)
        monitor.update("HELD", 1); monitor.update("HELD", 2)
        monitor.update("HELD", 3)
        assert len(monitor.transitions) == 1
        f, old, new, valid = monitor.transitions[0]
        assert isinstance(f, int)
        assert old == "NOT_HELD"
        assert new == "HELD"
        assert valid is True
