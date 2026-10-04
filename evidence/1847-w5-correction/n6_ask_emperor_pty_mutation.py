#!/usr/bin/env python3
"""#1847 N6 real-entry mutation: ask_emperor → PTY sendline.

Production seam = scripts/play_as_emperor.parse_emperor_output + ask_emperor
+ pexpect.sendline (same call sites as run()).

Model boundary replaced by a deterministic Agent stub (no network).
Old transport package (strip input + splitlines[0] + action[:200]) must FAIL;
current package must PASS byte-equal on the PTY-received line.

Exit 0 iff all checks PASS. Soft-close only; recorder exits naturally.
Not a permanent pytest; one-shot evidence under evidence/1847-w5-correction/.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

for k in ("AGY", "CODEX", "CLAUDE", "CURSOR", "KIMI", "GROK", "PI"):
    os.environ[f"MING_SIM_{k}_BIN"] = "/usr/bin/false"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = Path(
    os.environ.get(
        "MING1847_ASK_EMPEROR_MUTATION_OUT",
        str(ROOT / "evidence/1847-w5-correction/n6_ask_emperor_pty_mutation.txt"),
    )
)
lines: list[str] = []
failed = False


def log(msg: str) -> None:
    lines.append(msg)
    print(msg, flush=True)


def ok(name: str, cond: bool, detail: str = "") -> None:
    global failed
    if not cond:
        failed = True
    log(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}".rstrip())


class _DeterministicEmperor:
    """Replaces live model at ask_emperor boundary."""

    def __init__(self, payload: dict):
        self._raw = json.dumps(payload, ensure_ascii=False)

    def run(self, _prompt: str):
        return SimpleNamespace(content=self._raw)


def old_transport_package(raw_json: str) -> str:
    """Pre-fix package that rewrote free-prose keyboard action before sendline."""
    text = raw_json.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if not obj_match:
        raise ValueError("old parse fail")
    obj = json.loads(obj_match.group(0))
    action = str(obj.get("input", "")).strip()
    if "\n" in action:
        action = action.splitlines()[0]
    if len(action) > 200:
        action = action[:200]
    return action


def pty_capture_sendline(action: str) -> str:
    """Real pexpect.sendline into a recorder that prints RECEIVED=<repr> and exits."""
    import pexpect

    recorder = (
        "import sys\n"
        "line = sys.stdin.readline()\n"
        "sys.stdout.write('RECEIVED=' + repr(line[:-1] if line.endswith(chr(10)) else line) + chr(10))\n"
        "sys.stdout.flush()\n"
    )
    td = tempfile.mkdtemp(prefix="ming1847-pty-")
    script = Path(td) / "recorder.py"
    script.write_text(recorder, encoding="utf-8")
    child = pexpect.spawn(
        sys.executable,
        [str(script)],
        encoding="utf-8",
        timeout=8,
    )
    child.delaybeforesend = 0.05
    try:
        child.sendline(action)
        child.expect(r"RECEIVED=(.*)\r?\n", timeout=5)
        received = ast.literal_eval(child.match.group(1))
    finally:
        try:
            child.expect(pexpect.EOF, timeout=3)
        except Exception:
            pass
        if child.isalive():
            child.close(force=False)
    return received


def main() -> int:
    t0 = time.perf_counter()
    log("=== N6 ask_emperor → PTY sendline (production seam; model stubbed) ===")
    log("BIN guards: all MING_SIM_*_BIN=/usr/bin/false")
    log("NOTE: evidence/1847-mutation-probes.py HTTP/UI is NOT this entry (referee rejected).")

    from play_as_emperor import ask_emperor, parse_emperor_output

    # Multiline + outer envelope ws: parse/ask_emperor must keep input field intact.
    ACTION_MULTI = (
        "  命洪承畴急赈河南灾民，三月内回奏军饷实发与逋欠清册。\n"
        "次行不得裁\n  "
    )
    # Single-line long + edge ws: PTY readline seam (sendline→one line) vs old strip/[:200].
    ACTION_LINE = "  命洪承畴急赈河南灾民，三月内回奏。" + ("详" * 180) + "  "
    assert "\n" not in ACTION_LINE and len(ACTION_LINE) > 200

    for label, ACTION in (("MULTI", ACTION_MULTI), ("LINE", ACTION_LINE)):
        payload = {"reasoning": "试探运输", "input": ACTION}
        raw = "  \n" + json.dumps(payload, ensure_ascii=False) + "\n  "
        reasoning, action_cur = parse_emperor_output(raw)
        ok(
            f"N6_PARSE_INPUT_BYTE_EQUAL_{label}",
            action_cur == ACTION,
            f"len_cur={len(action_cur)} len_src={len(ACTION)}",
        )
        ok(f"N6_PARSE_REASONING_{label}", reasoning == "试探运输", repr(reasoning))
        action_old = old_transport_package(raw)
        ok(
            f"N6_OLD_PACKAGE_MUTATES_{label}",
            action_old != ACTION,
            f"old_len={len(action_old)}",
        )
        agent = _DeterministicEmperor(payload)
        reasoning2, action_ask = ask_emperor(
            agent,
            "CLI chunk " + ("块" * 4000),
            "朕问：",
            progress="【本月进度】探针",
        )
        ok(
            f"N6_ASK_EMPEROR_INPUT_BYTE_EQUAL_{label}",
            action_ask == ACTION,
            f"len={len(action_ask)}",
        )
        ok(f"N6_ASK_EMPEROR_REASONING_{label}", reasoning2 == "试探运输", "")

    # PTY sendline uses LINE action (line-oriented recorder = CLI prompt readline).
    payload_line = {"reasoning": "试探运输", "input": ACTION_LINE}
    raw_line = json.dumps(payload_line, ensure_ascii=False)
    _, action_ask_line = ask_emperor(
        _DeterministicEmperor(payload_line),
        "CLI",
        "朕问：",
    )
    action_old_line = old_transport_package(raw_line)
    received = pty_capture_sendline(action_ask_line)
    ok(
        "N6_PTY_SENDLINE_BYTE_EQUAL",
        received == ACTION_LINE,
        f"recv_len={len(received)} eq={received == ACTION_LINE}",
    )
    received_old = pty_capture_sendline(action_old_line)
    ok(
        "N6_MUTATION_EXIT_PAIR",
        (received_old != ACTION_LINE) and (received == ACTION_LINE),
        f"old_recv_len={len(received_old)} cur_recv_len={len(received)}",
    )

    src = (ROOT / "scripts" / "play_as_emperor.py").read_text(encoding="utf-8")
    ok("N6_NO_ACTION_SLICE_200", "action[:200]" not in src, "")
    fn_body = src.split("def parse_emperor_output", 1)[1].split("def ask_emperor", 1)[0]
    ok("N6_NO_INPUT_SPLITLINES0", "splitlines()[0]" not in fn_body, "")
    ok(
        "N6_EMPTY_GATE_USES_STRIP_NOT_ASSIGN",
        'if not str(raw or "").strip():' in fn_body,
        "",
    )

    elapsed = time.perf_counter() - t0
    log(f"=== DONE failed={failed} real={elapsed:.2f}s ===")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"WROTE {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
