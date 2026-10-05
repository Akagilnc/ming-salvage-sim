#!/usr/bin/env python3
"""J6 valid mutation proof: real dual-fault paths; only swap final primary diagnosis.

DEPRECATED: prior PRE that replaced minister_chat / atomic_and_reload wholesale
(see mutations.log / mutations.txt) is NOT valid proof — entry never traversed.
This script records ACTUAL_DOUBLE_FAULT from live failure branches.
"""
from __future__ import annotations

import inspect
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
    assert ei.value is chat_error
    assert ei.value.__cause__ is rollback_error"""

CLI_WEAK = """\
    with pytest.raises(RuntimeError) as ei:
        term.minister_chat(Session(), SimpleNamespace(name=\"魏忠贤\"))"""

MONTH_STRONG = """\
    assert caught.value.error_pack_path is None
    # 原结算诊断保真：注入异常对象／str 作期望；写包次生挂 cause，不得顶替。
    assert caught.value.args[:1] == settle_error.args[:1]
    assert caught.value.__cause__ is pack_error
    assert not db.staged_declarations.is_settled(ref)
    assert _ningyuan_ledger_rows(db) == []
    failure = _month_chain_of(db, turn).get(\"call_failure\") or {}
    assert failure.get(\"kind\") == \"code_exception\"
    assert failure.get(\"message\") == str(settle_error)
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
            raise body_error
    # 原异常对象保真：注入异常对象作期望；reload 次生只挂 cause。
    assert ei.value is body_error
    assert ei.value.__cause__ is reload_error"""

RELOAD_WEAK = """\
    with pytest.raises(RuntimeError) as ei:
        with atomic_and_reload(db, state, content=content):
            raise body_error
    assert isinstance(ei.value.__cause__, ValueError)"""


def _cli_mutant_src() -> str:
    import ming_sim.cli.terminal as term

    src = textwrap.dedent(inspect.getsource(term.minister_chat))
    old = (
        "            except BaseException as cleanup_error:\n"
        "                raise original_error from cleanup_error"
    )
    new = (
        "            except BaseException as cleanup_error:\n"
        "                _MUT_TRAIL.append(\n"
        "                    (type(original_error).__name__, str(original_error),\n"
        "                     type(cleanup_error).__name__, str(cleanup_error)))\n"
        "                raise cleanup_error from original_error"
    )
    if old not in src:
        raise RuntimeError("cli rethrow site missing")
    return src.replace(old, new, 1)


def _reload_mutant_src() -> str:
    import ming_sim.decree as decree

    src = textwrap.dedent(inspect.getsource(decree.atomic_and_reload))
    old = (
        "                outcome.reload_failed = True\n"
        "                raise exc from reload_exc"
    )
    new = (
        "                outcome.reload_failed = True\n"
        "                _MUT_TRAIL.append(\n"
        "                    (type(exc).__name__, str(exc),\n"
        "                     type(reload_exc).__name__, str(reload_exc)))\n"
        "                raise type(exc)(*reload_exc.args) from reload_exc"
    )
    if old not in src:
        raise RuntimeError("reload rethrow site missing")
    return src.replace(old, new, 1)


def _month_mutant_src() -> str:
    import ming_sim.month_chain as mc

    src = textwrap.dedent(inspect.getsource(mc._abort_month_call))
    old = (
        "    except Exception as caught_pack:\n"
        "        # 写包失败不得顶替原故障，也不得挡住已提交相位上的失败标记。\n"
        "        pack_exc = caught_pack"
    )
    new = (
        "    except Exception as caught_pack:\n"
        "        # 写包失败不得顶替原故障，也不得挡住已提交相位上的失败标记。\n"
        "        pack_exc = caught_pack\n"
        "        _MUT_TRAIL.append(\n"
        "            (type(exc).__name__, str(exc),\n"
        "             type(caught_pack).__name__, str(caught_pack)))\n"
        "        original = str(caught_pack)"
    )
    if old not in src:
        raise RuntimeError("month pack_exc site missing")
    return src.replace(old, new, 1)


def _preamble(key: str) -> str:
    if key == "cli":
        return textwrap.dedent(
            f"""
            import ming_sim.cli.terminal as term
            import tests.test_cli_play_turn as m
            _ORIG = term.minister_chat
            term._MUT_TRAIL = []
            exec(compile({_cli_mutant_src()!r}, "<mutant:minister_chat>", "exec"), term.__dict__)
            m.term.minister_chat = term.minister_chat
            def _restore():
                term.minister_chat = _ORIG
                m.term.minister_chat = _ORIG
            def _trail():
                return term._MUT_TRAIL
            """
        ).strip()
    if key == "month":
        return textwrap.dedent(
            f"""
            import ming_sim.month_chain as mc
            _ORIG = mc._abort_month_call
            mc._MUT_TRAIL = []
            exec(compile({_month_mutant_src()!r}, "<mutant:_abort_month_call>", "exec"), mc.__dict__)
            def _restore():
                mc._abort_month_call = _ORIG
            def _trail():
                return mc._MUT_TRAIL
            """
        ).strip()
    if key == "reload":
        return textwrap.dedent(
            f"""
            import ming_sim.decree as decree_mod
            _ORIG = decree_mod.atomic_and_reload
            decree_mod._MUT_TRAIL = []
            exec(compile({_reload_mutant_src()!r}, "<mutant:atomic_and_reload>", "exec"), decree_mod.__dict__)
            def _restore():
                decree_mod.atomic_and_reload = _ORIG
            def _trail():
                return decree_mod._MUT_TRAIL
            """
        ).strip()
    raise KeyError(key)


def run(label: str, node: str, key: str | None, tmp: pathlib.Path) -> tuple[int, str]:
    bt = tmp / label
    bt.mkdir(parents=True, exist_ok=True)
    trail_path = bt / "trail.txt"
    script_path = tmp / f"{label}.py"
    lines = [
        "import sys",
        f"sys.path.insert(0, {str(ROOT)!r})",
    ]
    if key:
        lines.append(_preamble(key))
        lines.append(
            "import atexit\n"
            f"def _dump():\n"
            f"    open({str(trail_path)!r}, 'w', encoding='utf-8').write(repr(_trail())+'\\n')\n"
            "    _restore()\n"
            "atexit.register(_dump)\n"
        )
    lines.append("import pytest")
    lines.append(
        "raise SystemExit(pytest.main(["
        '"-q","--tb=line","-p","no:cacheprovider",'
        f'"--basetemp", {str(bt)!r}, {node!r}'
        "]))"
    )
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    p = subprocess.run([PY, str(script_path)], cwd=str(ROOT), env=ENV, capture_output=True, text=True)
    trail = trail_path.read_text(encoding="utf-8").strip() if trail_path.exists() else "[]"
    print(f"=== {label} exit={p.returncode} ACTUAL_DOUBLE_FAULT={trail}")
    print((p.stdout or "").strip())
    if p.returncode not in (0, 1) and p.stderr:
        print((p.stderr or "")[-1500:])
    return p.returncode, trail


def main() -> None:
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    backups = {p: p.read_text(encoding="utf-8") for p in PATHS}
    assert CLI_STRONG in backups[PATHS[0]], "cli strong block missing"
    assert MONTH_STRONG in backups[PATHS[1]], "month strong block missing"
    assert RELOAD_STRONG in backups[PATHS[2]], "reload strong block missing"
    # Validate mutant sites compile against live modules before pytest.
    for builder in (_cli_mutant_src, _month_mutant_src, _reload_mutant_src):
        builder()

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="1900-j6-mut5-"))
    log: list[tuple[str, int, str]] = []
    try:
        for key, node in zip(("cli", "month", "reload"), NODES):
            code, trail = run(f"{key}-strong-red", node, key, tmp)
            log.append((f"{key}-strong-red", code, trail))
            assert code != 0, f"{key} expected red"
            assert trail not in ("[]", ""), f"{key} missing ACTUAL_DOUBLE_FAULT"

        for key, node in zip(("cli", "month", "reload"), NODES):
            code, trail = run(f"{key}-strong-green", node, None, tmp)
            log.append((f"{key}-strong-green", code, trail))
            assert code == 0, f"{key} restore green"

        PATHS[0].write_text(backups[PATHS[0]].replace(CLI_STRONG, CLI_WEAK), encoding="utf-8")
        PATHS[1].write_text(backups[PATHS[1]].replace(MONTH_STRONG, MONTH_WEAK), encoding="utf-8")
        PATHS[2].write_text(backups[PATHS[2]].replace(RELOAD_STRONG, RELOAD_WEAK), encoding="utf-8")
        for key, node in zip(("cli", "month", "reload"), NODES):
            code, trail = run(f"{key}-weak-false-green", node, key, tmp)
            log.append((f"{key}-weak-false-green", code, trail))
            assert code == 0, f"{key} weak should false-green"
            assert trail not in ("[]", ""), f"{key} weak missing trail"
    finally:
        for p, text in backups.items():
            p.write_text(text, encoding="utf-8")

    assert all(p.read_text(encoding="utf-8") == backups[p] for p in PATHS)
    for key, node in zip(("cli", "month", "reload"), NODES):
        code, trail = run(f"{key}-final-green", node, None, tmp)
        log.append((f"{key}-final-green", code, trail))
        assert code == 0, f"{key} final green"

    out_dir = pathlib.Path(__file__).resolve().parent
    (out_dir / "mutations-valid.log").write_text(
        "\n".join(f"{a}\texit={b}\tACTUAL_DOUBLE_FAULT={c}" for a, b, c in log) + "\n",
        encoding="utf-8",
    )
    (out_dir / "mutations-valid-summary.txt").write_text(
        "DEPRECATED_OLD_MUTATIONS: mutations.log / mutations.txt / mutations-summary.txt "
        "(whole-entry swap of minister_chat / atomic_and_reload; no real dual-fault traversal)\n"
        "METHOD: inspect.getsource + compile/exec into live module.__dict__; "
        "only final rethrow / original-diagnosis assignment swapped; trail records both faults\n"
        "strong+wrong-primary (real dual-fault): 3 red\n"
        "strong restore: 3 green\n"
        "weak+wrong-primary (real dual-fault): 3 false-green\n"
        "sources restored + final: 3 green\n"
        + "\n".join(f"{a}\texit={b}\tACTUAL_DOUBLE_FAULT={c}" for a, b, c in log)
        + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(tmp, ignore_errors=True)
    print("TEMP_REMOVED", not tmp.exists())
    print("SOURCES_RESTORED True")
    print("OK", [(a, b) for a, b, _ in log])


if __name__ == "__main__":
    main()
