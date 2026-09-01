"""#518 恩赏·拨帑：真实候选、案卷与 ADR 0055 钱粮/叙事效果。

Seams:
- ACTION_CLUSTERS grant_allocation 行 + materialize_fn
- run_materialize_pipeline / apply_cli_conversation_actions
- commit_pending_actions（收夜落案卷；国库源不成效果）
- apply_dossier_verdicts / create_decree_dossier（0055：国库判决后落，内帑豁免直落）
- create_fiscal_item / list_fiscal_effects_for_dossier / apply_fixed_period_flows
- person_logs 开放标签；characters.office 不被加衔覆盖
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
import ming_sim.cli_backend as cb
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    candidates_from_classifier_payload,
)
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.decree import reload_state_from_db
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.session import GameSession
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


def _ctx(db, character, candidates, turn, *, message, reply):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def _active_ming(db, content, *, exclude=""):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )


def _stage_grant(db, turn, *, action, amount=0, account="", cadence="",
                 name="", target_id="", message=None, reply=None):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "grant_allocation",
        "grant_action": action,
    }
    if amount:
        payload["amount"] = amount
    if account:
        payload["account"] = account
    if cadence:
        payload["cadence"] = cadence
    if name:
        payload["name"] = name
    if target_id:
        payload["target_id"] = target_id
    if action == "协饷":
        payload["target_kind"] = "army"
        payload["purpose"] = "补饷"
    candidate = candidates_from_classifier_payload(payload, soft=False)
    spoken = message or f"{action}。"
    ctx = _ctx(
        db, actor, candidate, turn,
        message=spoken,
        reply=reply or f"臣请奉行：{spoken}请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


def test_oneshot_treasury_relief_lands_economy_move_only_after_verdict(game):
    """AC1：调银三十万两赈灾（国库）→ 暂存 → 收夜落案卷 → economy_moves 只在顺颁后生效。"""
    db, state, content = game
    treasury_before = int(state.metrics["国库"])
    inner_before = int(state.metrics["内库"])

    ctx = _stage_grant(
        db, state.turn, action="赈灾", amount=30, account="国库",
        target_id="shaanxi",
        message="调银三十万两赈灾。",
        reply="臣请户部发帑三十万两赈陕西灾民，请陛下定夺准驳。",
    )
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "grant_allocation"
    assert pending["grant_action"] == "赈灾"
    assert pending["account"] == "国库"
    assert int(pending["amount"]) == 30
    assert int(state.metrics["国库"]) == treasury_before
    assert int(state.metrics["内库"]) == inner_before

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "grant_allocation"
    assert dossier["status"] == "proposed"
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []
    assert int(state.metrics["国库"]) == treasury_before, "收夜只落案卷，国库源不得先扣"

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert moves, "国库赈灾须在顺颁后落 economy_moves"
    assert int(moves[0]["delta"]) == -30
    assert moves[0]["account"] == "国库"
    assert int(state.metrics["国库"]) == treasury_before - 30
    assert int(state.metrics["内库"]) == inner_before
    assert moves[0]["account"] == "国库"


def test_inner_treasury_grant_lands_immediately_at_close_night(game):
    """AC1：发内帑豁免直落——收夜即扣内库，不等颁布判决。"""
    db, state, content = game
    target = _active_ming(db, content)
    state.metrics["内库"] = max(int(state.metrics["内库"]), 20)
    treasury_before = int(state.metrics["国库"])
    inner_before = int(state.metrics["内库"])

    ctx = _stage_grant(
        db, state.turn, action="发内帑", amount=8, name=target.name,
        message=f"发内帑八万两赐{target.name}。",
        reply=f"臣请内库发银八万两赏{target.name}。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert dossier["action_type"] == "grant_allocation"
    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert moves, "内帑须在成案时直落 economy_moves"
    assert int(moves[0]["delta"]) == -8
    assert moves[0]["account"] == "内库"
    assert int(state.metrics["内库"]) == inner_before - 8
    assert int(state.metrics["国库"]) == treasury_before

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert len(db.list_economy_moves_for_dossier(dossier["id"])) == 1
    assert int(state.metrics["内库"]) == inner_before - 8


def test_treasury_rejected_verdict_leaves_accounts_untouched(game):
    """AC1 打回拍：案卷在、国库零落。"""
    db, state, content = game
    treasury_before = int(state.metrics["国库"])
    ctx = _stage_grant(
        db, state.turn, action="赈灾", amount=30, account="国库",
        target_id="shaanxi", message="调银三十万两赈灾。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier["id"])], content=content)
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []
    assert int(state.metrics["国库"]) == treasury_before


def test_monthly_treasury_grant_creates_fiscal_item_after_verdict(game):
    """AC2：每月国库拨五十万两 → 判决后 fiscal_creates，月度流水按口谕额扣国库。"""
    db, state, content = game
    target = _active_ming(db, content)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_grant(
        db, state.turn, action="赏赉", amount=50, account="国库", cadence="每月",
        name=target.name,
        message="每月国库拨你五十万两。",
        reply=f"臣请自国库每月拨银五十万两予{target.name}。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []
    assert db.list_fiscal_effects_for_dossier(dossier["id"]) == []
    assert int(state.metrics["国库"]) == treasury_before

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []
    fiscal = db.list_fiscal_effects_for_dossier(dossier["id"])
    assert fiscal, "常项须落 fiscal_creates"
    bases = [row for row in fiscal if str(row["key"]).endswith("_base")]
    assert len(bases) == 1
    assert int(bases[0]["value"]) == 50
    assert bases[0]["origin_ref"] == f"dossier:{dossier['id']}"
    created = db.conn.execute(
        "SELECT account, direction, display FROM fiscal_config WHERE key=?",
        (bases[0]["key"],),
    ).fetchone()
    assert created["account"] == "国库"
    assert created["direction"] == "expense"
    assert "50" not in str(created["display"] or "")

    apply_fixed_period_flows(db, state)
    monthly = [
        row for row in db.conn.execute(
            "SELECT account, delta, category FROM economy_ledger WHERE category=?",
            (created["display"],),
        ).fetchall()
    ]
    assert monthly, "月度流水须按固定科目扣账"
    assert monthly[-1]["account"] == "国库"
    assert int(monthly[-1]["delta"]) == -50


def test_monthly_inner_treasury_fiscal_lands_at_close_night(game):
    """AC2+AC5：每月发内帑 → 豁免直落 fiscal_creates，账户为内库。"""
    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_grant(
        db, state.turn, action="发内帑", amount=12, cadence="每月",
        name=target.name,
        message="每月发内帑十二万两。",
        reply=f"臣请内库每月拨银予{target.name}。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []
    fiscal = db.list_fiscal_effects_for_dossier(dossier["id"])
    assert fiscal, "内帑常项须在成案时建项"
    bases = [row for row in fiscal if str(row["key"]).endswith("_base")]
    assert int(bases[0]["value"]) == 12
    created = db.conn.execute(
        "SELECT account, display FROM fiscal_config WHERE key=?",
        (bases[0]["key"],),
    ).fetchone()
    assert created["account"] == "内库"
    assert "12" not in str(created["display"] or "")

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert len(db.list_fiscal_effects_for_dossier(dossier["id"])) == len(fiscal)


def test_enshang_and_zhengwu_e2e_land_spoken_amount_on_spoken_account(game):
    """AC3+AC4+AC5：恩赏赏赉走内库、政务赈灾走国库，落库额=口谕额。"""
    db, state, content = game
    target = _active_ming(db, content)
    state.metrics["内库"] = max(int(state.metrics["内库"]), 20)
    treasury_before = int(state.metrics["国库"])
    inner_before = int(state.metrics["内库"])

    gift = _stage_grant(
        db, state.turn, action="赏赉", amount=6, account="内库",
        name=target.name,
        message=f"发内帑赏{target.name}六万两。",
        reply=f"臣请内库赏{target.name}银两。",
    )
    relief = _stage_grant(
        db, state.turn, action="赈灾", amount=30, account="国库",
        target_id="shaanxi",
        message="调银三十万两赈灾。",
        reply="臣请户部发帑赈陕西。",
    )
    gift_d = _close_night_dossier(db, state, content, gift.out["pending_action_id"])
    relief_d = _close_night_dossier(db, state, content, relief.out["pending_action_id"])

    gift_moves = db.list_economy_moves_for_dossier(gift_d["id"])
    assert gift_moves and int(gift_moves[0]["delta"]) == -6
    assert gift_moves[0]["account"] == "内库"
    assert int(state.metrics["内库"]) == inner_before - 6
    assert db.list_economy_moves_for_dossier(relief_d["id"]) == []
    assert int(state.metrics["国库"]) == treasury_before

    db.apply_dossier_verdicts(state, [
        {"dossier_id": gift_d["id"], "decision": "promulgated"},
        {"dossier_id": relief_d["id"], "decision": "promulgated"},
    ], content=content)
    relief_moves = db.list_economy_moves_for_dossier(relief_d["id"])
    assert relief_moves and int(relief_moves[0]["delta"]) == -30
    assert relief_moves[0]["account"] == "国库"
    assert int(state.metrics["国库"]) == treasury_before - 30
    assert int(state.metrics["内库"]) == inner_before - 6
    assert len(db.list_economy_moves_for_dossier(gift_d["id"])) == 1


def test_jiaxian_and_yinxu_land_narrative_tags_without_overwriting_office(game):
    """AC6：加衔与荫叙落开放标签；加衔后主官职不变。"""
    db, state, content = game
    jiaxian_target = _active_ming(db, content)
    yinxu_target = _active_ming(db, content, exclude=jiaxian_target.name)
    office_before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (jiaxian_target.name,),
    ).fetchone()["office"]
    assert office_before

    jia = _stage_grant(
        db, state.turn, action="加衔", name=jiaxian_target.name,
        message=f"加{jiaxian_target.name}太子太保。",
        reply=f"臣请加{jiaxian_target.name}太子太保衔。",
    )
    yin = _stage_grant(
        db, state.turn, action="荫叙", name=yinxu_target.name,
        message=f"荫{yinxu_target.name}一子入监。",
        reply=f"臣请荫叙{yinxu_target.name}一子。",
    )
    jia_d = _close_night_dossier(db, state, content, jia.out["pending_action_id"])
    yin_d = _close_night_dossier(db, state, content, yin.out["pending_action_id"])
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (jiaxian_target.name,),
    ).fetchone()["office"] == office_before
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=? AND action='加衔'",
        (jiaxian_target.name,),
    ).fetchone()[0] == 0

    db.apply_dossier_verdicts(state, [
        {"dossier_id": jia_d["id"], "decision": "promulgated"},
        {"dossier_id": yin_d["id"], "decision": "promulgated"},
    ], content=content)

    office_after = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (jiaxian_target.name,),
    ).fetchone()["office"]
    assert office_after == office_before
    assert content.characters[jiaxian_target.name].office == office_before

    jia_logs = db.conn.execute(
        "SELECT action, payload_summary FROM person_logs WHERE person_name=? AND action='加衔'",
        (jiaxian_target.name,),
    ).fetchall()
    yin_logs = db.conn.execute(
        "SELECT action, payload_summary FROM person_logs WHERE person_name=? AND action='荫叙'",
        (yinxu_target.name,),
    ).fetchall()
    assert len(jia_logs) == 1
    assert len(yin_logs) == 1
    assert jia_logs[0]["action"] == "加衔"
    assert yin_logs[0]["action"] == "荫叙"
    assert not any(ch.isdigit() for ch in str(jia_logs[0]["payload_summary"] or ""))
    assert not any(ch.isdigit() for ch in str(yin_logs[0]["payload_summary"] or ""))


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    return s


def _silence_serial(monkeypatch):
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "无", "draft_text": "", "target_candidate": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")


def test_scripted_grant_stages_via_apply_then_close_night(game, monkeypatch):
    """真实 apply 缝暂存拨帑；收夜落案卷后国库仍待判决。"""
    db, state, content = game
    actor = _active_ming(db, content)
    treasury_before = int(state.metrics["国库"])
    _silence_serial(monkeypatch)
    sess = _bind_apply(db, state, content)
    scripted = candidates_from_classifier_payload({
        "kind": "grant_allocation", "grant_action": "赈灾",
        "amount": 30, "account": "国库", "target_id": "shaanxi",
    }, soft=False)
    out = sess.apply_cli_conversation_actions(
        actor, "调银三十万两赈灾。",
        "臣请户部发帑三十万两赈陕西灾民，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None, preclassified_intent=scripted,
    )
    pending_id = out.get("pending_action_id")
    assert pending_id
    assert int(state.metrics["国库"]) == treasury_before
    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "grant_allocation"
    assert int(state.metrics["国库"]) == treasury_before
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert int(state.metrics["国库"]) == treasury_before - 30


def test_grant_restore_from_db_only_is_lossless(game):
    """P1：restore 只读 DB 能接续拨帑结果与案卷。"""
    db, state, content = game
    treasury_before = int(state.metrics["国库"])
    ctx = _stage_grant(
        db, state.turn, action="赈灾", amount=30, account="国库",
        target_id="shaanxi", message="调银三十万两赈灾。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    state.metrics["国库"] = treasury_before
    reload_state_from_db(db, state, content=content)
    assert int(state.metrics["国库"]) == treasury_before - 30
    restored = db.get_decree_dossier(dossier["id"])
    assert restored["action_type"] == "grant_allocation"
    assert int(json.loads(restored["payload_json"])["amount"]) == 30


def test_xiexang_oneshot_is_same_path_treasury_after_verdict(game):
    """同类型自查：协饷走同一案卷+判决双拍，口谕额扣国库（#1503 销欠）。"""
    db, state, content = game
    # #1503：协饷 target 须为真实 army_id；欠饷盖过口谕额以免 clamp 干扰面额断言。
    db.conn.execute(
        "UPDATE armies SET arrears=80, province_pay_arrears=0, central_pay_arrears=80 "
        "WHERE id='guanning'"
    )
    db.conn.commit()
    state.metrics["国库"] = max(int(state.metrics["国库"]), 50)
    treasury_before = int(state.metrics["国库"])
    ctx = _stage_grant(
        db, state.turn, action="协饷", amount=18, account="国库",
        target_id="guanning",
        message="着国库拨十八万两协饷关宁。",
        reply="臣请户部发帑协济关宁。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert int(state.metrics["国库"]) == treasury_before
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    moves = db.list_economy_moves_for_dossier(dossier["id"])
    assert moves and int(moves[0]["delta"]) == -18
    assert moves[0]["account"] == "国库"
    assert moves[0]["purpose"] == "补饷"
    assert int(state.metrics["国库"]) == treasury_before - 18


def test_jiaxian_rejected_does_not_write_office_or_tag(game):
    """引入 bug 自查：加衔打回不得改官职、不得落标签。"""
    db, state, content = game
    target = _active_ming(db, content)
    office_before = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target.name,),
    ).fetchone()["office"]
    ctx = _stage_grant(
        db, state.turn, action="加衔", name=target.name,
        message=f"加{target.name}太子太保。",
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier["id"])], content=content)
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target.name,),
    ).fetchone()["office"] == office_before
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=? AND action='加衔'",
        (target.name,),
    ).fetchone()[0] == 0


def test_confirm_accept_does_not_spend_treasury(game, monkeypatch):
    """应允只过确认闸，不得在判决前扣国库。"""
    db, state, content = game
    actor = _active_ming(db, content)
    treasury_before = int(state.metrics["国库"])
    _silence_serial(monkeypatch)
    sess = _bind_apply(db, state, content)
    scripted = candidates_from_classifier_payload({
        "kind": "grant_allocation", "grant_action": "赈灾",
        "amount": 30, "account": "国库", "target_id": "shaanxi",
    }, soft=False)
    out = sess.apply_cli_conversation_actions(
        actor, "调银三十万两赈灾。",
        "臣请户部发帑赈陕西。",
        has_directive=False, secret_order_id=None, preclassified_intent=scripted,
    )
    pending_id = out.get("pending_action_id")
    sess.apply_cli_conversation_actions(
        actor, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={int(pending_id)},
    )
    assert int(state.metrics["国库"]) == treasury_before


def _grant_pending_payloads(db, turn, *, target_id, grant_action):
    rows = []
    for row in db.list_pending_actions(int(turn)):
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "grant_allocation":
            continue
        if str(payload.get("target_id") or "").strip() != target_id:
            continue
        if str(payload.get("grant_action") or "").strip() != grant_action:
            continue
        rows.append((int(row["id"]), payload))
    return rows


def test_oneshot_and_monthly_same_target_stage_as_independent_candidates(game):
    """同句拆出：赏某臣一次性 + 同目标每月再拨 → 两道独立候选，不得互相覆盖。"""
    db, state, content = game
    target = _active_ming(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    candidates = candidates_from_classifier_payload([
        {
            "kind": "grant_allocation", "grant_action": "赏赉",
            "amount": 10, "account": "国库", "cadence": "一次性", "name": target.name,
        },
        {
            "kind": "grant_allocation", "grant_action": "赏赉",
            "amount": 5, "account": "国库", "cadence": "每月", "name": target.name,
        },
    ], soft=False)
    ctx = _ctx(
        db, actor, candidates, state.turn,
        message=f"赏{target.name}十万两，另每月再给五万两。",
        reply=f"臣请赏{target.name}银十万两，并自国库每月再拨五万两。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)

    staged = _grant_pending_payloads(
        db, state.turn, target_id=target.name, grant_action="赏赉",
    )
    assert len(staged) == 2, f"同目标两笔独立拨款应各自成条，实际 {len(staged)} 条"
    by_cadence = {payload.get("cadence"): int(payload.get("amount") or 0) for _, payload in staged}
    assert by_cadence == {"一次性": 10, "每月": 5}

    dossiers = []
    for pending_id, _ in staged:
        dossiers.append(_close_night_dossier(db, state, content, pending_id))
    assert len({d["id"] for d in dossiers}) == 2
    db.apply_dossier_verdicts(state, [
        {"dossier_id": d["id"], "decision": "promulgated"} for d in dossiers
    ], content=content)
    oneshot_moves = []
    monthly_fiscal = []
    for d in dossiers:
        oneshot_moves.extend(db.list_economy_moves_for_dossier(d["id"]))
        monthly_fiscal.extend(
            row for row in db.list_fiscal_effects_for_dossier(d["id"])
            if str(row["key"]).endswith("_base")
        )
    assert len(oneshot_moves) == 1 and int(oneshot_moves[0]["delta"]) == -10
    assert len(monthly_fiscal) == 1 and int(monthly_fiscal[0]["value"]) == 5


def test_later_additional_grant_same_target_stages_independently(game):
    """稍后再赏：无明确修改指向时，同目标第二笔另成候选，不覆盖首笔。"""
    db, state, content = game
    target = _active_ming(db, content)

    first = _stage_grant(
        db, state.turn, action="赏赉", amount=10, account="国库", cadence="一次性",
        name=target.name,
        message=f"赏{target.name}十万两。",
        reply=f"臣请赏{target.name}银十万两。",
    )
    first_id = int(first.out["pending_action_id"])
    second = _stage_grant(
        db, state.turn, action="赏赉", amount=5, account="国库", cadence="一次性",
        name=target.name,
        message=f"再赏{target.name}五万两。",
        reply=f"臣请再赏{target.name}银五万两。",
    )
    second_id = int(second.out["pending_action_id"])

    assert second_id != first_id
    staged = _grant_pending_payloads(
        db, state.turn, target_id=target.name, grant_action="赏赉",
    )
    assert len(staged) == 2
    amounts = sorted(int(payload.get("amount") or 0) for _, payload in staged)
    assert amounts == [5, 10]
    first_payload = next(p for i, p in staged if i == first_id)
    assert int(first_payload.get("amount") or 0) == 10, "首笔不得被再赏覆盖"

    d1 = _close_night_dossier(db, state, content, first_id)
    d2 = _close_night_dossier(db, state, content, second_id)
    db.apply_dossier_verdicts(state, [
        {"dossier_id": d1["id"], "decision": "promulgated"},
        {"dossier_id": d2["id"], "decision": "promulgated"},
    ], content=content)
    moves = (
        db.list_economy_moves_for_dossier(d1["id"])
        + db.list_economy_moves_for_dossier(d2["id"])
    )
    assert sorted(int(m["delta"]) for m in moves) == [-10, -5]


def test_explicit_target_candidate_still_updates_named_grant(game):
    """明确结构化修改指向时，仍只更新被点名的那一道拨款候选。"""
    from ming_sim.action_materialize import stage_grant_allocation_candidate

    db, state, content = game
    target = _active_ming(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    first_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=f"赏{target.name}银十万两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=target.name,
        amount=10,
        account="国库",
        cadence="一次性",
    )
    other_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=f"另赏{target.name}银三万两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=target.name,
        amount=3,
        account="国库",
        cadence="一次性",
    )
    assert first_id and other_id and first_id != other_id

    updated_id = stage_grant_allocation_candidate(
        db, state.turn, actor,
        text=f"前道赏银改作每月五万两。",
        grant_action="赏赉",
        target_kind="character",
        target_id=target.name,
        amount=5,
        account="国库",
        cadence="每月",
        target_candidate=str(first_id),
    )
    assert updated_id == first_id

    staged = dict(_grant_pending_payloads(
        db, state.turn, target_id=target.name, grant_action="赏赉",
    ))
    assert set(staged) == {first_id, other_id}
    assert int(staged[first_id].get("amount") or 0) == 5
    assert staged[first_id].get("cadence") == "每月"
    assert int(staged[other_id].get("amount") or 0) == 3
    assert staged[other_id].get("cadence") == "一次性"


def _grant_field_zh(name: str) -> str:
    from ming_sim.action_clusters import cluster_by_kind

    grant = cluster_by_kind("grant_allocation")
    assert grant is not None
    for spec in grant.fields:
        if spec.name == name:
            return spec.zh
    raise AssertionError(f"grant_allocation missing FieldSpec {name!r}")


def test_grant_target_field_carries_region_project_army_through_normalize(game):
    """政务拨款目标字段须能表达赈灾地区/项目/协饷军队，并经真实归一化到物化。"""
    from ming_sim.action_clusters import cluster_by_kind

    target_zh = _grant_field_zh("target_id")
    assert target_zh != "目标人物", "目标字段不得限缩为人物，否则赈灾/项目/协饷无法入契约"

    # 共享 target_id 契约须与 grant 行一致，分类中文键能贯通
    shared = next(f for c in ACTION_CLUSTERS for f in c.fields if f.name == "target_id")
    assert shared.zh == target_zh

    db, state, content = game
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    cases = (
        # (action, classifier_target, expected_kind, expected_staged_target)
        # #1503：协饷 stage 前解析为真实 army id；赈灾/项目保持原文。
        ("赈灾", "陕西", "region", "陕西"),
        ("项目经费", "运河疏浚", "issue", "运河疏浚"),
        # #1620：仅身份别名 exact；关宁军→guanning，禁 theater 子串升格
        ("协饷", "关宁军", "army", "guanning"),
    )
    for action, target, expected_kind, expected_staged in cases:
        payload = {
            "动作类型": "恩赏·拨帑",
            "恩赏拨帑": action,
            target_zh: target,
            "金额": 12,
            "账户": "国库",
        }
        if action == "协饷":
            payload[_grant_field_zh("target_kind")] = "army"
            payload[_grant_field_zh("purpose")] = "补饷"
        candidates = candidates_from_classifier_payload(payload, soft=False)
        assert len(candidates) == 1, action
        assert candidates[0]["target_id"] == target, action

        ctx = _ctx(
            db, actor, candidates, state.turn,
            message=f"{action}{target}银十二万两。",
            reply=f"臣请{action}{target}银十二万两，请陛下定夺准驳。",
        )
        run_materialize_pipeline(ctx)
        pending_id = ctx.out.get("pending_action_id")
        assert pending_id, action
        staged = json.loads(db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
        ).fetchone()["payload_json"])
        assert staged["grant_action"] == action
        assert staged["target_id"] == expected_staged
        assert staged["target_kind"] == expected_kind


def test_target_candidate_survives_classifier_normalize_to_materialize(game):
    """明确改草：target_candidate 进 FieldSpec，经真实分类归一化贯通到物化更新。"""
    db, state, content = game
    target = _active_ming(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    first = _stage_grant(
        db, state.turn, action="赏赉", amount=10, account="国库", cadence="一次性",
        name=target.name,
        message=f"赏{target.name}十万两。",
        reply=f"臣请赏{target.name}银十万两。",
    )
    other = _stage_grant(
        db, state.turn, action="赏赉", amount=3, account="国库", cadence="一次性",
        name=target.name,
        message=f"另赏{target.name}三万两。",
        reply=f"臣请另赏{target.name}银三万两。",
    )
    first_id = int(first.out["pending_action_id"])
    other_id = int(other.out["pending_action_id"])
    assert first_id != other_id

    target_zh = _grant_field_zh("target_id")
    candidate_zh = _grant_field_zh("target_candidate")
    payload = {
        "动作类型": "恩赏·拨帑",
        "恩赏拨帑": "赏赉",
        "姓名": target.name,
        target_zh: target.name,
        "金额": 5,
        "账户": "国库",
        "拨付节奏": "每月",
        candidate_zh: str(first_id),
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    assert len(candidates) == 1
    assert candidates[0].get("target_candidate") == str(first_id), (
        "target_candidate 必须经分类归一化保留，不得在 FieldSpec 外被丢掉"
    )

    ctx = _ctx(
        db, actor, candidates, state.turn,
        message=f"前道赏{target.name}改作每月五万两。",
        reply=f"臣请将前道赏银改作每月五万两予{target.name}。",
    )
    run_materialize_pipeline(ctx)
    assert int(ctx.out["pending_action_id"]) == first_id

    staged = dict(_grant_pending_payloads(
        db, state.turn, target_id=target.name, grant_action="赏赉",
    ))
    assert set(staged) == {first_id, other_id}
    assert int(staged[first_id].get("amount") or 0) == 5
    assert staged[first_id].get("cadence") == "每月"
    assert int(staged[other_id].get("amount") or 0) == 3
    assert staged[other_id].get("cadence") == "一次性"


def test_grant_shape_accepts_integer_string_rejects_bool_float():
    """#1716：grant shape 唯一权威接纳整数字符串；bool/float 仍 fail-loud（#1620）。"""
    import pytest
    from ming_sim.action_materialize import require_grant_allocation_shape

    shaped = require_grant_allocation_shape(
        grant_action="赈灾", amount="8", account="国库",
    )
    assert shaped["amount"] == 8
    assert shaped["account"] == "国库"
    with pytest.raises(ValueError, match="正整数"):
        require_grant_allocation_shape(
            grant_action="赈灾", amount=True, account="国库",
        )
    with pytest.raises(ValueError, match="正整数"):
        require_grant_allocation_shape(
            grant_action="赈灾", amount=1.5, account="国库",
        )


def test_grant_pipeline_stages_pending_from_classifier_string_amount(game):
    """#1716：classifier 运输 amount=\"8\" 经 materialize 须落 kind=directive pending。

    normalize 仍 raw 直达（#658 catalog 契约）；shape 边界收成 int。
    """
    db, state, content = game
    actor = content.characters["郭允厚"]
    # soft normalize 保留字符串（与 registry 515 契约一致）
    from ming_sim.action_clusters import normalize_one_candidate

    intent = normalize_one_candidate(
        {
            "kind": "grant_allocation",
            "grant_action": "赈灾",
            "amount": "8",
            "account": "国库",
            "target_id": "shaanxi",
            "target_kind": "region",
        },
        soft=True,
    )
    assert intent["amount"] == "8"  # catalog 契约：raw 直达

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="cli")
    sess.registry = None

    out = {"pending_action_id": 0, "secret_order_id": 0}
    ctx = MaterializeCtx(
        session=sess,
        character=actor,
        player_message="拟旨如下：着户部从国库拨银八万两赈济陕西饥民。",
        reply="臣领旨。请从国库拨银八万两赈济陕西。",
        message_text="拟旨如下：着户部从国库拨银八万两赈济陕西饥民。",
        explicit_prefixed=True,
        has_directive=False,
        pend_for_minister=[],
        out=out,
        intent=intent,
        intent_kind="grant_allocation",
        llm_config=None,
        intent_candidates=[intent],
    )
    run_materialize_pipeline(ctx)
    assert int(out.get("pending_action_id") or 0) > 0
    pending = [
        p for p in db.list_pending_actions(state.turn)
        if p["kind"] == "directive" and p["status"] == "pending"
    ]
    assert len(pending) == 1
    payload = json.loads(pending[0]["payload_json"])
    assert payload["dossier_action_type"] == "grant_allocation"
    assert payload["amount"] == 8
