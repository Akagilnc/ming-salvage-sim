from __future__ import annotations

import json

from ming_sim import llm_config


def test_load_runtime_llm_missing_file_keeps_empty_dict_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(tmp_path / "missing.json"))

    assert llm_config.load_runtime_llm() == {}


def test_load_runtime_llm_migrates_flat_api_config(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "https://api.example.com/v1",
                "model": "gpt-test",
                "api_key": "sk-test",
                "max_tokens": 4096,
                "timeout_seconds": 120,
                "thinking_level": "medium",
                "advanced_model": "gpt-advanced",
                "advanced_base_url": "https://advanced.example.com/v1",
                "advanced_api_key": "sk-advanced",
                "advanced_thinking_level": "high",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    runtime = llm_config.load_runtime_llm()

    assert runtime["channel"] == "api"
    assert runtime["api"] == {
        "base_url": "https://api.example.com/v1",
        "model": "gpt-test",
        "api_key": "sk-test",
        "max_tokens": "4096",
        "timeout_seconds": "120",
        "thinking_level": "medium",
        "advanced_model": "gpt-advanced",
        "advanced_base_url": "https://advanced.example.com/v1",
        "advanced_api_key": "sk-advanced",
        "advanced_thinking_level": "high",
    }
    assert runtime["cli"]["runner"] == ""
    assert runtime["cli"]["model"] == ""


def test_save_runtime_llm_persists_channel_slots(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "https://api.example.com/v1",
        "gpt-test",
        "sk-test",
        max_tokens=2048,
        timeout_seconds=150,
        thinking_level="minimal",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "cli"
    assert saved["api"]["model"] == "gpt-test"
    assert saved["api"]["api_key"] == "sk-test"
    assert saved["api"]["max_tokens"] == 2048
    assert saved["cli"] == {
        "runner": "codex",
        "model": "gpt-5.5",
        "timeout_seconds": 240,
    }


def test_load_runtime_llm_exposes_api_aliases_when_cli_is_active(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "cli",
                "api": {
                    "base_url": "https://api.example.com/v1",
                    "model": "gpt-test",
                    "api_key": "sk-test",
                },
                "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": 240},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    runtime = llm_config.load_runtime_llm()

    assert runtime["channel"] == "cli"
    assert runtime["base_url"] == "https://api.example.com/v1"
    assert runtime["model"] == "gpt-test"
    assert runtime["api_key"] == "sk-test"


def test_save_runtime_llm_preserves_existing_cli_slot_when_saving_api(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "cli",
                "api": {"base_url": "https://old.example.com/v1", "model": "old", "api_key": "old-key"},
                "cli": {"runner": "claude", "model": "claude-opus-4-8", "timeout_seconds": 300},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm("https://new.example.com/v1", "new-model", "new-key")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "api"
    assert saved["api"]["model"] == "new-model"
    assert saved["cli"] == {
        "runner": "claude",
        "model": "claude-opus-4-8",
        "timeout_seconds": "300",
    }


def test_save_runtime_llm_preserves_existing_api_slot_when_saving_cli(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "api",
                "api": {
                    "base_url": "https://api.example.com/v1",
                    "model": "gpt-api",
                    "api_key": "sk-api",
                    "max_tokens": 4096,
                    "timeout_seconds": 150,
                    "thinking_level": "minimal",
                },
                "cli": {"runner": "", "model": "", "timeout_seconds": ""},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "",
        "",
        "",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "cli"
    assert saved["api"]["base_url"] == "https://api.example.com/v1"
    assert saved["api"]["model"] == "gpt-api"
    assert saved["api"]["api_key"] == "sk-api"
    assert saved["api"]["max_tokens"] == "4096"
    assert saved["api"]["timeout_seconds"] == "150"
    assert saved["api"]["thinking_level"] == "minimal"
    assert saved["cli"] == {
        "runner": "codex",
        "model": "gpt-5.5",
        "timeout_seconds": 240,
    }


def test_load_runtime_flat_cli_backend_placeholder_not_api_channel(tmp_path, monkeypatch):
    # ship-pre CMR Group D：扁平旧配置 api_key=cli-backend（占位符、无真实 API 字段）
    # 不该被推成 channel=api（否则占位符走 API 路径、env CLI 后端被忽略）。
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({"api_key": "cli-backend"}), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    out = llm_config.load_runtime_llm()

    assert out["channel"] != "api"


def test_cli_backend_active_total_on_unsupported_runner(monkeypatch):
    # ship-pre CMR Group F：不支持的 runner 不该让守卫崩（应判 not-active，不抛 RuntimeError）。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False
    assert cli_backend._backend_label(cfg) == "agy"
