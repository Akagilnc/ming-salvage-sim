"""Minister chat uses a short timeout (≤ MINISTER_CHAT_CLI_TIMEOUT_SECONDS),
decoupled from settlement's long timeout (issue #353).

#1185: observe the constructed model.timeout (public agent seam), not
create_chat_model kwargs key names. Original LLMConfig must stay untouched.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

from ming_sim.models import CLI_DEFAULT_TIMEOUT_SECONDS, MINISTER_CHAT_CLI_TIMEOUT_SECONDS, LLMConfig
from ming_sim.registry import create_minister_agent


def _cfg_settlement_timeout(*, channel: str = "cli") -> LLMConfig:
    if channel == "cli":
        return LLMConfig(
            api_key="",
            base_url="",
            model="gpt-5.5",
            channel="cli",
            cli_runner="codex",
            cli_model="gpt-5.5",
            cli_timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
            timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
        )
    return LLMConfig(
        api_key="sk-test",
        base_url="https://example.com/v1",
        model="gpt-4",
        timeout_seconds=CLI_DEFAULT_TIMEOUT_SECONDS,
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


def _make_character() -> MagicMock:
    ch = MagicMock()
    ch.name = "测试大臣"
    ch.office = "内阁"
    ch.office_type = "cabinet"
    ch.personal_skills = ["谋略"]
    ch.style = "周正"
    ch.summary = "测试"
    ch.power_id = "ming"
    return ch


_REGISTRY_STUBS = [
    ("ming_sim.registry.build_character_knowledge_brief", ""),
    ("ming_sim.registry.build_recommendation_brief", ""),
    ("ming_sim.registry.build_secret_order_brief", ""),
    ("ming_sim.registry.build_minister_tools", []),
    ("ming_sim.registry._skills_for", MagicMock()),
    ("ming_sim.registry.character_context_with_db", "角色描述"),
]


@contextmanager
def _minister_agent_construction(ctx):
    """Stub registry side seams; keep real create_chat_model so model.timeout is live."""
    with ExitStack() as stack:
        for name, val in _REGISTRY_STUBS:
            stack.enter_context(patch(name, return_value=val))
        stack.enter_context(
            patch(
                "ming_sim.registry.Agent",
                side_effect=lambda **kwargs: MagicMock(model=kwargs.get("model")),
            )
        )
        stack.enter_context(patch("ming_sim.registry._ctx", return_value=ctx))
        yield


def test_minister_agent_cli_timeout_capped():
    """CLI minister agent model.timeout is capped even when cfg carries settlement 300s."""
    ctx = _make_context()
    cfg = _cfg_settlement_timeout(channel="cli")
    with _minister_agent_construction(ctx):
        agent = create_minister_agent(_make_character(), cfg, ctx, ctx.db)

    timeout = getattr(agent.model, "timeout", None)
    assert timeout is not None
    assert float(timeout) <= MINISTER_CHAT_CLI_TIMEOUT_SECONDS
    assert float(timeout) < CLI_DEFAULT_TIMEOUT_SECONDS


def test_minister_agent_api_timeout_capped():
    """API minister agent model.timeout is capped even when cfg carries settlement 300s."""
    ctx = _make_context()
    cfg = _cfg_settlement_timeout(channel="api")
    with _minister_agent_construction(ctx):
        agent = create_minister_agent(_make_character(), cfg, ctx, ctx.db)

    timeout = getattr(agent.model, "timeout", None)
    assert timeout is not None
    assert float(timeout) <= MINISTER_CHAT_CLI_TIMEOUT_SECONDS
    assert float(timeout) < CLI_DEFAULT_TIMEOUT_SECONDS


def test_minister_agent_does_not_mutate_original_llm_config():
    """create_minister_agent must not modify the caller's LLMConfig (no side-effects)."""
    original_cli = CLI_DEFAULT_TIMEOUT_SECONDS
    original_api = CLI_DEFAULT_TIMEOUT_SECONDS
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
    with _minister_agent_construction(ctx):
        agent = create_minister_agent(_make_character(), cfg, ctx, ctx.db)

    assert cfg.cli_timeout_seconds == original_cli
    assert cfg.timeout_seconds == original_api
    # constructed model is capped while caller cfg stays long
    assert float(getattr(agent.model, "timeout", 0)) <= MINISTER_CHAT_CLI_TIMEOUT_SECONDS
