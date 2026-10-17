from __future__ import annotations
from types import SimpleNamespace
import pytest
from agno.models.message import Message
import ming_sim.cli_backend as cb
from ming_sim.models import LLMConfig
from ming_sim.exceptions import LLMUnavailable
"""CLI backend contracts: public resolve/extract/runner seams (backend mocked).

#1185 wave2b: drop private helper unit pins; merge same-seam tracers; assert
typed/structural fields over free Chinese presentation copy. Runner subprocess
stays mocked (no real binary/LLM/network).
"""





def _cli_codex_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend", base_url="", model="api-fallback",
        channel="cli", cli_runner="codex", cli_model="gpt-5.5",
    )


# ── enrich_initiative_effects ──


# ── cli_backend_from_env / backend dispatch ──


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
            stdout_script=((spec.stdout,) if spec.stdout else ()),
            stderr_script=((spec.stderr,) if spec.stderr else ()),
            returncode=spec.returncode,
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
    assert captured["cmd"][mcp_at + 1] == '{"mcpServers":{}}'
    assert "--permission-mode" in captured["cmd"]
    assert "dontAsk" in captured["cmd"]
    assert "--disallowedTools" not in captured["cmd"]

@pytest.mark.parametrize("with_materials", [False, True])
def test_codex_popen_argv_env_and_materials_contract(monkeypatch, tmp_path, with_materials):
    """#1830 / #1827 / #1932 v5：Codex 真实入口结构化 argv、env、cwd。

    无推理档时 -c 参数对有且仅有 skills.include_instructions=false；env 不改写。
    材料路径保留 cwd 与只读旗；非材料路径不加材料专用旗。
    """
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    materials_dir = None
    root = None
    if with_materials:
        root = str((tmp_path / "materials").resolve())
        tmp_path.joinpath("materials").mkdir()
        materials_dir = root

    captured = _capture_run(monkeypatch, _P(stdout="ok"))
    out = cb.CliChat(
        id="cli-test", backend="codex", materials_dir=materials_dir,
    ).invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "ok"

    cmd = captured["cmd"]
    # 结构化收集 -c 参数对（值必须紧跟 -c；禁止裸值或错误配对）
    c_values = []
    i = 0
    while i < len(cmd):
        if cmd[i] == "-c":
            assert i + 1 < len(cmd), "-c missing value"
            c_values.append(cmd[i + 1])
            i += 2
            continue
        i += 1
    assert c_values == ["skills.include_instructions=false"]
    # 该值不得以非 -c 邻接形式出现
    for idx, tok in enumerate(cmd):
        if tok == "skills.include_instructions=false":
            assert idx > 0 and cmd[idx - 1] == "-c"

    assert captured["kw"].get("env") is None
    assert "--ephemeral" in cmd
    assert "--skip-git-repo-check" in cmd

    if with_materials:
        assert captured["kw"].get("cwd") == root
        assert "--ignore-user-config" in cmd
        assert "--sandbox" in cmd
        assert "read-only" in cmd
    else:
        # plain 路径 cwd 回落既有空沙箱（_AGY_CWD），与 #1932 无关；只禁材料专用旗。
        assert "--ignore-user-config" not in cmd
        assert "read-only" not in cmd


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


def test_run_claude_maps_reasoning_strength_to_thinking_tokens(monkeypatch):
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    captured = _capture_run(monkeypatch)
    out = cb.CliChat(id="cli-test", backend="claude", reasoning_strength="medium").invoke(
        [Message(role="user", content="p")], Message(role="assistant"),
    ).content
    assert out == "STDOUT_BODY"
    assert captured["kw"]["env"]["MAX_THINKING_TOKENS"] == "10000"


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



def test_clichat_call_cli_unknown_backend_raises():
    with pytest.raises(RuntimeError):
        cb.CliChat(id="m", backend="bogus").invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )

# ── agy 单次调用 / runner 失败分类（重试归 transport，runner 内无私有循环）──




def test_run_agy_nonzero_exit_is_terminal_and_runs_once(monkeypatch):
    """未知非零退出（无 typed status）= 确定性失败：不洗成瞬断、不私有重试。"""
    from tests.cli_process_doubles import install_fake_cli_runner

    script = install_fake_cli_runner(monkeypatch, [{"returncode": 1}])
    with pytest.raises(cb.subprocess.CalledProcessError) as caught:
        cb.CliChat(id="cli-test", backend="agy").invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )
    assert caught.value.returncode == 1
    assert len(script.processes) == 1

class _RcProc:
    pass

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
    with pytest.raises(cb.subprocess.CalledProcessError) as caught:
        cb.CliChat(id="cli-test", backend=runner).invoke(
            [Message(role="user", content="p")], Message(role="assistant"),
        )
    assert caught.value.returncode == 1
    assert caught.value.stderr == proc.stderr

def test_run_runner_empty_output_is_retryable_typed(monkeypatch):
    """rc=0 但零输出 = 可重试 typed 空输出（交 transport 再试），不是确定性失败。"""

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
        cb.CliChat(id="cli-test", backend="codex").invoke(
            [Message(role="user", content="任意提示")], Message(role="assistant"),
        )
    assert ei.value is injected
    assert len(recs) == 1
    # 可见诊断须能回溯到原故障来源，不是任意非空串
    assert recs[0].get("error") == str(injected)


# ── #1256 cursor / kimi / grok + #1274-qa-y1 pi runners ──

def test_public_cli_support(monkeypatch):
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import create_chat_model
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "opencode")
    with pytest.raises(LLMUnavailable):
        create_chat_model(LLMConfig(api_key="", base_url="", model="m", channel="cli", cli_runner="opencode"))







# ── #1256 S2 gate LLM args / config / evidence ──







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


def test_run_codex_stderr_banner_does_not_become_body(monkeypatch):
    """stdout 空时 stderr 日志／banner 不得冒充正文；走既有空输出失败契约。"""

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


def test_clichat_invoke_code_fault_traced_and_reraised(monkeypatch):
    """#1902：未知代码故障原样上浮，trace 仍记机器原文；不得套成 llm_cli_*。"""
    cc = cb.CliChat(id="cli-test", backend="agy")
    monkeypatch.setattr(cb.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(TypeError("cli down")))
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

    host = RuntimeError("cli down")
    typed = LLMUnavailable("typed host failure", code="llm_error", provider_message=str(host))
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
