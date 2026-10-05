#!/usr/bin/env python3
"""J6 mutation proof: wrong-primary under strong asserts (red) vs weak (false green)."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap

ROOT = pathlib.Path(__file__).resolve().parents[2]
PY = "/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python"
ENV = os.environ.copy()
for k in (
    "MING_SIM_AGY_BIN",
    "MING_SIM_CODEX_BIN",
    "MING_SIM_CLAUDE_BIN",
    "MING_SIM_CURSOR_BIN",
    "MING_SIM_KIMI_BIN",
    "MING_SIM_GROK_BIN",
    "MING_SIM_PI_BIN",
):
    ENV[k] = "/usr/bin/false"
ENV["PYTHONDONTWRITEBYTECODE"] = "1"

PATHS = [
    ROOT / "tests/test_cli_play_turn.py",
    ROOT / "tests/test_month_call_recovery_1846.py",
    ROOT / "tests/test_state_reload.py",
]
NODES = [
    "tests/test_cli_play_turn.py::test_terminal_minister_chat_preserves_chat_error_when_rollback_fails",
    "tests/test_month_call_recovery_1846.py::test_error_pack_failure_keeps_original_fault_and_retry_phase",
    "tests/test_state_reload.py::test_atomic_and_reload_chains_reload_failure",
]

CLI_STRONG = """\
    with pytest.raises(RuntimeError) as ei:
        term.minister_chat(Session(), SimpleNamespace(name=\"魏忠贤\"))
    assert ei.value.args == (\"LLM down\",)
    assert isinstance(ei.value.__cause__, RuntimeError)
    assert ei.value.__cause__.args == (\"rollback failed\",)"""

CLI_WEAK = """\
    with pytest.raises(RuntimeError):
        term.minister_chat(Session(), SimpleNamespace(name=\"魏忠贤\"))"""

MONTH_STRONG = """\
    assert caught.value.error_pack_path is None
    # 原结算诊断保真：写包次生故障挂 cause，不得顶替 SettlementAbort / 持久 call_failure。
    assert caught.value.args[:1] == (\"edict settle crashed\",)
    assert isinstance(caught.value.__cause__, OSError)
    assert caught.value.__cause__.args == (\"error pack unwritable\",)
    assert not db.staged_declarations.is_settled(ref)
    assert _ningyuan_ledger_rows(db) == []
    failure = _month_chain_of(db, turn).get(\"call_failure\") or {}
    assert failure.get(\"kind\") == \"code_exception\"
    assert failure.get(\"message\") == \"edict settle crashed\"
    assert not failure.get(\"error_pack_path\")"""

MONTH_WEAK = """\
    assert caught.value.error_pack_path is None
    assert isinstance(caught.value.__cause__, OSError)
    assert not db.staged_declarations.is_settled(ref)
    assert _ningyuan_ledger_rows(db) == []
    failure = _month_chain_of(db, turn).get(\"call_failure\") or {}
    assert failure.get(\"kind\") == \"code_exception\"
    assert str(failure.get(\"message\") or \"\").strip()
    assert not failure.get(\"error_pack_path\")"""

RELOAD_STRONG = """\
    with pytest.raises(RuntimeError) as ei:
        with atomic_and_reload(db, state, content=content):
            raise RuntimeError(\"orig\")
    # 原异常对象保真：主诊断仍是 body 故障；reload 次生故障只挂 cause。
    assert ei.value.args == (\"orig\",)
    assert isinstance(ei.value.__cause__, ValueError)
    assert ei.value.__cause__.args == (\"reload failed\",)"""

RELOAD_WEAK = """\
    with pytest.raises(RuntimeError) as ei:
        with atomic_and_reload(db, state, content=content):
            raise RuntimeError(\"orig\")
    assert isinstance(ei.value.__cause__, ValueError)"""

PRE = {
    "cli": textwrap.dedent(
        """
        import ming_sim.cli.terminal as term
        import tests.test_cli_play_turn as m
        def swapped(session, character, *, selected=False):
            raise RuntimeError("rollback failed")
        term.minister_chat = swapped
        m.term.minister_chat = swapped
        """
    ).strip(),
    "month": textwrap.dedent(
        """
        import ming_sim.month_chain as mc
        real = mc._abort_month_call
        def wrong(db, state, chain, *, decree_text, source, step, exc, kind, decree_ref=""):
            return real(
                db, state, chain, decree_text=decree_text, source=source, step=step,
                exc=OSError("error pack unwritable"), kind=kind, decree_ref=decree_ref,
            )
        mc._abort_month_call = wrong
        """
    ).strip(),
    "reload": textwrap.dedent(
        """
        import ming_sim.decree as decree_mod
        from contextlib import contextmanager
        @contextmanager
        def mutant_aar(db, state, *, content=None, on_error=None):
            class O:
                reload_failed = True
            try:
                yield O()
            except BaseException as exc:
                if on_error is not None:
                    on_error(exc)
                raise RuntimeError("reload failed") from ValueError("reload failed")
        decree_mod.atomic_and_reload = mutant_aar
        """
    ).strip(),
}


def run(label: str, node: str, pre: str, tmp: pathlib.Path) -> int:
    bt = tmp / label
    bt.mkdir(parents=True, exist_ok=True)
    script_path = tmp / f"{label}.py"
    script_path.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        + (pre + "\n" if pre else "")
        + "import pytest\n"
        + "raise SystemExit(pytest.main(["
        + '"-q","--tb=line","-p","no:cacheprovider",'
        + f'"--basetemp", {str(bt)!r}, {node!r}'
        + "]))\n",
        encoding="utf-8",
    )
    p = subprocess.run([PY, str(script_path)], cwd=str(ROOT), env=ENV, capture_output=True, text=True)
    print(f"=== {label} exit={p.returncode}")
    print((p.stdout or "").strip())
    if p.returncode not in (0, 1) and p.stderr:
        print((p.stderr or "")[-800:])
    return p.returncode


def main() -> None:
    backups = {p: p.read_text(encoding="utf-8") for p in PATHS}
    assert CLI_STRONG in backups[PATHS[0]]
    assert MONTH_STRONG in backups[PATHS[1]]
    assert RELOAD_STRONG in backups[PATHS[2]]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="1900-j6-mut4-"))
    log: list[tuple[str, int]] = []
    try:
        for key, node in zip(("cli", "month", "reload"), NODES):
            code = run(f"{key}-strong-red", node, PRE[key], tmp)
            log.append((f"{key}-strong-red", code))
            assert code != 0, key
        for key, node in zip(("cli", "month", "reload"), NODES):
            code = run(f"{key}-strong-green", node, "", tmp)
            log.append((f"{key}-strong-green", code))
            assert code == 0, key

        PATHS[0].write_text(backups[PATHS[0]].replace(CLI_STRONG, CLI_WEAK), encoding="utf-8")
        PATHS[1].write_text(backups[PATHS[1]].replace(MONTH_STRONG, MONTH_WEAK), encoding="utf-8")
        PATHS[2].write_text(backups[PATHS[2]].replace(RELOAD_STRONG, RELOAD_WEAK), encoding="utf-8")
        for key, node in zip(("cli", "month", "reload"), NODES):
            code = run(f"{key}-weak-false-green", node, PRE[key], tmp)
            log.append((f"{key}-weak-false-green", code))
            assert code == 0, key
    finally:
        for p, text in backups.items():
            p.write_text(text, encoding="utf-8")

    assert all(p.read_text(encoding="utf-8") == backups[p] for p in PATHS)
    for key, node in zip(("cli", "month", "reload"), NODES):
        code = run(f"{key}-final-green", node, "", tmp)
        log.append((f"{key}-final-green", code))
        assert code == 0, key

    out = pathlib.Path(__file__).resolve().parent / "mutations.log"
    out.write_text("\n".join(f"{a}\t{b}" for a, b in log) + "\n", encoding="utf-8")
    summary = pathlib.Path(__file__).resolve().parent / "mutations-summary.txt"
    summary.write_text(
        "strong+wrong-primary: 3 red\n"
        "strong restore: 3 green\n"
        "weak+wrong-primary: 3 false-green\n"
        "sources restored + final: 3 green\n"
        + "\n".join(f"{a}\t{b}" for a, b in log)
        + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(tmp, ignore_errors=True)
    print("TEMP_REMOVED", not tmp.exists())
    print("SOURCES_RESTORED True")
    print("OK", log)


if __name__ == "__main__":
    main()
