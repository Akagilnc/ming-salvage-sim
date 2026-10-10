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

import ming_sim.cli_backend as cb
import ming_sim.draft_intent as di
from ming_sim.models import LLMConfig


# #1902：七条一行转发（cb._run_agy/_run_codex/…）已删，注入点统一在 _run_cli_runner
# （分派点唯一）。本文件按 runner 名注入：单 runner 直接绑，多 runner 走路由表。
def _patch_runner(monkeypatch, runner: str, fake) -> None:
    """把某个 runner 的调用绑到 fake（fake 收 prompt + kwargs，同旧转发签名）。"""

    def _wrapped(_runner, prompt, **kwargs):
        assert _runner == runner, f"注入错宿主：{_runner} != {runner}"
        return fake(prompt, **kwargs)

    monkeypatch.setattr(cb, "_run_cli_runner", _wrapped)


def _patch_runners(monkeypatch, fakes: dict) -> None:
    """多 runner 路由：{runner: fake}，未列者原样放行到真实实现。"""
    real = cb._run_cli_runner

    def _router(runner, prompt, **kwargs):
        fake = fakes.get(runner)
        if fake is None:
            return real(runner, prompt, **kwargs)
        return fake(prompt, **kwargs)

    monkeypatch.setattr(cb, "_run_cli_runner", _router)


def _cli_codex_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend", base_url="", model="api-fallback",
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
    )


# ── enrich_initiative_effects ──

def test_enrich_army_parsed_and_normalized(monkeypatch):
    canned = json.dumps({
        "effect_on_resolve": {
            "metrics": {"皇威": 5},
            "new_armies": [{"id": "qinjun", "name": "秦兵", "owner_power": "ming",
                            "manpower": 20000, "maintenance_per_turn": 4, "commander": "孙传庭"}],
        },
        "ongoing_effects": {}, "effect_on_fail": {},
    }, ensure_ascii=False)
    _patch_runner(monkeypatch, "agy", lambda prompt, **kw: (canned, 1))
    out = di.enrich_initiative_effects("孙传庭练秦兵", "陕西督练新军", llm_config=LLMConfig(api_key="", base_url="", model="", channel="cli", cli_runner="agy"))
    armies = out["effect_on_resolve"]["new_armies"]
    assert armies[0]["id"] == "qinjun"
    assert armies[0]["manpower"] == 20000

def test_enrich_building_region_floor(monkeypatch):
    canned = json.dumps({
        "effect_on_resolve": {"buildings": [{"action": "create", "name": "格致局", "category": "科技"}]},
        "ongoing_effects": {}, "effect_on_fail": {},
    }, ensure_ascii=False)
    _patch_runner(monkeypatch, "agy", lambda prompt, **kw: (canned, 1))
    out = di.enrich_initiative_effects("设格致局", "", llm_config=LLMConfig(api_key="", base_url="", model="", channel="cli", cli_runner="agy"))
    assert out["effect_on_resolve"]["buildings"][0]["region_id"] == "beizhili"

def test_enrich_backend_error_returns_empty_effects(monkeypatch):
    # 只认 typed 模型/宿主失败 → 空效果；裸 RuntimeError 不得被补全核洗成空效果。
    from ming_sim.exceptions import LLMUnavailable

    def boom(prompt, llm_config=None, tag="", *, policy=None):
        raise LLMUnavailable("backend down", code="llm_cli_error")
    monkeypatch.setattr(cb, "_run_backend_for_config", boom)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    out = di.enrich_initiative_effects("设格致局", "")
    assert out == {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}}

def test_enrich_nondict_subfields_guarded(monkeypatch):
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda prompt, llm_config=None, tag="", *, policy=None: (
            '{"effect_on_resolve": "坏数据", "ongoing_effects": ["x"], "effect_on_fail": 3}', 1
        ),
    )
    monkeypatch.setattr(cb, "_trace", lambda r: None)
    out = di.enrich_initiative_effects("设局", "")
    assert out == {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}}


# ── cli_backend_from_env / backend dispatch ──

# #1902：cli_backend_from_env（MING_SIM_LLM_BACKEND 选宿主）退役——下列
# env 分派用例随之删除；无配置的直调路固定走默认 runner，
# 选宿主只认运行配置（channel + cli_runner）。


@pytest.mark.parametrize(
    "runner,out",
    [
        ("claude", "CLAUDE_OUT"),
        ("agy", "AGY_DEFAULT_OUT"),
        ("codex", "CODEX_OUT"),
    ],
)
def test_run_backend_dispatch(monkeypatch, runner, out):
    """#1902：宿主只由运行配置选（channel=cli + cli_runner），不再读环境变量。"""
    cfg = LLMConfig(
        api_key="", base_url="", model="m", channel="cli", cli_runner=runner,
    )
    _patch_runner(monkeypatch, runner, lambda p, **kw: (out, 1))
    assert cb._run_backend_for_config("x", cfg) == (out, 1)


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
    out, attempts = cb._dispatch_cli_runner("claude", "PROMPT")
    assert out == body and attempts == 1
    assert "-p" in captured["cmd"] and "--model" in captured["cmd"]
    assert "--output-format" in captured["cmd"] and "text" in captured["cmd"]
    assert captured["kw"].get("env") is None

def test_materials_dir_reaches_popen_cwd_and_readonly_argv(monkeypatch, tmp_path):
    """#1830 / #1827：Claude 材料模式传到真实子进程 seam（cwd + Read/Glob/Grep）。"""
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out, n = cb._dispatch_cli_runner("claude", "p", materials_dir=root)
    assert out == "ok" and n == 1
    assert captured["kw"].get("cwd") == root
    assert "--restricted" in captured["cmd"]
    assert "--strict-mcp-config" in captured["cmd"]
    assert "--bare" not in captured["cmd"]
    assert "--add-dir" not in captured["cmd"]
    assert "--allowedTools" in captured["cmd"]
    assert "Read" in captured["cmd"] and "Glob" in captured["cmd"] and "Grep" in captured["cmd"]
    mcp_at = captured["cmd"].index("--mcp-config")
    assert captured["cmd"][mcp_at + 1] == '{"mcpServers":{}}'
    assert "--permission-mode" in captured["cmd"]
    assert "dontAsk" in captured["cmd"]
    assert "--disallowedTools" not in captured["cmd"]

def test_codex_materials_dir_reaches_popen_cwd_and_readonly_argv(monkeypatch, tmp_path):
    """#1830 / #1827：Codex 材料模式 cwd + --ignore-user-config --sandbox read-only。"""
    root = str((tmp_path / "materials").resolve())
    tmp_path.joinpath("materials").mkdir()
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out, n = cb._dispatch_cli_runner("codex", "p", materials_dir=root)
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
    out, n = cb._dispatch_cli_runner("agy", "PROMPT", materials_dir=root)
    assert out == "ok" and n == 1
    assert captured["kw"].get("cwd") == root
    assert captured["cmd"][-1] == "--print=PROMPT"
    assert captured["kw"].get("stdin") is None
    assert "--sandbox" not in captured["cmd"]

def test_run_codex_flags_and_stdout(monkeypatch):
    body = '{"k": []}'
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr="OpenAI Codex v0\nlogs"))
    out, n = cb._dispatch_cli_runner("codex", "p")
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








@pytest.mark.parametrize(
    "runner,kwargs,model_flag",
    [
        ("codex", {"model": "gpt-configured"}, "gpt-configured"),
        ("claude", {"model": "claude-configured"}, "claude-configured"),
    ],
)
def test_run_runner_accepts_config_model(monkeypatch, runner, kwargs, model_flag):
    """#1465 切片③：cli_model 仍透传 --model；子进程不吃任何超时墙
    （Popen 无 timeout kwarg；跨墙不杀由 test_cli_transport_1465 真入口证明）。"""
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    out, n = cb._dispatch_cli_runner(runner, "p", **kwargs)
    assert out == "STDOUT_BODY" and n == 1
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == model_flag
    assert "timeout" not in captured["kw"]

def test_run_codex_reasoning_env_optional(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    joined = " ".join(captured["cmd"])
    assert "-c" in captured["cmd"]
    assert "model_reasoning_effort" in joined and "medium" in joined

def test_run_codex_maps_reasoning_strength_to_native_effort(monkeypatch):
    monkeypatch.setenv("MING_SIM_CODEX_REASONING", "medium")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p", reasoning_strength="high")
    joined = " ".join(captured["cmd"])
    assert 'model_reasoning_effort="xhigh"' in joined
    assert 'model_reasoning_effort="medium"' not in joined


def test_run_codex_stdout_empty_does_not_parse_stderr_banner(monkeypatch):
    """#1902 T2：stdout 空时不得从 stderr 呈现横幅切分正文（ADR 0142）。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(
        monkeypatch,
        _P(stdout="", stderr="STDOUT_BODY\nOpenAI Codex v0.125.0\nlogs"),
    )
    with pytest.raises(LLMUnavailable) as ei:
        cb._dispatch_cli_runner("codex", "p")
    assert ei.value.code == "llm_empty_output"

def test_run_claude_maps_reasoning_strength_to_thinking_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out, n = cb._dispatch_cli_runner("claude", "p", reasoning_strength="medium")
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "10000"

def test_run_claude_off_reasoning_uses_explicit_minimum_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out, n = cb._dispatch_cli_runner("claude", "p", reasoning_strength="off")
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "2000"

# ── _resolve_cli_bin / login shell path ──















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
        ("codex", "/Users/x/.local/bin/codex"),
        ("claude", "/opt/homebrew/bin/claude"),
        ("agy", "/Users/x/.local/bin/agy"),
    ],
)
def test_run_runner_execs_resolved_abspath(monkeypatch, runner, resolved):
    cb._BIN_CACHE.clear()
    monkeypatch.setattr(cb, "_resolve_cli_bin", lambda name, configured: resolved)
    monkeypatch.setattr(cb, "_warm_keychain", lambda: None)
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    captured = _capture_run(monkeypatch, _P(stdout="STDOUT_BODY"))
    cb._dispatch_cli_runner(runner, "p")
    assert captured["cmd"][0] == resolved

# ── lenient JSON via public extract seam ──

# ── CliChat public: prompt shape + typed completion structure ──

def test_clichat_invoke_passes_fixture_content_and_completion(monkeypatch):
    """公开 invoke：夹具正文按输入顺序透传，完成结构原样承接 runner 文本。"""
    cc = cb.CliChat(id="cli-test", backend="agy")

    # Deterministic fixture the old _strip_agent_narration would have rewritten
    # (drop leading "I will …" line). Public content must equal the stub verbatim.
    runner_text = "I will check the files.\nBODY_ZH_REPLY"

    def fake_cli(prompt):
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
    # typed completion + passthrough on structured content (fixture, not LLM prose)
    assert out.role == "assistant"
    assert out.event == "AssistantResponse"
    assert out.tool_calls == []
    assert out.content == runner_text


def test_clichat_invoke_code_fault_traced_and_reraised(monkeypatch):
    """#1902：未知代码故障原样上浮，trace 仍记机器原文；不得套成 llm_cli_*。"""
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cc, "_call_cli", lambda p: (_ for _ in ()).throw(TypeError("cli down")))
    traced = {}
    monkeypatch.setattr(cb, "_trace", lambda rec: traced.update(rec))
    prose = "你扮演被皇帝召见的大臣。请整理旧账并拟诏书。"
    with pytest.raises(TypeError, match="cli down"):
        cc.invoke(
            [SimpleNamespace(role="system", content=prose)],
            Message(role="assistant"),
            run_response=SimpleNamespace(agent_name="诏书润色官"),
        )
    assert traced.get("error") == "cli down"
    assert traced.get("tag") == "诏书润色官"


def test_clichat_invoke_typed_unavailable_traced_and_reraised(monkeypatch):
    """#1299/#1310：已 typed 的宿主/模型失败原样上浮；trace 记 provider 原文。"""
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import cli_runner_unavailable

    host = RuntimeError("cli down")
    typed = cli_runner_unavailable(host, backend="agy")
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cc, "_call_cli", lambda p: (_ for _ in ()).throw(typed))
    traced = {}
    monkeypatch.setattr(cb, "_trace", lambda rec: traced.update(rec))
    prose = "你扮演被皇帝召见的大臣。请整理旧账并拟诏书。"
    with pytest.raises(LLMUnavailable) as ei:
        cc.invoke(
            [SimpleNamespace(role="system", content=prose)],
            Message(role="assistant"),
            run_response=SimpleNamespace(agent_name="诏书润色官"),
        )
    assert ei.value is typed
    assert traced.get("error") == str(typed)
    assert traced.get("tag") == "诏书润色官"
    assert "cli down" in (ei.value.provider_message or "")
    assert "cli down" not in ei.value.message


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
    out, attempts = cb._dispatch_cli_runner("agy", "PROMPT")
    assert out == "STDOUT_BODY" and attempts == 1
    assert state["agy"] == 1
    assert state["warm"] >= 1  # 暖 keychain 是操作步骤，不是重试策略


def test_run_agy_nonzero_exit_is_terminal_and_runs_once(monkeypatch):
    """已确证非零退出 = typed 确定性失败：不洗成瞬断、不私有重试。"""
    from ming_sim.exceptions import LLMUnavailable

    state = _agy_popen(monkeypatch, [("", 1)])
    with pytest.raises(LLMUnavailable) as ei:
        cb._dispatch_cli_runner("agy", "p")
    assert str(ei.value.code or "").startswith("llm_cli_")
    assert state["agy"] == 1

class _RcProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

@pytest.mark.parametrize(
    "runner,proc",
    [
        ("codex", lambda: _RcProc(stderr="error: auth failed", returncode=1)),
        ("claude", lambda: _RcProc(stderr="auth required", returncode=1)),
    ],
)
def test_run_runner_fail_loud_on_bad_exit(monkeypatch, runner, proc):
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(monkeypatch, lambda cmd, **kw: proc())
    with pytest.raises(LLMUnavailable) as ei:
        cb._dispatch_cli_runner(runner, "p")
    assert str(ei.value.code or "").startswith("llm_cli_")

def test_run_runner_empty_output_is_retryable_typed(monkeypatch):
    """rc=0 但零输出 = 可重试 typed 空输出（交 transport 再试），不是确定性失败。"""
    from ming_sim.exceptions import LLMUnavailable

    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    _capture_run(monkeypatch, _P(stdout="", stderr="", returncode=0))
    with pytest.raises(LLMUnavailable) as ei:
        cb._dispatch_cli_runner("codex", "p")
    assert ei.value.code == "llm_empty_output"

# ── trace throat ──

def test_run_backend_for_config_traces_every_call(monkeypatch):
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    _patch_runner(monkeypatch, "codex", lambda prompt, model=None, **kwargs: ("外臣", 1))
    out, attempts = cb._run_backend_for_config("判官名：后金汗", _cli_codex_cfg(), tag="office_infer")
    assert out == "外臣" and attempts == 1
    assert len(recs) == 1
    r = recs[0]
    assert r["tag"] == "office_infer"
    assert "后金汗" in r["prompt"] and r["response"] == "外臣"
    assert r["backend"] == "codex" and r["error"] is None
    # 未传 tag 时不从提示词散文猜类别：旧标记词同时出现，记录仍是空 tag。
    prose = "你扮演被皇帝召见的大臣。请整理旧账并拟诏书。只输出合法 JSON。simulator_payload"
    cb._run_backend_for_config(prose, _cli_codex_cfg())
    assert recs[-1]["tag"] == ""
    assert recs[-1]["response"] == "外臣"


def test_run_backend_for_config_passes_reasoning_strength_to_codex(monkeypatch):
    seen = {}

    def fake_codex(prompt, model=None, reasoning_strength=None):
        seen["reasoning_strength"] = reasoning_strength
        return "外臣", 1

    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    _patch_runner(monkeypatch, "codex", fake_codex)
    cfg = SimpleNamespace(
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
        cli_timeout_seconds=240, reasoning_strength="low",
    )
    cb._run_backend_for_config("判官名：后金汗", cfg, tag="office_infer")
    assert seen["reasoning_strength"] == "low"


def test_run_backend_for_config_traces_on_backend_error(monkeypatch):
    """runner 路径未识别异常原样上浮；trace.error 保留原故障诊断（非闭包宽翻 typed）。"""
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    injected = RuntimeError("codex 挂了")

    def boom(prompt, model=None, **kwargs):
        raise injected

    _patch_runner(monkeypatch, "codex", boom)
    with pytest.raises(RuntimeError) as ei:
        cb._run_backend_for_config("任意提示", _cli_codex_cfg(), tag="probe")
    assert ei.value is injected
    assert len(recs) == 1
    # 可见诊断须能回溯到原故障来源，不是任意非空串
    assert recs[0].get("error") == str(injected)

def test_office_inference_llm_call_is_traced(monkeypatch):
    import ming_sim.db as dbmod
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    recs = []
    monkeypatch.setattr(cb, "_trace", lambda rec: recs.append(rec))
    _patch_runner(monkeypatch, "codex", lambda prompt, model=None, **kwargs: ("边镇", 1))
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    got = dbmod.infer_office_type_from_office("绝无此名的杜撰怪衔甲", llm_config=_cli_codex_cfg())
    assert got == "边镇"
    assert len(recs) == 1 and "绝无此名的杜撰怪衔甲" in recs[0]["prompt"]


# ── #1256 cursor / kimi / grok + #1274-qa-y1 pi runners ──

def test_public_cli_support_restores_existing_runners(monkeypatch):
    # #1902 F3：不锁内部 frozenset／字面名单；只钉公开闸与现役 runner 行为。
    from ming_sim.llm_config import cli_supports_reasoning_strength

    assert cb.is_supported_cli_runner("grok")
    assert cli_supports_reasoning_strength("grok")
    values = [row["value"] for row in cb.cli_runner_choices()]
    assert "grok" in values and "cursor" in values and "kimi" in values
    assert len(values) == len(set(values))
    assert not cb.is_supported_cli_runner("opencode")

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
    out, n = cb._dispatch_cli_runner("cursor", "PROMPT_BODY", model="auto")
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
    out, n = cb._dispatch_cli_runner("kimi", "PROMPT_BODY", model="kimi-k2")
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd and cmd[cmd.index("-p") + 1] == "PROMPT_BODY"
    assert "--yolo" not in cmd and "-y" not in cmd and "--auto" not in cmd
    assert "-m" in cmd and cmd[cmd.index("-m") + 1] == "kimi-k2"

def test_run_grok_flags_effort_and_plain(monkeypatch):
    body = "GROK_OK"
    captured = _capture_run(monkeypatch, _P(stdout=body, stderr=""))
    out, n = cb._dispatch_cli_runner("grok", "PROMPT_BODY", model="grok-4.5", reasoning_strength="medium")
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
    out, n = cb._dispatch_cli_runner("pi", 
        "PROMPT_BODY", model="openai/gpt-4o", reasoning_strength="medium",
    )
    assert out == body and n == 1
    cmd = captured["cmd"]
    assert "-p" in cmd
    assert "--no-tools" in cmd  # #1456：禁内置工具，防 prompt 注入驱动 read/bash/edit/write
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "openai/gpt-4o"
    # pi --help：--thinking off|minimal|low|medium|high|xhigh|max；抽象 medium 直传
    assert "--thinking" in cmd and cmd[cmd.index("--thinking") + 1] == "medium"
    assert "PROMPT_BODY" in cmd  # positional prompt
    assert captured["kw"].get("input") in (None, "")  # not stdin


@pytest.mark.parametrize("runner", ["cursor", "kimi", "grok", "pi"])
def test_run_backend_for_config_dispatches_new_runners(monkeypatch, runner):
    from ming_sim.models import LLMConfig

    seen = {}

    def fake(prompt, model=None, reasoning_strength=None, **kw):
        seen["args"] = (prompt, model, reasoning_strength)
        return (f"{runner}-ok", 1)

    _patch_runner(monkeypatch, runner, fake)
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
def test_new_runner_fail_loud_on_bad_exit(monkeypatch, runner):
    from ming_sim.exceptions import LLMUnavailable

    _capture_run(monkeypatch, _RcProc(stderr="auth failed", returncode=1))
    with pytest.raises(LLMUnavailable) as ei:
        cb._dispatch_cli_runner(runner, "p")
    assert str(ei.value.code or "").startswith("llm_cli_")

# ── #1256 S2 gate LLM args / config / evidence ──

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

def test_add_gate_llm_args_uses_gate_cli_runners():
    import argparse
    p = argparse.ArgumentParser()
    cb.add_gate_llm_args(p)
    # illegal runner rejected; legal accepted
    with pytest.raises(SystemExit):
        p.parse_args(["--runner", "opencode", "--model", "m"])
    ns = p.parse_args(["--runner", "claude", "--model", "claude-opus-4-8", "--channel", "cli"])
    assert ns.runner == "claude" and ns.model == "claude-opus-4-8"


def test_resolve_cli_bin_found_on_current_path(monkeypatch):
    monkeypatch.setattr(
        cb.shutil, "which",
        lambda name, path=None: "/usr/local/bin/codex" if path is None else None,
    )
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(cb, "_CODEX_BIN", "codex")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == "/usr/local/bin/codex"



def test_resolve_cli_bin_found_via_extra_dirs_when_gui_path_bare(monkeypatch):
    monkeypatch.setattr(cb, "_EXTRA_BIN_DIRS", ["/fake/extra/bin"])
    monkeypatch.setattr(cb.os.path, "isdir", lambda p: True)
    home_bin = "/fake/extra/bin/codex"

    def fake_which(name, path=None):
        return home_bin if path and "/fake/extra/bin" in path else None

    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(cb, "_CODEX_BIN", "codex")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == home_bin



def test_resolve_cli_bin_login_shell_path_last_resort(monkeypatch):
    def fake_which(name, path=None):
        if path and "/opt/odd/bin" in path:
            return "/opt/odd/bin/codex"
        return None

    monkeypatch.setattr(cb.shutil, "which", fake_which)
    monkeypatch.setattr(cb, "_login_shell_path", lambda: "/opt/odd/bin")
    monkeypatch.setattr(cb, "_CODEX_BIN", "codex")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == "/opt/odd/bin/codex"



def test_resolve_cli_bin_falls_back_and_miss_not_cached(monkeypatch):
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(cb.shutil, "which", lambda name, path=None: None)
    monkeypatch.setattr(cb, "_CODEX_BIN", "codex")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == "codex"
    monkeypatch.setattr(
        cb.shutil, "which",
        lambda name, path=None: "/Users/x/.local/bin/codex" if path is None else None,
    )
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == "/Users/x/.local/bin/codex"



def test_login_shell_path_extracts_from_sentinels_despite_noise(monkeypatch):
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)

    probe = _P(stdout=(
        "Warning: /usr/local/bin not writable: skipping\n"
        "<<<CMRPATH>>>/Users/x/.local/bin:/opt/homebrew/bin:/usr/bin<<<ENDPATH>>>\n"
    ))
    monkeypatch.setattr(cb, "_RAW_RUN", lambda *a, **k: probe)
    monkeypatch.setattr(cb, "_CODEX_BIN", "codex")
    monkeypatch.setenv("PATH", "/bare/bin")
    monkeypatch.setattr(cb, "_EXTRA_BIN_DIRS", [])
    monkeypatch.setattr(cb.shutil, "which", lambda name, path=None:
        "/Users/x/.local/bin/codex" if path and "/Users/x/.local/bin" in path else None)
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == "/Users/x/.local/bin/codex"



def test_login_shell_path_single_dir_not_dropped(monkeypatch):
    monkeypatch.setattr(cb, "_DISCOVERED_LOGIN_PATH", None)

    probe = _P(stdout="<<<CMRPATH>>>/usr/bin<<<ENDPATH>>>\n")
    monkeypatch.setattr(cb, "_RAW_RUN", lambda *a, **k: probe)
    monkeypatch.setattr(cb, "_CODEX_BIN", "codex")
    monkeypatch.setenv("PATH", "/bare/bin")
    monkeypatch.setattr(cb, "_EXTRA_BIN_DIRS", [])
    monkeypatch.setattr(cb.shutil, "which", lambda name, path=None:
        "/usr/bin/codex" if path and "/usr/bin" in path else None)
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == "/usr/bin/codex"



def test_resolve_cli_bin_absolutizes_relative_result(monkeypatch):
    monkeypatch.setattr(cb, "_login_shell_path", lambda: None)
    monkeypatch.setattr(
        cb.shutil, "which",
        lambda name, path=None: "./bin/codex" if path is None else None,
    )
    monkeypatch.setattr(cb, "_CODEX_BIN", "./bin/codex")
    captured = _capture_run(monkeypatch)
    cb._dispatch_cli_runner("codex", "p")
    assert captured["cmd"][0] == cb.os.path.abspath("./bin/codex")


def test_run_agy_exit_zero_prose_is_not_connection_error(monkeypatch):
    """#1902 T2：退出码 0 的自由词面不得判连接错误（ADR 0142）；宿主缺口如实当正文。"""
    state = _agy_popen(monkeypatch, [("Authentication required", 0)])
    out, attempts = cb._dispatch_cli_runner("agy", "p")
    assert out == "Authentication required" and attempts == 1
    assert state["agy"] == 1
