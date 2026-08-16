"""#519 一句多旨：一话语 → N 个已注册候选独立成条。

Seams:
- apply_cli_conversation_actions（preclassified_intent=list 整表入 pipeline）
- run_materialize_pipeline 逐项 materialize
- 跨 kind 准驳（族名 / confirm_target_ids）；拒绝不成案、应允进夜批/收夜案卷

不测活 LLM 拆句；不建第二 registry。
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 — install catalog
import ming_sim.audience_night as an
import ming_sim.cli_backend as cb
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.session import GameSession


# ── helpers（复用 515/518/502 节奏）──────────────────────────────────


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    return s


def _active_ch(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )


def _silence_serial(monkeypatch):
    """挡串行 LLM 回落；本片只消费 preclassified list。"""
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial appointment extractor")))
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial draft extractor")))
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial classifier")))


def _pending_rows(db, turn, *, minister_name=None):
    if minister_name:
        return list(db.list_pending_actions(int(turn), minister_name=minister_name))
    return list(db.list_pending_actions(int(turn)))


def _payload(row):
    try:
        return json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}


def _anchor_candidates():
    """北极星锚例：任免 + 国库赈灾（两已注册 kind）。"""
    return candidates_from_classifier_payload([
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
            "mode": "ordinary",
        },
        {
            "kind": "grant_allocation",
            "grant_action": "赈灾",
            "amount": 30,
            "account": "国库",
            "target_id": "shaanxi",
        },
    ], soft=False)


def _stage_anchor(sess, minister, monkeypatch, *, message=None, reply=None):
    _silence_serial(monkeypatch)
    spoken = message or "任命洪承畴为陕西巡抚，调银三十万两赈灾。"
    return sess.apply_cli_conversation_actions(
        minister, spoken,
        reply or "臣请任洪承畴巡抚陕西，并户部发帑三十万两赈灾，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=_anchor_candidates(),
    )


def _find_office_and_grant(rows):
    office = [r for r in rows if r["kind"] == "office"]
    grants = [
        r for r in rows
        if r["kind"] == "directive"
        and _payload(r).get("dossier_action_type") == "grant_allocation"
    ]
    return office, grants


def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


# ── A 锚例 ───────────────────────────────────────────────────────────


def test_anchor_appointment_and_grant_stage_two_independent_candidates(game, monkeypatch):
    """AC-A：任免+钱粮两独立候选；payload 各持姓名官职 / 金额账户目标。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    before_ids = {int(r["id"]) for r in _pending_rows(db, state.turn)}

    _stage_anchor(sess, minister, monkeypatch)

    rows = [
        r for r in _pending_rows(db, state.turn, minister_name=minister.name)
        if int(r["id"]) not in before_ids
    ]
    office, grants = _find_office_and_grant(rows)
    assert len(office) == 1, f"应恰 1 条 office，实际 kinds={[r['kind'] for r in rows]}"
    assert len(grants) == 1, f"应恰 1 条 grant_allocation，实际 {[ _payload(r).get('dossier_action_type') for r in rows ]}"
    assert int(office[0]["id"]) != int(grants[0]["id"])

    assert office[0]["action"] == "任命"
    op = _payload(office[0])
    assert op.get("name") == "洪承畴"
    assert op.get("office") == "陕西巡抚"

    gp = _payload(grants[0])
    assert gp.get("grant_action") == "赈灾"
    assert int(gp.get("amount") or 0) == 30
    assert gp.get("account") == "国库"
    assert gp.get("target_id") == "shaanxi"


def test_anchor_candidates_independently_confirmable(game, monkeypatch):
    """AC-A：两轮确认（confirm_target_ids）可分别应允任免、拒绝拨帑。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _stage_anchor(sess, minister, monkeypatch)

    rows = _pending_rows(db, state.turn, minister_name=minister.name)
    office, grants = _find_office_and_grant(rows)
    assert len(office) == 1 and len(grants) == 1
    office_id = int(office[0]["id"])
    grant_id = int(grants[0]["id"])

    # 应允任免
    _silence_serial(monkeypatch)
    sess.apply_cli_conversation_actions(
        minister, "任免准了。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={office_id},
    )
    approved_office = {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="office")
    }
    assert office_id in approved_office
    # 拨帑仍 pending
    still = {int(r["id"]) for r in _pending_rows(db, state.turn) if r.get("status") == "pending"}
    assert grant_id in still

    # 拒绝拨帑
    _silence_serial(monkeypatch)
    sess.apply_cli_conversation_actions(
        minister, "赈灾那道不必了。", "臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "拒绝"}],
        confirm_target_ids={grant_id},
    )
    remaining_ids = {int(r["id"]) for r in _pending_rows(db, state.turn)}
    assert grant_id not in remaining_ids
    # 任免仍在 night_approved，不得被拒拨帑拖垮
    assert office_id in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="office")
    }


# ── B 只落准的 ───────────────────────────────────────────────────────


def test_accept_one_reject_one_only_accepted_lands_dossier(game, monkeypatch):
    """AC-B：一准一驳 → 准的收夜落独立案卷；驳的 pending 消失且无对应 dossier。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _stage_anchor(sess, minister, monkeypatch)

    rows = _pending_rows(db, state.turn, minister_name=minister.name)
    office, grants = _find_office_and_grant(rows)
    office_id = int(office[0]["id"])
    grant_id = int(grants[0]["id"])

    _silence_serial(monkeypatch)
    # 应允任免
    sess.apply_cli_conversation_actions(
        minister, "准任免。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={office_id},
    )
    # 拒绝拨帑
    sess.apply_cli_conversation_actions(
        minister, "拨帑作罢。", "臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "拒绝"}],
        confirm_target_ids={grant_id},
    )

    assert grant_id not in {int(r["id"]) for r in _pending_rows(db, state.turn)}
    assert office_id in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="office")
    }

    # 收夜：只应允的 office 成案；不得出现 grant 案卷
    an.close_night(db, state, night_id=int(night["id"]), content=content)
    dossiers = db.list_decree_dossiers()
    by_pending = {
        int(d["pending_action_id"]): d
        for d in dossiers
        if d.get("pending_action_id") is not None
    }
    assert office_id in by_pending, "应允任免应收夜落独立案卷"
    assert grant_id not in by_pending, "拒绝拨帑不得成案"
    # 不得两败俱伤 / 两道同落
    grant_dossiers = [
        d for d in dossiers
        if d.get("action_type") == "grant_allocation"
        and int(d.get("pending_action_id") or 0) == grant_id
    ]
    assert not grant_dossiers


def test_accept_grant_reject_appointment_only_grant_lands(game, monkeypatch):
    """AC-B 对调：应允拨帑、拒绝任免 → 只落 grant 案卷。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _stage_anchor(sess, minister, monkeypatch)

    rows = _pending_rows(db, state.turn, minister_name=minister.name)
    office, grants = _find_office_and_grant(rows)
    office_id = int(office[0]["id"])
    grant_id = int(grants[0]["id"])

    _silence_serial(monkeypatch)
    sess.apply_cli_conversation_actions(
        minister, "准赈灾。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={grant_id},
    )
    sess.apply_cli_conversation_actions(
        minister, "任免作罢。", "臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "拒绝"}],
        confirm_target_ids={office_id},
    )

    assert office_id not in {int(r["id"]) for r in _pending_rows(db, state.turn)}
    assert grant_id in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="directive")
    }

    an.close_night(db, state, night_id=int(night["id"]), content=content)
    by_pending = {
        int(d["pending_action_id"]): d
        for d in db.list_decree_dossiers()
        if d.get("pending_action_id") is not None
    }
    assert grant_id in by_pending
    assert by_pending[grant_id]["action_type"] == "grant_allocation"
    assert office_id not in by_pending


# ── C 单旨不误拆 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        {
            "kind": "grant_allocation",
            "grant_action": "赈灾",
            "amount": 30,
            "account": "国库",
            "target_id": "shaanxi",
        },
        {
            "kind": "draft",
        },
    ],
    ids=["appointment", "grant_allocation", "draft"],
)
def test_single_candidate_does_not_inflate(game, monkeypatch, payload):
    """AC-C：单候选输入 pending 条数=1；与注入 list 长度一致。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    _silence_serial(monkeypatch)

    scripted = candidates_from_classifier_payload([payload], soft=False)
    assert len(scripted) == 1

    # draft 需要串行 extract 或 intent 字段；本片 draft 用 canned extract 给出成品
    if payload["kind"] == "draft":
        monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
            "draft_action": "拟旨",
            "draft_text": "着户部清查三边粮饷，限三月完报。",
            "target_candidate": "",
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "test-policy",
        })
        # draft materializer may call backend; silence classify still, allow draft path
        monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
            "appoint_action": "无", "name": "", "office": "",
        })

    before = len(_pending_rows(db, state.turn))
    sess.apply_cli_conversation_actions(
        minister, "单旨口谕。", "臣请奉行，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    after_rows = _pending_rows(db, state.turn)
    assert len(after_rows) == before + 1

    new = after_rows[-1] if len(after_rows) > before else None
    assert new is not None
    if payload["kind"] == "appointment":
        assert new["kind"] == "office"
        assert _payload(new).get("name") == "洪承畴"
    elif payload["kind"] == "grant_allocation":
        assert new["kind"] == "directive"
        assert _payload(new).get("dossier_action_type") == "grant_allocation"
    else:
        assert new["kind"] == "directive"


# ── D N>2 三聚类独立 ─────────────────────────────────────────────────


def _triple_candidates():
    return candidates_from_classifier_payload([
        {
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "洪承畴",
            "office": "陕西巡抚",
        },
        {
            "kind": "grant_allocation",
            "grant_action": "赈灾",
            "amount": 30,
            "account": "国库",
            "target_id": "shaanxi",
        },
        {
            "kind": "draft",
        },
    ], soft=False)


def test_three_registered_clusters_stage_independently(game, monkeypatch):
    """AC-D：appointment + grant + draft → 3 条独立 pending。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    _silence_serial(monkeypatch)
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨",
        "draft_text": "着兵部核饷九边军械，限两月呈览。",
        "target_candidate": "",
        "dossier_action_type": "policy",
        "target_kind": "issue",
        "target_id": "nine-borders-arms",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })

    before_ids = {int(r["id"]) for r in _pending_rows(db, state.turn)}
    sess.apply_cli_conversation_actions(
        minister,
        "任命洪承畴为陕西巡抚，调银三十万两赈灾，再拟一道核饷九边。",
        "臣已分别拟妥，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=_triple_candidates(),
    )
    new_rows = [
        r for r in _pending_rows(db, state.turn, minister_name=minister.name)
        if int(r["id"]) not in before_ids
    ]
    assert len(new_rows) == 3, f"应 3 条独立 pending，实际 {[(r['kind'], _payload(r).get('dossier_action_type')) for r in new_rows]}"
    kinds = {r["kind"] for r in new_rows}
    assert "office" in kinds
    directives = [r for r in new_rows if r["kind"] == "directive"]
    assert len(directives) == 2
    dtypes = {_payload(r).get("dossier_action_type") for r in directives}
    assert "grant_allocation" in dtypes
    # draft/policy 一条
    assert any(
        _payload(r).get("dossier_action_type") != "grant_allocation"
        or "核饷" in str(_payload(r).get("text") or "")
        for r in directives
    )


def test_three_candidates_confirm_reject_leave_unpolluted(game, monkeypatch):
    """AC-D：对一条应允、一条拒绝、一条不动 → 状态互不改写。"""
    db, state, content = game
    minister = _active_ch(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _silence_serial(monkeypatch)
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨",
        "draft_text": "着兵部核饷九边军械，限两月呈览。",
        "target_candidate": "",
        "dossier_action_type": "policy",
        "target_kind": "issue",
        "target_id": "nine-borders-arms",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })

    before_ids = {int(r["id"]) for r in _pending_rows(db, state.turn)}
    sess.apply_cli_conversation_actions(
        minister,
        "任命洪承畴为陕西巡抚，调银三十万两赈灾，再拟一道核饷九边。",
        "臣已分别拟妥，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=_triple_candidates(),
    )
    new_rows = [
        r for r in _pending_rows(db, state.turn, minister_name=minister.name)
        if int(r["id"]) not in before_ids
    ]
    assert len(new_rows) == 3
    office = next(r for r in new_rows if r["kind"] == "office")
    grant = next(
        r for r in new_rows
        if r["kind"] == "directive"
        and _payload(r).get("dossier_action_type") == "grant_allocation"
    )
    draft = next(
        r for r in new_rows
        if r["kind"] == "directive"
        and _payload(r).get("dossier_action_type") != "grant_allocation"
    )
    office_id, grant_id, draft_id = int(office["id"]), int(grant["id"]), int(draft["id"])
    draft_payload_before = _payload(draft)

    _silence_serial(monkeypatch)
    # 应允任免
    sess.apply_cli_conversation_actions(
        minister, "准任免。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={office_id},
    )
    # 拒绝拨帑
    sess.apply_cli_conversation_actions(
        minister, "赈灾作罢。", "臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "拒绝"}],
        confirm_target_ids={grant_id},
    )
    # draft 不动

    assert office_id in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="office")
    }
    remaining = {int(r["id"]): r for r in _pending_rows(db, state.turn)}
    assert grant_id not in remaining
    assert draft_id in remaining
    assert remaining[draft_id].get("status") == "pending"
    assert _payload(remaining[draft_id]).get("text") == draft_payload_before.get("text")
    # 任免不得被拒拨帑拖入 drop
    assert office_id in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="office")
    }
