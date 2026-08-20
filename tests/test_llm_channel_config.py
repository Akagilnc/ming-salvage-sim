from __future__ import annotations

import pytest
from agno.models.openai import OpenAIChat

from ming_sim import cli_backend
from ming_sim.cli_backend import CliChat
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_config import for_role, load_llm_config
from ming_sim import llm_model
from ming_sim.llm_model import create_chat_model, verify_llm_available
from ming_sim.models import LLMConfig


def test_create_chat_model_respects_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
    )

    model = create_chat_model(cfg)

    assert isinstance(model, OpenAIChat)
    assert not isinstance(model, CliChat)


def test_create_chat_model_uses_cli_channel_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="",  # CLI 通道 LLMConfig.api_key 永空；占位符在此构造时才注入
        base_url="",
        model="api-fallback-model",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
        reasoning_strength="high",
    )

    model = create_chat_model(cfg)

    assert isinstance(model, CliChat)
    assert model.backend == "codex"
    assert model.id == "gpt-5.5"
    assert model.timeout == 240
    assert model.reasoning_strength == "high"
    # 空 CLI key 也能构造：占位符在构造时注入以满足 OpenAIChat 父类。
    assert model.api_key == "cli-backend"


def test_load_llm_config_records_backend_env_as_cli_channel(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.setenv("MING_SIM_CODEX_MODEL", "gpt-codex-test")

    cfg = load_llm_config("https://api.example.com", "api-fallback", api_key="")

    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "gpt-codex-test"
    assert cfg.api_key == ""


def test_loaded_api_config_is_not_rerouted_by_later_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = load_llm_config("https://api.example.com", "gpt-test", api_key="sk-test")

    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    model = create_chat_model(cfg)

    assert cfg.channel == "api"
    assert isinstance(model, OpenAIChat)
    assert not isinstance(model, CliChat)


def test_load_llm_config_migrates_legacy_advanced_thinking_to_reasoning(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_REASONING_STRENGTH", raising=False)

    cfg = load_llm_config(
        "https://api.example.com",
        "gpt-test",
        api_key="sk-test",
        advanced_model="gpt-5.5",
        advanced_thinking_level="high",
    )
    advanced = for_role(cfg, "simulator")

    assert cfg.advanced_thinking_level == ""
    assert cfg.reasoning_strength == "high"
    assert advanced.reasoning_strength == "high"
    assert advanced.thinking_level == ""


def test_load_llm_config_migrates_legacy_none_thinking_to_off(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_REASONING_STRENGTH", raising=False)

    cfg = load_llm_config(
        "https://api.example.com",
        "gpt-5.5",
        api_key="sk-test",
        thinking_level="none",
    )

    assert cfg.reasoning_strength == "off"


def test_create_chat_model_maps_off_reasoning_to_openai_none(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-5.5",
        channel="api",
        thinking_level="high",
        reasoning_strength="off",
    )

    model = create_chat_model(cfg)

    assert model.reasoning_effort == "none"


def test_create_chat_model_off_reasoning_uses_none_for_gpt56_not_version_list(monkeypatch):
    """#1452：关思考档不得靠 gpt-5.1/5.2/5.4/5.5 盯文枚举——gpt-5.6 掉表外会落到 minimal。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://opencode.ai/zen/go/v1",
        model="gpt-5.6-luna",
        channel="api",
        reasoning_strength="off",
    )

    model = create_chat_model(cfg)

    assert model.reasoning_effort == "none"


def test_create_chat_model_off_reasoning_keeps_minimal_for_legacy_o1(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="o1-mini",
        channel="api",
        reasoning_strength="off",
    )

    model = create_chat_model(cfg)

    assert model.reasoning_effort == "minimal"


def test_create_chat_model_omits_max_tokens_when_unconfigured(monkeypatch):
    """未显式配置 max_tokens → 构造 kwargs 不含该键（取官方上限，不灌注 8000）。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    captured: list = []
    real = llm_model.OpenAIChat

    def spy(*args, **kwargs):
        captured.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(llm_model, "OpenAIChat", spy)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
    )
    assert cfg.max_tokens is None

    create_chat_model(cfg)
    create_chat_model(cfg, max_tokens=None)
    create_chat_model(cfg, max_tokens=0)

    assert len(captured) == 3
    for kwargs in captured:
        assert "max_tokens" not in kwargs


def test_create_chat_model_sends_max_tokens_when_explicit(monkeypatch):
    """显式 max_tokens>0 → kwargs 照发。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    captured: dict = {}
    real = llm_model.OpenAIChat

    def spy(*args, **kwargs):
        captured["kwargs"] = kwargs
        return real(*args, **kwargs)

    monkeypatch.setattr(llm_model, "OpenAIChat", spy)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
        max_tokens=4096,
    )

    model = create_chat_model(cfg, max_tokens=cfg.max_tokens)

    assert captured["kwargs"]["max_tokens"] == 4096
    assert model.max_tokens == 4096


def test_create_chat_model_strips_top_p_for_openai_reasoning_family(monkeypatch):
    """#1452：luna/gpt-5 推理族拒 top_p（HTTP 400 空 assistant → agno Unknown model error）。
    召对 registry 固定传 top_p=0.9，工厂必须剥离，temperature 可保留。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://opencode.ai/zen/go/v1",
        model="gpt-5.6-luna",
        channel="api",
    )

    model = create_chat_model(cfg, temperature=0.6, top_p=0.9, max_tokens=8000)

    assert model.temperature == 0.6
    assert model.max_tokens == 8000
    assert getattr(model, "top_p", None) is None
    # request 层同样不得带 top_p
    params = model.get_request_params()
    assert "top_p" not in params
    assert params.get("temperature") == 0.6


def test_create_chat_model_keeps_top_p_for_non_reasoning_api_models(monkeypatch):
    """#1452 零回归：glm/qwen 等非 OpenAI 推理族仍吃 top_p。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        channel="api",
    )

    model = create_chat_model(cfg, temperature=0.6, top_p=0.9)

    assert model.top_p == 0.9
    assert model.get_request_params().get("top_p") == 0.9


def test_create_chat_model_leaves_openai_reasoning_default_unset(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-5.5",
        channel="api",
    )

    model = create_chat_model(cfg, enable_thinking=False)

    assert getattr(model, "reasoning_effort", None) in ("", None)


def test_create_chat_model_maps_reasoning_strength_to_dashscope_thinking_budget(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        channel="api",
        reasoning_strength="medium",
    )

    model = create_chat_model(cfg, enable_thinking=False)

    assert model.extra_body == {"enable_thinking": True, "thinking_budget": 10000}


def test_create_chat_model_maps_reasoning_strength_to_minimax_thinking(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.minimaxi.com/v1",
        model="minimax-test",
        channel="api",
        reasoning_strength="off",
    )

    model = create_chat_model(cfg, enable_thinking=True)

    assert model.extra_body == {"thinking": {"type": "disabled"}, "reasoning_split": True}


def test_minimax_reasoning_strength_overrides_stale_thinking_level(monkeypatch):
    """#358 cmr: 统一推理强度选档（低/中/高）对 minimax 须直接映射 adaptive，不被遗留
    thinking_level=disabled 这个隐藏旋钮压回 disabled。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.minimaxi.com/v1",
        model="minimax-test",
        channel="api",
        thinking_level="disabled",
        reasoning_strength="medium",
    )

    model = create_chat_model(cfg, enable_thinking=False)

    assert model.extra_body == {"thinking": {"type": "adaptive"}, "reasoning_split": True}


def test_legacy_backend_env_uses_runner_default_model_not_api_model(monkeypatch):
    captured = {}

    class Proc:
        stdout = "臣领旨。"
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Proc()

    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    monkeypatch.delenv("MING_SIM_CODEX_REASONING", raising=False)
    monkeypatch.setattr(cli_backend.subprocess, "run", fake_run)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="deepseek-v4-flash",
    )

    model = create_chat_model(cfg)
    model._call_cli("p")

    assert isinstance(model, CliChat)
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == cli_backend._CODEX_MODEL


def test_verify_llm_available_respects_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["model"] = kwargs["model"]

        def run(self, prompt: str) -> str:
            captured["prompt"] = prompt
            return "ok"

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    monkeypatch.setattr(llm_model, "extract_agent_text", lambda output: output)
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-test",
        channel="api",
    )

    verify_llm_available(cfg)

    assert captured["prompt"] == "输出 ok"
    assert not isinstance(captured["model"], CliChat)


def test_verify_llm_available_smokes_cli_channel_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    seen = {}

    def fake_run(prompt, llm_config=None, tag=""):
        seen["prompt"] = prompt
        seen["config"] = llm_config
        return "ok", 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", fake_run)
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    verify_llm_available(cfg)

    assert seen["prompt"] == "输出 ok"
    assert seen["config"] is cfg


def test_verify_llm_available_cli_channel_failure_raises(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def boom(prompt, llm_config=None, tag=""):
        raise RuntimeError("codex missing")

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", boom)
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    with pytest.raises(LLMUnavailable):
        verify_llm_available(cfg)


def test_verify_llm_available_smokes_legacy_env_only_backend(monkeypatch):
    """legacy env-only 路径（无显式 channel + MING_SIM_LLM_BACKEND 设置）现在也真实 smoke
    （旧版直接 return 跳过）：触发 _run_backend_for_config，失败抛 LLMUnavailable，
    避免 fresh-start 在 runner 缺失时先删主库。"""
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = {}

    def fake_run(prompt, llm_config=None, tag=""):
        seen["prompt"] = prompt
        return "ok", 1

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", fake_run)
    cfg = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback", channel="")
    verify_llm_available(cfg)
    assert seen["prompt"] == "输出 ok"


def test_verify_llm_available_legacy_env_only_failure_raises(monkeypatch):
    """legacy env-only smoke 失败同样抛 LLMUnavailable（fail-fast，不静默放行）。"""
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")

    def boom(prompt, llm_config=None, tag=""):
        raise RuntimeError("agy missing")

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", boom)
    cfg = LLMConfig(api_key="cli-backend", base_url="", model="api-fallback", channel="")
    with pytest.raises(LLMUnavailable):
        verify_llm_available(cfg)


def _api_cfg(**overrides) -> LLMConfig:
    base = dict(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-5.6-luna",
        channel="api",
    )
    base.update(overrides)
    return LLMConfig(**base)


def test_verify_llm_available_api_smoke_uses_relaxed_token_budget(monkeypatch):
    """API 烟测不得用 8 token 掐死推理模型；一次校验成本可忽略，预算须够思考+短回。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["model"] = kwargs["model"]

        def run(self, prompt: str) -> str:
            return "ok"

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    monkeypatch.setattr(llm_model, "extract_agent_text", lambda output: output)
    verify_llm_available(_api_cfg())
    assert captured["model"].max_tokens >= 512


def test_verify_llm_available_api_empty_content_passes(monkeypatch):
    """推理模型思考耗尽回空 content：调用成功即过，空文不作失败。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    class EmptyOutput:
        content = ""
        status = None

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt: str) -> EmptyOutput:
            return EmptyOutput()

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    # 走真实 extract_agent_text：空 content 不得误杀
    verify_llm_available(_api_cfg())


def test_verify_llm_available_api_empty_content_none_passes(monkeypatch):
    """content=None 同空串：烟测不校验返回内容。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    class NoneContent:
        content = None
        status = None

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt: str) -> NoneContent:
            return NoneContent()

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    verify_llm_available(_api_cfg())


def test_verify_llm_available_api_empty_content_error_status_passes(monkeypatch):
    """extract_agent_text 若因空文+ERROR status 抛错，烟测路须捕之判过。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    class EmptyErrorOutput:
        content = ""
        status = "ERROR"

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt: str) -> EmptyErrorOutput:
            return EmptyErrorOutput()

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    verify_llm_available(_api_cfg())


def test_verify_llm_available_api_http_401_still_raises(monkeypatch):
    """真错：HTTP 401 仍须报 LLMUnavailable。"""
    import httpx
    from openai import APIStatusError

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    resp = httpx.Response(
        401,
        json={"error": {"message": "Invalid API key", "code": "invalid_api_key"}},
        request=req,
    )

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt: str):
            raise APIStatusError("Invalid API key", response=resp, body=None)

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    with pytest.raises(LLMUnavailable) as ei:
        verify_llm_available(_api_cfg())
    assert ei.value.status_code == 401


def test_verify_llm_available_api_timeout_still_raises(monkeypatch):
    """真错：超时仍须报。"""
    import httpx
    from openai import APITimeoutError

    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    req = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt: str):
            raise APITimeoutError(request=req)

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    with pytest.raises(LLMUnavailable) as ei:
        verify_llm_available(_api_cfg())
    assert ei.value.code == "llm_timeout"


def test_verify_llm_available_api_error_status_nonempty_content_raises(monkeypatch):
    """真错：生产 agno 形 status=ERROR 且 content 非空错误串，走真实 extract_agent_text，须报 llm_run_error。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    class ErrorOutput:
        content = "Invalid API key"
        status = "ERROR"

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, prompt: str) -> ErrorOutput:
            return ErrorOutput()

    monkeypatch.setattr(llm_model, "Agent", FakeAgent)
    # 不 stub extract_agent_text：咬住内层非空再抛
    with pytest.raises(LLMUnavailable) as ei:
        verify_llm_available(_api_cfg())
    assert ei.value.code == "llm_run_error"


def test_for_role_preserves_cli_channel_fields_for_advanced_roles():
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="https://api.example.com/v1",
        model="api-model",
        advanced_model="api-advanced",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    derived = for_role(cfg, "simulator")

    assert derived.channel == "cli"
    assert derived.cli_runner == "codex"
    assert derived.cli_model == "gpt-5.5"
    assert derived.cli_timeout_seconds == 240


def test_config_constants_single_source_in_models():
    """SSOT 接线（#58/#60）：channel/model/timeout 默认常量的 canonical 定义在 models，
    llm_config / cli_backend 旧址只是 re-export（同一对象），LLMConfig 默认值即引用这些常量——
    防未来在第二处重写字面量漂移。max_tokens 已取消默认灌注（None=不发/官方上限）。"""
    import ming_sim.models as m
    import ming_sim.llm_config as lc
    import ming_sim.cli_backend as cb
    from ming_sim.models import LLMConfig
    # re-export 同一对象（不是各写一份字面量）
    assert lc.CLI_DEFAULT_TIMEOUT_SECONDS is m.CLI_DEFAULT_TIMEOUT_SECONDS
    assert lc.VALID_CHANNELS is m.VALID_CHANNELS
    assert lc.CODEX_DEFAULT_MODEL is m.CODEX_DEFAULT_MODEL
    assert cb.CODEX_DEFAULT_MODEL is m.CODEX_DEFAULT_MODEL
    assert cb.CLAUDE_DEFAULT_MODEL is m.CLAUDE_DEFAULT_MODEL
    assert not hasattr(m, "API_DEFAULT_MAX_TOKENS")
    assert not hasattr(lc, "API_DEFAULT_MAX_TOKENS")
    assert lc.API_DEFAULT_TIMEOUT_SECONDS is m.API_DEFAULT_TIMEOUT_SECONDS
    # LLMConfig 默认值 == 常量（dataclass 默认引用 SSOT，非裸字面量）
    cfg = LLMConfig(api_key="", base_url="", model="m")
    assert cfg.max_tokens is None
    assert cfg.timeout_seconds == m.API_DEFAULT_TIMEOUT_SECONDS
    assert cfg.cli_timeout_seconds == m.CLI_DEFAULT_TIMEOUT_SECONDS


def test_load_llm_config_cli_env_uses_cli_default_timeout_not_api(monkeypatch):
    """codex R1 #2：legacy env CLI（MING_SIM_LLM_BACKEND 设）时 cli_timeout_seconds 必须用
    CLI 默认（300），不沿用 API 的 timeout_seconds（180）——后者会被当 CLI 子进程超时上限。"""
    from ming_sim.llm_config import load_llm_config, CLI_DEFAULT_TIMEOUT_SECONDS
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    cfg = load_llm_config(base_url="", model="m", api_key="", timeout_seconds=180.0)
    assert cfg.channel == "cli"
    assert cfg.cli_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS == 300.0
    assert cfg.cli_timeout_seconds != 180.0


def test_web_runtime_cli_no_saved_timeout_uses_cli_default(monkeypatch):
    """codex R1 #3：web env CLI 无 saved cli.timeout_seconds 时回落 CLI 默认（300），
    不回落 API request timeout（180）。"""
    import web_app
    from ming_sim.llm_config import CLI_DEFAULT_TIMEOUT_SECONDS
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "codex")
    cfg = web_app._llm_config_from_runtime(
        {"channel": "cli", "cli": {"runner": "codex", "model": "gpt-5.5"}},
        base_url="", model="m", api_key="", max_tokens=8000, timeout_seconds=180.0,
        thinking_level="", advanced_model="", advanced_base_url="",
        advanced_api_key="", advanced_thinking_level="",
    )
    assert cfg.channel == "cli"
    assert cfg.cli_timeout_seconds == CLI_DEFAULT_TIMEOUT_SECONDS == 300.0
    assert cfg.cli_timeout_seconds != 180.0


def test_for_role_advanced_empty_cli_model_no_api_model_leak(monkeypatch):
    """#52 核查:CLI 通道 + advanced 角色(simulator)+ cli_model 空时,for_role 把
    advanced_model 放进 model,但 create_chat_model(唯一 CliChat 工厂)不得把它当 --model
    漏给 runner——回落 runner 默认。RT2 已在单一工厂修,此为 for_role/advanced 路径回归钉。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_CODEX_MODEL", raising=False)
    cfg = LLMConfig(
        api_key="cli-backend", base_url="", model="api-main",
        channel="cli", cli_runner="codex", cli_model="",
        advanced_model="api-advanced",
    )
    derived = for_role(cfg, "simulator")
    assert derived.model == "api-advanced"   # for_role 已把 advanced_model 放进 model
    assert derived.cli_model == ""           # cli_model 仍空
    chat = create_chat_model(derived)
    assert chat.id == "gpt-5.5"              # runner 默认,不是 api-advanced
    assert chat.id != "api-advanced"


def test_cli_empty_cli_model_does_not_leak_api_model_to_runner(monkeypatch):
    """RT2(Red Team)：channel=cli + cli_model 空时，不许把 API model 名（llm_config.model）
    当 --model 漏给 codex/claude——回落到 runner 默认（codex→gpt-5.5、claude→默认、agy 无
    --model 故非 API 名即可）。覆盖 #52 同类的 for_role/advanced 触发路径。"""
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("MING_SIM_CODEX_MODEL", raising=False)
    monkeypatch.delenv("MING_SIM_CLAUDE_MODEL", raising=False)

    def _cli(runner: str) -> CliChat:
        return create_chat_model(LLMConfig(
            api_key="cli-backend", base_url="", model="api-fallback-model",
            channel="cli", cli_runner=runner, cli_model="",
        ))

    m_codex = _cli("codex")
    assert m_codex.id == "gpt-5.5"
    assert m_codex.id != "api-fallback-model"

    m_claude = _cli("claude")
    assert m_claude.id == "claude-opus-4-8"
    assert m_claude.id != "api-fallback-model"

    m_agy = _cli("agy")
    assert m_agy.id != "api-fallback-model"   # agy 无 --model，空 id 即可，关键是不漏 API 名


# --- #1271 S1: cli_supports_reasoning_strength 单源委派 ---

@pytest.mark.parametrize(
    "runner,expected",
    [
        ("codex", True),
        ("claude", True),
        ("grok", True),
        ("pi", True),  # #1274-qa-y1：pi --thinking / model:<thinking>
        ("agy", False),
        ("kimi", False),
        ("cursor", False),
        ("", False),
        ("CODEX", True),  # 大小写归一
        (" Grok ", True),
    ],
)
def test_cli_supports_reasoning_strength_matrix(runner, expected):
    """#1271/#1274-y1：能力名单含 grok/pi；agy/kimi/cursor 仍 False；codex/claude 不变。"""
    from ming_sim.llm_config import cli_supports_reasoning_strength

    assert cli_supports_reasoning_strength(runner) is expected


def test_cli_reasoning_strength_runners_single_source_in_cli_backend():
    """#1271：能力名单单源在 cli_backend（与 effort/thinking 表同缝），禁第二处手写。"""
    from ming_sim.cli_backend import CLI_REASONING_STRENGTH_RUNNERS

    assert CLI_REASONING_STRENGTH_RUNNERS == frozenset({"codex", "claude", "grok", "pi"})
    # 谓词委派同一 frozenset，不是 llm_config 内另写字面量集合
    from ming_sim.llm_config import cli_supports_reasoning_strength
    import inspect

    src = inspect.getsource(cli_supports_reasoning_strength)
    assert "CLI_REASONING_STRENGTH_RUNNERS" in src
    assert '{"codex"' not in src and "{'codex'" not in src
