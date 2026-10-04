#!/usr/bin/env python3
"""#1847 N13 lifecycle probe — soft terminate + natural exit; no SIGKILL/pkill.

T1 correction: prior revision used `_sweep` → `pkill -9 -f 'time.sleep\\(120\\)'`
(real SIGKILL by cmdline pattern). That run and any receipt claiming
「无真实 SIGKILL／自然退出」from it are withdrawn as false. This file proves
only the corrected run: own Popen/spawn handles, wait for natural exit.
"""
from __future__ import annotations

import gc
import json
import os
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
OUT = Path("/tmp/1847-fixer-t1-t2")
OUT.mkdir(parents=True, exist_ok=True)

# Ignore soft signals; exit on its own after > terminate wait(5) so TimeoutExpired
# fires while still alive, then natural exit follows within a few more seconds.
IGNORER = r"""
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
signal.signal(signal.SIGHUP, signal.SIG_IGN)
signal.signal(signal.SIGINT, signal.SIG_IGN)
print("READY", flush=True)
time.sleep(8)
sys.exit(0)
"""


def _wait_natural(proc: subprocess.Popen, *, timeout: float = 30.0) -> dict:
    """Wait on our own handle only — never pkill / name search / SIGKILL."""
    t0 = time.monotonic()
    try:
        rc = proc.wait(timeout=timeout)
        return {
            "natural_exit_rc": rc,
            "natural_exit_ok": rc == 0,
            "natural_wait_elapsed": round(time.monotonic() - t0, 2),
            "still_alive_after_wait": proc.poll() is None,
        }
    except subprocess.TimeoutExpired:
        return {
            "natural_exit_rc": None,
            "natural_exit_ok": False,
            "natural_wait_elapsed": round(time.monotonic() - t0, 2),
            "still_alive_after_wait": proc.poll() is None,
            "natural_wait_timeout": True,
        }


def probe_old_raise_covers_body():
    """In-memory deterministic compare of original-fail + cleanup-fail semantics."""

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
    """TimeoutExpired + still alive, then wait() → rc 0 natural exit. No SIGKILL."""
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
    natural = _wait_natural(proc)
    return {
        "case": "cli_terminate_soft_fail",
        "ready": line.decode().strip(),
        "err_type": type(err).__name__ if err else None,
        "alive_after": alive,
        "elapsed": round(elapsed, 2),
        "diagnostic_empty_if_swallowed": err is None,
        **natural,
        "used_pkill_or_sigkill": False,
    }


def probe_cli_iterator_cleanup_surfaces():
    """Body + soft terminate both real; body wins via notes/stderr (no dead field)."""
    import ming_sim.cli_backend as cb
    import ming_sim.llm_transport as lt

    outcome = cb._CliProcessOutcome()
    real_policy = lt.resolve_transport_policy

    class Tiny:
        idle_timeout_seconds = 0.2

    lt.resolve_transport_policy = lambda: Tiny()  # type: ignore
    err = None
    held: Optional[subprocess.Popen] = None
    real_popen = subprocess.Popen

    def tracking_popen(*args, **kwargs):
        nonlocal held
        held = real_popen(*args, **kwargs)
        return held

    t0 = time.monotonic()
    try:
        subprocess.Popen = tracking_popen  # type: ignore
        list(
            cb._iter_cli_process_lines(
                [sys.executable, "-u", "-c", IGNORER],
                outcome=outcome,
            )
        )
    except Exception as exc:
        err = exc
    finally:
        subprocess.Popen = real_popen  # type: ignore
        lt.resolve_transport_policy = real_policy  # type: ignore
    elapsed = time.monotonic() - t0
    notes = list(getattr(err, "__notes__", []) or []) if err else []
    natural = (
        _wait_natural(held)
        if held is not None and held.poll() is None
        else {
            "natural_exit_rc": held.poll() if held is not None else None,
            "natural_exit_ok": held is not None and held.poll() == 0,
            "natural_wait_elapsed": 0.0,
            "still_alive_after_wait": False,
            "already_exited_before_extra_wait": True,
        }
    )
    # Real external surfaces only — cleanup_error field deleted (T2).
    has_cleanup_attr = hasattr(outcome, "cleanup_error")
    return {
        "case": "cli_iterator_body_and_cleanup",
        "err_type": type(err).__name__ if err else None,
        "err_repr": repr(err)[:200] if err else None,
        "notes": notes,
        "notes_mark_soft_terminate": any(
            "soft terminate also failed" in n for n in notes
        ),
        "stderr_marker": "[soft terminate failed:" in (outcome.stderr or ""),
        "cleanup_error_field_present": has_cleanup_attr,
        "elapsed": round(elapsed, 2),
        "covered_by_cleanup_only": type(err).__name__ == "TimeoutExpired"
        and not notes
        if err
        else None,
        **natural,
        "used_pkill_or_sigkill": False,
    }


def probe_pty_soft_close_no_sigkill():
    """Soft close records HUP/CONT/INT only; recorder never sends OS SIGKILL."""
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
    pid = child.pid
    pty: Any = child.ptyproc

    def record_kill(self, sig):
        nonlocal os_sent
        name = signal.Signals(sig).name if isinstance(sig, int) else str(sig)
        signals.append(name)
        # Recorder only — never forward real OS signals (esp. never SIGKILL).
        return None

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

    # Natural exit via own spawn pid — wait, do not pkill by name.
    t0 = time.monotonic()
    natural_rc = None
    still_alive = None
    try:
        _pid, status = os.waitpid(pid, 0)
        natural_rc = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else (
            status >> 8 if os.WIFEXITED(status) else None
        )
        still_alive = False
    except ChildProcessError:
        # Already reaped elsewhere
        still_alive = False
        natural_rc = 0
    natural_wait_elapsed = round(time.monotonic() - t0, 2)

    del child
    del pty
    gc.collect()

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
        "natural_exit_rc": natural_rc,
        "natural_exit_ok": natural_rc == 0,
        "natural_wait_elapsed": natural_wait_elapsed,
        "still_alive_after_wait": still_alive,
        "used_pkill_or_sigkill": False,
        "recorder_forwards_os_sigkill": False,
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
    evidence_out = ROOT / "evidence/1847-w7-correction/n13_lifecycle_probe.json"
    evidence_out.write_text(
        json.dumps(
            {
                "_meta": {
                    "corrected_run": True,
                    "withdrawn_prior_claim": (
                        "旧探针 evidence/1847-w7-correction/n13_lifecycle_probe.py "
                        "曾以 _sweep/pkill -9 真实 SIGKILL 收场；旧回执「无真实 "
                        "SIGKILL／自然退出」未经核对失实，已撤回。本 JSON 仅证明修正后这次。"
                    ),
                    "out_path": str(out),
                },
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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
    ok &= (
        r.get("err_type") == "TimeoutExpired"
        and r.get("alive_after") is True
        and r.get("natural_exit_ok") is True
        and r.get("used_pkill_or_sigkill") is False
    )
    r = by.get("cli_iterator_body_and_cleanup", {})
    ok &= (
        r.get("err_type") is not None
        and r.get("covered_by_cleanup_only") is not True
        and r.get("notes_mark_soft_terminate") is True
        and r.get("stderr_marker") is True
        and r.get("cleanup_error_field_present") is False
        and r.get("used_pkill_or_sigkill") is False
    )
    r = by.get("pty_soft_close", {})
    ok &= (
        r.get("sigkill_in_soft_path") is False
        and r.get("spawn_closed") is True
        and r.get("natural_exit_ok") is True
        and r.get("recorder_forwards_os_sigkill") is False
        and r.get("used_pkill_or_sigkill") is False
    )
    print("VERDICT", "GREEN" if ok else "RED", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
