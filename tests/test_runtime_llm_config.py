from __future__ import annotations

import json

from ming_sim import llm_config


# ── F1：同一份运行档经 CLI 与 Web 两端建局必须是同一执行事实 ──────────────
# 判官原证：保存的 API 档下，游戏 CLI 仍以默认地址/默认模型/API 超时起局并索要
# API key，而 Web 消费保存值。落差原本只写在 WebGame 里（档覆盖入参），CLI 直接把
# 入参当最终值。现落差归 llm_config_from_runtime 一处，两端共用。


def _api_runtime(**over) -> dict:
    payload = {
        "channel": "api",
        "api": {
            "base_url": "https://saved.example/v1",
            "model": "saved-model",
            "api_key": "sk-saved",
            "timeout_seconds": 77,
        },
        "cli": {},
    }
    payload["api"].update(over)
    return llm_config._normalize_runtime_llm(payload)


def _project(runtime: dict, **entry_over) -> "object":
    entry = {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key": "",
        "timeout_seconds": 180,
        "thinking_level": "",
        "advanced_model": "",
        "advanced_base_url": "",
        "advanced_api_key": "",
        "advanced_thinking_level": "",
    }
    entry.update(entry_over)
    return llm_config.llm_config_from_runtime(runtime, **entry)


def test_runtime_profile_wins_over_entry_args():
    """运行档的地址/模型/key/超时优先于入口入参（两端同一口径）。"""
    cfg = _project(_api_runtime())
    assert cfg.base_url == "https://saved.example/v1"
    assert cfg.model == "saved-model"
    assert cfg.api_key == "sk-saved"
    assert cfg.timeout_seconds == 77


def test_same_profile_projects_identical_facts_for_both_entries():
    """同一份档 + 两端各自的入参/env 默认值 → 投影结果逐字段相同。"""
    runtime = _api_runtime()
    # CLI 入口：argparse 默认值（地址/模型/默认超时），无 env key。
    from_cli = _project(runtime)
    # Web 入口：env 默认值，同样无 key。
    from_web = _project(runtime)
    for field in ("base_url", "model", "api_key", "timeout_seconds", "channel"):
        assert getattr(from_cli, field) == getattr(from_web, field), field


def test_entry_args_still_used_when_profile_has_no_values():
    """档里没有的字段才回落入口入参（回落不是被删，是落差归位）。"""
    cfg = _project(
        llm_config._normalize_runtime_llm({"channel": "api", "api": {}, "cli": {}}),
        base_url="https://env.example/v1", model="env-model",
        api_key="sk-env", timeout_seconds=180,
    )
    assert cfg.base_url == "https://env.example/v1"
    assert cfg.model == "env-model"
    assert cfg.api_key == "sk-env"
    assert cfg.timeout_seconds == 180


def test_placeholder_key_in_profile_does_not_override_real_env_key():
    """档里的占位符/sentinel 不是真 key，不得盖掉入口带来的真实 key。"""
    cfg = _project(_api_runtime(api_key="cli-backend"), api_key="sk-env")
    assert cfg.api_key == "sk-env"
    cfg2 = _project(_api_runtime(api_key="__keep__"), api_key="sk-env")
    assert cfg2.api_key == "sk-env"


def test_cli_runtime_slot_and_timeout_come_from_profile():
    """CLI 通道的 runner/model/超时同样只由运行档声明。"""
    runtime = llm_config._normalize_runtime_llm({
        "channel": "cli",
        "api": {},
        "cli": {"runner": "codex", "model": "m-x", "timeout_seconds": 240},
    })
    cfg = _project(runtime, timeout_seconds=180, model="api-fallback")
    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex"
    assert cfg.cli_model == "m-x"
    assert cfg.cli_timeout_seconds == 240
    assert cfg.api_key == "", "CLI 通道不留 API key"


def test_load_runtime_llm_missing_file_keeps_empty_dict_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(tmp_path / "missing.json"))

    assert llm_config.load_runtime_llm() == {}


def test_load_runtime_llm_malformed_json_returns_empty(tmp_path, monkeypatch):
    """坏 JSON(语法错)走 json.JSONDecodeError 防御分支 → {}(Sourcery R2)。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text("{not valid json,,,", encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    assert llm_config.load_runtime_llm() == {}


def test_load_runtime_llm_coerces_stringified_numeric_fields(tmp_path, monkeypatch):
    """#53 _slot_number:旧存档把 timeout_seconds 存成字符串时,load 归一回数值
    (covers caster(value) / caster(float(value)) 兜底 / garbage→default 三分支)。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        # timeout_seconds="120.5":直接 float 可过；另用 "180.0" 形态钉 caster 路径。
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x",
                "timeout_seconds": "120.5"},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["api"]["timeout_seconds"] == 120.5 and isinstance(out["api"]["timeout_seconds"], float)
    assert "max_tokens" not in out["api"]


def test_load_runtime_llm_garbage_numeric_fields_fall_back_to_default(tmp_path, monkeypatch):
    """#53 _slot_number:不可解析的数值字段回落默认(timeout=180.0)。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x",
                "timeout_seconds": "xyz"},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["api"]["timeout_seconds"] == 180.0
    assert "max_tokens" not in out["api"]


def test_load_runtime_llm_ignores_legacy_max_tokens_key(tmp_path, monkeypatch):
    """#1472：旧 runtime_llm.json 带 max_tokens 键载入不炸、键被自然忽略（勿写迁移）。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {
            "base_url": "https://x/v1",
            "model": "m",
            "api_key": "sk-x",
            "max_tokens": 6000,
            "timeout_seconds": 120,
        },
        "max_tokens": 8000,
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["channel"] == "api"
    assert out["api"]["model"] == "m"
    assert out["api"]["timeout_seconds"] == 120
    assert "max_tokens" not in out["api"]
    assert "max_tokens" not in out


def test_load_runtime_llm_non_dict_payload_returns_empty(tmp_path, monkeypatch):
    """合法 JSON 但顶层非 dict(list / 字符串 / 数字)走 isinstance 防御分支 → {}。"""
    for payload in ("[1, 2, 3]", '"just a string"', "42"):
        path = tmp_path / "runtime_llm.json"
        path.write_text(payload, encoding="utf-8")
        monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
        assert llm_config.load_runtime_llm() == {}, f"payload={payload!r} 应回落空 dict"


def test_load_runtime_llm_migrates_flat_api_config(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "base_url": "https://api.example.com/v1",
                "model": "gpt-test",
                "api_key": "sk-test",
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
        "timeout_seconds": 120,
        "thinking_level": "medium",
        "advanced_model": "gpt-advanced",
        "advanced_base_url": "https://advanced.example.com/v1",
        "advanced_api_key": "sk-advanced",
        "advanced_thinking_level": "",
        "reasoning_strength": "high",
        "default_headers": {},
    }
    assert runtime["reasoning_strength"] == "high"
    assert runtime["cli"]["runner"] == ""
    assert runtime["cli"]["model"] == ""


def test_save_runtime_llm_persists_channel_slots(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "https://api.example.com/v1",
        "gpt-test",
        "sk-test",
        timeout_seconds=150,
        thinking_level="minimal",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
        reasoning_strength="low",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "cli"
    assert saved["api"]["model"] == "gpt-test"
    assert saved["api"]["api_key"] == "sk-test"
    assert "max_tokens" not in saved["api"]
    assert "max_tokens" not in saved
    assert saved["cli"] == {
        "runner": "codex",
        "model": "gpt-5.5",
        "timeout_seconds": 240,
        "reasoning_strength": "low",
    }


def test_save_runtime_llm_persists_api_reasoning_strength(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "https://api.example.com/v1",
        "gpt-5",
        "sk-test",
        channel="api",
        reasoning_strength="high",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["reasoning_strength"] == "high"


def test_save_runtime_llm_api_save_preserves_cli_reasoning_strength(tmp_path, monkeypatch):
    """#358 cmr r4: 保存 API 通道不得丢掉 CLI 槽已存的 reasoning_strength——它像 runner/model/
    timeout 一样按槽保留（API 选择器空=""并非有意清 CLI 槽，否则切回 CLI 设置无声蒸发）。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "cli",
                "reasoning_strength": "high",
                "api": {"base_url": "", "model": "", "api_key": ""},
                "cli": {
                    "runner": "codex",
                    "model": "gpt-5.5",
                    "timeout_seconds": 240,
                    "reasoning_strength": "high",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    # 保存 API 通道，API 推理强度空（默认）
    llm_config.save_runtime_llm(
        "https://api.example.com/v1", "gpt-5", "sk-test",
        channel="api", reasoning_strength="",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "api"
    assert saved["api"]["reasoning_strength"] == ""
    assert saved["cli"].get("reasoning_strength") == "high"  # CLI 槽设置保住


def test_save_runtime_llm_cli_save_preserves_api_reasoning_strength(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "api",
                "reasoning_strength": "low",
                "api": {"base_url": "https://api.example.com/v1", "model": "gpt-5", "api_key": "sk-test", "reasoning_strength": "low"},
                "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": 240},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm("", "", "", channel="cli", cli_runner="codex", reasoning_strength="high")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "cli"
    assert saved["reasoning_strength"] == "high"
    assert saved["api"]["reasoning_strength"] == "low"
    assert saved["cli"]["reasoning_strength"] == "high"


def test_save_runtime_llm_cli_save_can_seed_api_reasoning_strength(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "https://api.example.com/v1",
        "gpt-5",
        "sk-test",
        channel="cli",
        cli_runner="codex",
        reasoning_strength="off",
        api_reasoning_strength="high",
    )

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "cli"
    assert saved["reasoning_strength"] == "off"
    assert saved["api"]["reasoning_strength"] == "high"
    assert saved["cli"]["reasoning_strength"] == "off"


def test_save_runtime_llm_can_clear_reasoning_strength_to_default(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "cli",
                "reasoning_strength": "high",
                "api": {"base_url": "", "model": "", "api_key": ""},
                "cli": {
                    "runner": "codex",
                    "model": "gpt-5.5",
                    "timeout_seconds": 240,
                    "reasoning_strength": "high",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm("", "", "", channel="cli", reasoning_strength="")

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["reasoning_strength"] == ""
    assert "reasoning_strength" not in saved["cli"]


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


def test_load_runtime_llm_preserves_cli_reasoning_strength(tmp_path, monkeypatch):
    path = tmp_path / "runtime_llm.json"
    path.write_text(
        json.dumps(
            {
                "channel": "cli",
                "api": {"base_url": "", "model": "", "api_key": ""},
                "cli": {
                    "runner": "codex",
                    "model": "gpt-5.5",
                    "timeout_seconds": 240,
                    "reasoning_strength": "high",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    runtime = llm_config.load_runtime_llm()

    assert runtime["cli"]["reasoning_strength"] == "high"


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
    # #53:preserve 路径与 fresh 路径产出同一 JSON 形态——数值字段保持数值,不被 stringify。
    # #1472：max_tokens 不再写入；旧档残留也不再 preserve。
    assert "max_tokens" not in saved["api"]
    assert saved["api"]["timeout_seconds"] == 150
    assert isinstance(saved["api"]["timeout_seconds"], (int, float))
    assert not isinstance(saved["api"]["timeout_seconds"], str)
    assert saved["api"]["thinking_level"] == "minimal"
    assert saved["cli"] == {
        "runner": "codex",
        "model": "gpt-5.5",
        "timeout_seconds": 240,
    }


def test_load_runtime_flat_cli_backend_placeholder_not_api_channel(tmp_path, monkeypatch):
    # ship-pre CMR Group A'：真实扁平旧配置（占位符 key + 默认 timeout/
    # base_url/model + 旧档残留 max_tokens）不该被推成 channel=api。
    # 只有「存在真实 API key」才推 api。
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "api_key": "cli-backend",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "max_tokens": 8000,
        "timeout_seconds": 180,
    }), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    out = llm_config.load_runtime_llm()

    assert out["channel"] != "api"


def test_cli_backend_active_explicit_cli_bogus_runner_false_despite_env(monkeypatch):
    # ship-pre CMR Group F'：显式 channel=cli + 不支持 runner，即便 env 有 agy
    # 也不该误报 active（否则执行期 _run_backend_for_config 仍会崩）。
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False


def test_cli_backend_active_total_on_unsupported_runner(monkeypatch):
    # ship-pre CMR Group F：不支持的 runner 不该让守卫崩（应判 not-active，不抛 RuntimeError）。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    from ming_sim import cli_backend
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="", channel="cli", cli_runner="bogus")

    assert cli_backend.cli_backend_active(cfg) is False
    assert cli_backend._backend_label(cfg) == "agy"


def test_create_chat_model_unsupported_cli_runner_raises_unavailable(monkeypatch):
    # ship-pre CMR round-3：显式不支持的 CLI runner 在构造期优雅抛 LLMUnavailable，
    # 而非返回 CliChat、等首次 invoke 才 raw RuntimeError。
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    import pytest as _pytest
    from ming_sim.llm_model import create_chat_model
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(api_key="cli-backend", base_url="", model="x", channel="cli", cli_runner="bogus")

    with _pytest.raises(LLMUnavailable):
        create_chat_model(cfg)


def test_for_role_advanced_drops_placeholder_key():
    # ship-pre CMR round-4：advanced_api_key 占位符不该泄漏到 advanced 角色的 OpenAI client。
    from ming_sim.llm_config import for_role
    from ming_sim.models import LLMConfig

    cfg = LLMConfig(
        api_key="sk-main", base_url="https://api.x/v1", model="m",
        advanced_model="gpt-adv", advanced_api_key="cli-backend", channel="api",
    )
    adv = for_role(cfg, "simulator")

    assert adv.api_key == "sk-main"
    assert adv.api_key != "cli-backend"


def test_load_llm_config_api_mode_clears_placeholder(monkeypatch):
    # ship-pre CMR round-4：API 模式（无 env CLI）下占位符 api_key 不该当真 key，
    # 应清空走索要/报错，而非拿假 key 探 OpenAI。
    import pytest as _pytest
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: "")

    with _pytest.raises(SystemExit):
        llm_config.load_llm_config(base_url="https://api.x/v1", model="m", api_key="cli-backend")


def test_runtime_llm_transport_segment_is_retired(tmp_path, monkeypatch):
    """#1902：transport 段退役——策略不再从 runtime 档读，保存也不再写该段。

    旧档里残留的 transport 段被忽略（load 不炸、不生效），策略恒为 ADR 0157 那套。
    """
    from ming_sim.llm_transport import (
        audience_transport_policy,
        default_transport_policy,
        resolve_transport_policy,
    )

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        # 旧档残留的 transport 段：#1902 后不再被读
        "transport": {"max_attempts": 9, "attempt_timeout_seconds": 999.0,
                      "retry_interval_seconds": 42.0},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    out = llm_config.load_runtime_llm()
    assert "transport" not in out
    assert resolve_transport_policy(out) == default_transport_policy()
    assert resolve_transport_policy() == default_transport_policy()
    # 召对/过月那套（429 一次终止）在固定策略上只做收紧
    audience = audience_transport_policy()
    assert audience.max_attempts == default_transport_policy().max_attempts
    assert audience.retry_429 is False

    llm_config.save_runtime_llm(
        base_url="https://x/v1", model="m", api_key="sk-x", channel="api",
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "transport" not in saved
    assert saved["api"]["model"] == "m"


def test_runtime_llm_default_headers_roundtrip_and_empty_is_status_quo(tmp_path, monkeypatch):
    """#1794：API 槽附加请求头表经既有保存/加载路径原样保留；缺省/空表＝现状。"""
    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    headers = {
        "X-Custom-Session": "sess-fixed-1",
        "User-Agent": "ming-qa/1.0",
    }
    llm_config.save_runtime_llm(
        "https://api.example.com/v1",
        "gpt-test",
        "sk-test",
        channel="api",
        default_headers=headers,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["api"]["default_headers"] == headers

    loaded = llm_config.load_runtime_llm()
    assert loaded["api"]["default_headers"] == headers
    assert loaded["default_headers"] == headers  # 顶层 API alias 与槽同值

    # 未配置 → 空表
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
    }, ensure_ascii=False), encoding="utf-8")
    empty = llm_config.load_runtime_llm()
    assert empty["api"]["default_headers"] == {}


def test_runtime_llm_api_save_preserves_default_headers_when_omitted(tmp_path, monkeypatch):
    """#1794：设置保存重写 API 槽但未带头表时须保留文件中的头（不改 UI 的并存后果）。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {
            "base_url": "https://old.example.com/v1",
            "model": "old",
            "api_key": "sk-old",
            "default_headers": {"X-Keep": "yes", "User-Agent": "ming-qa/1.0"},
        },
        "cli": {"runner": "codex", "model": "gpt-5.5", "timeout_seconds": 240},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "https://new.example.com/v1", "new-model", "sk-new", channel="api",
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["api"]["model"] == "new-model"
    assert saved["api"]["default_headers"] == {"X-Keep": "yes", "User-Agent": "ming-qa/1.0"}
    assert saved["cli"]["runner"] == "codex"  # ADR 0001：API 保存不擦 CLI


def test_runtime_llm_cli_save_preserves_api_default_headers(tmp_path, monkeypatch):
    """#1794 / ADR 0001：保存 CLI 槽保留 API 槽附加头。"""
    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {
            "base_url": "https://api.example.com/v1",
            "model": "gpt-api",
            "api_key": "sk-api",
            "default_headers": {"X-Session": "keep-me"},
        },
        "cli": {"runner": "", "model": "", "timeout_seconds": ""},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))

    llm_config.save_runtime_llm(
        "", "", "",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["channel"] == "cli"
    assert saved["api"]["default_headers"] == {"X-Session": "keep-me"}
    assert saved["api"]["api_key"] == "sk-api"

