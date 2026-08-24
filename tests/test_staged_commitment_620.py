"""#620 分段承诺载体（0074）：一条多段=单一承诺对象 + 段到期写次回合召对待办。

Seams:
- apply_score_extraction / insert_issue（stages_json 落库；字符串面解析或响亮拒绝）
- 生产 capture_commitment_stages（召对 materializer / 邸报 new_issues，「三年X五年Y」）
- settle_with_delta 结算内确定性写 next_audience_todos
- list_next_audience_todos 下一召对回合可读 + load_state restore 接续
- 负向：不置 TurnPhase.AWAITING_DECISION；无 pending_decisions / <<DECISION>>
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.decree import settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase
from ming_sim.settlement_payload import augment_secret_orders_with_due_commitments
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    capture_commitment_stages,
    normalize_commitment_stages,
    stages_to_json,
    write_due_staged_commitment_todos,
)


def _promulgated_origin(db, state, token: str) -> str:
    # 起源夹具只需可颁布案卷 id。用 policy（非 multi_month 覆盖域）避免
    # #721 assignment 无点将时 duty_route_unmapped 拒成案，也不牵主办撤人边。
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"分段承诺：{token}",
        target_kind="issue",
        target_id=token,
        payload={"token": token},
    )
    assert dossier_id > 0
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _issue_row(db, issue_id: int):
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row is not None
    return row


def _settle_empty_month(db, state, content):
    before = state.turn
    report = settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1
    return report


def _insert_staged_commitment(db, state, content, *, stages, title="徐光启分段之诺"):
    origin = _promulgated_origin(db, state, title)
    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin,
                    "kind": "initiative",
                    "title": title,
                    "stage_text": "三年火器见眉目，五年新历成。",
                    "commitment_kind": "until_stop",
                    "ongoing_effects": {},
                    "stages": stages,
                }
            ]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    return int(created["issue_id"])


def _active_ming(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )


def _materialize_ctx(db, character, candidates, turn, *, message, reply):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False,
        has_directive=False,
        pend_for_minister=[],
        out={},
        intent=None,
        intent_kind="none",
        llm_config=None,
        intent_candidates=candidates,
        recent_context="",
    )


# ── AC1：一条多段=单一承诺对象，各段独立可查 ─────────────────────────


def test_one_multi_stage_commitment_is_single_issue_object(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn + 36,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn + 60,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    issue_id = _insert_staged_commitment(db, state, content, stages=stages)

    rows = db.conn.execute(
        "SELECT id FROM issues WHERE status='active' AND commitment_kind!=''"
    ).fetchall()
    assert len(rows) == 1
    assert int(rows[0]["id"]) == issue_id

    stored = normalize_commitment_stages(_issue_row(db, issue_id)["stages_json"])
    assert len(stored) == 2
    assert stored[0]["due_turn"] == state.turn + 36
    assert stored[0]["criterion_text"] == "火器见眉目"
    assert stored[1]["due_turn"] == state.turn + 60
    assert stored[1]["criterion_text"] == "新历成"


# ── AC2：生产捕获路径（召对 materializer / 邸报 score）scripted 夹具 ─


def test_audience_materializer_captures_三年x_五年y_into_stages(game):
    """召对生产路径：正文「三年X五年Y」经 stage_assignment_candidate 落段（非测专用 helper）。"""
    db, state, content = game
    actor = _active_ming(db, content)
    promise = "臣请立军令状：三年火器见眉目，五年新历成。请陛下定夺准驳。"
    # 分类器不给 stages——生产 capture 须从正文解析
    payload = {
        "kind": "assignment",
        "title": "徐光启火器历法之诺",
        "target_id": "xuguangqi-staged",
        "commitment_kind": "until_stop",
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _materialize_ctx(
        db, actor.name, candidates, state.turn,
        message="准徐光启分段之诺。",
        reply=promise,
    )
    run_materialize_pipeline(ctx)
    assert ctx.out.get("pending_action_id"), "须暂存交办候选"
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    stages = normalize_commitment_stages(pending.get("stages"))
    assert len(stages) == 2
    assert stages[0]["due_turn"] == state.turn + 36
    assert stages[0]["criterion_text"] == "火器见眉目"
    assert stages[0]["origin_context"] == "三年火器见眉目"
    assert stages[1]["due_turn"] == state.turn + 60
    assert stages[1]["criterion_text"] == "新历成"
    assert stages[1]["origin_context"] == "五年新历成"


def test_audience_entry_tolerates_classifier_bad_stages_falls_back_to_narrative(game):
    """召对入口分层：分类器坏形 stages 不抛未捕获异常；正文年诺仍文本捕获落段。

    库层 capture/stages_to_json 显式喂入仍 ValueError（见 list_bad_shape 测）。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    promise = "臣请立军令状：三年火器见眉目，五年新历成。请陛下定夺准驳。"
    payload = {
        "kind": "assignment",
        "title": "徐光启火器历法之诺",
        "target_id": "xuguangqi-staged-bad-clf",
        "commitment_kind": "until_stop",
        # 分类器产出坏形 list（due_turn=0）——入口须容错，不得掀翻召对
        "stages": [{"due_turn": 0, "criterion_text": "x"}],
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _materialize_ctx(
        db, actor.name, candidates, state.turn,
        message="准徐光启分段之诺。",
        reply=promise,
    )
    run_materialize_pipeline(ctx)  # 不得 raise
    assert ctx.out.get("pending_action_id"), "坏形 stages 不得阻断交办暂存"
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    stages = normalize_commitment_stages(pending.get("stages"))
    assert len(stages) == 2
    assert stages[0]["origin_context"] == "三年火器见眉目"
    assert stages[1]["origin_context"] == "五年新历成"
    # 库层仍响亮（分层：入口容错 ≠ 库层静默）
    with pytest.raises(ValueError, match="有效段"):
        capture_commitment_stages(
            [{"due_turn": 0, "criterion_text": "x"}], origin_turn=1,
        )


def test_audience_entry_structured_stages_without_year_promise_lands(game):
    """真入口结构化正向：分类器 nested stages 经 FieldSpec 运输后落段。

    正文无「三年X五年Y」字样——不得靠叙事年诺回落；证明 str(list)→repr
    运输洞已用 json.dumps 堵住（#620 r6 classifier-stages-string-transport）。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    reply = "臣请立军令状，分阶段推进火器与历法，请陛下定夺准驳。"
    assert "三年" not in reply and "五年" not in reply
    structured = [
        {
            "due_turn": int(state.turn) + 36,
            "criterion_text": "火器见眉目",
            "origin_context": "火器阶段",
        },
        {
            "due_turn": int(state.turn) + 60,
            "criterion_text": "新历成",
            "origin_context": "历法阶段",
        },
    ]
    payload = {
        "kind": "assignment",
        "title": "徐光启结构化分段之诺",
        "target_id": "xuguangqi-structured-clf",
        "commitment_kind": "until_stop",
        "stages": structured,
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    # 运输层：合法 JSON 数组串（非 Python repr 单引号）
    transported = candidates[0]["stages"]
    assert isinstance(transported, str)
    assert json.loads(transported) == structured
    ctx = _materialize_ctx(
        db, actor.name, candidates, state.turn,
        message="准徐光启分段之诺。",
        reply=reply,
    )
    run_materialize_pipeline(ctx)
    assert ctx.out.get("pending_action_id"), "结构化 stages 须落交办候选"
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    stages = normalize_commitment_stages(pending.get("stages"))
    assert len(stages) == 2
    assert stages[0]["due_turn"] == int(state.turn) + 36
    assert stages[0]["criterion_text"] == "火器见眉目"
    assert stages[0]["origin_context"] == "火器阶段"
    assert stages[1]["due_turn"] == int(state.turn) + 60
    assert stages[1]["criterion_text"] == "新历成"
    assert stages[1]["origin_context"] == "历法阶段"


def test_gazette_score_path_captures_三年x_五年y_from_stage_text(game):
    """邸报/score 生产路径：stage_text「三年X五年Y」经 capture 落 stages_json。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    origin = _promulgated_origin(db, state, "gazette-staged")
    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin,
                    "kind": "initiative",
                    "title": "徐光启分段之诺",
                    "stage_text": "三年火器见眉目，五年新历成。",
                    "commitment_kind": "until_stop",
                    "ongoing_effects": {},
                    # 不显式给 stages——生产 capture 从 stage_text 解析
                }
            ]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    stored = normalize_commitment_stages(_issue_row(db, int(created["issue_id"]))["stages_json"])
    assert [s["origin_context"] for s in stored] == [
        "三年火器见眉目",
        "五年新历成",
    ]
    assert stored[0]["due_turn"] == state.turn + 36
    assert stored[1]["due_turn"] == state.turn + 60


def test_capture_commitment_stages_is_production_entry(game):
    """CN year 解析挂在生产 capture 入口，非测试专用死码。"""
    db, state, _content = game
    stages = capture_commitment_stages(
        None,
        narrative_text="三年火器见眉目，五年新历成",
        origin_turn=state.turn,
    )
    assert len(stages) == 2
    assert stages[0]["origin_context"] == "三年火器见眉目"


# ── stages_json 字符串面：正确解析或响亮拒绝 ─────────────────────────


def test_stages_to_json_parses_json_string_not_char_iterate():
    raw = json.dumps([
        {
            "stage_idx": 0,
            "due_turn": 40,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        }
    ], ensure_ascii=False)
    blob = stages_to_json(raw)
    assert normalize_commitment_stages(blob) == [{
        "stage_idx": 0,
        "due_turn": 40,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]


def test_insert_issue_string_stages_json_persists_not_empty(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    origin = _promulgated_origin(db, state, "str-stages")
    stages_str = json.dumps([
        {
            "stage_idx": 0,
            "due_turn": state.turn + 12,
            "criterion_text": "见眉目",
            "origin_context": "一年见眉目",
        }
    ], ensure_ascii=False)
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="字符串段面",
        origin_kind="decree",
        origin_ref=origin,
        commitment_kind="until_stop",
        end_turn=state.turn + 12,
        stages_json=stages_str,
    )
    stored = normalize_commitment_stages(_issue_row(db, issue_id)["stages_json"])
    assert len(stored) == 1
    assert stored[0]["criterion_text"] == "见眉目"


def test_stages_to_json_invalid_string_refuses_loudly():
    with pytest.raises(ValueError, match="JSON"):
        stages_to_json("不是数组{")
    with pytest.raises(ValueError, match="JSON 数组|有效段"):
        stages_to_json('{"stage_idx":0}')
    with pytest.raises(ValueError, match="有效段"):
        stages_to_json('[{"due_turn":0,"criterion_text":"x"}]')


def test_capture_explicit_json_ish_garbage_stages_string_refuses_loudly():
    """负向：显式 stages 字符串 JSON-ish 坏形 → ValueError，勿静默 []。"""
    with pytest.raises(ValueError, match="JSON 数组|有效段"):
        capture_commitment_stages('{"stage_idx":0}', origin_turn=1)
    with pytest.raises(ValueError, match="有效段"):
        capture_commitment_stages(
            '[{"due_turn":0,"criterion_text":"x"}]',
            origin_turn=1,
        )
    with pytest.raises(ValueError, match="JSON 数组字符串|解析失败"):
        capture_commitment_stages("[{not-json", origin_turn=1)
    # 合法 JSON 段仍可捕获
    ok = capture_commitment_stages(
        json.dumps([
            {
                "stage_idx": 0,
                "due_turn": 40,
                "criterion_text": "火器见眉目",
                "origin_context": "三年火器见眉目",
            }
        ], ensure_ascii=False),
        origin_turn=1,
    )
    assert len(ok) == 1
    assert ok[0]["criterion_text"] == "火器见眉目"


def test_capture_and_stages_to_json_list_bad_shape_refuses_loudly():
    """负向：list/非 str 坏形与 str 同口径 raise；正向：合法 list 不误伤。"""
    bad_list = [{"due_turn": 0, "criterion_text": "x"}]
    with pytest.raises(ValueError, match="有效段"):
        capture_commitment_stages(bad_list, origin_turn=1)
    with pytest.raises(ValueError, match="有效段"):
        stages_to_json(bad_list)
    with pytest.raises(ValueError, match="JSON 数组"):
        capture_commitment_stages({"stage_idx": 0, "due_turn": 40}, origin_turn=1)
    with pytest.raises(ValueError, match="类型非法|JSON 数组"):
        stages_to_json({"stage_idx": 0, "due_turn": 40})
    # 正向：合法 list 段仍落
    good = [
        {
            "stage_idx": 0,
            "due_turn": 40,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        }
    ]
    captured = capture_commitment_stages(good, origin_turn=1)
    assert len(captured) == 1
    assert captured[0]["criterion_text"] == "火器见眉目"
    blob = stages_to_json(good)
    assert normalize_commitment_stages(blob)[0]["due_turn"] == 40


def test_insert_issue_invalid_stages_string_refuses(game):
    db, state, content = game
    origin = _promulgated_origin(db, state, "bad-stages")
    with pytest.raises(ValueError):
        db.insert_issue(
            state,
            kind="initiative",
            title="坏段",
            origin_kind="decree",
            origin_ref=origin,
            commitment_kind="until_stop",
            end_turn=state.turn + 3,
            stages_json="<<not-json>>",
        )


# ── AC3/P2：段到期写次回合召对待办；段间自动续 ───────────────────────


def test_stage_due_writes_next_audience_todo_and_continues(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stage0_due = state.turn + 1
    stage1_due = state.turn + 3
    stages = [
        {
            "stage_idx": 0,
            "due_turn": stage0_due,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": stage1_due,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    issue_id = _insert_staged_commitment(db, state, content, stages=stages)

    assert db.list_next_audience_todos() == []

    # 未到期：不写
    _settle_empty_month(db, state, content)
    assert db.list_next_audience_todos() == []

    # 段 0 到期当回合结算内写入
    _settle_empty_month(db, state, content)
    todos = db.list_next_audience_todos(status="pending")
    assert len(todos) == 1
    todo = todos[0]
    assert int(todo["commitment_ref"]) == issue_id
    assert int(todo["stage_idx"]) == 0
    assert int(todo["due_turn"]) == stage0_due
    assert todo["criterion_text"] == "火器见眉目"
    assert todo["origin_context"] == "三年火器见眉目"
    assert todo["status"] == "pending"
    assert todo["entry_kind"] == ENTRY_KIND_STAGED
    # 承诺对象仍 active，段间无需玩家 ACK
    assert _issue_row(db, issue_id)["status"] == "active"

    # 段 1 到期再写一条；去重键含 commitment_id×stage_idx。
    # #621 三拍：前回合 todo 于次回合 settle 消费，故段0已 consumed、段1 pending。
    _settle_empty_month(db, state, content)
    _settle_empty_month(db, state, content)
    pending = db.list_next_audience_todos(status="pending")
    consumed = db.list_next_audience_todos(status="consumed")
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in pending} == {
        (issue_id, 1),
    }
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in consumed} == {
        (issue_id, 0),
    }


def test_stage_due_dedup_key_is_commitment_id_times_stage_idx(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    issue_id = _insert_staged_commitment(db, state, content, stages=stages)

    n1 = write_due_staged_commitment_todos(db, state)
    n2 = write_due_staged_commitment_todos(db, state)
    assert n1 == 2
    assert n2 == 0  # 同 (commitment_id, stage_idx) 不重复写
    todos = db.list_next_audience_todos()
    assert len(todos) == 2
    assert {int(t["stage_idx"]) for t in todos} == {0, 1}
    assert all(int(t["commitment_ref"]) == issue_id for t in todos)


# ── AC 负向：不停轮（真入口 settle_with_delta + 闸类一条）────────────


def test_stage_due_via_settle_does_not_pause_turn(game):
    """经 settle_with_delta 真入口：段到期写 todo 后相位/pending_decisions/DECISION 均不停轮。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn + 1,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
    ]
    _insert_staged_commitment(db, state, content, stages=stages)

    _settle_empty_month(db, state, content)  # 未到期
    assert db.list_next_audience_todos() == []

    before = state.turn
    report = settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1
    # 相位
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    assert state.turn_phase not in {TurnPhase.AWAITING_DECISION.value, "awaiting_decision"}
    assert state.turn_phase == TurnPhase.SUMMONING.value
    # pending_decisions 空
    assert db.list_pending_decisions(state.turn - 1) == []
    assert db.list_pending_decisions(state.turn) == []
    # 无 DECISION 标记；todo 已写
    assert isinstance(report, str) and report
    assert "<<DECISION>>" not in report
    todos = db.list_next_audience_todos(status="pending")
    assert len(todos) == 1


def test_multi_stage_due_settlement_stays_out_of_awaiting_decision(game):
    """第二条不停轮负向：多段接连到期结算后仍不进 awaiting_decision。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn + 1,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    _insert_staged_commitment(db, state, content, stages=stages)

    _settle_empty_month(db, state, content)  # 段0
    assert state.turn_phase == TurnPhase.SUMMONING.value
    assert db.list_pending_decisions(state.turn) == []
    assert len(db.list_next_audience_todos(status="pending")) == 1

    _settle_empty_month(db, state, content)  # 段1：#621 消费段0，新写段1
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    assert state.turn_phase == TurnPhase.SUMMONING.value
    assert db.list_pending_decisions(state.turn) == []
    assert len(db.list_next_audience_todos(status="pending")) == 1
    assert int(db.list_next_audience_todos(status="pending")[0]["stage_idx"]) == 1
    assert len(db.list_next_audience_todos(status="consumed")) == 1


def test_staged_commitment_skips_form3_one_shot_due_channel(game):
    """闸类负向：分段不落派生 end_turn、不进 form③ due_commitment（避免 DECISION 停轮通道）。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
    ]
    issue_id = _insert_staged_commitment(db, state, content, stages=stages)
    # 派生 end_turn 不落 DB（仅 stages 承载段到期）
    row = _issue_row(db, issue_id)
    assert int(row["end_turn"] or 0) == 0
    payload = build_simulator_payload(state, db, "", "")
    due = [
        item
        for item in payload.get("due_commitments") or []
        if item.get("entry_kind") == "due_commitment"
        and int(item.get("issue_id") or 0) == issue_id
    ]
    assert due == []
    write_due_staged_commitment_todos(db, state)
    assert db.list_next_audience_todos()


def test_last_stage_due_with_ongoing_does_not_mechanical_expire(game):
    """验收：多段+ongoing 末段到期 settle → issue 仍 active + 末段 todo 已写 + 无 expire。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    state.metrics["国库"] = 500
    db.save_state(state)

    stage0_due = state.turn + 1
    stage1_due = state.turn + 2
    stages = [
        {
            "stage_idx": 0,
            "due_turn": stage0_due,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": stage1_due,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    origin = _promulgated_origin(db, state, "staged-ongoing")
    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin,
                    "kind": "initiative",
                    "title": "分段+ongoing",
                    "stage_text": "三年火器见眉目，五年新历成。",
                    "commitment_kind": "until_stop",
                    "ongoing_effects": {
                        "economy": [
                            {
                                "account": "国库",
                                "delta": -5,
                                "reason": "分段在办",
                                "purpose": "补饷",
                            }
                        ]
                    },
                    "stages": stages,
                }
            ]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    issue_id = int(created["issue_id"])
    assert int(_issue_row(db, issue_id)["end_turn"] or 0) == 0

    _settle_empty_month(db, state, content)  # 未到期
    _settle_empty_month(db, state, content)  # 段0
    _settle_empty_month(db, state, content)  # 段1 末段到期

    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=? ORDER BY id",
        (issue_id,),
    ).fetchall()
    assert "expire" not in {a["trigger_kind"] for a in advances}
    # #621 三拍消费：末段 settle 后段0 consumed、段1 本拍新写仍 pending
    pending = db.list_next_audience_todos(status="pending")
    consumed = db.list_next_audience_todos(status="consumed")
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in pending} == {
        (issue_id, 1),
    }
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in consumed} == {
        (issue_id, 0),
    }


def test_residual_stage_derived_end_turn_does_not_expire(game):
    """残存段派生 end_turn（=max due）+ ongoing：expire 路径仍排除，独立 end_turn 不受影响。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    state.metrics["国库"] = 500
    db.save_state(state)

    due = state.turn + 1
    stages = [
        {
            "stage_idx": 0,
            "due_turn": due,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": due,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    origin = _promulgated_origin(db, state, "residual-derived")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="残存派生 end_turn",
        origin_kind="decree",
        origin_ref=origin,
        commitment_kind="until_stop",
        end_turn=due,  # 故意写入段派生形状
        ongoing_effects={
            "economy": [
                {"account": "国库", "delta": -5, "reason": "残存", "purpose": "补饷"}
            ]
        },
        stages_json=stages,
    )
    _settle_empty_month(db, state, content)  # 到期回合
    row = _issue_row(db, issue_id)
    assert row["status"] == "active"
    advances = db.conn.execute(
        "SELECT trigger_kind FROM issue_advances WHERE issue_id=?",
        (issue_id,),
    ).fetchall()
    assert "expire" not in {a["trigger_kind"] for a in advances}


def test_ack_rejects_residual_stage_derived_end_turn(game):
    """闸类负向：acknowledged 不得收尾残存段派生 end_turn（=max due）承诺。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    due = state.turn  # 已到期，使 end_turn 门槛通过，专测段派生闸
    stages = [
        {
            "stage_idx": 0,
            "due_turn": due,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": due,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    origin = _promulgated_origin(db, state, "ack-derived")
    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="ack 残存派生 end_turn",
        origin_kind="decree",
        origin_ref=origin,
        commitment_kind="until_stop",
        end_turn=due,  # 故意写入段派生形状
        ongoing_effects={},
        stages_json=stages,
    )
    out = apply_score_extraction(
        db,
        state,
        {
            "close_issues": [
                {
                    "issue_id": issue_id,
                    "reason": "acknowledged",
                    "narrative": "试图以 ack 收尾段派生承诺",
                }
            ]
        },
        content=content,
    )
    closed = out["issue_summary"]["closes"][0]
    assert closed.get("rejected") is True, closed
    assert closed.get("category") == "invalid_enum"
    assert "段派生" in str(closed.get("reason") or "")
    assert _issue_row(db, issue_id)["status"] == "active"


def test_independent_end_turn_not_swallowed_when_stages_present(game):
    """C1：同行独立 end_turn（≠ max 段 due）仍走 form③ 待裁，不得被分段跳过面吞掉。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    independent_end = state.turn  # form③ 当回合到期
    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn + 36,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn + 60,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    origin = _promulgated_origin(db, state, "independent-end")
    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin,
                    "kind": "initiative",
                    "title": "分段+独立期满",
                    "stage_text": "另有三月期满复核",
                    "commitment_kind": "until_stop",
                    "ongoing_effects": {},
                    "end_turn": independent_end,
                    "stages": stages,
                }
            ]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    issue_id = int(created["issue_id"])
    row = _issue_row(db, issue_id)
    assert int(row["end_turn"]) == independent_end
    assert int(row["end_turn"]) != max(s["due_turn"] for s in stages)

    groups = augment_secret_orders_with_due_commitments({}, db, state)
    due_ids = {
        int(item["issue_id"])
        for item in (groups.get("待核议") or [])
        if item.get("entry_kind") == "due_commitment"
    }
    assert issue_id in due_ids


# ── AC：跨段 restore 无损（P1/TD-3）──────────────────────────────────


def test_mid_stage_restore_continues_later_stages(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn + 1,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn + 3,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    issue_id = _insert_staged_commitment(db, state, content, stages=stages)

    _settle_empty_month(db, state, content)  # turn+1 前
    _settle_empty_month(db, state, content)  # 段0 到期写入
    assert len(db.list_next_audience_todos()) == 1

    # 中段存档恢复：只读 DB 接续
    reloaded = db.load_state()
    assert reloaded.turn == state.turn
    todos_after_restore = db.list_next_audience_todos(status="pending")
    assert len(todos_after_restore) == 1
    assert int(todos_after_restore[0]["commitment_ref"]) == issue_id
    assert int(todos_after_restore[0]["stage_idx"]) == 0

    stored = normalize_commitment_stages(_issue_row(db, issue_id)["stages_json"])
    assert len(stored) == 2

    _settle_empty_month(db, reloaded, content)
    _settle_empty_month(db, reloaded, content)  # 段1 到期；#621 消费段0
    pending = db.list_next_audience_todos(status="pending")
    consumed = db.list_next_audience_todos(status="consumed")
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in pending} == {
        (issue_id, 1),
    }
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in consumed} == {
        (issue_id, 0),
    }


# ── AC：原诺语境持久可查 ─────────────────────────────────────────────


def test_origin_context_persists_on_stages_and_todos(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = capture_commitment_stages(
        None,
        narrative_text="三年火器见眉目，五年新历成",
        origin_turn=state.turn,
    )
    # 压到当回合到期以便写 todo
    for s in stages:
        s["due_turn"] = state.turn
    issue_id = _insert_staged_commitment(db, state, content, stages=stages)

    stored = normalize_commitment_stages(_issue_row(db, issue_id)["stages_json"])
    assert stored[0]["origin_context"] == "三年火器见眉目"
    assert stored[1]["origin_context"] == "五年新历成"

    write_due_staged_commitment_todos(db, state)
    todos = sorted(db.list_next_audience_todos(), key=lambda t: int(t["stage_idx"]))
    assert todos[0]["origin_context"] == "三年火器见眉目"
    assert todos[1]["origin_context"] == "五年新历成"


# ── AC6：不改 #520 本体——无 stages 的军令状 shape 仍可落 ─────────────


def test_plain_until_stop_without_stages_still_lands(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    origin = _promulgated_origin(db, state, "plain-until-stop")
    out = apply_score_extraction(
        db,
        state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree",
                    "origin_ref": origin,
                    "kind": "initiative",
                    "title": "三月后复试",
                    "commitment_kind": "until_stop",
                    "ongoing_effects": {},
                    "end_turn": state.turn + 3,
                }
            ]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False
    row = _issue_row(db, int(created["issue_id"]))
    assert row["commitment_kind"] == "until_stop"
    assert int(row["end_turn"]) == state.turn + 3
    assert normalize_commitment_stages(row["stages_json"]) == []
