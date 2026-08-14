"""S6 / ADR 0045 organic-markdown display strip (Python side of the shared contract).

Frontend source of truth: ``web/src/format.ts`` ``stripOrganicMarkdown`` (markdown-it).
This module mirrors that token walk with markdown-it-py so the unique highlight write
boundary can strip + exact-match before persistence. Frontend may keep a display-time
defense; it is not the sole gate.
"""

from __future__ import annotations

import html
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence

from markdown_it import MarkdownIt


@lru_cache(maxsize=1)
def _markdown() -> MarkdownIt:
    # Match web/src/format.ts: html/linkify/typographer off; tables enabled for cell walk.
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable("table")
    return md


def _inline_text(tokens: Sequence[object]) -> str:
    def render(token: object) -> str:
        kind = getattr(token, "type", "")
        content = getattr(token, "content", "") or ""
        if kind in ("text", "html_inline"):
            return html.unescape(content) if "&" in content else content
        if kind == "entity":
            return html.unescape(content) if content.startswith("&") else content
        if kind == "code_inline":
            # JS side preserves pre-trim literalContent; python-markdown-it normalizes.
            # Highlight phrases rarely depend on code-span padding parity.
            return content
        if kind == "image":
            children = getattr(token, "children", None) or []
            return "".join(render(child) for child in children)
        if kind in ("softbreak", "hardbreak"):
            return "\n"
        return ""

    return "".join(render(token) for token in tokens)


def _append_block_separator(
    result: str,
    previous_end_line: Optional[int],
    start_line: Optional[int],
    *,
    in_table: bool,
) -> str:
    if in_table or previous_end_line is None or start_line is None:
        return result
    return result + "\n" * max(1, start_line - previous_end_line + 1)


def strip_organic_markdown(text: str) -> str:
    """Strip organic markdown markers; keep readable display text (ADR 0045 / S6)."""
    if not text:
        return ""
    tokens = _markdown().parse(text)
    result = ""
    previous_end_line: Optional[int] = None
    table_end_line: Optional[int] = None
    in_table = False

    for token in tokens:
        start_line = end_line = None
        token_map = getattr(token, "map", None)
        if token_map:
            start_line, end_line = token_map[0], token_map[1]
        kind = getattr(token, "type", "")

        if kind == "inline":
            result = _append_block_separator(
                result, previous_end_line, start_line, in_table=in_table
            )
            result += _inline_text(getattr(token, "children", None) or [])
            if end_line is not None and not in_table:
                previous_end_line = end_line
        elif kind in ("fence", "code_block", "html_block"):
            result = _append_block_separator(
                result, previous_end_line, start_line, in_table=False
            ) + (getattr(token, "content", "") or "")
            if end_line is not None:
                previous_end_line = end_line
        elif kind == "hr":
            if end_line is not None:
                previous_end_line = end_line
        elif kind == "table_open":
            result = _append_block_separator(
                result, previous_end_line, start_line, in_table=False
            )
            table_end_line = end_line
            in_table = True
        elif kind in ("td_close", "th_close"):
            result += "\t"
        elif kind == "tr_close":
            if result.endswith("\t"):
                result = result[:-1] + "\n"
            else:
                result += "\n"
        elif kind == "table_close":
            if result.endswith("\n"):
                result = result[:-1]
            previous_end_line = table_end_line
            table_end_line = None
            in_table = False

    return result


def filter_matched_highlights(answer: str, highlights: Iterable[str]) -> List[str]:
    """Strip phrases, exact-match against stripped answer; drop misses (ADR 0045).

    Returns the canonical stripped phrases that hit. Order of first hits preserved;
    empty/whitespace-only after strip are dropped.
    """
    display = strip_organic_markdown(answer or "")
    if not display:
        return []
    matched: List[str] = []
    for raw in highlights or ():
        phrase = strip_organic_markdown(str(raw or ""))
        if phrase and phrase in display:
            matched.append(phrase)
    return matched
