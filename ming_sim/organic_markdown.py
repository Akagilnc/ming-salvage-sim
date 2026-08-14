"""Write-seam consumer of the single organic-markdown authority product.

Release product (sole runtime authority): ``web/dist/organicMarkdown.js``.
Browser and this module load those same bytes from the release layout.
No sibling copy, no external Node subprocess, no post-judge timeout window.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable, List

from quickjs import Context

from ming_sim.paths import bundled_path

_AUTHORITY_PARTS = ("web", "dist", "organicMarkdown.js")
_thread_state = threading.local()


def authority_product_path() -> Path:
    """Resolve the sole authority product shipped in the release layout."""
    path = Path(bundled_path(*_AUTHORITY_PARTS))
    if not path.is_file():
        raise FileNotFoundError(
            "organic markdown authority product missing: "
            f"expected release layout file {path}"
        )
    return path


def _context() -> Context:
    ctx = getattr(_thread_state, "ctx", None)
    path = authority_product_path()
    if ctx is not None and getattr(_thread_state, "path", None) == path:
        return ctx
    source = path.read_text(encoding="utf-8")
    ctx = Context()
    ctx.eval(source)
    _thread_state.ctx = ctx
    _thread_state.path = path
    return ctx


def filter_matched_highlights(answer: str, highlights: Iterable[str]) -> List[str]:
    """Filter at the write seam using the release authority product bytes."""
    expr = (
        "JSON.stringify(OrganicMarkdown.filterMatchedHighlights("
        f"{json.dumps(answer or '')}, "
        f"{json.dumps([str(item) for item in (highlights or ())])}"
        "))"
    )
    raw = _context().eval(expr)
    value = json.loads(raw)
    return [str(item) for item in value] if isinstance(value, list) else []
