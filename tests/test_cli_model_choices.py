"""CLI runner 策展模型清单（前端下拉的单一真源）。

CLI Model 从自由文本框改成 per-runner 策展下拉，清单在后端单点定义、经
config 端点暴露给前端。这里测清单结构 + 默认档语义 + 与默认常量的一致性
（不重写字面量），以及两个 config 端点确实把清单带出去。
"""

from __future__ import annotations

import asyncio

import pytest

import ming_sim.cli_backend as cb


def test_choices_cover_all_supported_runners():
    choices = cb.cli_model_choices()
    # 每个受支持的 CLI runner 都要有一档清单（与 _CLI_BACKENDS 单一真源对齐，#1256）。
    assert set(choices) == set(cb._CLI_BACKENDS)
    assert {"agy", "codex", "claude", "cursor", "kimi", "grok"} <= set(choices)


def test_each_runner_has_default_escape_option_first():
    choices = cb.cli_model_choices()
    for runner, options in choices.items():
        assert options, f"{runner} 清单不能为空"
        # 每档都是 {value,label}；第一个必须是默认档（value=""，对应「留空=后端默认」语义）。
        for opt in options:
            assert set(opt) == {"value", "label"}
            assert isinstance(opt["value"], str) and isinstance(opt["label"], str)
        assert options[0]["value"] == "", f"{runner} 首档须为默认档(value='')"
        # value 不重复（含默认空串）。
        values = [o["value"] for o in options]
        assert len(values) == len(set(values)), f"{runner} 档位 value 重复"


def test_default_labels_reuse_single_source_constants(monkeypatch):
    """无 env 覆盖时，默认档 label 复用 cli_backend 的默认常量，不重写字面量（单一真源）。"""
    monkeypatch.delenv("MING_SIM_CODEX_MODEL", raising=False)
    monkeypatch.delenv("MING_SIM_CLAUDE_MODEL", raising=False)
    choices = cb.cli_model_choices()
    assert cb.CODEX_DEFAULT_MODEL in choices["codex"][0]["label"]
    assert cb.CLAUDE_DEFAULT_MODEL in choices["claude"][0]["label"]


def test_default_label_reflects_env_override(monkeypatch):
    """设了 MING_SIM_CODEX_MODEL → 默认档 label 跟随真实 resolved 默认（cli_model_from_env），
    与 api_menu_status 的 resolved cli_model 同源，不停留在内置常量（CMR R2 codex spec-impl）。"""
    monkeypatch.setenv("MING_SIM_CODEX_MODEL", "env-override-model")
    label = cb.cli_model_choices()["codex"][0]["label"]
    assert "env-override-model" in label
    assert cb.CODEX_DEFAULT_MODEL not in label


def test_codex_offers_spark_fast_tier():
    values = [o["value"] for o in cb.cli_model_choices()["codex"]]
    assert "gpt-5.3-codex-spark" in values  # bench「可用主力·快」档


def test_claude_offers_haiku_and_sonnet_tiers():
    values = [o["value"] for o in cb.cli_model_choices()["claude"]]
    assert "claude-haiku-4-5" in values
    assert "claude-sonnet-4-6" in values


def test_curated_values_are_lowercase_known_ids():
    """策展值都用规范小写 id——下拉的全部意义就是挡住大小写/拼写错。"""
    for options in cb.cli_model_choices().values():
        for opt in options:
            assert opt["value"] == opt["value"].lower()


def test_choices_returns_independent_copies():
    """返回独立副本，调用方改动不污染下一次调用（防共享可变态）。"""
    a = cb.cli_model_choices()
    a["codex"].append({"value": "x", "label": "x"})
    b = cb.cli_model_choices()
    assert all(o["value"] != "x" for o in b["codex"])


# ── 端点暴露：两个 config 端点都把清单带给前端 ──

def _patch_status_io(monkeypatch, runtime):
    """把 api_menu_status 的全部磁盘 I/O monkeypatch 掉（含 load_runtime_llm），
    使端点测试 hermetic、不与本地配置文件耦合（gemini R1）。"""
    import web_app
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: runtime)
    monkeypatch.setattr(web_app, "_scan_saves", lambda: [])
    monkeypatch.setattr(web_app, "_scan_campaigns", lambda: [])
    monkeypatch.setattr(web_app, "_main_db_campaign_id", lambda: None)
    monkeypatch.setattr(web_app, "_has_main_db", lambda: False)
    return web_app


def test_menu_status_exposes_choices(monkeypatch):
    web_app = _patch_status_io(monkeypatch, {})
    data = asyncio.run(web_app.api_menu_status())
    assert data["llm"]["cli_model_choices"] == cb.cli_model_choices()


def test_menu_status_exposes_raw_cli_model_saved_default(monkeypatch):
    """空 saved model（=用户选「默认」档）→ menu-status 须暴露 raw cli_model_saved=''，
    前端据此显示「默认」档；不能只给被 cli_model_from_env 兜底成默认名的 resolved 值，
    否则下拉把默认误判成「其他(手填)」、空保存把字面量钉死（CMR R1 Claude+Gemini concur）。"""
    monkeypatch.delenv("MING_SIM_CODEX_MODEL", raising=False)  # hermetic：断言内置默认名
    web_app = _patch_status_io(monkeypatch, {
        "channel": "cli", "api": {}, "cli": {"runner": "codex", "model": "", "timeout_seconds": 300},
    })
    llm = asyncio.run(web_app.api_menu_status())["llm"]
    assert llm["cli_model_saved"] == ""        # raw 留空 = 默认档（表单用）
    assert llm["cli_model"] == "gpt-5.5"        # resolved 仍供「当前后端」展示


def test_menu_status_cli_model_saved_passes_explicit(monkeypatch):
    """显式存了某档 → raw 原样回传（表单选中该档）。"""
    web_app = _patch_status_io(monkeypatch, {
        "channel": "cli", "api": {},
        "cli": {"runner": "codex", "model": "gpt-5.3-codex-spark", "timeout_seconds": 300},
    })
    llm = asyncio.run(web_app.api_menu_status())["llm"]
    assert llm["cli_model_saved"] == "gpt-5.3-codex-spark"


def test_get_llm_config_exposes_choices(monkeypatch):
    import web_app
    from ming_sim.models import LLMConfig

    fake_cfg = LLMConfig(
        api_key="", base_url="https://x/v1", model="m",
        channel="cli", cli_runner="codex", cli_model="",
    )
    monkeypatch.setattr(
        web_app, "get_game",
        lambda: type("G", (), {"session": type("S", (), {"llm_config": fake_cfg})()})(),
    )
    data = asyncio.run(web_app.api_get_llm_config())
    assert data["cli_model_choices"] == cb.cli_model_choices()
