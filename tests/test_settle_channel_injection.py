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

import pytest

import ming_sim.decree as decree
import ming_sim.cli_backend as _cb
from ming_sim.decree import settle_with_delta
from ming_sim.models import LLMConfig



def _decree_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(state, action_type="policy", decree_text="测试国策来源", target_kind="issue", target_id="test")
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"

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
    delta = {"new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "注入通道国策", "kind": "initiative"}]}
    monkeypatch.setattr(decree, "build_extractor_shared_context", lambda *a, **k: "")
    monkeypatch.setattr(decree, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree, "create_score_extractor_module_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree, "extract_scores_by_modules_with_agno",
                        lambda *a, **k: (delta, "extractor-out", "extractor-in"))
    # 本用例只验 channel-aware delta_applier 的闭包注入；章节记忆是同一真实
    # settle 路径上的另一条 LLM 调用。若不封闭它，全量共享进程里前序测试已
    # bind agents content，factory 会成功并真的 spawn chapter-memory（约 19s）；
    # 单跑则因未 bind 而立即降级，仅 0.02s。
    chapter_calls = []
    chapter_agent = object()
    monkeypatch.setattr(decree, "create_chapter_memory_agent", lambda *a, **k: chapter_agent)
    monkeypatch.setattr(
        decree,
        "record_chapter_memory",
        lambda *args, **kwargs: chapter_calls.append((args, kwargs)),
    )

    decree._settle_after_narrative(
        state, db, None, _cli_cfg(),
        decree_text="试旨", narrative="本月邸报。",
        simulator_payload={"transit_semantics": []}, relevant_memories=[], secret_orders=[],
        before_turn=state.turn, _emit=lambda *a, **k: None,
        content=content, registry=None,
    )

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='注入通道国策'").fetchone()
    assert row is not None
    assert _j.loads(row["effect_on_resolve"]) == {"metrics": {"民心": 1}}
    assert len(chapter_calls) == 1
    assert chapter_calls[0][0][0] is chapter_agent


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
    delta = {"new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "driver国策", "kind": "initiative"}]}

    settle_with_delta(state, db, delta, before_turn=state.turn, content=content, registry=None)

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='driver国策'").fetchone()
    assert row is not None
    assert called == []
    assert _j.loads(row["effect_on_resolve"]) == {}


def test_settle_none_branch_legacy_env_enriches(game, monkeypatch):
    """钉住 settle_with_delta 的**裸 None 分支**语义:delta_applier=None 时
    apply_score_extraction(llm_config=None),`cli_backend_active(None)` 仍回落
    MING_SIM_LLM_BACKEND → legacy enrichment(floor)。注:#54 后**探针 driver 已不走此裸
    None 分支**(driver 注入确定性 applier,见 test_driver_run_settle_deterministic_under_legacy_env);
    此分支保留为安全默认,行为不变。"""
    db, state, content = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    delta = {"new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "none分支国策", "kind": "initiative"}]}

    settle_with_delta(state, db, delta, before_turn=state.turn, content=content, registry=None)

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='none分支国策'").fetchone()
    assert row is not None
    assert _j.loads(row["effect_on_resolve"]) == {"metrics": {"民心": 1}}


def test_driver_run_settle_records_malformed_delta(game):
    """ADR0015：driver.run_settle 对可拆畸形 delta 逐项拒收留痕，净化后继续。"""
    from tests.section_rejection_helpers import prepare_then_settle
    db, state, content = game
    turn = state.turn
    prepare_then_settle(db, state, content, {
        "metric_delta": {"国库": 50},
        "region_delta": {"shanxi": "not-a-dict"},
    })
    rows = db.conn.execute("SELECT section, item_json FROM rejection_reports WHERE turn=?", (turn,)).fetchall()
    assert any(r["section"] == "region_delta" and '"entity_id": "shanxi"' in r["item_json"] for r in rows)


def test_driver_run_settle_deterministic_under_legacy_env(game, monkeypatch):
    """#54:探针 driver(run_settle)即便设了 MING_SIM_LLM_BACKEND 也**绝不** spawn CLI
    enrichment——dialogue-Claude 已自产完整 delta,落库核不得再起第二个 LLM(ADR-0004)。
    注入确定性 applier 使 cli_backend_active 恒 False,enrich 不被调用、国策效果不落 floor。"""
    from tests.section_rejection_helpers import prepare_then_settle
    db, state, content = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    called = []
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: called.append((a, k)) or {
                            "effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})

    prepare_then_settle(
        db, state, content,
        {"new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "driver确定性国策", "kind": "initiative"}]},
        narrative="本月邸报。",
    )

    assert called == []   # driver 确定性:enrich 从未被调用
    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='driver确定性国策'").fetchone()
    assert row is not None
    assert _j.loads(row["effect_on_resolve"]) == {}   # 无 enrichment、无 floor
