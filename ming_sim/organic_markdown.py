"""Adapter to the single display-strip authority in web/src/organicMarkdown.mjs."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Iterable, List

_STRIPPER = Path(__file__).resolve().parents[1] / "web" / "src" / "organicMarkdown.mjs"


def filter_matched_highlights(answer: str, highlights: Iterable[str]) -> List[str]:
    """Filter at the write seam using the exact module consumed by the renderer."""
    payload = json.dumps({"answer": answer or "", "highlights": list(highlights or ())})
    completed = subprocess.run(
        ["node", str(_STRIPPER), "--filter"], input=payload, text=True,
        capture_output=True, check=True, timeout=5,
    )
    value = json.loads(completed.stdout)
    return [str(item) for item in value] if isinstance(value, list) else []
