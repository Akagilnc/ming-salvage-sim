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

import json
import types
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
import ming_sim.action_materialize as am
import ming_sim.cli_backend as cb
from ming_sim.action_clusters import candidates_from_classifier_payload, cluster_by_kind
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.decree import reload_state_from_db
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


def _stage_punishment(db, turn, target, *, action="拿问下狱", amount=0, message=None, reply=None):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "punishment",
        "punish_action": action,
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


def test_naowen_quzhi_is_punishment_not_dismiss(game, monkeypatch):
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

    import inspect
    import ming_sim.cli_backend as cb
    source = inspect.getsource(cb.extract_appointment_action)
    assert "拿问去职=罢免" not in source
    assert "拿问去职" not in source

    captured = {}

    def _capture(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        return '{"任免动作":"无","姓名":"","官职":""}', 0

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    cb.extract_appointment_action(f"将{target.name}拿问去职。", "臣遵旨。")
    instructions = captured["prompt"].split("【皇帝】")[0]
    assert "拿问去职=罢免" not in instructions
    assert "拿问去职" not in instructions

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


def test_punish_action_enum_is_cluster_fieldspec_sole_source():
    """类1：ACTION_CLUSTERS FieldSpec 为 punish_action 唯一真源；无未用 PUNISH_* 分裂。"""
    assert not hasattr(am, "PUNISH_IMPRISON")
    assert not hasattr(am, "PUNISH_PARDON")
    cluster = cluster_by_kind("punishment")
    assert cluster is not None
    spec = next(f for f in cluster.fields if f.name == "punish_action")
    assert spec.allowed is not None
    assert "流放" in spec.allowed
    assert "无" in spec.allowed
    # 物化/准入 helper 必须读同一 FieldSpec，不得另抄 frozenset
    assert am.punish_actions_allowed() is spec.allowed
    assert am.punish_actions_effective() == (spec.allowed - {"无"})


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

    projected = project_dossiers_for_simulator(visible)
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
        int(r["id"]) for r in project_dossiers_for_simulator(rejected_visible)
    }
    assert int(dossier["id"]) not in rejected_ids


def test_api_tool_punishment_stages_structured_not_special_decree(game):
    """r2 类4：API propose_directive 惩处走结构化暂存，不降级 special_decree。"""
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
    )
    assert pending_id > 0
    assert not failures
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert payload["dossier_action_type"] == "punishment"
    assert payload["punish_action"] == "拿问下狱"
    assert payload["target_id"] == target.name
    assert payload.get("dossier_action_type") != "special_decree"


def test_api_tool_punishment_unknown_or_incomplete_fails_loud_not_special_decree(game):
    """r2 类4：惩处目标未知/罚俸无金额 → fail-loud，不得 special_decree。"""
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
    )
    assert pending_id2 == 0
    assert failures2

    after = _pending_directive_payloads(db, state.turn, minister)
    assert after == before
    assert not any(
        p.get("dossier_action_type") == "special_decree" for _, p in after
    )


def test_api_tool_fine_with_amount_stages(game):
    """r2 类4：罚俸带正数金额经 API 缝结构化暂存。"""
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
    )
    assert pending_id > 0
    assert not failures
    payload = dict(_pending_directive_payloads(db, state.turn, minister))[pending_id]
    assert payload["dossier_action_type"] == "punishment"
    assert payload["punish_action"] == "罚俸"
    assert payload["target_id"] == target.name
    assert int(payload["amount"]) == 80
