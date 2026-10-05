#!/usr/bin/env python3
"""J6 mutation: replace original-fault diagnosis on live failure branches.

Mutates production assignment only (not whole entry). Expects focused tests to RED,
then restores and expects GREEN. Does not invent new proof tests.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(".").resolve()
OUT = ROOT / "evidence/1900-j6-final-rescan"
ENV_PREFIX = [
    "MING_SIM_AGY_BIN=/usr/bin/false",
    "MING_SIM_CODEX_BIN=/usr/bin/false",
    "MING_SIM_CLAUDE_BIN=/usr/bin/false",
    "MING_SIM_CURSOR_BIN=/usr/bin/false",
    "MING_SIM_KIMI_BIN=/usr/bin/false",
    "MING_SIM_GROK_BIN=/usr/bin/false",
    "MING_SIM_PI_BIN=/usr/bin/false",
]

CASES = [
    {
        "id": "cli_trace_error",
        "file": "ming_sim/cli_backend.py",
        "old": '        error = str(exc)\n        raise',
        "new": '        error = "unrelated-diag-mutation"\n        raise',
        "tests": [
            "tests/test_cli_backend.py::test_run_backend_for_config_traces_on_backend_error",
        ],
    },
    {
        "id": "sse_postprocess_message",
        "file": "web_app.py",
        # narrow: only the non-LLMUnavailable error emit in chat_stream worker
        "old": (
            '                    else:\n'
            '                        ev_queue.put({\n'
            '                            "type": "error",\n'
            '                            "message": str(error),\n'
            '                            **identity,\n'
            '                        })'
        ),
        "new": (
            '                    else:\n'
            '                        ev_queue.put({\n'
            '                            "type": "error",\n'
            '                            "message": "unrelated-diag-mutation",\n'
            '                            **identity,\n'
            '                        })'
        ),
        "tests": [
            "tests/test_chat_stream_failpaths_393.py::test_worker_postprocess_exception_emits_error_end",
        ],
    },
    {
        "id": "mechanical_tail_error",
        "file": "ming_sim/mechanical_tail.py",
        "old": '                chain["mechanical_tail"]["error"] = str(exc)\n',
        "new": '                chain["mechanical_tail"]["error"] = "unrelated-diag-mutation"\n',
        "tests": [
            "tests/test_mechanical_tail_1845.py::test_mechanical_tail_missing_llm_config_surfaces_retry",
        ],
    },
]


def run_pytest(tests: list[str]) -> tuple[int, str, float]:
    env = dict(**__import__("os").environ)
    for item in ENV_PREFIX:
        k, _, v = item.partition("=")
        env[k] = v
    cmd = [sys.executable, "-m", "pytest", "-q", *tests]
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    dt = time.monotonic() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out, dt


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    summary: list[str] = []
    all_ok = True

    for case in CASES:
        path = ROOT / case["file"]
        original = path.read_text(encoding="utf-8")
        if case["old"] not in original:
            lines.append(f"FAIL locate {case['id']}: old snippet missing in {case['file']}")
            summary.append(f"{case['id']}: LOCATE_FAIL")
            all_ok = False
            continue
        # mutate
        path.write_text(original.replace(case["old"], case["new"], 1), encoding="utf-8")
        try:
            code, out, dt = run_pytest(case["tests"])
            red = code != 0
            lines.append(f"=== MUTATE {case['id']} expect RED ({dt:.2f}s) rc={code} ===\n{out}\n")
            if not red:
                summary.append(f"{case['id']}: FALSE_GREEN")
                all_ok = False
            else:
                summary.append(f"{case['id']}: RED_OK")
        finally:
            path.write_text(original, encoding="utf-8")

        code2, out2, dt2 = run_pytest(case["tests"])
        lines.append(f"=== RESTORE {case['id']} expect GREEN ({dt2:.2f}s) rc={code2} ===\n{out2}\n")
        if code2 != 0:
            summary.append(f"{case['id']}: RESTORE_RED")
            all_ok = False
        else:
            summary.append(f"{case['id']}: GREEN_OK")

    (OUT / "mutations.log").write_text("".join(lines), encoding="utf-8")
    (OUT / "mutations-summary.txt").write_text(
        "\n".join(summary) + f"\nall_ok={all_ok}\n", encoding="utf-8"
    )
    print("\n".join(summary))
    print(f"all_ok={all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
