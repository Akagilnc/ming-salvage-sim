"""Minister chat uses a short timeout (≤ MINISTER_CHAT_CLI_TIMEOUT_SECONDS), decoupled from
settlement's 300 s timeout (issue #353).

Tests verify external behaviour through public interfaces only:
- create_minister_agent produces a model whose timeout config is short.
- MINISTER_CHAT_CLI_TIMEOUT_SECONDS < CLI_DEFAULT_TIMEOUT_SECONDS (constant contract).
"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
from unittest.mock import MagicMock, patch

from ming_sim.models import CLI_DEFAULT_TIMEOUT_SECONDS, MINISTER_CHAT_CLI_TIMEOUT_SECONDS, LLMConfig
from ming_sim.registry import create_minister_agent

def _cfg_300() -> LLMConfig:
    """A CLI-channel config that mimics the full settlement timeout (300 s)."""
    return LLMConfig(
        api_key="",
        base_url="",
        model="gpt-5.5",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,  # 300 s
    )

def _make_context() -> MagicMock:
    state = MagicMock(year=1640, period=1, turn=1)
    db_mock = MagicMock()
    db_mock.get_consort_traits.return_value = {"extra_skills": [], "extra_traits": []}
    db_mock.conn.execute.return_value.fetchone.return_value = [0]
    db_mock.get_character_status.return_value = ("active", "在朝")
    db_mock.resolve_power_id.return_value = "ming"
    db_mock.army_roster.return_value = ""
    ctx = MagicMock()
    ctx.state = state
    ctx.db = db_mock
    ctx.game_world_prompt = ""
    ctx.minister_agent_prompt = ""
    ctx.consort_agent_prompt = ""
    ctx.characters = {}
    return ctx

def _make_character(is_consort: bool = False) -> MagicMock:
    ch = MagicMock()
    ch.name = "测试大臣"
    ch.office = "内阁"
    ch.office_type = "后宫" if is_consort else "cabinet"
    ch.personal_skills = ["谋略"]
    ch.style = "周正"
    ch.summary = "测试"
    ch.power_id = "ming"
    return ch

_REGISTRY_PATCHES = [
    ("ming_sim.registry.build_character_knowledge_brief", ""),
    ("ming_sim.registry.build_recommendation_brief", ""),
    ("ming_sim.registry.build_secret_order_brief", ""),
    ("ming_sim.registry.build_minister_tools", []),
    ("ming_sim.registry._skills_for", MagicMock()),
    ("ming_sim.registry.character_context_with_db", "角色描述"),
    ("ming_sim.registry.Agent", MagicMock(return_value=MagicMock())),
]

# ── create_minister_agent uses short CLI timeout ──────────────────────────────

def test_minister_agent_cli_timeout_capped():
    """Agent created for minister chat must use a CLI timeout ≤ MINISTER_CHAT_CLI_TIMEOUT_SECONDS,
    even when LLMConfig.cli_timeout_seconds is the full 300 s settlement value."""
    captured: dict = {}

    def fake_create_chat_model(cfg: LLMConfig, **kwargs):
        captured["cli_timeout"] = cfg.cli_timeout_seconds
        return MagicMock()

    ctx = _make_context()
    character = _make_character()

    patches = [patch(name, return_value=val) for name, val in _REGISTRY_PATCHES]
    patches.append(patch("ming_sim.registry.create_chat_model", fake_create_chat_model))
    patches.append(patch("ming_sim.registry._ctx", return_value=ctx))

    with _nested_patches(patches):
        create_minister_agent(character, _cfg_300(), ctx, ctx.db)

    assert "cli_timeout" in captured, "create_chat_model was not called"
    assert captured["cli_timeout"] <= MINISTER_CHAT_CLI_TIMEOUT_SECONDS, (
        f"CLI timeout {captured['cli_timeout']} exceeds cap {MINISTER_CHAT_CLI_TIMEOUT_SECONDS}"
    )

def test_minister_agent_api_timeout_capped():
    """For API channel, minister agent must use timeout_seconds ≤ MINISTER_CHAT_CLI_TIMEOUT_SECONDS."""
    captured: dict = {}

    def fake_create_chat_model(cfg: LLMConfig, **kwargs):
        captured["timeout_seconds"] = cfg.timeout_seconds
        return MagicMock()

    ctx = _make_context()
    character = _make_character()

    api_cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="gpt-4",
        timeout_seconds=300.0,  # same large value as settlement
    )

    patches = [patch(name, return_value=val) for name, val in _REGISTRY_PATCHES]
    patches.append(patch("ming_sim.registry.create_chat_model", fake_create_chat_model))
    patches.append(patch("ming_sim.registry._ctx", return_value=ctx))

    with _nested_patches(patches):
        create_minister_agent(character, api_cfg, ctx, ctx.db)

    assert "timeout_seconds" in captured
    assert captured["timeout_seconds"] <= MINISTER_CHAT_CLI_TIMEOUT_SECONDS, (
        f"API timeout {captured['timeout_seconds']} exceeds cap {MINISTER_CHAT_CLI_TIMEOUT_SECONDS}"
    )

def test_minister_agent_does_not_mutate_original_llm_config():
    """create_minister_agent must not modify the caller's LLMConfig (no side-effects)."""
    original_cli = 300.0
    original_api = 300.0
    cfg = _cfg_300()
    cfg = LLMConfig(
        api_key="",
        base_url="",
        model="gpt-5.5",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=original_cli,
        timeout_seconds=original_api,
    )

    ctx = _make_context()
    character = _make_character()

    patches = [patch(name, return_value=val) for name, val in _REGISTRY_PATCHES]
    patches.append(patch("ming_sim.registry.create_chat_model", return_value=MagicMock()))
    patches.append(patch("ming_sim.registry._ctx", return_value=ctx))

    with _nested_patches(patches):
        create_minister_agent(character, cfg, ctx, ctx.db)

    assert cfg.cli_timeout_seconds == original_cli, "original config was mutated"
    assert cfg.timeout_seconds == original_api, "original config was mutated"

# ── helper ────────────────────────────────────────────────────────────────────

@contextmanager
def _nested_patches(patch_list):
    """Enter all patches in a list and yield, then exit all."""
    with ExitStack() as stack:
        for p in patch_list:
            stack.enter_context(p)
        yield
