"""#517 惩处·宥赦：真实候选、案卷与 ADR 0055 判决后人物效果。

Seams:
- ACTION_CLUSTERS punishment 行 + materialize_fn
- run_materialize_pipeline / apply_cli_conversation_actions
- commit_pending_actions（收夜落案卷，不成效果）
- apply_dossier_verdicts（0055 顺颁才落机械效果）
- extract_appointment_action（「拿问去职」不得折罢免）
- reload_state_from_db（只读 DB 无损接续）
"""

from __future__ import annotations

import inspect
import json
import types
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
import ming_sim.action_materialize as am
import ming_sim.cli_backend as cb
import web_app
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.decree import reload_state_from_db
from ming_sim.models import CourtContext
from ming_sim.session import GameSession
from ming_sim.tools import build_minister_tools
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


def _stage_punishment(db, turn, target, *, action="拿问下狱", amount=0, message=None, reply=None):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "punishment",
        "punish_action": action,
        "transaction_category": "缉拿",
        "name": target,
    }
    if amount:
        payload["amount"] = amount
    candidate = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor, candidate, turn,
        message=message or f"将{target}{action}。",
        reply=reply or f"臣请将{target}{action}，请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


def test_naowen_stages_then_dossier_then_imprisoned_only_after_verdict(game):
    """AC1：拿问下狱 → 暂存 → 收夜落案卷 → imprisoned 只在 0055 顺颁后生效。"""
    db, state, content = game
    target = _active_ming(db, content)
    before_status = db.get_character_status(target.name)[0]
    assert before_status == "active"

    ctx = _stage_punishment(db, state.turn, target.name, action="拿问下狱")
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "punishment"
    assert pending["punish_action"] == "拿问下狱"
    assert pending["target_id"] == target.name
    assert db.get_character_status(target.name)[0] == "active"

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "punishment"
    assert dossier["status"] == "proposed"
    assert dossier["target_id"] == target.name
    assert db.get_character_status(target.name)[0] == "active", "收夜只落案卷，不得先下狱"

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "imprisoned"
    assert content.characters[target.name].status == "imprisoned"


@pytest.mark.parametrize("disposition", ["办人", "压下"])
def test_active_impeachment_disposition_flows_from_player_tool_to_dossier(game, disposition):
    """#660：玩家动作的 typed 处置直达案卷；办人目标由动作选择而非 roster 顺序决定。"""
    db, state, content = game
    actor = _active_ming(db, content)
    first = _active_ming(db, content, exclude=actor.name)
    selected = next(
        ch for ch in content.characters.values()
        if ch.name not in {actor.name, first.name}
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )
    faction = db.conn.execute("SELECT name FROM factions ORDER BY name LIMIT 1").fetchone()["name"]
    issue_id = db.insert_issue(
        state, kind="situation", title="御史发难", origin_kind="impeachment_surge",
        origin_ref="commitment:660:deformation_exposure", faction_hint=faction,
        target_roster=[first.name, selected.name],
    )
    reply = "臣据实拟就，不替圣意增删一字。"

    class Agent:
        def run(self, _message):
            return SimpleNamespace(content=reply, tools=[SimpleNamespace(
                tool_name="propose_directive", result="", arguments={
                    "decree_text": "照此处置。",
                    "punish_action": "拿问下狱" if disposition == "办人" else "无",
                    "target_id": selected.name if disposition == "办人" else "",
                    "issue_id": issue_id,
                    "issue_disposition": disposition,
                },
            )])

    sess = _directive_session(db, state, content)
    sess.registry = SimpleNamespace(get=lambda _character: Agent(), build_draft_line=lambda: "无")
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None
    result = GameSession.chat(sess, actor.name, f"对此弹劾潮{disposition}。")
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (result.pending_action_id,),
    ).fetchone()["payload_json"])
    assert pending["text"] == "照此处置。"
    assert pending["issue_id"] == issue_id
    assert pending["issue_disposition"] == disposition
    assert pending["target_id"] == (selected.name if disposition == "办人" else str(issue_id))

    dossier = _close_night_dossier(db, state, content, result.pending_action_id)
    before_authority = state.metrics["皇威"]
    before_sat = db.faction_satisfaction(faction)
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}], content=content,
    )
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()["status"] == "resolved"
    assert db.get_character_status(selected.name)[0] == ("imprisoned" if disposition == "办人" else "active")
    assert db.get_character_status(first.name)[0] == "active"
    assert state.metrics["皇威"] == before_authority - (disposition == "压下")
    assert db.faction_satisfaction(faction) == before_sat - (disposition == "压下")


def test_prestaged_impeachment_punishments_skip_person_writes_after_first_closes_issue(game):
    """#660：同 issue 预暂存两案；首案结案后第二案在人物写前幂等返回。"""
    db, state, content = game
    actor = _active_ming(db, content)
    targets = [
        ch for ch in content.characters.values()
        if ch.name != actor.name and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    ][:2]
    issue_id = db.insert_issue(
        state, kind="situation", title="御史发难", origin_kind="impeachment_surge",
        origin_ref="commitment:660:prestage", target_roster=[ch.name for ch in targets],
    )
    dossiers = []
    for target in targets:
        pending_id = am.stage_punishment_candidate(
            db, state.turn, actor.name, text="照此处置。", target_id=target.name,
            punish_action="拿问下狱", issue_id=issue_id, issue_disposition="办人",
        )
        dossiers.append(_close_night_dossier(db, state, content, pending_id))
    db.apply_dossier_verdicts(state, [
        {"dossier_id": dossier["id"], "decision": "promulgated"} for dossier in dossiers
    ], content=content)
    assert db.get_character_status(targets[0].name)[0] == "imprisoned"
    assert db.get_character_status(targets[1].name)[0] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?",
        (targets[1].name,)
    ).fetchone()[0] == 0


def test_naowen_rejected_verdict_leaves_status_untouched(game):
    """AC1 打回拍：案卷在、imprisoned 零落。"""
    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_punishment(db, state.turn, target.name)
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier["id"])], content=content)
    assert db.get_character_status(target.name)[0] == "active"
    assert content.characters[target.name].status == "active"


def test_pardon_migrates_imprisoned_to_active_after_verdict(game):
    """AC2：宥赦回迁 imprisoned→active，同样走案卷+判决双拍。"""
    db, state, content = game
    target = _active_ming(db, content)
    db.set_character_status(state, target.name, "imprisoned", "旧案在押")
    content.characters[target.name].status = "imprisoned"
    ctx = _stage_punishment(db, state.turn, target.name, action="放归")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.get_character_status(target.name)[0] == "imprisoned"
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "active"
    assert content.characters[target.name].status == "active"


def test_fine_stripping_and_beating_land_distinct_effects(game):
    """AC3：罚俸落钱粮减项；削籍=dismissed+获罪削籍；廷杖只落叙事、无状态转移。"""
    db, state, content = game
    fine_target = _active_ming(db, content)
    strip_target = _active_ming(db, content, exclude=fine_target.name)
    names = {fine_target.name, strip_target.name}
    beat_target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name not in names
        and str(getattr(ch, "office", "") or "").strip()
    )

    treasury_before = int(state.metrics["国库"])
    fine_status = db.get_character_status(fine_target.name)[0]
    beat_status = db.get_character_status(beat_target.name)[0]
    beat_logs_before = db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?", (beat_target.name,),
    ).fetchone()[0]

    fine_ctx = _stage_punishment(
        db, state.turn, fine_target.name, action="罚俸", amount=80,
    )
    strip_ctx = _stage_punishment(db, state.turn, strip_target.name, action="削籍")
    beat_ctx = _stage_punishment(db, state.turn, beat_target.name, action="廷杖")
    fine_d = _close_night_dossier(db, state, content, fine_ctx.out["pending_action_id"])
    strip_d = _close_night_dossier(db, state, content, strip_ctx.out["pending_action_id"])
    beat_d = _close_night_dossier(db, state, content, beat_ctx.out["pending_action_id"])
    assert db.get_character_status(fine_target.name)[0] == fine_status
    assert db.get_character_status(strip_target.name)[0] == "active"
    assert db.get_character_status(beat_target.name)[0] == beat_status

    db.apply_dossier_verdicts(state, [
        {"dossier_id": fine_d["id"], "decision": "promulgated"},
        {"dossier_id": strip_d["id"], "decision": "promulgated"},
        {"dossier_id": beat_d["id"], "decision": "promulgated"},
    ], content=content)

    moves = db.list_economy_moves_for_dossier(fine_d["id"])
    assert moves, "罚俸须落 economy_moves"
    assert moves[0]["category"] == "罚俸"
    assert int(moves[0]["delta"]) == -80
    assert int(state.metrics["国库"]) == treasury_before - 80
    assert db.get_character_status(fine_target.name)[0] == fine_status

    status, reason = db.get_character_status(strip_target.name)
    row = db.conn.execute(
        "SELECT status, reason_code, status_reason FROM characters WHERE name=?",
        (strip_target.name,),
    ).fetchone()
    assert status == "dismissed"
    assert row["reason_code"] == "获罪削籍"
    assert content.characters[strip_target.name].status == "dismissed"

    assert db.get_character_status(beat_target.name)[0] == beat_status
    beat_logs = db.conn.execute(
        "SELECT action, payload_summary FROM person_logs WHERE person_name=? ORDER BY id",
        (beat_target.name,),
    ).fetchall()
    assert len(beat_logs) == beat_logs_before + 1
    assert beat_logs[-1]["action"] == "廷杖"
    assert "80" not in str(beat_logs[-1]["payload_summary"] or "")


def test_naowen_quzhi_is_punishment_not_dismiss(game):
    """AC4：拿问去职走惩处下狱，不得折成任免罢免。"""
    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_punishment(db, state.turn, target.name, action="拿问去职")
    pending_id = ctx.out["pending_action_id"]
    row = db.conn.execute(
        "SELECT kind, action, payload_json FROM pending_actions WHERE id=?",
        (pending_id,),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    assert row["kind"] == "directive"
    assert payload["dossier_action_type"] == "punishment"
    assert payload["punish_action"] == "拿问去职"
    office_rows = [
        r for r in db.list_pending_actions(int(state.turn))
        if r["kind"] == "office" and r["action"] == "罢免"
    ]
    assert office_rows == []

    dossier = _close_night_dossier(db, state, content, pending_id)
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "imprisoned"


def test_punishment_restore_from_db_only_is_lossless(game):
    """AC5：restore 只读 DB 能接续下狱结果与案卷。"""
    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_punishment(db, state.turn, target.name, action="拿问下狱")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    content.characters[target.name].status = "active"
    reload_state_from_db(db, state, content=content)
    assert db.get_character_status(target.name)[0] == "imprisoned"
    assert content.characters[target.name].status == "imprisoned"
    restored = db.get_decree_dossier(dossier["id"])
    assert restored["action_type"] == "punishment"
    assert restored["target_id"] == target.name


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


def test_scripted_punishment_stages_via_apply_then_close_night(game, monkeypatch):
    """真实 apply 缝暂存惩处；收夜落案卷后 imprisoned 仍待判决。"""
    db, state, content = game
    actor = _active_ming(db, content)
    target = _active_ming(db, content, exclude=actor.name)
    _silence_serial(monkeypatch)
    monkeypatch.setattr(
        cb, "extract_appointment_action",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("拿问不得走任免抽取")),
    )
    sess = _bind_apply(db, state, content)
    scripted = candidates_from_classifier_payload({
        "kind": "punishment", "punish_action": "拿问下狱", "name": target.name,
        "transaction_category": "缉拿",
    }, soft=False)
    out = sess.apply_cli_conversation_actions(
        actor, f"将{target.name}拿问下狱。",
        f"臣请将{target.name}拿问下狱，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None, preclassified_intent=scripted,
    )
    pending_id = out.get("pending_action_id")
    assert pending_id
    assert db.get_character_status(target.name)[0] == "active"
    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "punishment"
    assert db.get_character_status(target.name)[0] == "active"
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "imprisoned"


def test_confirm_accept_does_not_imprison(game, monkeypatch):
    """应允只过确认闸，不得在判决前落下狱。"""
    db, state, content = game
    actor = _active_ming(db, content)
    target = _active_ming(db, content, exclude=actor.name)
    _silence_serial(monkeypatch)
    sess = _bind_apply(db, state, content)
    scripted = candidates_from_classifier_payload({
        "kind": "punishment", "punish_action": "拿问下狱", "name": target.name,
    }, soft=False)
    out = sess.apply_cli_conversation_actions(
        actor, f"将{target.name}拿问下狱。",
        f"臣请将{target.name}拿问下狱，请陛下定夺准驳。",
        has_directive=False, secret_order_id=None, preclassified_intent=scripted,
    )
    pending_id = out.get("pending_action_id")
    sess.apply_cli_conversation_actions(
        actor, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={int(pending_id)},
    )
    assert db.get_character_status(target.name)[0] == "active"
    assert content.characters[target.name].status == "active"


def test_cisi_kills_only_after_verdict(game):
    """同类型：赐死走同一案卷+判决双拍，顺颁后 dead。"""
    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_punishment(db, state.turn, target.name, action="赐死")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.get_character_status(target.name)[0] == "active"
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "dead"
    assert content.characters[target.name].status == "dead"


def test_zhaoxue_restores_dismissed_to_active_after_verdict(game):
    """同类型：昭雪回迁 dismissed→active。"""
    db, state, content = game
    target = _active_ming(db, content)
    db.set_character_status(
        state, target.name, "dismissed", "获罪削籍", reason_code="获罪削籍",
    )
    content.characters[target.name].status = "dismissed"
    ctx = _stage_punishment(db, state.turn, target.name, action="昭雪")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.get_character_status(target.name)[0] == "dismissed"
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "active"
    assert content.characters[target.name].status == "active"


def test_punishment_admission_rejects_missing_blank_or_illegal_action(game):
    """类2：admission 对缺失/空白/非法 punish_action 响亮拒绝。"""
    db, state, content = game
    target = _active_ming(db, content)
    base = {
        "text": f"将{target.name}拿问下狱。",
        "actor": target.name,
        "dossier_action_type": "punishment",
        "target_kind": "character",
        "target_id": target.name,
        "mode": "ordinary",
    }
    with pytest.raises(ValueError, match="punish_action"):
        db._normalize_directive_dossier_payload(
            dict(base), content=content, current_turn=state.turn,
        )
    with pytest.raises(ValueError, match="punish_action"):
        db._normalize_directive_dossier_payload(
            {**base, "punish_action": "   "},
            content=content, current_turn=state.turn,
        )
    with pytest.raises(ValueError, match="punish_action"):
        db._normalize_directive_dossier_payload(
            {**base, "punish_action": "抄家"},
            content=content, current_turn=state.turn,
        )
    ok = db._normalize_directive_dossier_payload(
        {**base, "punish_action": "拿问下狱"},
        content=content, current_turn=state.turn,
    )
    assert ok["punish_action"] == "拿问下狱"


def test_pardon_refuses_dead_keeps_terminal_status(game):
    """类3：宥赦拒绝 dead，人物保持终态。"""
    db, state, content = game
    target = _active_ming(db, content)
    db.set_character_status(state, target.name, "dead", "旧案赐死")
    content.characters[target.name].status = "dead"
    ctx = _stage_punishment(db, state.turn, target.name, action="放归")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.get_character_status(target.name)[0] == "dead"
    with pytest.raises(ValueError, match="dead|终态|宥赦|放归"):
        db.apply_dossier_verdicts(
            state,
            [{"dossier_id": dossier["id"], "decision": "promulgated"}],
            content=content,
        )
    assert db.get_character_status(target.name)[0] == "dead"
    assert content.characters[target.name].status == "dead"


# ── #517 r2 四类 ──────────────────────────────────────────────


def _directive_session(db, state, content):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    return sess


def _pending_directive_payloads(db, turn, minister):
    rows = [
        p for p in db.list_pending_actions(turn, minister_name=minister)
        if p.get("kind") == "directive" and p.get("status") == "pending"
    ]
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        out.append((int(row["id"]), payload if isinstance(payload, dict) else {}))
    return out


def test_fine_admission_requires_positive_amount(game):
    """r2 类1：罚俸缺正数 amount 不得成案（normalize + stage 双缝）。"""
    db, state, content = game
    target = _active_ming(db, content)
    base = {
        "text": f"罚{target.name}俸银八十两。",
        "actor": target.name,
        "dossier_action_type": "punishment",
        "target_kind": "character",
        "target_id": target.name,
        "punish_action": "罚俸",
        "mode": "ordinary",
    }
    for bad in ({}, {"amount": 0}, {"amount": -8}, {"amount": "八十"}):
        with pytest.raises(ValueError, match="amount|罚俸"):
            db._normalize_directive_dossier_payload(
                {**base, **bad}, content=content, current_turn=state.turn,
            )

    ok = db._normalize_directive_dossier_payload(
        {**base, "amount": 80}, content=content, current_turn=state.turn,
    )
    assert ok["amount"] == 80

    # stage 缝：非法/缺额不得写入 pending
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    before = db.list_pending_actions(state.turn, minister_name=actor)
    for amount in (None, 0, -3, "坏"):
        pending_id = am.stage_punishment_candidate(
            db, state.turn, actor,
            text=f"罚{target.name}俸。",
            target_id=target.name,
            punish_action="罚俸",
            amount=amount,
        )
        assert pending_id == 0
    after = db.list_pending_actions(state.turn, minister_name=actor)
    assert len(after) == len(before)

    staged = am.stage_punishment_candidate(
        db, state.turn, actor,
        text=f"罚{target.name}俸银八十两。",
        target_id=target.name,
        punish_action="罚俸",
        amount=80,
    )
    assert staged > 0
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (staged,),
    ).fetchone()["payload_json"])
    assert payload["amount"] == 80


def test_fine_underfunded_treasury_fails_loud_not_fulfilled(game):
    """r2 类2：罚俸减项不足额/零落账响亮失败，事务回滚，不得 fulfilled。"""
    db, state, content = game
    target = _active_ming(db, content)
    state.metrics["国库"] = 30
    db.sync_economy_accounts(state)
    treasury_before = int(state.metrics["国库"])

    ctx = _stage_punishment(
        db, state.turn, target.name, action="罚俸", amount=80,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []

    with pytest.raises(ValueError, match="不足|罚俸|amount"):
        db.apply_dossier_verdicts(
            state,
            [{"dossier_id": dossier["id"], "decision": "promulgated"}],
            content=content,
        )

    # 回滚：国库与案卷均不得伪造成功结案
    assert int(state.metrics["国库"]) == treasury_before
    assert db.list_economy_moves_for_dossier(dossier["id"]) == []
    row = db.get_decree_dossier(dossier["id"])
    assert row["status"] == "proposed"
    assert str(row.get("execution_outcome") or "") != "fulfilled"


def test_promulgated_terminal_punishment_enters_sim_as_inert_context(game):
    """r2 类3：顺颁 terminal punishment 进当月推演惰性上下文；无叙事重放物化面。"""
    from ming_sim.decree import project_dossiers_for_simulator

    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_punishment(db, state.turn, target.name, action="拿问下狱")
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    decree_text = str(dossier.get("decree_text") or "")

    # 结算组装窗：list_for_simulation 含 proposed；settlement_verdict=promulgated 表示顺颁。
    visible = []
    for row in db.list_decree_dossiers_for_simulation(state.turn):
        item = dict(row)
        if int(item["id"]) == int(dossier["id"]):
            item["settlement_verdict"] = "promulgated"
        visible.append(item)

    projected = project_dossiers_for_simulator(visible, db=db, state=state)
    hit = next(r for r in projected if int(r["id"]) == int(dossier["id"]))
    assert hit["action_type"] == "punishment"
    assert hit["target_id"] == target.name
    assert "decree_text" not in hit
    assert "payload" not in hit and "payload_json" not in hit
    summary = hit["execution_summary"]
    assert summary["command"] == decree_text
    assert summary.get("punish_action") == "拿问下狱"
    # 目标在行级 target_id，不重复塞进 summary，避免破坏既有 in-transit 组装契约
    assert hit["target_id"] == target.name

    # 打回不得进推演上下文
    rejected_visible = []
    for row in db.list_decree_dossiers_for_simulation(state.turn):
        item = dict(row)
        if int(item["id"]) == int(dossier["id"]):
            item["settlement_verdict"] = "rejected"
        rejected_visible.append(item)
    rejected_ids = {
        int(r["id"]) for r in project_dossiers_for_simulator(
            rejected_visible, db=db, state=state,
        )
    }
    assert int(dossier["id"]) not in rejected_ids


def test_api_tool_punishment_stages_structured_not_special_decree(game):
    """r2/r3：API propose_directive 惩处只认结构化字段，不降级 special_decree。"""
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1",
        (target.name,),
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    failures = []

    pending_id = sess._stage_directive_tool_candidate(
        f"着将{target.name}拿问下狱，严加看管。",
        minister,
        f"拟旨拿问{target.name}。",
        failures_out=failures,
        punish_action="拿问下狱",
        target_id=target.name,
        transaction_category="缉拿",
    )
    assert pending_id > 0
    assert not failures
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert payload["dossier_action_type"] == "punishment"
    assert payload["punish_action"] == "拿问下狱"
    assert payload["target_id"] == target.name
    assert payload["transaction_category"] == "缉拿"
    assert payload.get("dossier_action_type") != "special_decree"


def test_api_tool_punishment_unknown_or_incomplete_fails_loud_not_special_decree(game):
    """r2/r3：结构化惩处目标未知/罚俸无金额 → fail-loud，不得 special_decree。"""
    db, state, content = game
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    before = _pending_directive_payloads(db, state.turn, minister)

    failures = []
    pending_id = sess._stage_directive_tool_candidate(
        "着将并不存在的人拿问下狱。",
        minister,
        "拿问下狱。",
        failures_out=failures,
        punish_action="拿问下狱",
        name="并不存在的人",
    )
    assert pending_id == 0
    assert failures
    assert all("惩处" in str(f.get("message") or "") or "拿问" in str(f.get("message") or "")
              for f in failures)

    target = _active_ming(db, content)
    failures2 = []
    pending_id2 = sess._stage_directive_tool_candidate(
        f"着罚{target.name}俸示惩。",
        minister,
        f"罚{target.name}俸。",
        failures_out=failures2,
        punish_action="罚俸",
        target_id=target.name,
    )
    assert pending_id2 == 0
    assert failures2

    after = _pending_directive_payloads(db, state.turn, minister)
    assert after == before
    assert not any(
        p.get("dossier_action_type") == "special_decree" for _, p in after
    )


def test_api_tool_fine_with_amount_stages(game):
    """r2/r3：罚俸正数金额经显式 tool 字段结构化暂存，不从散文猜数字。"""
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1",
        (target.name,),
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    failures = []
    pending_id = sess._stage_directive_tool_candidate(
        f"着罚{target.name}俸银80两。",
        minister,
        f"罚俸{target.name}。",
        failures_out=failures,
        punish_action="罚俸",
        target_id=target.name,
        amount=80,
    )
    assert pending_id > 0
    assert not failures
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert payload["dossier_action_type"] == "punishment"
    assert payload["punish_action"] == "罚俸"
    assert payload["target_id"] == target.name
    assert int(payload["amount"]) == 80


def test_api_tool_prose_discussion_of_caning_exile_pardon_stays_ordinary(game):
    """r3：讨论廷杖/流放/昭雪且点名大臣 → 普通拟旨，不升 punishment。"""
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1",
        (target.name,),
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)

    for prose in (
        f"臣以为{target.name}若再误事可议廷杖，然今日仅请陛下审慎。",
        f"流放{target.name}之议尚早，请先查明再议。",
        f"昭雪{target.name}旧案仍待核部，臣请从长计议。",
    ):
        failures = []
        pending_id = sess._stage_directive_tool_candidate(
            prose,
            minister,
            "拟旨如下：请议处分制度。",
            failures_out=failures,
        )
        assert pending_id > 0, prose
        assert not failures, prose
        payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
        assert payload.get("dossier_action_type") != "punishment", prose
        assert payload.get("punish_action") in (None, "", "无"), prose


def test_api_tool_prose_date_number_before_fine_does_not_become_amount(game):
    """r3：拟旨散文含日期/次数数字且无结构化 amount → 不升罚俸惩处。"""
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1",
        (target.name,),
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    failures = []
    # 首个数字是日期/次数；若仍走散文猜金额会误取 3 或 15 为罚俸两数。
    prose = f"三月十五日再议，{target.name}罚俸之例容后核。"
    pending_id = sess._stage_directive_tool_candidate(
        prose,
        minister,
        "拟旨如下：请议罚俸制度。",
        failures_out=failures,
    )
    assert pending_id > 0
    assert not failures
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert payload.get("dossier_action_type") != "punishment"
    assert payload.get("punish_action") in (None, "", "无")
    assert int(payload.get("amount") or 0) == 0


def test_api_tool_args_deliver_punishment_fields_through_chat(game):
    """r3：propose_directive tool arguments 契约交付 punish_action/目标/金额。

    散文首个数字是日期；金额只认 arguments.amount，防止散文猜数伪绿。
    """
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1",
        (target.name,),
    ).fetchone()["name"]

    class Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣已拟旨，请陛下定夺。",
                tools=[
                    SimpleNamespace(
                        tool_name="propose_directive",
                        result="",
                        arguments={
                            "decree_text": f"三月再议，着罚{target.name}俸示惩。",
                            "punish_action": "罚俸",
                            "target_id": target.name,
                            "amount": 120,
                        },
                    )
                ],
            )

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *_args, **_kwargs: None
    sess._finish_cli_action_intent = lambda *_args, **_kwargs: None

    result = GameSession.chat(sess, minister, f"拟旨罚{target.name}俸。")
    assert result.pending_action_id
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[
        int(result.pending_action_id)
    ]
    assert payload["dossier_action_type"] == "punishment"
    assert payload["punish_action"] == "罚俸"
    assert payload["target_id"] == target.name
    assert int(payload["amount"]) == 120


def test_propose_directive_exposes_optional_transaction_category(game):
    db, state, content = game
    character = _active_ming(db, content)
    context = CourtContext(state=state, db=db, previous_summary="")
    tool = next(
        item for item in build_minister_tools(character, context)
        if item.__name__ == "propose_directive"
    )
    parameter = inspect.signature(tool).parameters["transaction_category"]
    assert parameter.default == ""


def test_api_tool_invalid_punishment_category_fails_without_side_effects(game):
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1", (target.name,),
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    pending_before = db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
    dossiers_before = db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0]
    failures = []

    pending_id = sess._stage_directive_tool_candidate(
        f"着将{target.name}拿问下狱。", minister, f"拟旨拿问{target.name}。",
        failures_out=failures, punish_action="拿问下狱", target_id=target.name,
        transaction_category="修仙",
    )

    assert pending_id == 0
    assert failures
    assert db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == pending_before
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == dossiers_before


def test_web_stream_transports_punishment_category_to_real_stage(game):
    db, state, content = game
    target = _active_ming(db, content)
    minister = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' "
        "AND name!=? LIMIT 1", (target.name,),
    ).fetchone()["name"]
    sess = _directive_session(db, state, content)
    web_game = web_app.WebGame.__new__(web_app.WebGame)
    web_game.session = sess
    web_game.chat_history = {name: [] for name in content.characters}
    web_game.suggestions_for = lambda _character: []
    web_game.chat_projection = lambda name: list(web_game.chat_history.get(name) or [])
    web_game.directive_rows = lambda: []
    web_game.directive_payload = lambda row: row
    web_game.can_undo_last_chat = lambda _name: False
    web_game._record_chat_rollback_items = lambda *_a, **_k: None
    def interpret(category_marker):
        arguments = {
            "decree_text": f"着将{target.name}拿问下狱。",
            "punish_action": "拿问下狱", "target_id": target.name,
        }
        if category_marker is not None:
            arguments["transaction_category"] = category_marker
        run_output = SimpleNamespace(tools=[SimpleNamespace(
            tool_name="propose_directive", result="", arguments=arguments,
        )])
        return web_app.WebGame._chat_stream_interpret_tools(
            web_game, minister, f"拟旨拿问{target.name}。", content.characters[minister],
            "臣已拟旨。", run_output, None, 0,
        )

    missing = interpret(None)
    pending_id = int(missing["pending_action_id"])
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert "transaction_category" not in payload
    assert not missing.get("pending_action_failures")

    valid = interpret("缉拿")
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert payload["transaction_category"] == "缉拿"
    assert not valid.get("pending_action_failures")

    pending_before = db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
    dossiers_before = db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0]
    invalid = interpret("修仙")
    assert invalid.get("pending_action_id") in (0, None)
    assert invalid.get("pending_action_failures")
    assert db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == pending_before
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == dossiers_before


def test_punishment_promulgation_refreshes_target_after_outer_commit(game):
    """#672：惩处人物处置经 outer-commit callback 刷新 registry。"""
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    target = _active_ming(db, content)
    ctx = _stage_punishment(db, state.turn, target.name, action="拿问下狱")
    pending_id = ctx.out["pending_action_id"]
    dossier = _close_night_dossier(db, state, content, pending_id)

    class _Reg:
        def __init__(self):
            self.refreshed = []

        def refresh(self, name):
            self.refreshed.append(name)

    reg = _Reg()
    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content, registry=reg,
        dossier_verdicts=[{"dossier_id": dossier["id"], "decision": "promulgated"}],
        delta_applier=lambda *a, **k: {},
    )
    assert target.name in reg.refreshed
    assert db.get_character_status(target.name)[0] == "imprisoned"
