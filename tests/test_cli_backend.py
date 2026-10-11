"""CLI backend contracts: public model/extractor entries (backend mocked).

#1185 wave2b: drop private helper unit pins; merge same-seam tracers; assert
typed/structural fields over free Chinese presentation copy. Runner subprocess
stays mocked (no real binary/LLM/network).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agno.models.message import Message

import ming_sim.cli_backend as cb
from ming_sim.models import LLMConfig
from ming_sim.exceptions import LLMUnavailable

def _cli_codex_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend", base_url="", model="api-fallback",
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
    )


def test_typed_secret_exclusions_canonicalize_roster_alias_and_office(game):
    from ming_sim.db import canonical_secret_order_exclusions

    content = game[2]
    character = next(
        ch for ch in content.characters.values() if getattr(ch, "aliases", None)
    )
    alias = character.aliases[0]
    office = character.office_type
    people, offices = canonical_secret_order_exclusions(
        content, [alias], [office], "勿使玩家散文成为第二输入源",
    )
    assert people == [character.name]
    assert offices == [office]







# ── cli_backend_from_env / backend dispatch ──

def test_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert cb.cli_backend_from_env() is None
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    assert cb.cli_backend_from_env() == "agy"

def test_backend_env_claude(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "claude")
    assert cb.cli_backend_from_env() == "claude"

# ── secret extract keep family ──

# ── runner argv / error contracts (subprocess mocked) ──

class _P:
    def __init__(self, stdout="STDOUT_BODY", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

def _capture_run(monkeypatch, proc=None):
    """runner 子进程边界替身（生产已改 Popen + 增量读）；保留 argv/kwargs 观察面。"""
    from tests.cli_process_doubles import FakeCliProcess

    captured = {}
    proc = proc or _P()

    def fake_popen(cmd, **kw):
        captured["cmd"] = list(cmd)
        captured["kw"] = kw
        spec = proc(cmd, **kw) if callable(proc) else proc
        fake = FakeCliProcess(
            cmd,
            stdout_script=((spec.stdout,) if spec.stdout else ()),
            stderr_script=((spec.stderr,) if spec.stderr else ()),
            returncode=spec.returncode,
            popen_kwargs=kw,
        )
        captured["proc"] = fake
        return fake

    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    return captured

def test_run_claude_stdout_only(monkeypatch):
    body = "STDOUT_BODY"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="LOG_NOISE"))
    out = cb.CliChat(id="cli-test", backend="claude").invoke(
        [Message(role="user", content="PROMPT")], Message(role="assistant"),
    ).content
    assert out == body
    assert "-p" in captured["cmd"] and "--model" in captured["cmd"]
    assert "--output-format" in captured["cmd"] and "text" in captured["cmd"]
    assert captured["kw"].get("env") is None

def test_materials_dir_reaches_popen_cwd_and_readonly_argv(monkeypatch, tmp_path):
    """#1830 / #1827：Claude 材料模式传到真实子进程 seam（cwd + Read/Glob/Grep）。"""
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out = cb.CliChat(id="cli-test", backend="claude", materials_dir=root).invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "ok"
    assert captured["kw"].get("cwd") == root
    assert "--restricted" in captured["cmd"]
    assert "--strict-mcp-config" in captured["cmd"]
    assert "--bare" not in captured["cmd"]
    assert "--add-dir" not in captured["cmd"]
    assert "--allowedTools" in captured["cmd"]
    assert "Read" in captured["cmd"] and "Glob" in captured["cmd"] and "Grep" in captured["cmd"]
    mcp_at = captured["cmd"].index("--mcp-config")
    assert json.loads(captured["cmd"][mcp_at + 1]) == {"mcpServers": {}}
    assert "--permission-mode" in captured["cmd"]
    assert "dontAsk" in captured["cmd"]
    assert "--disallowedTools" not in captured["cmd"]

def test_codex_materials_dir_reaches_popen_cwd_and_readonly_argv(monkeypatch, tmp_path):
    """#1830 / #1827：Codex 材料模式 cwd + --ignore-user-config --sandbox read-only。"""
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out = cb.CliChat(id="cli-test", backend="codex", materials_dir=root).invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "ok"
    assert captured["kw"].get("cwd") == root
    assert "--ignore-user-config" in captured["cmd"]
    assert "--sandbox" in captured["cmd"]
    assert "read-only" in captured["cmd"]
    assert "--skip-git-repo-check" in captured["cmd"]
    assert "--ephemeral" in captured["cmd"]

def test_agy_materials_mode_uses_material_cwd_and_print_argument(monkeypatch, tmp_path):
    """Agy 1.2.0 材料调用用 --print=<prompt>，不再走失效 sandbox/stdin。"""
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    monkeypatch.setattr(cb, "_trace", lambda rec: captured.update(trace=rec))
    out = cb.CliChat(id="cli-test", backend="agy", materials_dir=root).invoke(
        [Message(role="user", content="PROMPT")], Message(role="assistant"),
    ).content
    assert out == "ok"
    assert captured["kw"].get("cwd") == root
    assert captured["cmd"][-1] == "--print=" + captured["trace"]["prompt"]
    assert captured["kw"].get("stdin") is None
    assert "--sandbox" not in captured["cmd"]

@pytest.mark.parametrize(
    "runner,model_flag",
    [
        ("codex", "gpt-configured"),
        ("claude", "claude-configured"),
    ],
)
def test_run_runner_accepts_config_model(monkeypatch, runner, model_flag):
    """#1465 切片③：cli_model 仍透传 --model；子进程不吃任何超时墙
    （Popen 无 timeout kwarg；跨墙不杀由 test_cli_transport_1465 真入口证明）。"""
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    out = cb.CliChat(id=model_flag, backend=runner).invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "STDOUT_BODY"
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == model_flag
    assert "timeout" not in captured["kw"]


def test_run_codex_maps_reasoning_strength_to_native_effort(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb.CliChat(id="cli-test", backend="codex", reasoning_strength="high").invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    )
    joined = " ".join(captured["cmd"])
    assert 'model_reasoning_effort="xhigh"' in joined
    assert 'model_reasoning_effort="medium"' not in joined


def test_run_codex_stderr_banner_does_not_become_body(monkeypatch):
    """stdout 空时 stderr 日志／banner 不得冒充正文；走既有空输出失败契约。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(
        monkeypatch,
        _P(stdout="", stderr="diag\nOpenAI Codex v0.125.0\nlogs", returncode=0),
    )
    with pytest.raises(LLMUnavailable) as ei:
        cb.CliChat(id="cli-test", backend="codex").invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )
    assert ei.value.code == "llm_empty_output"

def test_run_claude_maps_reasoning_strength_to_thinking_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out = cb.CliChat(id="cli-test", backend="claude", reasoning_strength="medium").invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "10000"

def test_run_claude_off_reasoning_uses_explicit_minimum_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out = cb.CliChat(id="cli-test", backend="claude", reasoning_strength="off").invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "2000"

# ── _resolve_cli_bin / login shell path ──


@pytest.mark.parametrize(
    "runner,resolved",
    [
        ("codex", "/Users/x/.local/bin/codex"),
        ("claude", "/opt/homebrew/bin/claude"),
        ("agy", "/Users/x/.local/bin/agy"),
    ],
)
def test_run_runner_execs_resolved_abspath(monkeypatch, runner, resolved):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured: resolved)
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    cb.CliChat(id="cli-test", backend=runner).invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    )
    assert captured["cmd"][0] == resolved


# ── lenient JSON via public extract seam ──


# ── CliChat public: prompt shape + typed completion structure ──

def test_clichat_invoke_builds_prompt_and_completion_structure(monkeypatch):
    """#1563：公开 invoke 带回 typed completion，原文透传（不锁 prompt 拼装哨兵）。"""
    cc = cb.CliChat(id="cli-test", backend="agy")

    # Deterministic fixture the old _strip_agent_narration would have rewritten
    # (drop leading "I will …" line). Public content must equal the stub verbatim.
    runner_text = "I will check the files.\nBODY_ZH_REPLY"

    _capture_run(monkeypatch, _P(stdout=runner_text))
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    msgs = [
        SimpleNamespace(role="system", content="SYS_ROLE"),
        SimpleNamespace(role="user", content="USER_MSG"),
        SimpleNamespace(role="user", content="   "),
        SimpleNamespace(role="assistant", content=None),
        SimpleNamespace(role="assistant", content="PRIOR_ASST"),
        SimpleNamespace(role="tool", content="TOOL_OUT"),
        SimpleNamespace(role="developer", content=12345),
    ]
    out = cc.invoke(msgs, Message(role="assistant"))
    # typed completion + passthrough on structured content (fixture, not LLM prose)
    assert out.role == "assistant"
    assert out.event == "AssistantResponse"
    assert out.tool_calls == []
    assert out.content == runner_text

def test_clichat_invoke_error_traced_and_reraised(monkeypatch):
    """#1299/#1310：runner 失败翻 typed LLMUnavailable；trace 仍记机器原文。"""
    from ming_sim.exceptions import LLMUnavailable
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cli down")))
    traced = {}
    monkeypatch.setattr(cb, "_trace", lambda rec: traced.update(rec))
    with pytest.raises(LLMUnavailable) as ei:
        cc.invoke([SimpleNamespace(role="user", content="x")], Message(role="assistant"))
    assert traced.get("error") == "cli down"
    assert "cli down" in (ei.value.provider_message or "")
    assert "cli down" not in ei.value.message

def test_clichat_call_cli_unknown_backend_raises():
    with pytest.raises(LLMUnavailable):
        cb.CliChat(id="m", backend="bogus").invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )

# ── agy 单次调用 / runner 失败分类（重试归 transport，runner 内无私有循环）──


def test_run_agy_nonzero_exit_is_terminal_and_runs_once(monkeypatch):
    """未知非零退出（无 typed status）= 确定性失败：不洗成瞬断、不私有重试。"""
    from tests.cli_process_doubles import install_fake_cli_runner

    script = install_fake_cli_runner(monkeypatch, [{"returncode": 1}])
    with pytest.raises(LLMUnavailable):
        cb.CliChat(id="cli-test", backend="agy").invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )
    assert len(script.processes) == 1


@pytest.mark.parametrize(
    "runner,proc",
    [
        ("codex", _P(stderr="error: auth failed", returncode=1)),
        ("claude", _P(stderr="auth required", returncode=1)),
    ],
)
def test_run_runner_fail_loud_on_bad_exit(monkeypatch, runner, proc):
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(monkeypatch, proc)
    with pytest.raises(LLMUnavailable):
        cb.CliChat(id="cli-test", backend=runner).invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )

def test_run_runner_empty_output_is_retryable_typed(monkeypatch):
    """rc=0 但零输出 = 可重试 typed 空输出（交 transport 再试），不是确定性失败。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(monkeypatch, _P(stdout="", stderr="", returncode=0))
    with pytest.raises(LLMUnavailable) as ei:
        cb.CliChat(id="cli-test", backend="codex").invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )
    assert ei.value.code == "llm_empty_output"

# ── trace throat ──


def test_run_backend_for_config_traces_on_backend_error(monkeypatch):
    """真实 runner 失败后，trace.error 须保留原故障可见诊断（非仅非空）。"""
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    injected = RuntimeError("codex 挂了")

    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(injected))
    # 官方：ExceptionInfo.value 对象身份
    # https://docs.pytest.org/en/stable/how-to/assert.html#assertions-about-expected-exceptions
    with pytest.raises(RuntimeError) as ei:
        cb.capture_manual_directive_payload("任意提示", _cli_codex_cfg())
    assert ei.value is injected
    assert len(recs) == 1
    # 可见诊断须能回溯到原故障来源，不是任意非空串
    assert recs[0].get("error") == str(injected)

def test_office_inference_llm_call_is_traced(monkeypatch):
    import ming_sim.db as dbmod
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    _capture_run(monkeypatch, _P(stdout="边镇"))
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    got = dbmod.infer_office_type_from_office("绝无此名的杜撰怪衔甲", llm_config=_cli_codex_cfg())
    assert got == "边镇"
    assert len(recs) == 1 and "绝无此名的杜撰怪衔甲" in recs[0]["prompt"]
