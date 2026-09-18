"""#1837 C1a：召对转译——交办载荷与应允。

Seams:
- translate_audience_turn / run_audience_turn_translation（转译 → C0 分派）
- GameSession.scene_chat（回话后转译；退役并行分类器）
- close_night 收夜成案 → 过月落账
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    close_night,
    get_open_night,
    mark_actions_night_approved,
    open_night,
)
from ming_sim.audience_translate import (
    apply_audience_turn_translation,
    normalize_audience_declaration,
    run_audience_turn_translation,
    translate_audience_turn,
)
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.session import GameSession


def _sess(db, state, content, *, llm_config=None, translate_fn=None):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = None
    sess._audience_translate_fn = translate_fn
    return sess


def _region_id(db, preferred: str = "shaanxi") -> str:
    row = db.conn.execute(
        "SELECT id FROM regions WHERE id=? LIMIT 1", (preferred,),
    ).fetchone()
    if row is not None:
        return str(row["id"])
    row = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def _hong_name(db, content) -> str:
    if "洪承畴" in getattr(content, "characters", {}):
        return "洪承畴"
    row = db.conn.execute(
        "SELECT name FROM characters WHERE name='洪承畴' LIMIT 1"
    ).fetchone()
    if row is not None:
        return str(row["name"])
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def test_normalize_keeps_only_c1a_sections():
    raw = {
        "commissions": [{"text": "拟旨"}],
        "promises": [{"action_id": 1, "decision": "应允"}],
        "presence": [{"name": "王绍徽", "effect": "enter"}],
        "noise": 1,
    }
    out = normalize_audience_declaration(raw)
    assert set(out) == {"commissions", "promises"}
    assert out["commissions"] == [{"text": "拟旨"}]
    assert out["promises"] == [{"action_id": 1, "decision": "应允"}]


def test_appointment_and_relief_grant_stages_typed_then_close_and_settle(game):
    """AC1：任命+赈灾经转译落暂存（载荷 typed），应允收夜成案，过月落账。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    person = _hong_name(db, content)
    region = _region_id(db)
    edict = f"任命{person}为陕西巡抚，调银三十万两赈灾"

    declaration = {
        "commissions": [{
            "text": edict,
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
            "grant": {
                "grant_action": "赈灾",
                "amount": 30,
                "account": "国库",
                "target_kind": "region",
                "target_id": region,
                "cadence": "一次性",
                "execution_surface": "immediate",
            },
        }],
    }
    result = dispatch_declaration(
        db, state, declaration, minister_name="", night_id=night_id,
    )
    assert result.commissions.rejected == [], result.commissions.rejected
    kinds = {row["kind"] for row in result.commissions.applied}
    assert "directive" in kinds
    assert "office" in kinds

    # typed 载荷：拨帑与任免同挂
    directive = next(r for r in result.commissions.applied if r["kind"] == "directive")
    payload = directive["payload"]
    assert payload["text"] == edict
    assert payload["grant_action"] == "赈灾"
    assert int(payload["amount"]) == 30
    assert payload["account"] == "国库"
    assert payload["target_id"] == region
    assert payload["name"] == person
    assert payload["office"] == "陕西巡抚"

    office = next(r for r in result.commissions.applied if r["kind"] == "office")
    assert office["payload"]["name"] == person
    assert office["payload"]["office"] == "陕西巡抚"

    # 应允全部本夜交办 → 收夜成案
    ids = [int(r["id"]) for r in result.commissions.applied]
    mark_actions_night_approved(db, ids, night_id=night_id)
    close_night(db, state, content=content, registry=None, wait_timeout_s=0.0)

    office_row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (int(office["id"]),),
    ).fetchone()
    assert office_row["status"] == "committed"

    dir_row = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE id=?",
        (int(directive["id"]),),
    ).fetchone()
    assert dir_row["status"] == "committed"
    assert int(dir_row["committed_directive_id"] or 0) > 0

    # appointment 案卷
    appt = db.conn.execute(
        "SELECT id, status, action_type, target_id FROM decree_dossiers "
        "WHERE action_type='appointment' AND target_id=? "
        "ORDER BY id DESC LIMIT 1",
        (person,),
    ).fetchone()
    assert appt is not None
    assert appt["status"] in {"proposed", "promulgated", "executing", "closed"}

    # grant 案卷（draft directive → ensure dossier）
    grant_dossiers = [
        d for d in db.list_decree_dossiers()
        if d["action_type"] == "grant_allocation"
        and str(d.get("target_id") or "") == region
    ]
    assert grant_dossiers, "收夜后应有赈灾 grant 案卷"

    # 过月落账：颁布 + 物化
    treasury_before = int(state.metrics.get("国库") or 0)
    state.metrics["国库"] = max(treasury_before, 100)
    db.save_state(state)

    for d in grant_dossiers:
        db.apply_dossier_promulgation(
            state, int(d["id"]), decision="promulgated", content=content,
        )
    if appt is not None and str(appt["status"]) == "proposed":
        db.apply_dossier_promulgation(
            state, int(appt["id"]), decision="promulgated", content=content,
        )

    # 职
    char = db.conn.execute(
        "SELECT office, status FROM characters WHERE name=?", (person,),
    ).fetchone()
    assert char is not None
    assert "陕西巡抚" in str(char["office"] or "")

    # 银
    moved = db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE account='国库' "
        "AND target_id=? AND delta < 0 ORDER BY id DESC LIMIT 1",
        (region,),
    ).fetchone()
    assert moved is not None
    assert int(moved["delta"]) == -30


def test_emperor_准_is_promise_approval_no_reply_stays_unapproved(game):
    """AC2：皇帝「准」由转译判应允；不回默认同意不变。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    # 经分派器落一条可成案的纯正文交办（与生产同形）。
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "着户部备赈灾银"}]},
        minister_name="", night_id=night_id,
    )
    assert staged.commissions.applied and not staged.commissions.rejected
    staged_id = int(staged.commissions.applied[0]["id"])

    # 不回 / 转译未声明 promises → 仍 night_approved=0
    empty = apply_audience_turn_translation(
        db, state, {"commissions": [], "promises": []}, night_id=night_id,
    )
    assert empty.promises.applied == []
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 0

    # 「准」→ 转译声明应允
    approved = apply_audience_turn_translation(
        db, state,
        {"commissions": [], "promises": [{"action_id": staged_id, "decision": "应允"}]},
        night_id=night_id,
    )
    assert len(approved.promises.applied) == 1
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 1

    # 收夜提交即准旨（成 draft 案）
    close_night(db, state, content=content, registry=None, wait_timeout_s=0.0)
    pa = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    assert pa["status"] == "committed"
    assert int(pa["committed_directive_id"] or 0) > 0


def test_scene_chat_cli_and_api_same_translation_shape(game, monkeypatch):
    """AC3：CLI 与 API 通道产出同一形状，不再前缀+二次分类两套路。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    region = _region_id(db)
    person = _hong_name(db, content)
    edict = f"任命{person}为陕西巡抚，调银三十万两赈灾"

    declaration = {
        "commissions": [{
            "text": edict,
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
            "grant": {
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        }],
        "promises": [],
    }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    # 分类器若仍被调用即失败——C1a 已退役场景入口分类器。
    import ming_sim.cli_backend as cb

    def boom(*a, **k):
        raise AssertionError("scene_chat 不得再调 classify_cli_action_intent")

    monkeypatch.setattr(cb, "classify_cli_action_intent", boom)

    shapes = []
    for channel in ("api", "cli"):
        def translate_fn(prompt, llm_config, _decl=declaration):
            shapes.append({
                "channel": getattr(llm_config, "channel", None),
                "declaration": normalize_audience_declaration(_decl),
            })
            return _decl

        sess = _sess(
            db, state, content,
            llm_config=SimpleNamespace(channel=channel),
            translate_fn=translate_fn,
        )
        # 每通道独立开夜上下文：重用同一 night 亦可；pending 累计可接受。
        before = db.conn.execute(
            "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"]
        result = sess.scene_chat(edict)
        assert result.answer == "臣等遵旨。"
        after = db.conn.execute(
            "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"]
        assert after > before
        assert result.pending_action_id > 0

    assert len(shapes) == 2
    assert shapes[0]["declaration"] == shapes[1]["declaration"]
    assert set(shapes[0]["declaration"]) == {"commissions", "promises"}


def test_unhandleable_commission_returns_as_fact_no_forced_ask(game):
    """AC4：承接不了的交办当事实回场，代码不做强制追问闸。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    # 幻影目标 → 分派拒收，不抛、不改写为追问
    declaration = {
        "commissions": [{
            "text": "着拨银赈济无此州",
            "grant": {
                "grant_action": "赈灾",
                "amount": 10,
                "account": "国库",
                "target_kind": "region",
                "target_id": "no-such-region-xyz",
                "execution_surface": "immediate",
            },
        }],
        "promises": [],
    }
    # region 不存在时 stage 仍可能成功（target 校验在成案/物化）；用非法 grant_action 证拒收。
    declaration["commissions"][0]["grant"]["grant_action"] = "不是合法拨帑"

    result = run_audience_turn_translation(
        db, state,
        emperor_message="着拨银",
        reply="臣…",
        night_id=night_id,
        translate_fn=lambda prompt, cfg: declaration,
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected, "须逐项拒收留痕"
    # 无 clarification 副作用字段；调用方只见 rejected
    assert all(getattr(r, "category", "") for r in result.commissions.rejected)


def test_scene_chat_translate_reads_emperor_reply_and_pending(game, monkeypatch):
    """转译读本轮皇帝原话 + 回话 + 暂存清单（prompt 组装）。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    staged = db.stage_pending_action(
        int(state.turn), "directive", "拟旨", "", {"text": "旧暂存旨"},
    )

    seen = {}

    def translate_fn(prompt, llm_config):
        seen["prompt"] = prompt
        return {
            "commissions": [],
            "promises": [{"action_id": staged, "decision": "应允"}],
        }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣领旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(db, state, content, translate_fn=translate_fn)
    sess.scene_chat("准")

    assert "准" in seen["prompt"]
    assert "臣领旨" in seen["prompt"]
    assert f"#{staged}" in seen["prompt"]
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 1
