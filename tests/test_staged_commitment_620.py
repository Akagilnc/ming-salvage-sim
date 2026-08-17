"""#620 分段承诺载体（0074）：一条多段=单一承诺对象 + form③ 扩段到期写次回合召对待办。

Seams:
- apply_score_extraction / insert_issue（stages_json 落库）
- scripted stages materializer（AC2「三年X五年Y」，禁 live-LLM 唯一验收）
- settle_with_delta 结算内确定性写 next_audience_todos
- list_next_audience_todos 下一召对回合可读 + load_state restore 接续
- 负向：不置 TurnPhase.AWAITING_DECISION；不因本片条目产生 ResolveResult.awaiting
"""

from __future__ import annotations

import json

from ming_sim.decree import ResolveResult, settle_with_delta
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase
from ming_sim.staged_commitment import (
    ENTRY_KIND_STAGED,
    normalize_commitment_stages,
    parse_staged_year_promise,
    write_due_staged_commitment_todos,
)


def _promulgated_origin(db, state, token: str) -> str:
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text=f"分段承诺：{token}",
        target_kind="issue",
        target_id=token,
        payload={"token": token},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


def _issue_row(db, issue_id: int):
    row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    assert row is not None
    return row


def _settle_empty_month(db, state, content):
    before = state.turn
    settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1


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


# ── AC2：scripted「三年X五年Y」夹具，禁 live-LLM 唯一验收 ─────────────


def test_scripted_三年x_五年y_captures_two_stages(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    text = "臣请立军令状：三年火器见眉目，五年新历成。请陛下定夺准驳。"
    stages = parse_staged_year_promise(text, origin_turn=state.turn)
    assert len(stages) == 2
    assert stages[0]["due_turn"] == state.turn + 36
    assert stages[0]["criterion_text"] == "火器见眉目"
    assert stages[0]["origin_context"] == "三年火器见眉目"
    assert stages[1]["due_turn"] == state.turn + 60
    assert stages[1]["criterion_text"] == "新历成"
    assert stages[1]["origin_context"] == "五年新历成"

    issue_id = _insert_staged_commitment(db, state, content, stages=stages)
    stored = normalize_commitment_stages(_issue_row(db, issue_id)["stages_json"])
    assert [s["origin_context"] for s in stored] == [
        "三年火器见眉目",
        "五年新历成",
    ]


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

    # 段 1 到期再写一条；去重键含 commitment_id×stage_idx
    _settle_empty_month(db, state, content)
    _settle_empty_month(db, state, content)
    todos = db.list_next_audience_todos(status="pending")
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in todos} == {
        (issue_id, 0),
        (issue_id, 1),
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


# ── AC 负向：不停轮 / 不 awaiting ────────────────────────────────────


def test_stage_due_settlement_does_not_set_awaiting_decision(game):
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
    _settle_empty_month(db, state, content)  # 段到期当回合结算内写入
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    assert state.turn_phase not in {TurnPhase.AWAITING_DECISION.value, "awaiting_decision"}

    todos = db.list_next_audience_todos(status="pending")
    assert len(todos) == 1
    # 结算完成后相位不在 awaiting_decision
    assert state.turn_phase == TurnPhase.SUMMONING.value
    assert db.list_pending_decisions(state.turn - 1) == []
    assert db.list_pending_decisions(state.turn) == []


def test_stage_due_does_not_produce_resolve_result_awaiting(game):
    """本片条目不得把 ResolveResult.awaiting 置 True（不接 DECISION 停轮路径）。"""
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
    _insert_staged_commitment(db, state, content, stages=stages)

    before = state.turn
    # settle_with_delta 是不停轮结算体；本片只经此写 todo，不经 HITL DECISION
    report = settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert isinstance(report, str) and report
    assert state.turn == before + 1
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    # 构造对照：本片写路径本身等价于 awaiting=False 的结算完成
    result = ResolveResult(awaiting=False, report=report)
    assert result.awaiting is False
    assert db.list_next_audience_todos(status="pending")
    assert "<<DECISION>>" not in report


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
    _settle_empty_month(db, reloaded, content)  # 段1 到期
    todos = db.list_next_audience_todos(status="pending")
    assert {(int(t["commitment_ref"]), int(t["stage_idx"])) for t in todos} == {
        (issue_id, 0),
        (issue_id, 1),
    }


# ── AC：原诺语境持久可查 ─────────────────────────────────────────────


def test_origin_context_persists_on_stages_and_todos(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    stages = parse_staged_year_promise(
        "三年火器见眉目，五年新历成",
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


def test_staged_commitment_skips_form3_one_shot_due_channel(game):
    """分段承诺不走 form③ 单值 end_turn 待核议通道（避免 DECISION 停轮）。"""
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
    payload = build_simulator_payload(state, db, "", "")
    due = [
        item
        for item in payload.get("due_commitments") or []
        if item.get("entry_kind") == "due_commitment"
        and int(item.get("issue_id") or 0) == issue_id
    ]
    assert due == []
    # 而是写次回合召对待办
    write_due_staged_commitment_todos(db, state)
    assert db.list_next_audience_todos()
