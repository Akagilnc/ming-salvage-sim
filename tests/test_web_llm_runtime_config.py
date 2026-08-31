from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import web_app
from ming_sim.models import LLMConfig
from tests.http_test_support import run_to_terminal


def test_runtime_cli_slot_builds_cli_llm_config_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    runtime = {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240", "reasoning_strength": "low"},
    }

    cfg = web_app._llm_config_from_runtime(
        runtime,
        base_url="https://api.example.com/v1",
        model="gpt-api",
        api_key="",
        timeout_seconds=180,
        thinking_level="",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )

    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "gpt-5.5"
    assert cfg.cli_timeout_seconds == 240
    assert cfg.reasoning_strength == "low"
    assert cfg.api_key == ""  # CLI 通道 LLMConfig.api_key 永空（占位符只在构造 CliChat 时注入）


def test_advanced_llm_verification_preserves_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    monkeypatch.setattr(web_app, "verify_llm_available", lambda cfg: seen.append(cfg))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        advanced_model="gpt-advanced",
        channel="api",
    )

    web_app._verify_llm_configs_or_raise(cfg)

    assert [item.channel for item in seen] == ["api", "api"]


def test_advanced_llm_verification_preserves_reasoning_strength(monkeypatch):
    seen = []
    monkeypatch.setattr(web_app, "verify_llm_available", lambda cfg: seen.append(cfg))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-main",
        advanced_model="gpt-advanced",
        channel="api",
        reasoning_strength="high",
        advanced_thinking_level="minimal",
    )

    web_app._verify_llm_configs_or_raise(cfg)

    assert [item.reasoning_strength for item in seen] == ["high", "high"]
    assert seen[1].thinking_level == ""


def test_runtime_api_reasoning_strength_builds_llm_config(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    runtime = {
        "channel": "api",
        "reasoning_strength": "high",
        "api": {"base_url": "https://api.example.com/v1", "model": "gpt-5", "api_key": "sk-test"},
        "cli": {"runner": "", "model": "", "timeout_seconds": ""},
    }

    cfg = web_app._llm_config_from_runtime(
        runtime,
        base_url="https://api.example.com/v1",
        model="gpt-5",
        api_key="sk-test",
        timeout_seconds=180,
        thinking_level="",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )

    assert cfg.channel == "api"
    assert cfg.reasoning_strength == "high"


def test_runtime_env_legacy_advanced_thinking_builds_reasoning_strength(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    cfg = web_app._llm_config_from_runtime(
        {},
        base_url="https://api.example.com/v1",
        model="gpt-main",
        api_key="sk-test",
        timeout_seconds=180,
        thinking_level="",
        advanced_model="gpt-5.5",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="high",
    )

    assert cfg.channel == "api"
    assert cfg.advanced_thinking_level == ""
    assert cfg.reasoning_strength == "high"


def test_build_llm_config_switches_to_api_on_real_key_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))
    current = LLMConfig(
        api_key="cli-backend",
        base_url="https://old.example.com/v1",
        model="old-model",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-cli",
        cli_timeout_seconds=240,
    )
    fake = SimpleNamespace(
        session=SimpleNamespace(
            llm_config=current,
            begin_turn=lambda: None,
        )
    )

    # apply = build → verify → commit（#56 拆分后等价分步）。填了真实 key=切 api（#51）。
    cfg = web_app.WebGame.build_llm_config(
        fake,
        "https://api.example.com",
        "gpt-api",
        "sk-test",
        timeout_seconds=90,
        thinking_level="medium",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )
    web_app._verify_llm_configs_or_raise(cfg)
    web_app.WebGame.commit_llm_config(fake, cfg)

    assert cfg.channel == "api"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "gpt-cli"
    assert seen[0].channel == "api"
    assert fake.session.llm_config.channel == "api"
    assert saved
    assert saved[0][1]["channel"] == "api"
    assert saved[0][1]["cli_runner"] == "codex"
    assert saved[0][1]["cli_model"] == "gpt-cli"
    assert saved[0][1]["cli_timeout_seconds"] == 240


def test_build_llm_config_recovers_preserved_api_key_on_switch_back(monkeypatch):
    """Gemini R1:从 cli 显式切回 api、表单 key 留空时,从 runtime_llm.json 的 api 槽回收被保留的
    真实 key(cur.api_key 在 cli 模式已归一为空),免得切回 api 还得重输。"""
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {"api": {"api_key": "sk-preserved"}})
    current = LLMConfig(api_key="", base_url="https://x/v1", model="m", channel="cli",
                        cli_runner="codex", cli_model="gpt-5.5")
    fake = SimpleNamespace(session=SimpleNamespace(llm_config=current, begin_turn=lambda: None))

    cfg = web_app.WebGame.build_llm_config(fake, "", "", "", channel="api")

    assert cfg.channel == "api"
    assert cfg.api_key == "sk-preserved"


def test_set_llm_config_cli_placeholder_not_real_api_key(monkeypatch):
    # 游戏内 POST /api/llm/config：CLI 通道的占位符 cli-backend 不应回报为真实 key。
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="gpt-5.5",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
    )
    # api_set_llm_config 改为 build→verify(offload)→commit 分步（#56）：fake 提供新两法。
    fake = SimpleNamespace(
        build_llm_config=lambda *a, **k: cfg,
        commit_llm_config=lambda c: c,
    )
    monkeypatch.setattr(web_app, "get_game", lambda: fake)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)

    result = asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(
        base_url="",
        model="gpt-5.5",
        api_key="",
    )))

    assert result["has_api_key"] is False
    assert result["channel"] == "cli"


def test_api_set_llm_config_response_reports_reasoning_capability(monkeypatch):
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        channel="api",
    )
    fake = SimpleNamespace(
        build_llm_config=lambda *a, **k: cfg,
        commit_llm_config=lambda c: c,
    )
    monkeypatch.setattr(web_app, "get_game", lambda: fake)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)

    result = asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key="sk-test",
    )))

    assert result["reasoning_supported"] is False
    assert result["reasoning_strengths"] == list(web_app.REASONING_STRENGTH_CHOICES)


def test_api_set_llm_config_explicit_cli_channel_switch(monkeypatch):
    """#51:in-game 显式选 CLI 通道(channel=cli + cli_runner)→ build 收到 cli 通道参数,
    回报 cli 配置(不要求 API key)。"""
    built = {}

    def fake_build(*a, **k):
        built.update(k)
        return LLMConfig(api_key="", base_url="", model="api-fallback",
                         channel="cli", cli_runner="agy", cli_model="", cli_timeout_seconds=240,
                         reasoning_strength=k.get("reasoning_strength") or "")

    fake = SimpleNamespace(build_llm_config=fake_build, commit_llm_config=lambda c: c)
    monkeypatch.setattr(web_app, "get_game", lambda: fake)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)

    result = asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(
        channel="cli", cli_runner="agy", cli_timeout_seconds=240, reasoning_strength="off",
    )))

    assert built["channel"] == "cli"          # "__keep__"→None 之外的值原样传给 build
    assert built["cli_runner"] == "agy"
    assert built["reasoning_strength"] == "off"
    assert result["channel"] == "cli"
    assert result["cli_runner"] == "agy"
    assert result["reasoning_strength"] == "off"
    assert result["reasoning_supported"] is False
    assert result["reasoning_strengths"] == list(web_app.REASONING_STRENGTH_CHOICES)
    assert result["has_api_key"] is False


def test_api_set_llm_config_keep_sentinels_pass_none_to_build(monkeypatch):
    """Sourcery:channel/cli_runner/cli_model 缺省 "__keep__" → 映射 None 传给 build(保留当前),
    不被当作字面值「__keep__」覆盖通道。"""
    built = {}

    def fake_build(*a, **k):
        built.update(k)
        return LLMConfig(api_key="sk", base_url="https://x/v1", model="m", channel="api")

    fake = SimpleNamespace(build_llm_config=fake_build, commit_llm_config=lambda c: c)
    monkeypatch.setattr(web_app, "get_game", lambda: fake)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)

    asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest()))  # 全默认 = __keep__

    assert built["channel"] is None
    assert built["cli_runner"] is None
    assert built["cli_model"] is None


def test_commit_cli_seeds_api_slot_from_session_when_slot_empty(monkeypatch):
    """CMR R2(codex):切到 cli 时 api 槽空但当前 session 有真实 key(可能来自 OPENAI_API_KEY env),
    commit 须把它写进 api 槽,否则 api→cli→api 往返丢 key。"""
    saved_args = []
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})   # 无已存 api 槽
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: saved_args.append((a, k)))
    prev = LLMConfig(
        api_key="sk-env", base_url="https://x/v1", model="m", channel="api",
        reasoning_strength="high",
    )
    new_cli = LLMConfig(api_key="", base_url="https://x/v1", model="m", channel="cli",
                        cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240,
                        reasoning_strength="off")
    fake = SimpleNamespace(session=SimpleNamespace(llm_config=prev, begin_turn=lambda: None))

    web_app.WebGame.commit_llm_config(fake, new_cli)

    args, kw = saved_args[0]
    assert kw["channel"] == "cli"
    assert kw["reasoning_strength"] == "off"
    assert kw["api_reasoning_strength"] == "high"
    assert args[2] == "sk-env"   # api_key 位参写进 api 槽,不是空


def test_commit_cli_preserves_when_slot_already_has_key(monkeypatch):
    """槽里已有真实 key 时,commit 传空 api 输入走 preserve_api(不重写)。"""
    saved_args = []
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {"api": {"api_key": "sk-slot"}})
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: saved_args.append((a, k)))
    prev = LLMConfig(api_key="", base_url="", model="m", channel="cli", cli_runner="codex", cli_model="gpt-5.5")
    new_cli = LLMConfig(api_key="", base_url="", model="m", channel="cli",
                        cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240)
    fake = SimpleNamespace(session=SimpleNamespace(llm_config=prev, begin_turn=lambda: None))

    web_app.WebGame.commit_llm_config(fake, new_cli)

    args, kw = saved_args[0]
    assert args[:3] == ("", "", "")   # 传空 → preserve_api 保留 sk-slot
    assert kw["channel"] == "cli"


def test_api_set_llm_config_commit_runs_on_event_loop(monkeypatch):
    """CMR R5 后回退:commit(改 session 态)**留在 event loop 主线程**同步跑——单人 CLI 串行探针
    下原子无 race,避免 offload-to-thread 引入的并发/断连边缘(见 CMR R3-R5)。verify 仍 offload。"""
    import threading
    cfg = LLMConfig(api_key="", base_url="", model="m", channel="cli",
                    cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240)
    seen = {}

    def rec_commit(c):
        seen["thread"] = threading.current_thread()

    def rec_verify(c):
        seen["verify_thread"] = threading.current_thread()

    fake = SimpleNamespace(build_llm_config=lambda *a, **k: cfg, commit_llm_config=rec_commit)
    monkeypatch.setattr(web_app, "get_game", lambda: fake)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", rec_verify)

    asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(channel="cli", cli_runner="codex")))

    assert seen["thread"] is threading.main_thread()        # commit 在主线程(on loop)
    assert seen["verify_thread"] is not threading.main_thread()  # verify 仍 offload 到线程池


def test_api_set_llm_config_verify_runs_off_event_loop(monkeypatch):
    """#56:in-game /api/llm/config 的 verify(CLI smoke ~12s)offload 出 asyncio event loop,
    commit(落盘/重建)留在 loop。断言 verify 在非主线程跑。"""
    import threading
    cfg = LLMConfig(api_key="", base_url="", model="m", channel="cli",
                    cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240)
    seen = {}
    fake = SimpleNamespace(build_llm_config=lambda *a, **k: cfg, commit_llm_config=lambda c: c)
    monkeypatch.setattr(web_app, "get_game", lambda: fake)

    def rec_verify(c):
        seen["thread"] = threading.current_thread()

    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", rec_verify)

    asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(channel="cli", cli_runner="codex")))

    assert seen.get("thread") is not None
    assert seen["thread"] is not threading.main_thread()


def test_api_set_llm_config_verify_failure_skips_commit_and_passes_through_httpexception(monkeypatch):
    """#56 负路径:_verify_llm_configs_or_raise 真实抛的是已包好 detail 的 HTTPException(经
    run_in_executor 透传)。端点须原样抛(不被 except Exception 二次包裹 mangle,Gemini R2),
    且绝不 commit(不落盘/不改 session)。"""
    cfg = LLMConfig(api_key="", base_url="", model="m", channel="cli",
                    cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240)
    commit_calls = []
    fake = SimpleNamespace(
        build_llm_config=lambda *a, **k: cfg,
        commit_llm_config=lambda c: commit_calls.append(c),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: fake)

    sentinel_detail = {"code": "llm_unavailable", "message": "主模型连通性检查失败：runner missing"}

    def boom(c):
        raise web_app.HTTPException(status_code=400, detail=sentinel_detail)

    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", boom)

    with pytest.raises(web_app.HTTPException) as ei:
        asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(channel="cli", cli_runner="codex")))
    assert ei.value.status_code == 400
    assert ei.value.detail == sentinel_detail   # 原样透传,未被二次包裹
    assert commit_calls == []                    # verify 失败 → commit 从未被调


def test_menu_status_active_cli_unsupported_runner_not_ready_despite_preserved_api_key(monkeypatch):
    # ADR 0001: 切到 CLI 时 API 槽被保留。readiness 必须按 active channel 判，
    # 不能因 inactive API 槽里有真实 key 就把不可用的 CLI runner 误报成 ready。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "https://api.example.com/v1", "model": "gpt-api", "api_key": "sk-real-key"},
        "cli": {"runner": "bogus", "model": "gpt-5.5", "timeout_seconds": "240"},
        # 顶层别名暴露 API 槽（_normalize_runtime_llm 行为）。
        "base_url": "https://api.example.com/v1",
        "model": "gpt-api",
        "api_key": "sk-real-key",
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["llm"]["channel"] == "cli"
    assert status["llm"]["cli_runner"] == "bogus"
    # active channel = cli + 不受支持 runner → 不 ready，哪怕 API 槽留着真实 key。
    assert status["llm_ready"] is False


def test_menu_status_active_cli_placeholder_api_key_not_counted(monkeypatch):
    # 占位符 cli-backend 不应被当成真实 API key。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": "cli-backend"},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
        "api_key": "cli-backend",
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["has_api_key"] is False
    assert status["llm"]["has_api_key"] is False
    # CLI runner 受支持 → ready（靠 runner，不靠占位符）。
    assert status["llm_ready"] is True


def test_menu_status_reports_reasoning_strength_capability_for_cli_runner(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "agy", "model": "", "timeout_seconds": "240", "reasoning_strength": "high"},
        "reasoning_strength": "high",
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["llm"]["reasoning_strength"] == "high"
    assert status["llm"]["cli_reasoning_strength"] == "high"
    assert status["llm"]["reasoning_supported"] is False
    assert "reasoning_strengths" in status["llm"]


def test_menu_status_reports_inactive_cli_reasoning_strength(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "reasoning_strength": "low",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-5",
            "api_key": "sk-test",
            "reasoning_strength": "low",
        },
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240", "reasoning_strength": "high"},
        "base_url": "https://api.example.com/v1",
        "model": "gpt-5",
        "api_key": "sk-test",
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["llm"]["reasoning_strength"] == "low"
    assert status["llm"]["api_reasoning_strength"] == "low"
    assert status["llm"]["cli_reasoning_strength"] == "high"


def test_menu_status_uses_advanced_model_for_api_reasoning_capability(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-test",
        "advanced_base_url": "https://api.example.com/v1",
        "advanced_model": "gpt-5",
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["llm"]["reasoning_supported"] is True


def test_menu_save_llm_persists_cli_channel_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    result = asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="",
        model="",
        api_key="",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
        reasoning_strength="low",
    )))

    assert result["ok"] is True
    assert result["llm"]["channel"] == "cli"
    assert result["llm"]["cli_runner"] == "codex"
    assert result["llm"]["cli_model"] == "gpt-5.5"
    assert result["llm"]["reasoning_strength"] == "low"
    assert result["llm"]["has_api_key"] is False
    assert seen and seen[0].channel == "cli"
    assert seen[0].cli_runner == "codex"
    assert seen[0].cli_model == "gpt-5.5"
    assert seen[0].reasoning_strength == "low"
    assert saved and saved[0][1]["channel"] == "cli"
    assert saved[0][1]["cli_runner"] == "codex"
    assert saved[0][1]["cli_model"] == "gpt-5.5"
    assert saved[0][1]["cli_timeout_seconds"] == 240
    assert saved[0][1]["reasoning_strength"] == "low"


def test_menu_save_cli_verify_runs_off_event_loop(monkeypatch):
    """P1/P2:CLI verify smoke(~12s,最长 300s)不许同步跑在 asyncio event loop 上卡住
    并发请求——api_menu_save_llm 须经 run_in_executor offload。断言 verify 在非主线程跑。"""
    import threading
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    seen = {}

    def rec_verify(cfg):
        seen["thread"] = threading.current_thread()

    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", rec_verify)
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="", model="", api_key="", channel="cli",
        cli_runner="codex", cli_model="gpt-5.5", cli_timeout_seconds=240,
    )))

    assert seen.get("thread") is not None
    assert seen["thread"] is not threading.main_thread()


def test_menu_status_unsupported_cli_runner_not_ready(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "bogus", "model": "gpt-5.5", "timeout_seconds": "240"},
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["has_api_key"] is False
    assert status["llm"]["channel"] == "cli"
    assert status["llm"]["cli_runner"] == "bogus"
    assert status["llm_ready"] is False


def test_menu_save_llm_cli_channel_rejects_empty_runner(monkeypatch):
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))

    with pytest.raises(web_app.HTTPException) as exc_info:
        asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
            base_url="",
            model="",
            api_key="",
            channel="cli",
            cli_runner="",
            cli_model="gpt-5.5",
        )))

    assert exc_info.value.status_code == 400
    assert not seen
    assert not saved


def test_menu_save_llm_validates_api_channel_over_backend_env(monkeypatch):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))

    result = asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="https://api.example.com",
        model="gpt-api",
        api_key="sk-test",
        timeout_seconds=90,
        thinking_level="medium",
    )))

    assert result["ok"] is True
    assert seen[0].channel == "api"
    assert saved
    assert saved[0][1]["channel"] == "api"


def test_menu_status_treats_saved_cli_runtime_as_ready_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
        "base_url": "",
        "model": "",
        "api_key": "",
        "timeout_seconds": "180",
        "thinking_level": "",
        "advanced_model": "",
        "advanced_base_url": "",
        "advanced_api_key": "",
        "advanced_thinking_level": "",
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["has_api_key"] is False
    assert status["llm_ready"] is True
    assert status["llm"]["channel"] == "cli"
    assert status["llm"]["cli_runner"] == "codex"


def test_game_llm_config_reports_active_cli_channel_without_fake_api_key(monkeypatch):
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="https://api.example.com/v1",
        model="api-fallback",
        timeout_seconds=180,
        reasoning_strength="medium",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )
    monkeypatch.setattr(web_app, "web_game", SimpleNamespace(
        session=SimpleNamespace(llm_config=cfg),
    ))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "api-fallback",
            "api_key": "",
            "timeout_seconds": "180",
            "thinking_level": "",
            "advanced_model": "",
            "advanced_base_url": "",
            "advanced_api_key": "",
            "advanced_thinking_level": "",
            "reasoning_strength": "medium",
        },
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240", "reasoning_strength": "medium"},
        "base_url": "https://api.example.com/v1",
        "model": "api-fallback",
        "api_key": "",
        "timeout_seconds": "180",
        "thinking_level": "",
        "advanced_model": "",
        "advanced_base_url": "",
        "advanced_api_key": "",
        "advanced_thinking_level": "",
        "reasoning_strength": "medium",
    })

    result = asyncio.run(web_app.api_get_llm_config())

    assert result["channel"] == "cli"
    assert result["cli_runner"] == "codex"
    assert result["cli_model"] == "gpt-5.5"
    assert result["cli_timeout_seconds"] == 240
    assert result["reasoning_strength"] == "medium"
    assert result["has_api_key"] is False
    assert result["persisted"]["channel"] == "cli"
    assert result["persisted"]["cli_runner"] == "codex"
    assert result["persisted"]["cli_model"] == "gpt-5.5"
    assert result["persisted"]["cli_timeout_seconds"] == 240
    assert result["persisted"]["reasoning_strength"] == "medium"


def test_game_llm_config_reports_inactive_cli_reasoning_strength(monkeypatch):
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-5",
        channel="api",
        reasoning_strength="",
    )
    monkeypatch.setattr(web_app, "web_game", SimpleNamespace(
        session=SimpleNamespace(llm_config=cfg),
    ))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "reasoning_strength": "low",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-5",
            "api_key": "sk-test",
            "reasoning_strength": "low",
        },
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240", "reasoning_strength": "high"},
        "base_url": "https://api.example.com/v1",
        "model": "gpt-5",
        "api_key": "sk-test",
    })

    result = asyncio.run(web_app.api_get_llm_config())

    assert result["reasoning_strength"] == ""
    assert result["persisted"]["api_reasoning_strength"] == "low"
    assert result["persisted"]["cli_reasoning_strength"] == "high"


def test_game_llm_config_uses_advanced_model_for_api_reasoning_capability(monkeypatch):
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        channel="api",
        advanced_base_url="https://api.example.com/v1",
        advanced_model="gpt-5",
    )
    monkeypatch.setattr(web_app, "web_game", SimpleNamespace(
        session=SimpleNamespace(llm_config=cfg),
    ))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {"cli": {}})

    result = asyncio.run(web_app.api_get_llm_config())

    assert result["reasoning_supported"] is True


# --- #1271 S3: grok reasoning_strength 存取 round-trip + 三端 payload 名单 ---


def test_1271_menu_save_cli_grok_high_round_trip(monkeypatch):
    """#1271：POST channel=cli/cli_runner=grok/reasoning_strength=high 存取 round-trip。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: None)
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: saved.append((a, k)))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    result = asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="",
        model="",
        api_key="",
        channel="cli",
        cli_runner="grok",
        cli_model="",
        cli_timeout_seconds=240,
        reasoning_strength="high",
    )))

    assert result["ok"] is True
    assert result["llm"]["channel"] == "cli"
    assert result["llm"]["cli_runner"] == "grok"
    assert result["llm"]["reasoning_strength"] == "high"
    assert saved and saved[0][1]["channel"] == "cli"
    assert saved[0][1]["cli_runner"] == "grok"
    assert saved[0][1]["reasoning_strength"] == "high"


def test_1271_three_endpoints_grok_reasoning_supported_and_capability_list(monkeypatch):
    """#1271：status/GET/POST 三端 reasoning_supported=True + payload 名单含 grok。"""
    from ming_sim.cli_backend import CLI_REASONING_STRENGTH_RUNNERS

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "grok", "model": "", "timeout_seconds": "240", "reasoning_strength": "high"},
        "reasoning_strength": "high",
    })

    status = asyncio.run(web_app.api_menu_status())
    assert status["llm"]["cli_runner"] == "grok"
    assert status["llm"]["reasoning_strength"] == "high"
    assert status["llm"]["reasoning_supported"] is True
    assert "grok" in status["llm"]["cli_reasoning_runners"]
    assert set(status["llm"]["cli_reasoning_runners"]) == set(CLI_REASONING_STRENGTH_RUNNERS)

    cfg = LLMConfig(
        api_key="",
        base_url="",
        model="",
        channel="cli",
        cli_runner="grok",
        cli_model="",
        cli_timeout_seconds=240,
        reasoning_strength="high",
    )
    monkeypatch.setattr(web_app, "web_game", SimpleNamespace(
        session=SimpleNamespace(llm_config=cfg),
    ))
    get_result = asyncio.run(web_app.api_get_llm_config())
    assert get_result["cli_runner"] == "grok"
    assert get_result["reasoning_strength"] == "high"
    assert get_result["reasoning_supported"] is True
    assert "grok" in get_result["cli_reasoning_runners"]
    assert set(get_result["cli_reasoning_runners"]) == set(CLI_REASONING_STRENGTH_RUNNERS)

    fake = SimpleNamespace(
        build_llm_config=lambda *a, **k: cfg,
        commit_llm_config=lambda c: c,
    )
    monkeypatch.setattr(web_app, "get_game", lambda: fake)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)
    post_result = asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(
        channel="cli",
        cli_runner="grok",
        cli_timeout_seconds=240,
        reasoning_strength="high",
    )))
    assert post_result["cli_runner"] == "grok"
    assert post_result["reasoning_strength"] == "high"
    assert post_result["reasoning_supported"] is True
    assert "grok" in post_result["cli_reasoning_runners"]
    assert set(post_result["cli_reasoning_runners"]) == set(CLI_REASONING_STRENGTH_RUNNERS)


def test_1271_cli_supports_reasoning_strength_has_no_literal_set():
    """#1271 验收①：grep 谓词无字面量集合 + 委派 CLI_REASONING_STRENGTH_RUNNERS。"""
    import inspect

    from ming_sim.llm_config import cli_supports_reasoning_strength

    src = inspect.getsource(cli_supports_reasoning_strength)
    assert "CLI_REASONING_STRENGTH_RUNNERS" in src
    assert '{"codex"' not in src and "{'codex'" not in src
    assert '"codex", "claude"' not in src


def _count_llm_calls(monkeypatch):
    """#1228 行为验收：统计连通 smoke / CLI 后端真实调用次数（不断言墙钟）。"""
    import ming_sim.cli_backend as _cb

    calls: list[str] = []

    def _track_verify(cfg):
        calls.append("verify_llm_available")
        raise AssertionError("入口路径不得调用 verify_llm_available")

    def _track_backend(prompt, llm_config=None, tag=""):
        calls.append(f"backend:{tag or ''}")
        raise AssertionError(f"入口路径不得调用 CLI 后端 tag={tag!r}")

    monkeypatch.setattr(web_app, "verify_llm_available", _track_verify)
    monkeypatch.setattr(_cb, "_run_backend_for_config", _track_backend)
    return calls


def _assert_hud(payload: dict) -> None:
    assert isinstance(payload, dict)
    assert "turn" in payload and "phase" in payload["turn"]
    assert "ministers" in payload


def test_fresh_start_zero_llm_calls_disposes_old_main_db(tmp_path, monkeypatch):
    """#1228：fresh 构造零 LLM 调用，旧主库按既有 fresh 语义删除。"""
    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    calls = _count_llm_calls(monkeypatch)

    game = web_app.WebGame(fresh=True)
    try:
        _assert_hud(game.state_payload())
        assert not db_path.exists() or db_path.read_bytes() != b"existing-progress"
        assert calls == [], f"fresh 构造不应触发 LLM 调用，实得 {calls}"
    finally:
        try:
            game.session.close()
        except Exception:
            pass


def test_continue_load_save_reset_reach_hud_zero_llm_calls(tmp_path, monkeypatch):
    """#1228 行为：continue / load_save / 重置进 HUD，全程零 LLM 调用直至真实动作。"""
    db_path = tmp_path / "ming.db"
    ud = tmp_path / "ud"
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(ud))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    calls = _count_llm_calls(monkeypatch)

    # 前置：同一临时主库先 seed 再建 continue——证明读的是既存库，非空库初始化。
    seed_marker = "__seed_continue_1228__"
    seed = web_app.WebGame(fresh=True)
    try:
        seed.favorites = {seed_marker}
        seed.db.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        assert db_path.exists()

        # 构造同一回合可区分的 begin/preresolve 自动档；热加载不得改写任一源档。
        begin_marker = "__begin_1702__"
        preresolve_marker = "__preresolve_1702__"
        seed.favorites = {begin_marker}
        seed.db.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        begin_path = Path(seed.session.auto_save("begin"))
        seed.favorites = {preresolve_marker}
        seed.db.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        preresolve_path = Path(seed.session.auto_save("preresolve"))
        begin_bytes = begin_path.read_bytes()
        preresolve_bytes = preresolve_path.read_bytes()

        # 真正建立下一回合的 end_turn 产出 begin；重复普通 begin_turn 刷新不改写内容。
        seed.state.turn += 1
        seed.state.period += 1
        seed.db.save_state(seed.state)
        seed.session.end_turn()
        next_begin_path = next((ud / "saves").glob(
            f"auto_*_{seed.state.year:04d}_{seed.state.period:02d}_t{seed.state.turn:04d}_begin.db"
        ))
        next_begin_bytes = next_begin_path.read_bytes()
        after_begin_marker = "__after_begin_1702__"
        seed.favorites = {after_begin_marker}
        seed.db.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        seed.session.begin_turn()
        seed.session.begin_turn()
        assert next_begin_path.read_bytes() == next_begin_bytes
        with sqlite3.connect(next_begin_path) as checkpoint:
            archived_favorites = json.loads(checkpoint.execute(
                "SELECT value FROM kv_store WHERE key = 'favorites'"
            ).fetchone()[0])
        assert archived_favorites == [preresolve_marker]
        assert after_begin_marker in json.loads(seed.db.kv_get("favorites"))
    finally:
        try:
            seed.session.close()
        except Exception:
            pass

    # continue：已有主库 fresh=False
    cont = web_app.WebGame(fresh=False)
    try:
        _assert_hud(cont.state_payload())
        assert after_begin_marker in cont.favorites, (
            "continue 须加载最后写入的可辨识持久状态，证明读的是既存主库"
        )
        cont.save_to("slot_a")

        # load_save：真实热替换不改写源自动档，并可切回原月初 begin 状态继续写。
        cont.load_save(preresolve_path.stem)
        _assert_hud(cont.state_payload())
        assert preresolve_marker in cont.favorites
        assert begin_path.read_bytes() == begin_bytes
        assert preresolve_path.read_bytes() == preresolve_bytes

        cont.load_save(begin_path.stem)
        _assert_hud(cont.state_payload())
        assert begin_marker in cont.favorites
        cont.favorites.add(seed_marker)
        cont.db.kv_set("favorites", json.dumps(sorted(cont.favorites), ensure_ascii=False))
        assert seed_marker in json.loads(cont.db.kv_get("favorites"))

        # 重置：清主库重建，并为重建后新 campaign 的首月留下唯一 begin。
        cont.reset_game()
        _assert_hud(cont.state_payload())
        reset_campaign_id = cont.db.kv_get("campaign_id")
        reset_begin_paths = list((ud / "saves").glob(
            f"auto_{reset_campaign_id}_{cont.state.year:04d}_{cont.state.period:02d}_"
            f"t{cont.state.turn:04d}_begin.db"
        ))
        assert len(reset_begin_paths) == 1
        with sqlite3.connect(reset_begin_paths[0]) as checkpoint:
            archived_turn = checkpoint.execute(
                "SELECT year, period, turn FROM game_state WHERE id = 1"
            ).fetchone()
        assert archived_turn == (cont.state.year, cont.state.period, cont.state.turn)

        assert calls == [], f"continue/load_save/重置不应触发 LLM 调用，实得 {calls}"
    finally:
        try:
            cont.session.close()
        except Exception:
            pass


@pytest.mark.parametrize("op", ["load", "reset"])
def test_hot_replace_http_success_reopens_state_and_writes(tmp_path, monkeypatch, op):
    db_path = tmp_path / "ming.db"
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    runtime = web_app.WebGame(fresh=True)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    saved_marker, live_marker, write_minister = list(runtime.content.characters)[:3]
    runtime.favorites = {saved_marker}
    runtime.db.kv_set("favorites", json.dumps(sorted(runtime.favorites), ensure_ascii=False))
    if op == "load":
        from ming_sim import audience_extraction
        from tests.test_audience_extraction_501 import (
            _minister,
            _open_night_with_persisted_reply,
        )

        _open_night_with_persisted_reply(
            runtime.db, runtime.state, _minister(runtime.db, runtime.content),
        )
        assert runtime.db.list_unextracted_replies()
        monkeypatch.setattr(
            audience_extraction, "extract_story_facts", lambda *_a, **_k: [],
        )
    runtime.save_to("before")
    if op == "load":
        runtime.favorites = {live_marker}
        runtime.db.kv_set("favorites", json.dumps(sorted(runtime.favorites), ensure_ascii=False))

    path = "/api/saves/before/load" if op == "load" else "/api/game/reset"
    response = run_to_terminal(lambda: TestClient(web_app.app).post(path))
    assert response.status_code == 200
    state = TestClient(web_app.app).get("/api/game/state")
    assert state.status_code == 200
    assert "turn" in state.json()
    write = TestClient(web_app.app).post(f"/api/favorites/{write_minister}")
    assert write.status_code == 200
    favorites = write.json()["favorites"]
    assert write_minister in favorites
    if op == "load":
        assert saved_marker in favorites
        assert live_marker not in favorites
        runtime._runtime_write_queue().barrier(lambda: None)
        assert runtime.db.list_unextracted_replies() == []
    else:
        assert saved_marker not in favorites
    runtime.session.close()


@pytest.mark.parametrize("op", ["load", "reset"])
@pytest.mark.parametrize("failure", ["candidate", "backup"])
def test_hot_replace_http_failure_keeps_old_state_and_writes_usable(
    tmp_path, monkeypatch, op, failure,
):
    db_path = tmp_path / "ming.db"
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    runtime = web_app.WebGame(fresh=True)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    saved_marker, live_marker, write_minister = list(runtime.content.characters)[:3]
    runtime.favorites = {saved_marker}
    runtime.db.kv_set("favorites", json.dumps(sorted(runtime.favorites), ensure_ascii=False))
    runtime.save_to("before")
    if op == "load":
        runtime.favorites = {live_marker}
        runtime.db.kv_set("favorites", json.dumps(sorted(runtime.favorites), ensure_ascii=False))
    old_turn = runtime.state.turn

    if failure == "candidate":
        real_session = web_app.GameSession
        attempts = 0

        def fail_first_candidate(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("candidate sentinel")
            return real_session(*args, **kwargs)

        monkeypatch.setattr(web_app, "GameSession", fail_first_candidate)
    else:
        monkeypatch.setattr(
            runtime.db, "backup_to",
            lambda _path: (_ for _ in ()).throw(RuntimeError("backup sentinel")),
        )

    path = "/api/saves/before/load" if op == "load" else "/api/game/reset"
    response = run_to_terminal(lambda: TestClient(web_app.app).post(path))
    assert response.status_code == 500
    state = TestClient(web_app.app).get("/api/game/state")
    assert state.status_code == 200
    assert state.json()["turn"]["turn"] == old_turn
    write = TestClient(web_app.app).post(f"/api/favorites/{write_minister}")
    assert write.status_code == 200
    favorites = write.json()["favorites"]
    expected_marker = live_marker if op == "load" else saved_marker
    rejected_marker = saved_marker if op == "load" else live_marker
    assert expected_marker in favorites
    assert rejected_marker not in favorites
    assert write_minister in favorites
    runtime.session.close()


def test_menu_save_llm_api_channel_rejects_placeholder_existing_key(monkeypatch):
    # ship-pre CMR Group A：API 通道存档，空 api_key 时不能把占位符 cli-backend 当真 key 复用。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: saved.append((a, k)))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {"api_key": "cli-backend"})

    with pytest.raises(web_app.HTTPException) as exc:
        asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
            base_url="https://api.example.com",
            model="gpt-api",
            api_key="",
        )))

    assert exc.value.status_code == 400
    assert not saved


def test_build_llm_config_does_not_reuse_placeholder_as_api_key(monkeypatch):
    # ship-pre CMR Group A：CLI session 上提交空 key 的 API 设置，不能把 cli-backend 当 API key 带进去。
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: saved.append((a, k)))
    current = LLMConfig(
        api_key="cli-backend",
        base_url="https://old.example.com/v1",
        model="old-model",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-cli",
    )
    fake = SimpleNamespace(session=SimpleNamespace(llm_config=current, begin_turn=lambda: None))

    # 空表单 + CLI 局：保留 cli 通道（#51）、不把占位符当 API key 带入。
    cfg = web_app.WebGame.build_llm_config(fake, "", "", "")

    assert cfg.api_key != "cli-backend"
    assert cfg.channel == "cli"


def test_llm_config_from_runtime_api_channel_drops_placeholder_key(monkeypatch):
    # ship-pre CMR Group A'（Claude R1）：无 env runner 时空 channel 推成 api，
    # 但占位符不当真 key（清空让下游报「未配 API key」，而非拿假 key 探 OpenAI）。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    cfg = web_app._llm_config_from_runtime(
        {"channel": ""},
        base_url="https://api.example.com/v1",
        model="gpt-api",
        api_key="cli-backend",
        timeout_seconds=180,
        thinking_level="",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )

    assert cfg.channel == "api"
    assert cfg.api_key == ""
