"""NOTICE carries the acknowledgment the WireGuard trademark policy asks for.

The policy (https://www.wireguard.com/trademark-policy/, section C.i) says any
use of the mark should be accompanied by the sentence below. Seventy-one
tracked files use the word and, until 2026-09-25, none carried it.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ACK = ('"WireGuard" and the "WireGuard" logo are registered trademarks of Jason A.\n'
       'Donenfeld.')


def test_notice_carries_the_acknowledgment():
    assert ACK in (REPO / "NOTICE").read_text(encoding="utf-8")
