"""Leitner spaced-repetition logic (pure functions, no I/O).

Box levels 1-7. Higher boxes = better known = longer intervals.
Box 1 is reviewed daily, Box 2 every 3 days, etc. (per spec).
A wrong answer drops the card back (never below Box 1).
"""
from __future__ import annotations

from datetime import datetime, timedelta

MIN_BOX = 1
MAX_BOX = 7

# Interval (in days) per box level — Box 1: daily, Box 2: every 3 days, ...
BOX_INTERVALS_DAYS: dict[int, int] = {
    1: 1,
    2: 3,
    3: 7,
    4: 14,
    5: 30,
    6: 60,
    7: 90,
}


def next_review_date(box_level: int, from_dt: datetime | None = None) -> datetime:
    """UTC datetime when a card in `box_level` should be reviewed next."""
    days = BOX_INTERVALS_DAYS.get(box_level, BOX_INTERVALS_DAYS[MIN_BOX])
    return (from_dt or datetime.utcnow()) + timedelta(days=days)


def promote(box_level: int) -> int:
    """Correct answer -> move up one box (capped at MAX_BOX)."""
    return min(box_level + 1, MAX_BOX)


def demote(box_level: int) -> int:
    """Wrong answer -> drop back one box (floored at MIN_BOX)."""
    return max(box_level - 1, MIN_BOX)


def is_graduated(box_level: int) -> bool:
    """Box 7 cards are considered 'mastered' (still reviewed, but rarely)."""
    return box_level >= MAX_BOX
