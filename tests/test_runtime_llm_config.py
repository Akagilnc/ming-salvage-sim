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
