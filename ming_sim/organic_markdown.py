"""In-process consumer of the organic-markdown authority product.

Authority source: ``web/src/organicMarkdown.mjs`` (also consumed by the UI bundle).
Release product: ``web/dist/organicMarkdown.js`` (IIFE), packaged with the app.
Dev/test sibling copy: ``ming_sim/organic_markdown.authority.js`` (same bytes).

No external Node subprocess and no extra timeout window after the judge.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable, List

from quickjs import Context

from ming_sim.paths import bundled_path

_RELEASE_AUTHORITY = ("web", "dist", "organicMarkdown.js")
_SIBLING_AUTHORITY = Path(__file__).with_name("organic_markdown.authority.js")
_thread_state = threading.local()


def authority_product_path() -> Path:
    """Resolve the authority product the write seam executes.

    Prefer the release layout path (what PyInstaller ships under web/dist/);
    fall back to the packaged sibling copy so dev/tests work without a full UI build.
    """
    release = Path(bundled_path(*_RELEASE_AUTHORITY))
    if release.is_file():
        return release
    if _SIBLING_AUTHORITY.is_file():
        return _SIBLING_AUTHORITY
    raise FileNotFoundError(
        "organic markdown authority product missing: "
        f"expected {release} (release layout) or {_SIBLING_AUTHORITY}"
    )


def _context() -> Context:
    ctx = getattr(_thread_state, "ctx", None)
    path = authority_product_path()
    # Rebuild when the resolved product path changes (e.g. tests swap release layout).
    if ctx is not None and getattr(_thread_state, "path", None) == path:
        return ctx
    source = path.read_text(encoding="utf-8")
    ctx = Context()
    ctx.eval(source)
    _thread_state.ctx = ctx
    _thread_state.path = path
    return ctx


def filter_matched_highlights(answer: str, highlights: Iterable[str]) -> List[str]:
    """Filter at the write seam using the same authority product the release ships."""
    expr = (
        "JSON.stringify(OrganicMarkdown.filterMatchedHighlights("
        f"{json.dumps(answer or '')}, "
        f"{json.dumps([str(item) for item in (highlights or ())])}"
        "))"
    )
    raw = _context().eval(expr)
    value = json.loads(raw)
    return [str(item) for item in value] if isinstance(value, list) else []
