#!/usr/bin/env python3
"""#1847 w8 N13 — dual-cause text on existing provider_message / trace.error exits.

Replay (from repo root, seven false bins):
  MING_SIM_*_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w8-scans/probe_n13_dual_cause.py
"""
from __future__ import annotations

import traceback
from types import SimpleNamespace

from ming_sim.llm_transport import (
    _exception_text_with_causes,
    classify_transport_failure,
)


def main() -> None:
    cleanup = RuntimeError("wait timed out (soft terminate fail)")
    idle = TimeoutError("idle > 0.05s")
    cleanup.__cause__ = idle

    only = "".join(traceback.format_exception_only(type(cleanup), cleanup)).strip()
    assert "idle" not in only
    text = _exception_text_with_causes(cleanup)
    assert "wait timed out" in text and "idle > 0.05s" in text
    print("stdlib_format_exception_only", only)
    print("te_walk_text", text)
    print("N13_STDLIB_CHECK: no compact cause-only exit; TE cause walk kept")

    cf = classify_transport_failure(cleanup)
    print("classified", cf.code, cf.retryable)
    print("classified_provider_message", cf.provider_message)
    assert "idle" in (cf.provider_message or "")

    msg = _exception_text_with_causes(cleanup)
    print("consumer_exc", type(cleanup).__name__, msg)
    trace = SimpleNamespace(error=msg)
    print("trace_error", trace.error)
    assert "soft terminate" in trace.error and "idle" in trace.error
    print("N13_PERSISTENT_PROBE PASS")


if __name__ == "__main__":
    main()
