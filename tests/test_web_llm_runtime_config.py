from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.models import LLMConfig


def test_runtime_cli_slot_builds_cli_llm_config_without_backend_env(monkeypatch):
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    runtime = {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
    }

    cfg = web_app._llm_config_from_runtime(
        runtime,
        base_url="https://api.example.com/v1",
        model="gpt-api",
        api_key="",
        max_tokens=8000,
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
    assert cfg.api_key == "cli-backend"


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


def test_apply_llm_config_saves_api_channel_over_backend_env(monkeypatch):
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

    cfg = web_app.WebGame.apply_llm_config(
        fake,
        "https://api.example.com",
        "gpt-api",
        "sk-test",
        max_tokens=16000,
        timeout_seconds=90,
        thinking_level="medium",
        advanced_model="",
        advanced_base_url="",
        advanced_api_key="",
        advanced_thinking_level="",
    )

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
    fake = SimpleNamespace(apply_llm_config=lambda *a, **k: cfg)
    monkeypatch.setattr(web_app, "get_game", lambda: fake)

    result = asyncio.run(web_app.api_set_llm_config(web_app.LLMConfigRequest(
        base_url="",
        model="gpt-5.5",
        api_key="",
    )))

    assert result["has_api_key"] is False


def test_menu_status_active_cli_unsupported_runner_not_ready_despite_preserved_api_key(monkeypatch):
    # ADR 0001: 切到 CLI 时 API 槽被保留。readiness 必须按 active channel 判，
    # 不能因 inactive API 槽里有真实 key 就把不可用的 CLI runner 误报成 ready。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_game", lambda: {"hitl_min_decisions": 1})
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
    monkeypatch.setattr(web_app, "load_runtime_game", lambda: {"hitl_min_decisions": 1})
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
    )))

    assert result["ok"] is True
    assert result["llm"]["channel"] == "cli"
    assert result["llm"]["cli_runner"] == "codex"
    assert result["llm"]["cli_model"] == "gpt-5.5"
    assert result["llm"]["has_api_key"] is False
    assert seen and seen[0].channel == "cli"
    assert seen[0].cli_runner == "codex"
    assert seen[0].cli_model == "gpt-5.5"
    assert saved and saved[0][1]["channel"] == "cli"
    assert saved[0][1]["cli_runner"] == "codex"
    assert saved[0][1]["cli_model"] == "gpt-5.5"
    assert saved[0][1]["cli_timeout_seconds"] == 240


def test_menu_status_unsupported_cli_runner_not_ready(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_game", lambda: {"hitl_min_decisions": 1})
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
        max_tokens=16000,
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
    monkeypatch.setattr(web_app, "load_runtime_game", lambda: {"hitl_min_decisions": 1})
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
        "base_url": "",
        "model": "",
        "api_key": "",
        "max_tokens": "8000",
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
        max_tokens=8000,
        timeout_seconds=180,
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
            "max_tokens": "8000",
            "timeout_seconds": "180",
            "thinking_level": "",
            "advanced_model": "",
            "advanced_base_url": "",
            "advanced_api_key": "",
            "advanced_thinking_level": "",
        },
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
        "base_url": "https://api.example.com/v1",
        "model": "api-fallback",
        "api_key": "",
        "max_tokens": "8000",
        "timeout_seconds": "180",
        "thinking_level": "",
        "advanced_model": "",
        "advanced_base_url": "",
        "advanced_api_key": "",
        "advanced_thinking_level": "",
    })

    result = asyncio.run(web_app.api_get_llm_config())

    assert result["channel"] == "cli"
    assert result["cli_runner"] == "codex"
    assert result["cli_model"] == "gpt-5.5"
    assert result["cli_timeout_seconds"] == 240
    assert result["has_api_key"] is False
    assert result["persisted"]["channel"] == "cli"
    assert result["persisted"]["cli_runner"] == "codex"
    assert result["persisted"]["cli_model"] == "gpt-5.5"
    assert result["persisted"]["cli_timeout_seconds"] == 240


def test_fresh_start_without_llm_keeps_existing_main_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    with pytest.raises(web_app.LLMUnavailable):
        web_app.WebGame(fresh=True)

    assert db_path.read_bytes() == b"existing-progress"


def test_fresh_start_verify_failure_keeps_existing_main_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})

    def fail_verify(config):
        raise web_app.LLMUnavailable("LLM unavailable")

    monkeypatch.setattr(web_app, "verify_llm_available", fail_verify)

    with pytest.raises(web_app.LLMUnavailable):
        web_app.WebGame(fresh=True)

    assert db_path.read_bytes() == b"existing-progress"


def test_fresh_start_cli_verify_failure_keeps_existing_main_db(tmp_path, monkeypatch):
    import ming_sim.cli_backend as _cb

    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": "240"},
    })

    def fail_cli_verify(prompt, llm_config=None):
        raise RuntimeError("codex missing")

    monkeypatch.setattr(_cb, "_run_backend_for_config", fail_cli_verify)

    with pytest.raises(web_app.LLMUnavailable):
        web_app.WebGame(fresh=True)

    assert db_path.read_bytes() == b"existing-progress"


def test_fresh_start_invalid_cli_runner_keeps_existing_main_db(tmp_path, monkeypatch):
    import ming_sim.cli_backend as _cb

    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    monkeypatch.setenv("MING_SIM_DB", str(db_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "cli",
        "api": {"base_url": "", "model": "", "api_key": ""},
        "cli": {"runner": "bogus", "model": "gpt-5.5", "timeout_seconds": "240"},
    })
    monkeypatch.setattr(_cb, "_run_agy", lambda prompt, timeout=None: ("ok", 1))

    with pytest.raises(web_app.LLMUnavailable):
        web_app.WebGame(fresh=True)

    assert db_path.read_bytes() == b"existing-progress"


def test_reset_cli_verify_failure_keeps_existing_main_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )
    fake = SimpleNamespace(
        db_path=str(db_path),
        session=SimpleNamespace(llm_config=cfg, close=lambda: None),
        _rebuild_session=lambda llm_config, **kwargs: None,
    )

    def fail_verify(llm_config):
        raise web_app.LLMUnavailable("codex missing")

    monkeypatch.setattr(web_app, "verify_llm_available", fail_verify)

    with pytest.raises(web_app.LLMUnavailable):
        web_app.WebGame.reset_game(fake)

    assert db_path.read_bytes() == b"existing-progress"


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


def test_apply_llm_config_does_not_reuse_placeholder_as_api_key(monkeypatch):
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

    cfg = web_app.WebGame.apply_llm_config(fake, "", "", "", max_tokens=16000)

    assert cfg.api_key != "cli-backend"
