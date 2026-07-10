"""Shared score-to-language primitives for player-facing presentation."""

from __future__ import annotations


def qualitative_band(value: object, words: tuple[str, ...], default: int = 0) -> str:
    """Return one of five ordered labels without exposing the source score."""
    try:
        score = int(value or default)
    except (TypeError, ValueError):
        score = default
    index = 4 if score >= 80 else 3 if score >= 60 else 2 if score >= 40 else 1 if score >= 20 else 0
    return words[index]
