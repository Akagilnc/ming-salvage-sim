"""通道 enrichment 经 settle_with_delta 的注入闭包回归（ADR-0004 一致）。

base 的 ADR-0004 把月末结算抽成「不依赖 llm_config 的确定性核 settle_with_delta
+ 注入闭包（chapter_recorder / ending_summarizer）」。通道分支的 issue enrichment /
office 推断靠 llm_config 选 channel，藏在 apply_score_extraction 里。两者相撞后，
真实流若不把 llm_config 经注入闭包送进结算核，通道 enrichment 会被静默关掉。

- 真实流（_settle_after_narrative）：注入捕获 llm_config 的 delta_applier → CLI 通道
  enrich 空时落 floor，证明 llm_config 到达 apply_score_extraction。
- 探针 driver 路径（settle_with_delta 无 delta_applier）+ **无 legacy env**：确定性
  apply，不 enrich，effect 留空——settle_with_delta 本体不依赖 llm_config（ADR-0004 纯度）。
- 探针 driver 路径 + **设了 legacy env（MING_SIM_LLM_BACKEND）**：apply_score_extraction
  对 llm_config=None 仍按旧 env 判定，故仍触发 legacy enrichment/floor（base 既有行为，
  非绝对确定性；是否在 driver 屏蔽属 probe 设计待决）。
"""

from __future__ import annotations

import json as _j

import ming_sim.decree as decree
import ming_sim.cli_backend as _cb
from ming_sim.decree import settle_with_delta
from ming_sim.models import LLMConfig


def _cli_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )


def test_real_flow_injects_channel_enrichment_into_settle(game, monkeypatch):
    """_settle_after_narrative 须把 llm_config 经 delta_applier 闭包送进结算核：
    CLI 通道 + enrich 空 → 新国策落 floor（民心+1），证明通道未被静默关掉。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    # enrich 返回空 → 触发 CLI floor 兜底（与 test_issue_entities 同款探针）。
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    # 绕过真实 extractor LLM：直接喂一份 canonical delta。
    delta = {"new_issues": [{"origin_kind": "decree", "title": "注入通道国策", "kind": "initiative"}]}
    monkeypatch.setattr(decree, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: (delta, "extractor-out", "extractor-in"))

    decree._settle_after_narrative(
        state, db, None, _cli_cfg(),
        decree_text="试旨", narrative="本月邸报。",
        simulator_payload={}, relevant_memories=[], secret_orders=[],
        before_turn=state.turn, _emit=lambda *a, **k: None,
        content=content, registry=None,
    )

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='注入通道国策'").fetchone()
    assert row is not None
    assert _j.loads(row["effect_on_resolve"]) == {"metrics": {"民心": 1}}


def test_driver_path_no_env_is_deterministic(game, monkeypatch):
    """settle_with_delta 无 delta_applier + 无 legacy env（driver 默认）= 确定性 apply，
    不 enrich：新国策 effect 留空，证明结算核本体不注入运行时通道。"""
    db, state, content = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    # 无闭包 + 无 env：enrich 不该被调用。
    called = []
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: called.append((a, k)) or {
                            "effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    delta = {"new_issues": [{"origin_kind": "decree", "title": "driver国策", "kind": "initiative"}]}

    settle_with_delta(state, db, delta, before_turn=state.turn, content=content, registry=None)

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='driver国策'").fetchone()
    assert row is not None
    assert called == []
    assert _j.loads(row["effect_on_resolve"]) == {}


def test_driver_path_legacy_env_still_enriches(game, monkeypatch):
    """钉住现状（CMR R1）：delta_applier=None 不等于「绝对无 LLM」——apply_score_extraction
    对 llm_config=None 仍按旧 env 后端判定，`cli_backend_active(None)` 回落
    MING_SIM_LLM_BACKEND。故 driver 路径在 env 设置时仍会触发 legacy enrichment（floor）。
    这是 base 既有行为；是否在 driver 屏蔽 legacy env 属 probe 设计待决（deferred）。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    delta = {"new_issues": [{"origin_kind": "decree", "title": "driver-env国策", "kind": "initiative"}]}

    settle_with_delta(state, db, delta, before_turn=state.turn, content=content, registry=None)

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='driver-env国策'").fetchone()
    assert row is not None
    # legacy env 路径触发 floor 兜底，非空壳——证明 None 路径并非绝对确定性。
    assert _j.loads(row["effect_on_resolve"]) == {"metrics": {"民心": 1}}
