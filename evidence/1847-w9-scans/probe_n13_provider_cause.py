#!/usr/bin/env python3
"""#1847 w9 N13-R2 — LLMUnavailable keeps provider_message and appends cause chain.

Mutation red/green (from repo root, seven false bins):
  MING_SIM_*_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \\
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \\
    evidence/1847-w9-scans/probe_n13_provider_cause.py
"""
from __future__ import annotations

from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_transport import classify_transport_failure


def main() -> None:
    ex = LLMUnavailable(
        "LLM失败(人读)",
        code="llm_error",
        provider_message="PROVIDER_BODY_xyz",
        status_code=500,
    )
    ex.__cause__ = ValueError("inner")
    cf = classify_transport_failure(ex)
    pmsg = cf.provider_message or ""
    print("classified", cf.code, cf.retryable, cf.status_code)
    print("provider_message", pmsg)
    assert "PROVIDER_BODY_xyz" in pmsg, pmsg
    assert "inner" in pmsg, pmsg
    assert "LLM失败(人读)" not in pmsg or "PROVIDER_BODY_xyz" in pmsg
    # Human-readable message must not replace structured provider body.
    assert not pmsg.startswith("LLM失败(人读)"), pmsg
    print("N13_PROVIDER_CAUSE_PROBE PASS")


if __name__ == "__main__":
    main()
