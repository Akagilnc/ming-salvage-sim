"""CLI backend contracts: public resolve/extract/runner seams (backend mocked).

#1185 wave2b: drop private helper unit pins; merge same-seam tracers; assert
typed/structural fields over free Chinese presentation copy. Runner subprocess
stays mocked (no real binary/LLM/network).
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from agno.models.message import Message
from pydantic import BaseModel

import ming_sim.cli_backend as cb
from ming_sim.models import LLMConfig


def _cli_codex_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend", base_url="", model="api-fallback",
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
    )


def _patch_backend(monkeypatch, payload: str):
    monkeypatch.setattr(cb, "_run_backend", lambda p: (payload, 1))


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


@pytest.mark.parametrize(
    "env,attr,out",
    [
        ("claude", "_run_claude", "CLAUDE_OUT"),
        (None, "_run_agy", "AGY_DEFAULT_OUT"),
        ("codex", "_run_codex", "CODEX_OUT"),
    ],
)
def test_run_backend_dispatch(monkeypatch, env, attr, out):
    if env is None:
        monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    else:
        monkeypatch.setenv("MING_SIM_LLM_BACKEND", env)
    monkeypatch.setattr(cb, attr, lambda p, **kw: (out, 1))
    assert cb._run_backend("x") == (out, 1)


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
    out, attempts = cb._run_claude("PROMPT")
    assert out == body and attempts == 1
    assert "-p" in captured["cmd"] and "--model" in captured["cmd"]
    assert "--output-format" in captured["cmd"] and "text" in captured["cmd"]
    assert captured["kw"].get("env") is None


def test_materials_dir_reaches_popen_cwd_and_readonly_argv(monkeypatch, tmp_path):
    """#1830 / #1827：Claude 材料模式传到真实子进程 seam（cwd + Read/Glob/Grep）。"""
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out, n = cb._run_claude("p", materials_dir=root)
    assert out == "ok" and n == 1
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
    out, n = cb._run_codex("p", materials_dir=root)
    assert out == "ok" and n == 1
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
    out, n = cb._run_agy("PROMPT", materials_dir=root)
    assert out == "ok" and n == 1
    assert captured["kw"].get("cwd") == root
    assert captured["cmd"][-1] == "--print=PROMPT"
    assert captured["kw"].get("stdin") is None
    assert "--sandbox" not in captured["cmd"]


def test_run_codex_flags_and_stdout(monkeypatch):
    body = '{"k": []}'
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="OpenAI Codex v0\nlogs"))
    out, n = cb._run_codex("p")
    assert out == body and n == 1
    assert "--skip-git-repo-check" in captured["cmd"]
    assert "--ephemeral" in captured["cmd"]
    assert "-c" not in captured["cmd"]


def test_clichat_codex_response_stream_passes_reasoning_strength(monkeypatch):
    seen = {}

    def fake_chunks(runner, prompt, *, model=None,
                    reasoning_strength=None, json_events=False, clock=None,
                    materials_dir=None):
        seen["runner"] = runner
        seen["json_events"] = json_events
        seen["reasoning_strength"] = reasoning_strength
        yield "STREAM_CHUNK"

    monkeypatch.setattr(cb, "_iter_cli_runner_text", fake_chunks)
    chat = cb.CliChat(id="gpt-test", backend="codex", reasoning_strength="low")
    chunks = list(chat.response_stream([Message(role="user", content="PROMPT")]))
    assert [c.content for c in chunks if c.content] == ["STREAM_CHUNK"]
    assert seen["reasoning_strength"] == "low"
    assert seen["runner"] == "codex" and seen["json_events"] is True


def test_codex_final_text_handles_item_completed_shape():
    assert cb._codex_final_text(
        {"type": "item.completed", "item": {"type": "agent_message", "text": "BODY"}}
    ) == "BODY"
    assert cb._codex_final_text(
        {"type": "item.completed", "item": {"type": "reasoning", "text": "DRAFT"}}
    ) == ""
    assert cb._codex_final_text({"type": "agent_message", "message": "TOP"}) == "TOP"


@pytest.mark.parametrize(
    "runner,kwargs,model_flag",
    [
        ("_run_codex", {"model": "gpt-configured"}, "gpt-configured"),
        ("_run_claude", {"model": "claude-configured"}, "claude-configured"),
    ],
)
def test_run_runner_accepts_config_model(monkeypatch, runner, kwargs, model_flag):
    """#1465 切片③：cli_model 仍透传 --model；子进程不吃任何超时墙
    （Popen 无 timeout kwarg；跨墙不杀由 test_cli_transport_1465 真入口证明）。"""
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    out, n = getattr(cb, runner)("p", **kwargs)
    assert out == "STDOUT_BODY" and n == 1
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == model_flag
    assert "timeout" not in captured["kw"]


def test_run_codex_reasoning_env_optional(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb._run_codex("p")
    joined = " ".join(captured["cmd"])
    assert "-c" in captured["cmd"]
    assert "model_reasoning_effort" in joined and "medium" in joined


def test_run_codex_maps_reasoning_strength_to_native_effort(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb._run_codex("p", reasoning_strength="high")
    joined = " ".join(captured["cmd"])
    assert 'model_reasoning_effort="xhigh"' in joined
    assert 'model_reasoning_effort="medium"' not in joined


def test_run_claude_maps_reasoning_strength_to_thinking_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out, n = cb._run_claude("p", reasoning_strength="medium")
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "10000"


def test_run_claude_off_reasoning_uses_explicit_minimum_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out, n = cb._run_claude("p", reasoning_strength="off")
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "2000"










def test_login_shell_path_uses_printenv_not_dollar_path(monkeypatch):
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)
    captured = {}

    class _R:
        stdout = "<<<CMRPATH>>>/a/bin:/b/bin<<<ENDPATH>>>"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(cb, "_RAW_RUN", lambda cmd, **kw: captured.update(cmd=cmd) or _R())
    assert cb._login_shell_path() == "/a/bin:/b/bin"
    joined = " ".join(captured["cmd"])
    assert "printenv PATH" in joined
    assert '"$PATH"' not in joined
    assert "-lic" not in captured["cmd"]
    assert {"-l", "-i", "-c"} <= set(captured["cmd"])



@pytest.mark.parametrize(
    "runner,resolved",
    [
        ("_run_codex", "/Users/x/.local/bin/codex"),
        ("_run_claude", "/opt/homebrew/bin/claude"),
        ("_run_agy", "/Users/x/.local/bin/agy"),
    ],
)
def test_run_runner_execs_resolved_abspath(monkeypatch, runner, resolved):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured: resolved)
    monkeypatch.setattr(cb, "_warm_keychain", lambda: None)
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    getattr(cb, runner)("p")
    assert captured["cmd"][0] == resolved


# ── lenient JSON via public extract seam ──


# ── CliChat public: prompt shape + typed completion structure ──

def test_clichat_invoke_builds_prompt_and_completion_structure(monkeypatch):
    """#1563：公开 invoke 证各条非空输入按原顺序进入 prompt，以及 typed completion 原样带回。"""
    cc = cb.CliChat(id="cli-test", backend="agy")
    seen = {}

    # Deterministic fixture the old _strip_agent_narration would have rewritten
    # (drop leading "I will …" line). Public content must equal the stub verbatim.
    runner_text = "I will check the files.\nBODY_ZH_REPLY"

    def fake_cli(prompt):
        seen["prompt"] = prompt
        return (runner_text, 1)

    monkeypatch.setattr(cc, "_call_cli", fake_cli)
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
    p = seen["prompt"]
    assert p.index("SYS_ROLE") < p.index("USER_MSG") < p.index("PRIOR_ASST") < p.index("TOOL_OUT") < p.index("12345")
    assert p.count("USER_MSG") == 1
    # typed completion + passthrough on structured content (fixture, not LLM prose)
    assert out.role == "assistant"
    assert out.event == "AssistantResponse"
    assert out.tool_calls == []
    assert out.content == runner_text


def test_clichat_invoke_json_constraint_and_no_constraint(monkeypatch):
    cc = cb.CliChat(id="cli-test", backend="agy")
    seen = []

    def fake_cli(prompt):
        seen.append(prompt)
        return ("{}", 1)

    monkeypatch.setattr(cc, "_call_cli", fake_cli)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    msgs = [SimpleNamespace(role="user", content="EXTRACT")]
    cc.invoke(msgs, Message(role="assistant"), response_format={"type": "json_object"})

    class _RF(BaseModel):
        x: int = 0

    cc.invoke(msgs, Message(role="assistant"), response_format=_RF)
    cc.invoke(msgs, Message(role="assistant"))
    assert all("EXTRACT" in prompt for prompt in seen)
    assert seen[0] != seen[2]
    assert seen[1] != seen[2]


def test_clichat_invoke_error_traced_and_reraised(monkeypatch):
    """#1299/#1310：runner 失败翻 typed LLMUnavailable；trace 仍记机器原文。"""
    from ming_sim.exceptions import LLMUnavailable
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cc, "_call_cli", lambda p: (_ for _ in ()).throw(RuntimeError("cli down")))
    traced = {}
    monkeypatch.setattr(cb, "_trace", lambda rec: traced.update(rec))
    with pytest.raises(LLMUnavailable) as ei:
        cc.invoke([SimpleNamespace(role="user", content="x")], Message(role="assistant"))
    assert traced.get("error") == "cli down"
    assert "cli down" in (ei.value.provider_message or "")
    assert "cli down" not in ei.value.message


def test_clichat_call_cli_dispatch(monkeypatch):
    seen = {}

    def fake_codex(p, model=None, **kwargs):
        seen["codex"] = model
        return ("CODEX", 1)

    def fake_claude(p, model=None, **kwargs):
        seen["claude"] = model
        return ("CLAUDE", 1)

    def fake_agy(p):
        seen["agy"] = "called"
        return ("AGY", 1)

    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    monkeypatch.setattr(cb, "_run_claude", fake_claude)
    monkeypatch.setattr(cb, "_run_agy", fake_agy)
    assert cb.CliChat(id="m-codex", backend="codex", timeout=111)._call_cli("p") == ("CODEX", 1)
    assert cb.CliChat(id="m-claude", backend="claude", timeout=222)._call_cli("p") == ("CLAUDE", 1)
    assert cb.CliChat(id="m-agy", backend="agy", timeout=333)._call_cli("p") == ("AGY", 1)
    # #1465 切片③：model.timeout 不再下发给 runner；等多久算死归 transport 策略。
    assert seen["codex"] == "m-codex"
    assert seen["claude"] == "m-claude"
    assert seen["agy"] == "called"


def test_clichat_call_cli_unknown_backend_raises():
    with pytest.raises(RuntimeError):
        cb.CliChat(id="m", backend="bogus")._call_cli("p")


# ── agy 单次调用 / runner 失败分类（重试归 transport，runner 内无私有循环）──


def _agy_popen(monkeypatch, script):
    """agy 子进程替身：script 为逐次调用的 (stdout, returncode)。"""
    from tests.cli_process_doubles import FakeCliProcess

    state = {"agy": 0, "warm": 0}

    def fake_warm():
        state["warm"] += 1

    def fake_popen(cmd, **kw):
        index = state["agy"]
        state["agy"] += 1
        text, rc = script[min(index, len(script) - 1)]
        return FakeCliProcess(
            cmd,
            stdout_script=((text,) if text else ()),
            returncode=rc,
            popen_kwargs=kw,
        )

    monkeypatch.setattr(cb, "_warm_keychain", fake_warm)
    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    return state


def test_run_agy_success_single_subprocess(monkeypatch):
    state = _agy_popen(monkeypatch, [("STDOUT_BODY", 0)])
    out, attempts = cb._run_agy("PROMPT")
    assert out == "STDOUT_BODY" and attempts == 1
    assert state["agy"] == 1
    assert state["warm"] >= 1  # 暖 keychain 是操作步骤，不是重试策略


def test_run_agy_nonzero_exit_is_terminal_and_runs_once(monkeypatch):
    """未知非零退出（无 typed status）= 确定性失败：不洗成瞬断、不私有重试。"""
    state = _agy_popen(monkeypatch, [("", 1)])
    with pytest.raises(RuntimeError):
        cb._run_agy("p")
    assert state["agy"] == 1


class _RcProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


@pytest.mark.parametrize(
    "runner,proc",
    [
        ("_run_codex", lambda: _RcProc(stderr="error: auth failed", returncode=1)),
        ("_run_claude", lambda: _RcProc(stderr="auth required", returncode=1)),
    ],
)
def test_run_runner_fail_loud_on_bad_exit(monkeypatch, runner, proc):
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(monkeypatch, lambda cmd, **kw: proc())
    with pytest.raises(RuntimeError):
        getattr(cb, runner)("p")


def test_run_runner_empty_output_is_retryable_typed(monkeypatch):
    """rc=0 但零输出 = 可重试 typed 空输出（交 transport 再试），不是确定性失败。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(monkeypatch, _P(stdout="", stderr="", returncode=0))
    with pytest.raises(LLMUnavailable) as ei:
        cb._run_codex("p")
    assert ei.value.code == "llm_empty_output"


# ── trace throat ──



def test_run_backend_empty_tag_is_other_not_prompt_guess(monkeypatch):
    """公共咽喉 _run_backend_for_config：tag 空时记 other，不从自由 prompt 猜分类。"""
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(
        cb, "_run_codex",
        lambda prompt, model=None, **kwargs: ("ok", 1),
    )
    # Prompt contains words that the retired prose→tag guesser would have classified.
    cb._run_backend_for_config(
        "你扮演被皇帝召见的大臣，请拟一道诏书，只输出合法 JSON",
        _cli_codex_cfg(),
    )
    assert len(recs) == 1
    assert recs[0]["tag"] == "other"


def test_run_backend_for_config_traces_every_call(monkeypatch):
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(cb, "_run_codex", lambda prompt, model=None, **kwargs: ("外臣", 1))
    out, attempts = cb._run_backend_for_config("判官名：后金汗", _cli_codex_cfg(), tag="office_infer")
    assert out == "外臣" and attempts == 1
    assert len(recs) == 1
    r = recs[0]
    assert r["tag"] == "office_infer"
    assert "后金汗" in r["prompt"] and r["response"] == "外臣"
    assert r["backend"] == "codex" and r["error"] is None


def test_run_backend_for_config_passes_reasoning_strength_to_codex(monkeypatch):
    seen = {}

    def fake_codex(prompt, model=None, reasoning_strength=None):
        seen["reasoning_strength"] = reasoning_strength
        return "外臣", 1

    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    monkeypatch.setattr(cb, "_run_codex", fake_codex)
    cfg = SimpleNamespace(
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
        cli_timeout_seconds=240, reasoning_strength="low",
    )
    cb._run_backend_for_config("判官名：后金汗", cfg, tag="office_infer")
    assert seen["reasoning_strength"] == "low"


def test_run_backend_for_config_traces_on_backend_error(monkeypatch):
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))

    def boom(prompt, model=None, **kwargs):
        raise RuntimeError("codex 挂了")

    monkeypatch.setattr(cb, "_run_codex", boom)
    with pytest.raises(RuntimeError):
        cb._run_backend_for_config("任意提示", _cli_codex_cfg(), tag="probe")
    assert len(recs) == 1
    assert recs[0]["error"] and "codex 挂了" in recs[0]["error"]


def test_office_inference_llm_call_is_traced(monkeypatch):
    import ming_sim.db as dbmod
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    monkeypatch.setattr(cb, "_run_codex", lambda prompt, model=None, **kwargs: ("边镇", 1))
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    got = dbmod.infer_office_type_from_office("绝无此名的杜撰怪衔甲", llm_config=_cli_codex_cfg())
    assert got == "边镇"
    assert len(recs) == 1 and "绝无此名的杜撰怪衔甲" in recs[0]["prompt"]


# ── #1256 cursor / kimi / grok + #1274-qa-y1 pi runners ──


def test_public_cli_support_restores_existing_runners(monkeypatch):
    assert cb.GATE_CLI_RUNNERS == ("codex", "claude", "cursor", "kimi", "grok", "pi")
    assert [row["value"] for row in cb.cli_runner_choices()] == ["agy", "codex", "claude", "cursor", "kimi", "grok", "pi"]
    assert set(cb.cli_model_choices()) == {row["value"] for row in cb.cli_runner_choices()}
    for name in ("opencode",):
        assert not cb.is_supported_cli_runner(name)
        monkeypatch.setenv("MING_SIM_LLM_BACKEND", name)
        assert cb.cli_backend_from_env() is None


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok", "pi"])
def test_material_runner_uses_cwd_and_read_only_tool_surface(monkeypatch, tmp_path, runner):
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out, n = cb._run_cli_runner(runner, "PROMPT", materials_dir=root)
    assert out == "ok" and n == 1
    assert captured["kw"].get("cwd") == root
    cmd = captured["cmd"]
    if runner == "cursor":
        assert "ask" in cmd and "enabled" in cmd
    elif runner == "kimi":
        agent_path = cmd[cmd.index("--agent-file") + 1]
        assert not os.path.exists(agent_path)
        created = []
        real_named_temp = cb.tempfile.NamedTemporaryFile

        def tracked_temp(*args, **kwargs):
            handle = real_named_temp(*args, **kwargs)
            created.append(handle.name)
            return handle

        monkeypatch.setattr(cb.tempfile, "NamedTemporaryFile", tracked_temp)
        monkeypatch.setattr(
            cb, "_resolve_cli_bin",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("missing")),
        )
        with pytest.raises(RuntimeError):
            list(cb._iter_cli_runner_text("kimi", "PROMPT", materials_dir=root))
        assert created and not os.path.exists(created[0])
    elif runner == "grok":
        assert "Read,Glob,Grep" in cmd and "read-only" in cmd
        assert "--always-approve" not in cmd
    else:
        assert "read,grep,find,ls" in cmd
        for flag in ("--no-session", "--no-extensions", "--no-skills",
                     "--no-prompt-templates", "--no-themes", "--no-context-files"):
            assert flag in cmd


def test_run_cursor_flags_and_stdout(monkeypatch):
    body = "CURSOR_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="noise"))
    out, n = cb._run_cursor("PROMPT_BODY", model="auto")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "text"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "auto"
    assert "--trust" in cmd
    assert "PROMPT_BODY" in cmd  # positional prompt
    assert captured["kw"].get("input") in (None, "")  # not stdin


def test_run_kimi_prompt_flag_no_yolo_stdout_only(monkeypatch):
    body = "KIMI_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="kimi version 0.36.1\nTo resume..."))
    out, n = cb._run_kimi("PROMPT_BODY", model="kimi-k2")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "PROMPT_BODY"
    assert "--yolo" not in cmd and "-y" not in cmd and "--auto" not in cmd
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "kimi-k2"
    # stderr noise must not pollute answer
    assert "resume" not in out.lower()


def test_run_grok_flags_effort_and_plain(monkeypatch):
    body = "GROK_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr=""))
    out, n = cb._run_grok("PROMPT_BODY", model="grok-4.5", reasoning_strength="medium")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "PROMPT_BODY"
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "grok-4.5"
    assert "--output-format" in cmd and cmd[cmd.index("--output-format") + 1] == "plain"
    # ticket: effort only low/med/high；medium → med
    assert "--effort" in cmd and cmd[cmd.index("--effort") + 1] == "med"


def test_run_pi_flags_thinking_and_stdout(monkeypatch):
    """#1274-qa-y1：pi -p 非交互；stdout 取文；reasoning → --thinking；model 透传。"""
    body = "PI_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="pi log noise"))
    out, n = cb._run_pi(
        "PROMPT_BODY", model="openai/gpt-4o", reasoning_strength="medium",
    )
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd or "--print" in cmd
    assert "--no-tools" in cmd  # #1456：禁内置工具，防 prompt 注入驱动 read/bash/edit/write
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "openai/gpt-4o"
    # pi --help：--thinking off|minimal|low|medium|high|xhigh|max；抽象 medium 直传
    assert "--thinking" in cmd and cmd[cmd.index("--thinking") + 1] == "medium"
    assert "PROMPT_BODY" in cmd  # positional prompt
    assert captured["kw"].get("input") in (None, "")  # not stdin
    assert "noise" not in out.lower()


@pytest.mark.parametrize(
    "env,attr,out",
    [
        ("cursor", "_run_cursor", "CURSOR_OUT"),
        ("kimi", "_run_kimi", "KIMI_OUT"),
        ("grok", "_run_grok", "GROK_OUT"),
        ("pi", "_run_pi", "PI_OUT"),
    ],
)
def test_run_backend_dispatch_new_runners(monkeypatch, env, attr, out):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", env)
    monkeypatch.setattr(cb, attr, lambda p, **kw: (out, 1))
    assert cb._run_backend("x") == (out, 1)


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok", "pi"])
def test_run_backend_for_config_dispatches_new_runners(monkeypatch, runner):
    from ming_sim.models import LLMConfig

    seen = {}

    def fake(prompt, model=None, reasoning_strength=None, **kw):
        seen["args"] = (prompt, model, reasoning_strength)
        return (f"{runner}-ok", 1)

    monkeypatch.setattr(cb, f"_run_{runner}", fake)
    cfg = LLMConfig(
        api_key="", base_url="", model="m", channel="cli",
        cli_runner=runner, cli_model="mdl-x", cli_timeout_seconds=12.0,
        reasoning_strength="low",
    )
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    text, n = cb._run_backend_for_config("P", cfg, tag="t")
    assert text == f"{runner}-ok" and n == 1
    assert seen["args"][0] == "P"
    assert seen["args"][1] == "mdl-x"
    # 槽位（cli_timeout_seconds）是设置页的静默判死阈值，不逐调用透传给 runner
    assert seen["args"][2] == "low"


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok", "pi"])
def test_clichat_call_cli_dispatches_new_runners(monkeypatch, runner):
    seen = {}

    def fake(prompt, model=None, reasoning_strength=None, **kw):
        seen["model"] = model
        return ("OK", 1)

    monkeypatch.setattr(cb, f"_run_{runner}", fake)
    chat = cb.CliChat(id="mdl", backend=runner, timeout=99)
    assert chat._call_cli("p") == ("OK", 1)
    # cli_model 仍透传；model.timeout 不再下发给 runner（等多久算死归 transport 策略）
    assert seen["model"] == "mdl"


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok", "pi"])
def test_describe_effective_model_includes_new_runners(runner):
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(
        api_key="", base_url="", model="api-fallback", channel="cli",
        cli_runner=runner, cli_model="live-model",
    )
    assert cb.describe_effective_model(cfg) == f"{runner}/live-model"


@pytest.mark.parametrize("runner", ["_run_cursor", "_run_kimi", "_run_grok", "_run_pi"])
def test_new_runner_fail_loud_on_bad_exit(monkeypatch, runner):
    _capture_run(monkeypatch, _RcProc(stderr="auth failed", returncode=1))
    with pytest.raises(RuntimeError):
        getattr(cb, runner)("p")


# ── #1256 S2 gate LLM args / config / evidence ──


def test_gate_llm_config_cli_channel():
    args = SimpleNamespace(channel="cli", runner="codex", model="gpt-5.3-codex-spark", api_key="", base_url="")
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex" and cfg.cli_model == "gpt-5.3-codex-spark"
    assert cfg.api_key == "" and cfg.base_url == ""


def test_gate_llm_config_api_from_args_not_persisted_shape(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MING_SIM_API_BASE_URL", raising=False)
    args = SimpleNamespace(
        channel="api", runner="", model="deepseek-v4-flash",
        api_key="sk-test", base_url="https://opencode.ai/zen/v1",
    )
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.channel == "api"
    assert cfg.model == "deepseek-v4-flash"
    assert cfg.api_key == "sk-test"
    assert cfg.base_url == "https://opencode.ai/zen/v1"
    assert cfg.cli_runner == ""  # api 不写 runner


def test_gate_llm_config_api_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    args = SimpleNamespace(channel="api", runner="", model="m", api_key="", base_url="")
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.api_key == "sk-env" and cfg.base_url == "https://example.test/v1"


def test_gate_llm_config_cli_requires_runner():
    args = SimpleNamespace(channel="cli", runner="", model="m", api_key="", base_url="")
    with pytest.raises(ValueError):
        cb.gate_llm_config_from_args(args)


def test_gate_llm_config_api_requires_key_and_url(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MING_SIM_API_BASE_URL", raising=False)
    args = SimpleNamespace(channel="api", runner="", model="m", api_key="", base_url="")
    with pytest.raises(ValueError):
        cb.gate_llm_config_from_args(args)
    args.api_key = "sk-x"
    with pytest.raises(ValueError):
        cb.gate_llm_config_from_args(args)


def test_gate_evidence_config_honest_cli_and_api():
    cli_args = SimpleNamespace(channel="cli", runner="claude", model="claude-opus-4-8")
    cli_cfg = cb.gate_llm_config_from_args(cli_args)
    cli_block = cb.gate_evidence_config(cli_args, cli_cfg)
    assert cli_block["channel"] == "cli"
    assert cli_block["runner"] == "claude"
    assert cli_block["model"] == "claude-opus-4-8"

    api_args = SimpleNamespace(
        channel="api", runner="codex", model="deepseek-v4-flash",
        api_key="sk", base_url="https://opencode.ai/zen/v1",
    )
    api_cfg = cb.gate_llm_config_from_args(api_args)
    api_block = cb.gate_evidence_config(api_args, api_cfg)
    assert api_block["channel"] == "api"
    assert api_block["runner"] == ""  # api 如实不挂 cli runner 名
    assert api_block["model"] == "deepseek-v4-flash"


def test_add_gate_llm_args_uses_gate_cli_runners():
    import argparse
    p = argparse.ArgumentParser()
    cb.add_gate_llm_args(p)
    # illegal runner rejected; legal accepted
    with pytest.raises(SystemExit):
        p.parse_args(["--runner", "opencode", "--model", "m"])
    ns = p.parse_args(["--runner", "claude", "--model", "claude-opus-4-8", "--channel", "cli"])
    assert ns.runner == "claude" and ns.model == "claude-opus-4-8"
