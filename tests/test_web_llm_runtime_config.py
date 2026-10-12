from __future__ import annotations
import asyncio
import json
from pathlib import Path
import sqlite3
import threading
import pytest
import web_app
from fastapi.testclient import TestClient
from ming_sim.models import LLMConfig























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
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["llm"]["reasoning_strength"] == "low"
    assert status["llm"]["api_reasoning_strength"] == "low"
    assert status["llm"]["cli_reasoning_strength"] == "high"
    assert status["llm"]["effective_reasoning_strengths"] == {"api": "low", "cli": "high"}


def test_menu_status_uses_advanced_model_for_api_reasoning_capability(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "api": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
            "advanced_base_url": "https://api.example.com/v1",
            "advanced_model": "gpt-5",
        },
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


def test_menu_save_llm_verify_carries_runtime_default_headers(monkeypatch):
    """#1794：请求体未带头时，菜单保存 verify 仍装入档内头表（兼容旧客户端）。"""
    headers = {"X-Session": "from-disk", "User-Agent": "ming-qa/1.0"}
    seen = []
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "api": {
            "base_url": "https://old.example.com/v1",
            "model": "old-model",
            "api_key": "sk-old",
            "default_headers": headers,
        },
        "default_headers": headers,
    })
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: None)

    result = asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="https://api.example.com",
        model="gpt-api",
        api_key="sk-test",
    )))

    assert result["ok"] is True
    assert seen and seen[0].default_headers == headers


def test_menu_save_llm_accepts_default_headers_from_request(monkeypatch):
    """#1794 决定 5：设置页同一保存动作带头表；verify 与落盘用同一张。"""
    headers = {"X-Session": "from-ui", "User-Agent": "ming-qa/1.0"}
    seen = []
    saved = []
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "api": {
            "base_url": "https://old.example.com/v1",
            "model": "old-model",
            "api_key": "sk-old",
            "default_headers": {"X-Old": "drop-me"},
        },
        "default_headers": {"X-Old": "drop-me"},
    })
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda cfg: seen.append(cfg))
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *args, **kwargs: saved.append((args, kwargs)))

    result = asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
        base_url="https://api.example.com",
        model="gpt-api",
        api_key="sk-test",
        default_headers=headers,
    )))

    assert result["ok"] is True
    assert seen and seen[0].default_headers == headers
    assert saved and saved[0][1].get("default_headers") == headers
    assert result["llm"]["default_headers"] == headers






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
    })

    status = asyncio.run(web_app.api_menu_status())

    assert status["has_api_key"] is False
    assert status["llm_ready"] is True
    assert status["llm"]["channel"] == "cli"
    assert status["llm"]["cli_runner"] == "codex"








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




def _count_llm_calls(monkeypatch):
    """#1228 行为验收：统计连通 smoke / CLI 后端真实调用次数（不断言墙钟）。"""
    import ming_sim.cli_backend as _cb

    calls: list[str] = []

    def _track_verify(cfg):
        calls.append("verify_llm_available")
        raise AssertionError("入口路径不得调用 verify_llm_available")

    def _track_backend(prompt, llm_config=None, tag="", *, policy=None):
        calls.append(f"backend:{tag or ''}")
        raise AssertionError(f"入口路径不得调用 CLI 后端 tag={tag!r}")

    monkeypatch.setattr(web_app, "verify_llm_available", _track_verify)
    monkeypatch.setattr(_cb, "_run_backend_for_config", _track_backend)
    return calls


def _assert_hud(payload: dict) -> None:
    assert "turn" in payload and "phase" in payload["turn"]
    assert "ministers" in payload


def test_fresh_start_zero_llm_calls_disposes_old_main_db(tmp_path, monkeypatch, webgame_env):
    """#1228：fresh 构造零 LLM 调用，旧主库按既有 fresh 语义删除。"""
    db_path = tmp_path / "ming.db"
    db_path.write_bytes(b"existing-progress")
    calls = _count_llm_calls(monkeypatch)

    game = web_app.WebGame(fresh=True)
    try:
        _assert_hud(game.state_payload())
        assert not db_path.exists() or db_path.read_bytes() != b"existing-progress"
        assert calls == [], f"fresh 构造不应触发 LLM 调用，实得 {calls}"
    finally:
        game.session.close()


def test_continue_load_save_reach_hud_zero_llm_calls(tmp_path, monkeypatch, webgame_env):
    """#1228 行为：continue / load_save 进 HUD，全程零 LLM 调用直至真实动作。
    #1732：局内销毁式 reset 已删；新局走 menu/new_game 归档路径，不在此覆盖。"""
    db_path = tmp_path / "ming.db"
    ud = tmp_path / "ud"
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(ud))
    calls = _count_llm_calls(monkeypatch)

    # 前置：同一临时主库先 seed 再建 continue——证明读的是既存库，非空库初始化。
    seed_marker = "__seed_continue_1228__"
    seed = web_app.WebGame(fresh=True)
    try:
        seed.favorites = {seed_marker}
        seed.db.reign.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        assert db_path.exists()

        # 构造同一回合可区分的 begin/preresolve 自动档；热加载不得改写任一源档。
        begin_marker = "__begin_1702__"
        preresolve_marker = "__preresolve_1702__"
        seed.favorites = {begin_marker}
        seed.db.reign.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        begin_path = Path(seed.session.auto_save("begin"))
        seed.favorites = {preresolve_marker}
        seed.db.reign.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        preresolve_path = Path(seed.session.auto_save("preresolve"))
        begin_bytes = begin_path.read_bytes()
        preresolve_bytes = preresolve_path.read_bytes()

        # 真正建立下一回合的 end_turn 产出 begin；重复普通 begin_turn 刷新不改写内容。
        seed.state.turn += 1
        seed.state.period += 1
        seed.db.reign.save_game_state(seed.state)
        seed.session.end_turn()
        next_begin_path = next((ud / "saves").glob(
            f"auto_*_{seed.state.year:04d}_{seed.state.period:02d}_t{seed.state.turn:04d}_begin.db"
        ))
        next_begin_bytes = next_begin_path.read_bytes()
        after_begin_marker = "__after_begin_1702__"
        seed.favorites = {after_begin_marker}
        seed.db.reign.kv_set("favorites", json.dumps(sorted(seed.favorites), ensure_ascii=False))
        seed.session.begin_turn()
        seed.session.begin_turn()
        assert next_begin_path.read_bytes() == next_begin_bytes
        with sqlite3.connect(next_begin_path) as checkpoint:
            archived_favorites = json.loads(checkpoint.execute(
                "SELECT value FROM kv_store WHERE key = 'favorites'"
            ).fetchone()[0])
        assert archived_favorites == [preresolve_marker]
        assert after_begin_marker in json.loads(seed.db.reign.kv_get("favorites"))
    finally:
        seed.session.close()

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
        cont.db.reign.kv_set("favorites", json.dumps(sorted(cont.favorites), ensure_ascii=False))
        assert seed_marker in json.loads(cont.db.reign.kv_get("favorites"))

        assert calls == [], f"continue/load_save 不应触发 LLM 调用，实得 {calls}"
    finally:
        cont.session.close()






def test_menu_save_llm_api_channel_rejects_placeholder_existing_key(monkeypatch):
    # ship-pre CMR Group A：API 通道存档，空 api_key 时不能把占位符 cli-backend 当真 key 复用。
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    saved = []
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)
    monkeypatch.setattr(web_app, "save_runtime_llm", lambda *a, **k: saved.append((a, k)))
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {"api": {"api_key": "cli-backend"}})

    with pytest.raises(web_app.HTTPException) as exc:
        asyncio.run(web_app.api_menu_save_llm(web_app.LlmSetupRequest(
            base_url="https://api.example.com",
            model="gpt-api",
            api_key="",
        )))

    assert exc.value.status_code == 400
    assert not saved





def test_menu_status_exposes_default_headers(monkeypatch):
    """#1794：设置页读回入口 menu/status 露出 default_headers。"""
    headers = {"X-Session": "read-me", "User-Agent": "ming-qa/1.0"}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: "")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {
        "channel": "api",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-api",
            "api_key": "sk-test",
            "default_headers": headers,
        },
    })

    status = asyncio.run(web_app.api_menu_status())
    assert status["llm"]["default_headers"] == headers


def test_1271_menu_status_grok_reasoning_supported_and_capability_list(monkeypatch):
    """#1271：menu/status reasoning_supported=True + payload 名单含 grok。"""
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
    assert set(status["llm"]["cli_reasoning_floor_runners"]) == {"codex", "claude", "grok"}

# ── #1902 F28：局中 /api/llm/config、/api/saves 真 HTTP 入口（共享 web_game）──

def _bind_real_runtime_llm(monkeypatch, tmp_path):
    """撤销 webgame stub，把 runtime 落盘接到临时路径（真 load/save）。"""
    import ming_sim.llm_config as llm_config

    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    monkeypatch.setattr(web_app, "load_runtime_llm", llm_config.load_runtime_llm)
    monkeypatch.setattr(web_app, "save_runtime_llm", llm_config.save_runtime_llm)
    return path


def test_game_llm_config_http_get_exposes_persisted_slots_and_f41_fields(
    web_game, tmp_path, monkeypatch,
):
    """GET /api/llm/config：真入口读 session + 真 runtime；露出 F41 字段与双槽强度。"""
    import ming_sim.llm_config as llm_config
    from ming_sim.cli_backend import CLI_REASONING_FLOOR_RUNNERS, CLI_REASONING_STRENGTH_RUNNERS

    _bind_real_runtime_llm(monkeypatch, tmp_path)
    llm_config.save_runtime_llm(
        "", "", "",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
        reasoning_strength="high",
    )
    llm_config.save_runtime_llm(
        "https://api.example.com/v1",
        "gpt-5",
        "sk-test",
        channel="api",
        reasoning_strength="low",
        advanced_base_url="https://api.example.com/v1",
        advanced_model="gpt-5",
        default_headers={"X-Session": "read-me", "User-Agent": "ming-qa/1.0"},
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )
    # 会话侧对齐 advanced，使 reasoning_supported 走 advanced 模型判定。
    web_game.session.llm_config = LLMConfig(
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        channel="api",
        advanced_base_url="https://api.example.com/v1",
        advanced_model="gpt-5",
        default_headers={"X-Session": "read-me", "User-Agent": "ming-qa/1.0"},
    )

    result = TestClient(web_app.app).get("/api/llm/config")
    assert result.status_code == 200
    body = result.json()
    assert body["channel"] == "api"
    assert body["reasoning_supported"] is True
    assert body["default_headers"] == {"X-Session": "read-me", "User-Agent": "ming-qa/1.0"}
    assert body["persisted"]["api_reasoning_strength"] == "low"
    assert body["persisted"]["cli_reasoning_strength"] == "high"
    assert body["persisted"]["default_headers"] == {
        "X-Session": "read-me", "User-Agent": "ming-qa/1.0",
    }
    assert body["persisted"]["cli_timeout_seconds"] == 240
    assert body["effective_reasoning_strengths"] == {"api": "low", "cli": "high"}
    assert set(body["cli_reasoning_runners"]) == set(CLI_REASONING_STRENGTH_RUNNERS)
    assert set(body["cli_reasoning_floor_runners"]) == set(CLI_REASONING_FLOOR_RUNNERS)


def test_game_llm_config_http_post_cli_persist_and_api_headers(
    web_game, tmp_path, monkeypatch,
):
    """POST /api/llm/config：env-only 往返 + 局中 headers + advanced 显式清空。

    #1902 F28-R2/R3/R4：真 HTTP 入口 + 真 build/commit/persist；只 mock verify。
    """
    import ming_sim.llm_config as llm_config
    from ming_sim.cli_backend import CLI_REASONING_FLOOR_RUNNERS
    from ming_sim.models import API_DEFAULT_BASE_URL, API_DEFAULT_MODEL

    _bind_real_runtime_llm(monkeypatch, tmp_path)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)
    # 起始：盘上无 API 槽；会话侧已由 webgame_env 的 OPENAI_* 建出 API 配置。
    disk0 = llm_config.load_runtime_llm()
    api0 = disk0.get("api") if isinstance(disk0.get("api"), dict) else {}
    assert not str(api0.get("base_url") or "").strip()
    assert not str(api0.get("model") or "").strip()
    seed_base = web_game.session.llm_config.base_url
    seed_model = web_game.session.llm_config.model
    seed_key = web_game.session.llm_config.api_key
    assert seed_base == API_DEFAULT_BASE_URL
    assert seed_model == API_DEFAULT_MODEL
    assert seed_key == "sk-test"
    client = TestClient(web_app.app)

    cli = client.post("/api/llm/config", json={
        "channel": "cli",
        "cli_runner": "grok",
        "cli_model": "",
        "cli_timeout_seconds": 240,
        "reasoning_strength": "high",
        "api_key": "cli-backend",
    })
    assert cli.status_code == 200
    cli_body = cli.json()
    assert cli_body["channel"] == "cli"
    assert cli_body["cli_runner"] == "grok"
    assert cli_body["cli_model"] == ""
    assert cli_body["base_url"] == seed_base
    assert cli_body["model"] == seed_model
    assert cli_body["has_api_key"] is False
    assert cli_body["reasoning_supported"] is True
    assert cli_body["reasoning_strength"] == "high"
    assert set(cli_body["cli_reasoning_floor_runners"]) == set(CLI_REASONING_FLOOR_RUNNERS)
    assert cli_body["effective_reasoning_strengths"]["cli"] == "high"
    saved = llm_config.load_runtime_llm()
    assert saved["channel"] == "cli"
    assert saved["cli"]["runner"] == "grok"
    assert saved["cli"]["model"] == ""
    assert saved["api"]["base_url"] == seed_base
    assert saved["api"]["model"] == seed_model
    assert saved["api"]["api_key"] == seed_key

    got = client.get("/api/llm/config")
    assert got.status_code == 200
    assert got.json()["channel"] == "cli"
    assert got.json()["base_url"] == seed_base
    assert got.json()["model"] == seed_model
    assert got.json()["has_api_key"] is False
    assert got.json()["persisted"]["has_api_key"] is True

    # 不经 UI 回填地址/模型：只切回 API，须沿用 session/盘上未丢失的槽。
    api = client.post("/api/llm/config", json={
        "channel": "api",
        "cli_runner": "__keep__",
        "cli_model": "__keep__",
    })
    assert api.status_code == 200
    api_body = api.json()
    assert api_body["channel"] == "api"
    assert api_body["base_url"] == seed_base
    assert api_body["model"] == seed_model
    assert api_body["has_api_key"] is True
    assert api_body["cli_runner"] == "grok"
    assert api_body["cli_timeout_seconds"] == 240
    assert api_body["effective_reasoning_strengths"]["cli"] == "high"
    saved_api = llm_config.load_runtime_llm()
    assert saved_api["channel"] == "api"
    assert saved_api["api"]["base_url"] == seed_base
    assert saved_api["api"]["model"] == seed_model
    assert saved_api["api"]["api_key"] == seed_key

    # #1794 / F28-R4：API 保存时界面传来的 default_headers 回显并落盘；
    # 同时写入 advanced_*，供后续显式清空（F28-R3）。
    api_headers = client.post("/api/llm/config", json={
        "channel": "api",
        "advanced_model": "gpt-5",
        "advanced_base_url": "https://adv.example/v1",
        "advanced_api_key": "sk-adv-real",
        "default_headers": {"X-From-UI": "ok"},
        "cli_runner": "__keep__",
        "cli_model": "__keep__",
    })
    assert api_headers.status_code == 200
    headers_body = api_headers.json()
    assert headers_body["default_headers"] == {"X-From-UI": "ok"}
    assert headers_body["advanced_model"] == "gpt-5"
    assert headers_body["advanced_base_url"] == "https://adv.example/v1"
    assert headers_body["has_advanced_api_key"] is True
    disk_headers = llm_config.load_runtime_llm()
    assert disk_headers["api"]["default_headers"] == {"X-From-UI": "ok"}
    assert disk_headers["api"]["advanced_model"] == "gpt-5"
    assert disk_headers["api"]["advanced_base_url"] == "https://adv.example/v1"
    assert disk_headers["api"]["advanced_api_key"] == "sk-adv-real"

    # #1794 / F28-R4：切到 CLI 后，未激活 API 槽的 default_headers 仍落盘。
    cli_keep = client.post("/api/llm/config", json={
        "channel": "cli",
        "cli_runner": "grok",
        "cli_model": "",
        "cli_timeout_seconds": 240,
        "reasoning_strength": "high",
        "api_key": "cli-backend",
    })
    assert cli_keep.status_code == 200
    saved_cli = llm_config.load_runtime_llm()
    assert saved_cli["channel"] == "cli"
    assert saved_cli["api"]["default_headers"] == {"X-From-UI": "ok"}
    assert client.get("/api/llm/config").json()["persisted"]["default_headers"] == {
        "X-From-UI": "ok",
    }

    # F28-R3：激活 API 时 advanced_* 空串＝显式清空（响应 + 落盘）。
    cleared = client.post("/api/llm/config", json={
        "channel": "api",
        "advanced_model": "",
        "advanced_base_url": "",
        "advanced_api_key": "",
        "cli_runner": "__keep__",
        "cli_model": "__keep__",
    })
    assert cleared.status_code == 200
    clear_body = cleared.json()
    assert clear_body["advanced_model"] == ""
    assert clear_body["advanced_base_url"] == ""
    assert clear_body["has_advanced_api_key"] is False
    disk_clear = llm_config.load_runtime_llm()
    assert disk_clear["api"]["advanced_model"] == ""
    assert disk_clear["api"]["advanced_base_url"] == ""
    assert disk_clear["api"]["advanced_api_key"] == ""


def test_game_llm_config_http_verify_failure_skips_persist(
    web_game, tmp_path, monkeypatch,
):
    """verify 失败经 HTTP 400 透传，且不 commit/落盘。"""
    import ming_sim.llm_config as llm_config

    _bind_real_runtime_llm(monkeypatch, tmp_path)
    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", lambda c: None)
    client = TestClient(web_app.app)
    seed = client.post("/api/llm/config", json={
        "channel": "cli",
        "cli_runner": "agy",
        "cli_model": "",
        "cli_timeout_seconds": 240,
        "reasoning_strength": "off",
    })
    assert seed.status_code == 200
    before = llm_config.load_runtime_llm()

    sentinel = {"code": "llm_unavailable", "message": "主模型连通性检查失败：runner missing"}

    def boom(_cfg):
        raise web_app.HTTPException(status_code=400, detail=sentinel)

    monkeypatch.setattr(web_app, "_verify_llm_configs_or_raise", boom)
    failed = client.post("/api/llm/config", json={
        "channel": "cli",
        "cli_runner": "codex",
        "cli_model": "gpt-5.5",
        "reasoning_strength": "high",
    })
    assert failed.status_code == 400
    assert failed.json()["detail"] == sentinel
    assert llm_config.load_runtime_llm() == before
    assert client.get("/api/llm/config").json()["cli_runner"] == "agy"


def test_saves_http_lifecycle_hot_replace_and_delete(web_game, tmp_path, monkeypatch):
    """POST /api/saves → load 热替换 → DELETE；成功路径复用共享 web_game。"""
    from tests.conftest import stub_audience_translate

    stub_audience_translate(monkeypatch)
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    client = TestClient(web_app.app)
    saved_marker, live_marker, write_minister = list(web_game.content.characters)[:3]
    web_game.favorites = {saved_marker}
    web_game.db.reign.kv_set(
        "favorites", json.dumps(sorted(web_game.favorites), ensure_ascii=False),
    )
    created = client.post("/api/saves", json={"name": "before"})
    assert created.status_code == 200
    assert created.json()["save"]["name"] == "before"

    web_game.favorites = {live_marker}
    web_game.db.reign.kv_set(
        "favorites", json.dumps(sorted(web_game.favorites), ensure_ascii=False),
    )
    loaded = client.post("/api/saves/before/load")
    assert loaded.status_code == 200
    state = client.get("/api/game/state")
    assert state.status_code == 200
    assert "turn" in state.json()
    write = client.post(f"/api/favorites/{write_minister}")
    assert write.status_code == 200
    favorites = write.json()["favorites"]
    assert write_minister in favorites
    assert saved_marker in favorites
    assert live_marker not in favorites

    deleted = client.delete("/api/saves/before")
    assert deleted.status_code == 200
    assert all(s.get("name") != "before" for s in deleted.json()["saves"])


@pytest.mark.parametrize("failure", ["candidate", "backup"])
def test_hot_replace_http_failure_keeps_old_state_and_writes_usable(
    web_game, tmp_path, monkeypatch, failure,
):
    """热替换失败：旧局可继续写；存档经 POST /api/saves 制备。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "ud"))
    client = TestClient(web_app.app)
    saved_marker, live_marker, write_minister = list(web_game.content.characters)[:3]
    web_game.favorites = {saved_marker}
    web_game.db.reign.kv_set(
        "favorites", json.dumps(sorted(web_game.favorites), ensure_ascii=False),
    )
    created = client.post("/api/saves", json={"name": "before"})
    assert created.status_code == 200
    web_game.favorites = {live_marker}
    web_game.db.reign.kv_set(
        "favorites", json.dumps(sorted(web_game.favorites), ensure_ascii=False),
    )
    old_turn = web_game.state.turn

    if failure == "candidate":
        import ming_sim.session as session_mod

        real_session = session_mod.GameSession
        attempts = 0

        def fail_first_candidate(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("candidate sentinel")
            return real_session(*args, **kwargs)

        monkeypatch.setattr(session_mod, "GameSession", fail_first_candidate)
    else:
        monkeypatch.setattr(
            web_game.db, "backup_to",
            lambda _path: (_ for _ in ()).throw(RuntimeError("backup sentinel")),
        )

    response = client.post("/api/saves/before/load")
    assert response.status_code == 500
    state = client.get("/api/game/state")
    assert state.status_code == 200
    assert state.json()["turn"]["turn"] == old_turn
    write = client.post(f"/api/favorites/{write_minister}")
    assert write.status_code == 200
    favorites = write.json()["favorites"]
    assert live_marker in favorites
    assert saved_marker not in favorites
    assert write_minister in favorites
