from __future__ import annotations

import json

from ming_sim import llm_config


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


def test_runtime_llm_transport_slot_defaults_and_preserve(tmp_path, monkeypatch):
    """#1465：transport 与 api/cli 平级；旧档无段填默认；保存通道时保留 transport。"""
    from ming_sim.models import (
        TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_MAX_ATTEMPTS,
    )

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert out["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert out["transport"]["idle_timeout_seconds"] == TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS

    llm_config.save_runtime_llm(
        base_url="https://x/v1",
        model="m",
        api_key="sk-x",
        channel="api",
        transport_max_attempts=5,
        transport_attempt_timeout_seconds=12.5,
        transport_idle_timeout_seconds=9.0,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["transport"] == {
        "max_attempts": 5,
        "attempt_timeout_seconds": 12.5,
        "idle_timeout_seconds": 9.0,
    }
    # 再存 API 不显式传 transport → 保留既有段（ADR 0001 平级不擦）
    llm_config.save_runtime_llm(
        base_url="https://x/v1", model="m2", api_key="sk-y", channel="api",
    )
    saved2 = json.loads(path.read_text(encoding="utf-8"))
    assert saved2["api"]["model"] == "m2"
    assert saved2["transport"]["max_attempts"] == 5


def test_runtime_llm_transport_nonpositive_falls_back_to_defaults(tmp_path, monkeypatch):
    """#1465 fo2Nb：transport 非正数（0/负）回落 typed 默认，不进空 range/即死预算。"""
    from ming_sim.llm_transport import transport_policy_from_mapping
    from ming_sim.models import (
        TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS,
        TRANSPORT_DEFAULT_MAX_ATTEMPTS,
    )

    path = tmp_path / "runtime_llm.json"
    path.write_text(json.dumps({
        "channel": "api",
        "api": {"base_url": "https://x/v1", "model": "m", "api_key": "sk-x"},
        "transport": {
            "max_attempts": 0,
            "attempt_timeout_seconds": -1,
            "idle_timeout_seconds": 0,
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(llm_config, "RUNTIME_LLM_PATH", str(path))
    out = llm_config.load_runtime_llm()
    assert out["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert out["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert out["transport"]["idle_timeout_seconds"] == TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS
    policy = transport_policy_from_mapping(out)
    assert policy.max_attempts == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert policy.attempt_timeout_seconds == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert policy.idle_timeout_seconds == TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS
    # 保存路径同样经单权威：显式 0 不得落盘为 0
    llm_config.save_runtime_llm(
        base_url="https://x/v1",
        model="m",
        api_key="sk-x",
        channel="api",
        transport_max_attempts=0,
        transport_attempt_timeout_seconds=0.0,
        transport_idle_timeout_seconds=-5.0,
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["transport"]["max_attempts"] == TRANSPORT_DEFAULT_MAX_ATTEMPTS
    assert saved["transport"]["attempt_timeout_seconds"] == TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    assert saved["transport"]["idle_timeout_seconds"] == TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS
