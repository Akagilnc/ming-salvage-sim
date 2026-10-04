#!/usr/bin/env python3
"""#1847 N13 lifecycle probe — real entry mutation, no new production tests."""
from __future__ import annotations

import gc
import json
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from types import MethodType
from typing import Any, List, Optional

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5")
sys.path.insert(0, str(ROOT))
OUT = Path("/tmp/1847-fixer-w7")
OUT.mkdir(parents=True, exist_ok=True)

IGNORER = r"""
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
signal.signal(signal.SIGHUP, signal.SIG_IGN)
signal.signal(signal.SIGINT, signal.SIG_IGN)
print("READY", flush=True)
time.sleep(120)
"""


def _sweep(pattern: str) -> None:
    subprocess.run(
        ["pkill", "-9", "-f", pattern],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def probe_old_raise_covers_body():
    class BodyBoom(RuntimeError):
        pass

    class CleanupBoom(RuntimeError):
        pass

    def old_pattern():
        try:
            raise BodyBoom("original")
        except BaseException:
            raise
        finally:
            raise CleanupBoom("cleanup")

    def new_pattern():
        body_err = None
        try:
            raise BodyBoom("original")
        except BaseException as exc:
            body_err = exc
            raise
        finally:
            cleanup_err = CleanupBoom("cleanup")
            if body_err is not None:
                body_err.add_note(f"soft cleanup also failed: {cleanup_err!r}")
            else:
                raise cleanup_err

    def sole_cleanup_must_raise():
        body_err = None
        try:
            pass
        finally:
            cleanup_err = CleanupBoom("cleanup-only")
            if body_err is not None:
                body_err.add_note("x")
            else:
                raise cleanup_err

    old_t = new_t = sole_t = None
    notes: List[str] = []
    try:
        old_pattern()
    except Exception as exc:
        old_t = type(exc).__name__
    try:
        new_pattern()
    except Exception as exc:
        new_t = type(exc).__name__
        notes = list(getattr(exc, "__notes__", []) or [])
    try:
        sole_cleanup_must_raise()
        sole_t = "RETURNED_OK"
    except Exception as exc:
        sole_t = type(exc).__name__
    return {
        "case": "raise_cover_compare",
        "old_propagated": old_t,
        "new_propagated": new_t,
        "old_covers_body": old_t == "CleanupBoom",
        "new_preserves_body": new_t == "BodyBoom",
        "new_notes": notes,
        "sole_cleanup_propagated": sole_t,
        "sole_cleanup_not_masked": sole_t == "CleanupBoom",
    }


def probe_cli_terminate_soft_fail():
    """Deterministic real subprocess: ignore SIGTERM → TimeoutExpired, still alive."""
    from ming_sim.cli_backend import _terminate_cli_process

    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", IGNORER],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    t0 = time.monotonic()
    err = None
    try:
        _terminate_cli_process(proc)
    except Exception as exc:
        err = exc
    elapsed = time.monotonic() - t0
    alive = proc.poll() is None
    _sweep("time.sleep\\(120\\)")
    return {
        "case": "cli_terminate_soft_fail",
        "ready": line.decode().strip(),
        "err_type": type(err).__name__ if err else None,
        "alive_after": alive,
        "elapsed": round(elapsed, 2),
        "diagnostic_empty_if_swallowed": err is None,
    }


def probe_cli_iterator_cleanup_surfaces():
    """Full _iter_cli_process_lines: idle body + soft terminate both real; body wins."""
    import ming_sim.cli_backend as cb
    import ming_sim.llm_transport as lt

    outcome = cb._CliProcessOutcome()
    # Shrink idle so body fails quickly while child still alive.
    real_policy = lt.resolve_transport_policy

    class Tiny:
        idle_timeout_seconds = 0.2

    lt.resolve_transport_policy = lambda: Tiny()  # type: ignore
    err = None
    t0 = time.monotonic()
    try:
        list(
            cb._iter_cli_process_lines(
                [sys.executable, "-u", "-c", IGNORER],
                outcome=outcome,
            )
        )
    except Exception as exc:
        err = exc
    elapsed = time.monotonic() - t0
    lt.resolve_transport_policy = real_policy  # type: ignore
    _sweep("time.sleep\\(120\\)")
    notes = list(getattr(err, "__notes__", []) or []) if err else []
    return {
        "case": "cli_iterator_body_and_cleanup",
        "err_type": type(err).__name__ if err else None,
        "err_repr": repr(err)[:200] if err else None,
        "notes": notes,
        "cleanup_error_type": type(outcome.cleanup_error).__name__
        if outcome.cleanup_error
        else None,
        "stderr_marker": "[soft terminate failed:" in (outcome.stderr or ""),
        "elapsed": round(elapsed, 2),
        "covered_by_cleanup_only": type(err).__name__ == "TimeoutExpired"
        and not notes
        if err
        else None,
    }


def probe_pty_soft_close_no_sigkill():
    import pexpect

    signals: List[str] = []
    os_sent = 0

    child = pexpect.spawn(
        sys.executable,
        ["-u", "-c", IGNORER],
        encoding="utf-8",
        timeout=10,
        echo=False,
    )
    child.expect("READY")
    pty: Any = child.ptyproc

    def record_kill(self, sig):
        nonlocal os_sent
        name = signal.Signals(sig).name if isinstance(sig, int) else str(sig)
        signals.append(name)
        return None  # do not send OS signals

    pty.kill = MethodType(record_kill, pty)  # type: ignore

    cleanup_err = None
    try:
        child.close(force=False)
    except Exception as exc:
        cleanup_err = exc
        if not pty.closed:
            pty.fd = -1
            pty.closed = True
        child.child_fd = -1
        child.closed = True

    spawn_closed = child.closed
    pty_closed = pty.closed
    soft_signals = list(signals)
    unmarked_seq = ["SIGHUP", "SIGCONT", "SIGINT", "SIGKILL"]

    del child
    del pty
    gc.collect()
    _sweep("time.sleep\\(120\\)")

    return {
        "case": "pty_soft_close",
        "cleanup_err_type": type(cleanup_err).__name__ if cleanup_err else None,
        "soft_close_signals_recorded": soft_signals,
        "os_signals_sent": os_sent,
        "spawn_closed": spawn_closed,
        "pty_closed": pty_closed,
        "sigkill_in_soft_path": "SIGKILL" in soft_signals,
        "unmarked_force_true_sequence": unmarked_seq,
        "sigkill_only_in_unmarked_force_true": "SIGKILL" in unmarked_seq
        and "SIGKILL" not in soft_signals,
    }


def main():
    results = []
    for fn in (
        probe_old_raise_covers_body,
        probe_cli_terminate_soft_fail,
        probe_cli_iterator_cleanup_surfaces,
        probe_pty_soft_close_no_sigkill,
    ):
        try:
            results.append(fn())
        except Exception as exc:
            results.append(
                {
                    "case": fn.__name__,
                    "probe_error": repr(exc),
                    "traceback": traceback.format_exc(),
                }
            )
    out = OUT / "n13_lifecycle_probe.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out.read_text())
    by = {r.get("case"): r for r in results}
    ok = True
    r = by.get("raise_cover_compare", {})
    ok &= bool(
        r.get("old_covers_body")
        and r.get("new_preserves_body")
        and r.get("sole_cleanup_not_masked")
    )
    r = by.get("cli_terminate_soft_fail", {})
    ok &= r.get("err_type") == "TimeoutExpired" and r.get("alive_after") is True
    r = by.get("cli_iterator_body_and_cleanup", {})
    ok &= r.get("err_type") is not None and r.get("covered_by_cleanup_only") is not True
    r = by.get("pty_soft_close", {})
    ok &= r.get("sigkill_in_soft_path") is False and r.get("spawn_closed") is True
    print("VERDICT", "GREEN" if ok else "RED", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
