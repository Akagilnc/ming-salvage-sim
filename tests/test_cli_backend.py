"""Public CLI invocation/config contracts; subprocess is the external seam."""
from __future__ import annotations

import argparse
import json
import os
from types import SimpleNamespace

import pytest
from agno.models.message import Message

import ming_sim.cli_backend as cb
from ming_sim.exceptions import LLMUnavailable
from tests.cli_process_doubles import FakeCliProcess


def _capture_run(monkeypatch, *, stdout="OK", stderr="", returncode=0):
    captured = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = list(cmd)
        captured["kw"] = kw
        return FakeCliProcess(
            cmd, stdout_script=((stdout,) if stdout else ()),
            stderr_script=((stderr,) if stderr else ()),
            returncode=returncode, popen_kwargs=kw,
        )

    monkeypatch.setattr(cb.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    return captured


@pytest.mark.parametrize("runner,model,flags", [
    ("agy", "agy", []),
    ("codex", "gpt-test", ["--ignore-user-config", "--sandbox", "read-only", "--ephemeral"]),
    ("claude", "claude-test", ["--restricted", "--strict-mcp-config", "Read", "Glob", "Grep", "dontAsk"]),
    ("cursor", "auto", ["ask", "enabled"]),
    ("kimi", "kimi-k2", ["--agent-file"]),
    ("grok", "grok-4.5", ["Read,Glob,Grep", "read-only"]),
    ("pi", "openai/gpt-4o", ["read,grep,find,ls", "--no-session", "--no-extensions", "--no-context-files"]),
])
def test_material_runner_uses_cwd_and_read_only_tool_surface(monkeypatch, tmp_path, runner, model, flags):
    root = str(tmp_path / "materials")
    os.mkdir(root)
    captured = _capture_run(monkeypatch, stderr="provider diagnostics")
    chat = cb.CliChat(id=model, backend=runner, materials_dir=root, reasoning_strength="medium")
    response = chat.invoke([Message(role="user", content="request")], Message(role="assistant"))
    assert response.role == "assistant"
    assert response.event == "AssistantResponse"
    assert response.tool_calls == []
    assert captured["kw"]["cwd"] == root
    cmd = captured["cmd"]
    assert all(flag in cmd for flag in flags)
    if runner == "agy":
        assert any(arg.startswith("--print=") for arg in cmd)
        assert "--sandbox" not in cmd
    elif runner == "claude":
        assert cmd[cmd.index("--model") + 1] == model
        assert json.loads(cmd[cmd.index("--mcp-config") + 1]) == {"mcpServers": {}}
    elif runner == "kimi":
        assert cmd[cmd.index("-m") + 1] == model
        assert not os.path.exists(cmd[cmd.index("--agent-file") + 1])
        assert not any(flag in cmd for flag in ("--yolo", "-y", "--auto"))
    elif runner == "grok":
        assert cmd[cmd.index("-m") + 1] == model
        assert cmd[cmd.index("--effort") + 1] == "med"
        assert "--always-approve" not in cmd
    elif runner == "pi":
        assert cmd[cmd.index("--model") + 1] == model
        assert cmd[cmd.index("--thinking") + 1] == "medium"
    else:
        assert cmd[cmd.index("--model") + 1] == model


@pytest.mark.parametrize("runner", ["agy", "codex", "claude", "cursor", "kimi", "grok", "pi"])
@pytest.mark.parametrize("stdout,returncode", [("", 1), ("", 0)])
def test_run_runner_fail_loud_on_bad_exit(monkeypatch, runner, stdout, returncode):
    captured = _capture_run(monkeypatch, stdout=stdout, returncode=returncode)
    chat = cb.CliChat(id="m", backend=runner)
    with pytest.raises(LLMUnavailable) as failure:
        chat.invoke([Message(role="user", content="request")], Message(role="assistant"))
    assert failure.value.code == ("llm_empty_output" if returncode == 0 else f"llm_cli_{runner}")
    assert captured["cmd"]


@pytest.mark.parametrize("banner", ["Authentication required", "authentication timed out"])
def test_run_agy_auth_race_is_retryable_typed_without_private_loop(monkeypatch, banner):
    captured = _capture_run(monkeypatch, stdout=banner)
    with pytest.raises(LLMUnavailable) as failure:
        cb.CliChat(id="m", backend="agy").invoke(
            [Message(role="user", content="request")], Message(role="assistant"),
        )
    assert failure.value.code == "llm_connection_error"
    assert captured["cmd"]


def test_kimi_material_file_is_removed_on_start_failure(monkeypatch, tmp_path):
    created = []
    real_temp = cb.tempfile.NamedTemporaryFile

    def tracked_temp(*args, **kwargs):
        handle = real_temp(*args, **kwargs)
        created.append(handle.name)
        return handle

    def fail_start(*args, **kwargs):
        raise FileNotFoundError("provider unavailable")

    monkeypatch.setattr(cb.tempfile, "NamedTemporaryFile", tracked_temp)
    monkeypatch.setattr(cb.subprocess, "Popen", fail_start)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    with pytest.raises(LLMUnavailable):
        cb.CliChat(id="kimi-k2", backend="kimi", materials_dir=str(tmp_path)).invoke(
            [Message(role="user", content="request")], Message(role="assistant"),
        )
    assert created
    assert all(not os.path.exists(path) for path in created)


def test_clichat_codex_response_stream_passes_reasoning_strength(monkeypatch):
    captured = _capture_run(monkeypatch, stdout=json.dumps({
        "type": "item.completed", "item": {"type": "agent_message", "text": "reply"},
    }) + "\n")
    list(cb.CliChat(id="gpt-test", backend="codex", reasoning_strength="low").response_stream([
        Message(role="user", content="request"),
    ]))
    assert "--json" in captured["cmd"]
    assert "model_reasoning_effort=\"low\"" in captured["cmd"]


def test_clichat_call_cli_unknown_backend_raises(monkeypatch):
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    with pytest.raises(LLMUnavailable):
        cb.CliChat(id="m", backend="bogus").invoke(
            [Message(role="user", content="request")], Message(role="assistant"),
        )


def test_enrich_army_parsed_and_normalized(monkeypatch):
    canned = json.dumps({
        "effect_on_resolve": {"new_armies": [{"id": "qinjun", "name": "秦兵", "owner_power": "ming",
            "manpower": 20000, "maintenance_per_turn": 4, "commander": "孙传庭"}]},
        "ongoing_effects": {}, "effect_on_fail": {},
    }, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt, **kw: (canned, 1))
    out = cb.enrich_initiative_effects("孙传庭练秦兵", "陕西督练新军")
    assert out["effect_on_resolve"]["new_armies"][0]["id"] == "qinjun"
    assert out["effect_on_resolve"]["new_armies"][0]["manpower"] == 20000


def test_enrich_building_region_floor(monkeypatch):
    canned = json.dumps({"effect_on_resolve": {"buildings": [{"action": "create", "name": "格致局", "category": "科技"}]},
        "ongoing_effects": {}, "effect_on_fail": {}}, ensure_ascii=False)
    monkeypatch.setattr(cb, "_run_agy", lambda prompt, **kw: (canned, 1))
    out = cb.enrich_initiative_effects("设格致局", "")
    assert out["effect_on_resolve"]["buildings"][0]["region_id"] == "beizhili"


@pytest.mark.parametrize("reply", [None, '{"effect_on_resolve":"bad","ongoing_effects":[1],"effect_on_fail":3}'])
def test_enrich_backend_error_returns_empty_effects(monkeypatch, reply):
    def backend(prompt):
        if reply is None:
            raise RuntimeError("backend down")
        return reply, 1

    monkeypatch.setattr(cb, "_run_backend", backend)
    monkeypatch.setattr(cb, "_trace", lambda rec: None)
    assert cb.enrich_initiative_effects("设局", "") == {
        "effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {},
    }


@pytest.mark.parametrize("runner", ["agy", "codex", "claude", "cursor", "kimi", "grok", "pi", "bogus"])
def test_backend_env(monkeypatch, runner):
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", runner)
    assert cb.cli_backend_from_env() == (None if runner == "bogus" else runner)


def test_gate_llm_config_cli_channel():
    args = SimpleNamespace(channel="cli", runner="codex", model="gpt-test", api_key="", base_url="")
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.channel == "cli"
    assert cfg.cli_runner == "codex" and cfg.cli_model == "gpt-test"
    assert cfg.api_key == "" and cfg.base_url == ""


def test_gate_llm_config_api_from_args_not_persisted_shape(monkeypatch):
    for key in ("OPENAI_API_KEY", "MING_SIM_API_KEY", "OPENAI_BASE_URL", "MING_SIM_API_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    args = SimpleNamespace(channel="api", runner="", model="api-model", api_key="sk-test", base_url="https://example.test/v1")
    cfg = cb.gate_llm_config_from_args(args)
    assert cfg.channel == "api"
    assert cfg.model == "api-model"
    assert cfg.api_key == "sk-test" and cfg.base_url == "https://example.test/v1"
    assert cfg.cli_runner == ""


def test_gate_llm_config_api_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    cfg = cb.gate_llm_config_from_args(SimpleNamespace(channel="api", runner="", model="m", api_key="", base_url=""))
    assert cfg.api_key == "sk-env" and cfg.base_url == "https://example.test/v1"


def test_gate_llm_config_cli_requires_runner():
    with pytest.raises(ValueError):
        cb.gate_llm_config_from_args(SimpleNamespace(channel="cli", runner="", model="m", api_key="", base_url=""))


def test_gate_llm_config_api_requires_key_and_url(monkeypatch):
    for key in ("OPENAI_API_KEY", "MING_SIM_API_KEY", "OPENAI_BASE_URL", "MING_SIM_API_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    args = SimpleNamespace(channel="api", runner="", model="m", api_key="", base_url="")
    with pytest.raises(ValueError):
        cb.gate_llm_config_from_args(args)
    args.api_key = "sk-x"
    with pytest.raises(ValueError):
        cb.gate_llm_config_from_args(args)


def test_gate_evidence_config_honest_cli_and_api():
    for channel, runner, key, url in [("cli", "claude", "", ""), ("api", "codex", "sk", "https://example.test/v1")]:
        args = SimpleNamespace(channel=channel, runner=runner, model="m", api_key=key, base_url=url)
        block = cb.gate_evidence_config(args, cb.gate_llm_config_from_args(args))
        assert block["channel"] == channel
        assert block["runner"] == (runner if channel == "cli" else "")
        assert block["model"] == "m"


def test_add_gate_llm_args_uses_gate_cli_runners():
    parser = argparse.ArgumentParser()
    cb.add_gate_llm_args(parser)
    with pytest.raises(SystemExit):
        parser.parse_args(["--runner", "opencode", "--model", "m"])
    args = parser.parse_args(["--runner", "claude", "--model", "m", "--channel", "cli"])
    assert args.runner == "claude" and args.model == "m"
