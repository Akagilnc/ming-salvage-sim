"""#621 到期复核判官（0076）——复命触发形态。

Seams:
- next_audience_todos 消费单写口 pending→consumed（幂等 / 滚存 / restore）
- list_due_review_scenes 次回合召对复命场面（P4 定性、含 origin_context）
- apply_pending_due_reviews → record_dossier_execution 适配器（有案卷桥）
- 无案卷分支：只场面+奏报，不伪造案卷
- 中段 executing+close=False 不连坐 vs 末段终值+close+至多一次连坐
- EXTRACTION_MODULES 基数不变；无 AWAITING_DECISION / <<DECISION>>
- 接管：到期目标 extractor 重复终值拒收
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issue_engine
from ming_sim.audience_night import list_ledger, open_night
from ming_sim.decree import settle_with_delta
from ming_sim.due_review import (
    apply_pending_due_reviews,
    build_due_review_input,
    dossiers_with_pending_due_review,
    list_due_review_scenes,
    project_due_review_scene,
)
from ming_sim.issues import apply_score_extraction
from ming_sim.models import TurnPhase
from ming_sim.simulation import EXTRACTION_MODULES
from ming_sim.staged_commitment import (
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    write_due_staged_commitment_todos,
)


# ── fixtures ──────────────────────────────────────────────────────────


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


def _executing_policy_dossier(db, state, *, token: str = "due-review-621"):
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈差务·{token}",
        target_kind="issue",
        target_id=token,
        participants=[
            {"character_id": "倪元璐", "tier": "主办", "role": "清丈"},
            {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        ],
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id


def _insert_staged_commitment(
    db, state, content, *, stages, title="徐光启分段之诺", origin_ref: str = "",
):
    origin = origin_ref or _promulgated_origin(db, state, title)
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
    return int(created["issue_id"]), origin


def _settle_empty_month(db, state, content):
    before = state.turn
    report = settle_with_delta(state, db, {}, before_turn=before, content=content)
    assert state.turn == before + 1
    return report


def _cost_events(db, dossier_id, *, identity="连坐"):
    return [
        dict(row)
        for row in db.conn.execute(
            "SELECT * FROM decree_cost_events WHERE dossier_id=? AND cost_identity=? ORDER BY id",
            (int(dossier_id), identity),
        ).fetchall()
    ]


# ── P3 待办消费 ───────────────────────────────────────────────────────


def test_mark_todo_pending_to_consumed_is_idempotent(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(db, state, content, stages=stages)
    write_due_staged_commitment_todos(db, state)
    todos = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    assert len(todos) == 1
    todo_id = int(todos[0]["id"])

    assert db.mark_next_audience_todo_status(todo_id, TODO_STATUS_CONSUMED) is True
    assert db.mark_next_audience_todo_status(todo_id, TODO_STATUS_CONSUMED) is False
    row = db.list_next_audience_todos(commitment_ref=int(todos[0]["commitment_ref"]))[0]
    assert row["status"] == TODO_STATUS_CONSUMED
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []


def test_consumed_todo_does_not_resurrect_on_rescan(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(db, state, content, stages=stages)
    write_due_staged_commitment_todos(db, state)
    todo_id = int(db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]["id"])
    db.mark_next_audience_todo_status(todo_id, TODO_STATUS_CONSUMED)

    n = write_due_staged_commitment_todos(db, state)
    assert n == 0
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []
    assert len(db.list_next_audience_todos(status=TODO_STATUS_CONSUMED)) == 1


def test_unconsumed_todo_rolls_across_settles_and_restore(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(db, state, content, stages=stages)
    # 只写 todo，不走 apply_pending（直接写端）——滚存面
    write_due_staged_commitment_todos(db, state)
    pending = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    assert len(pending) == 1
    origin_context = pending[0]["origin_context"]

    # 再结算一拍（apply 会消费；此处用手工保持 pending 测滚存读端）
    # 先把 apply 路径旁路：直接推进并断言 list 仍可读
    state.turn += 1
    db.save_state(state)
    still = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    assert len(still) == 1
    assert still[0]["origin_context"] == origin_context

    # restore 只读 DB
    from ming_sim.db import GameDB
    path = db.path
    db.conn.close()
    db2 = GameDB(path)
    state2 = db2.load_state()
    todos2 = db2.list_next_audience_todos(status=TODO_STATUS_PENDING)
    assert len(todos2) == 1
    assert todos2[0]["origin_context"] == origin_context
    assert int(state2.turn) == int(state.turn)


# ── P4 场面顶出 + 原诺语境 ────────────────────────────────────────────


def test_due_review_scene_tops_next_audience_with_origin_context(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(db, state, content, stages=stages)
    write_due_staged_commitment_todos(db, state)

    scenes = list_due_review_scenes(db, state)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["origin_context"] == "三年火器见眉目"
    assert "复命" in scene["scene_text"]
    assert "三年火器见眉目" in scene["scene_text"]
    # P4 哨兵：枚举/系统词不进玩家可见串
    banned = (
        "fulfilled", "degraded", "failed", "transformed", "executing",
        "AWAITING_DECISION", "<<DECISION>>", "EXTRACTION_MODULES",
        "progress_band", "is_terminal",
    )
    blob = json.dumps(scene, ensure_ascii=False)
    for token in banned:
        assert token not in blob
        assert token not in scene["scene_text"]


def test_due_review_scene_tops_live_open_night_even_with_body(game):
    """C1：生产 open-beat 供 body 时，复命仍须顶上真实召对开夜账。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(db, state, content, stages=stages)
    write_due_staged_commitment_todos(db, state)

    # 模拟生产 ensure_open_night_for_audience(..., body=open_beat_text)
    open_beat = "戌时乾清宫，烛影摇红，召对启。"
    night = open_night(
        db, state, time_of_day="戌时", location="乾清宫", body=open_beat,
    )
    ledger = list_ledger(db, int(night["id"]))
    open_entries = [e for e in ledger if "开夜" in (e.get("tags") or [])]
    assert open_entries, ledger
    open_text = str(open_entries[0].get("body") or "")
    assert open_beat in open_text
    assert "复命" in open_text
    assert "三年火器见眉目" in open_text
    for token in ("fulfilled", "AWAITING_DECISION", "<<DECISION>>"):
        assert token not in open_text


# ── P1 有案卷桥 / 无案卷分支 ──────────────────────────────────────────


def test_dossier_branch_writes_execution_slot_via_adapter(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state)
    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn + 24,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    _insert_staged_commitment(
        db, state, content, stages=stages,
        origin_ref=f"dossier:{dossier_id}",
        title="有案卷分段之诺",
    )
    # settle 写 todo（中段到期）→ 次回合 settle 落格
    _settle_empty_month(db, state, content)
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    scenes = list_due_review_scenes(db, state)
    assert scenes and scenes[0]["origin_context"] == "三年火器见眉目"

    _settle_empty_month(db, state, content)
    dossier = db.get_decree_dossier(dossier_id)
    # 中段：过程态 executing，不结案
    assert dossier["execution_outcome"] == "executing"
    assert dossier["status"] == "executing"
    assert _cost_events(db, dossier_id) == []
    # todo 已消费
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []


def test_dossier_branch_negative_does_not_open_parallel_slot(game):
    """负向：有案卷桥不得另建第二执行格/平行案卷。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state)
    before_count = db.conn.execute("SELECT COUNT(*) AS c FROM decree_dossiers").fetchone()["c"]
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    write_due_staged_commitment_todos(db, state)
    # 人为把 created_turn 调旧，使本 settle 可消费
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)
    after_count = db.conn.execute("SELECT COUNT(*) AS c FROM decree_dossiers").fetchone()["c"]
    assert after_count == before_count
    assert db.get_decree_dossier(dossier_id)["id"] == dossier_id


def test_no_dossier_branch_only_scene_no_forged_dossier(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    before_count = db.conn.execute("SELECT COUNT(*) AS c FROM decree_dossiers").fetchone()["c"]
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    # origin 指向已颁但非 executing 的 assignment 案卷（或空执行面）——走无执行面案卷分支
    # 用无 origin_ref 的承诺：insert 仍需合法 origin；用已 close 的案卷模拟无执行桥
    origin = _promulgated_origin(db, state, "no-exec-surface")
    # promulgated assignment without executing transition stays promulgated if terminal?
    # assignment 有执行面；改为直接空 origin_ref 不可。用已 closed 案卷：
    did = int(origin.split(":")[1])
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed', execution_outcome='fulfilled' WHERE id=?",
        (did,),
    )
    db.conn.commit()
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=origin, title="无案卷桥之诺",
    )
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    scenes_before = list_due_review_scenes(db, state)
    assert scenes_before

    results = apply_pending_due_reviews(db, state, commit=True)
    assert results
    assert all(r.get("branch") == "no_dossier" for r in results)
    after_count = db.conn.execute("SELECT COUNT(*) AS c FROM decree_dossiers").fetchone()["c"]
    # 不新建案卷
    assert after_count == before_count + 1  # +1 是 origin 那条已存在的
    # 不改已结案卷执行格为第二真源
    assert db.get_decree_dossier(did)["status"] == "closed"
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []


def test_no_dossier_branch_negative_does_not_create_dossier(game):
    """负向：无案卷分支禁止 create_decree_dossier。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "农政见效",
        "origin_context": "七八年农政见效",
    }]
    origin = _promulgated_origin(db, state, "neg-no-dossier")
    did = int(origin.split(":")[1])
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed', execution_outcome='fulfilled' WHERE id=?",
        (did,),
    )
    db.conn.commit()
    before_ids = {
        int(r["id"])
        for r in db.conn.execute("SELECT id FROM decree_dossiers").fetchall()
    }
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=origin, title="负向无案卷",
    )
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)
    after_ids = {
        int(r["id"])
        for r in db.conn.execute("SELECT id FROM decree_dossiers").fetchall()
    }
    assert after_ids == before_ids


# ── P2 中段 vs 末段 ───────────────────────────────────────────────────


def test_mid_stage_no_close_no_joint_liability(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="mid")
    stages = [
        {
            "stage_idx": 0,
            "due_turn": state.turn,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": state.turn + 12,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["execution_outcome"] == "executing"
    assert dossier["status"] == "executing"
    assert _cost_events(db, dossier_id) == []
    # 过程奏报 is_terminal=False
    progress = db.list_dossier_progress(dossier_id)
    assert progress
    assert all(not p.get("is_terminal") for p in progress)


def test_final_stage_terminal_close_joint_liability_at_most_once(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="final")
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["execution_outcome"] in {"fulfilled", "degraded", "failed", "transformed"}
    assert dossier["status"] == "closed"
    # 无实账无表报 → failed ∈ 连坐触发集；整笔幂等门闩 cost_kind=liability 恰一行
    costs = _cost_events(db, dossier_id)
    liability_gates = [c for c in costs if c.get("cost_kind") == "liability"]
    assert len(liability_gates) == 1

    # 幂等腿：恢复 todo pending + created_turn < turn，并回退案卷 executing
    # （resolve 仅对 executing 走 dossier 枝），使二次真正再入 _apply_dossier_verdict/连坐
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?",
        (int(dossier_id),),
    )
    db.conn.execute(
        "UPDATE next_audience_todos SET status=?, created_turn=?",
        (TODO_STATUS_PENDING, state.turn - 1),
    )
    db.conn.commit()
    second = apply_pending_due_reviews(db, state, commit=True)
    assert second, "幂等腿须真正再入正式复核"
    assert second[0].get("branch") == "dossier", second
    assert (second[0].get("execution") or {}).get("rejected") is not True, second
    costs_after = _cost_events(db, dossier_id)
    assert costs_after == costs
    liability_after = [c for c in costs_after if c.get("cost_kind") == "liability"]
    assert len(liability_after) == 1


def test_executing_outcome_rejects_close_true(game):
    """负向：executing 不得 close=True（适配器契约）。"""
    db, state, _content = game
    dossier_id = _executing_policy_dossier(db, state, token="close-guard")
    with pytest.raises(ValueError, match="executing"):
        db.record_dossier_execution(
            dossier_id, "executing", "中段过程", state.turn, close=True, commit=True,
        )


# ── P4/P5 时序与机械哨兵 ──────────────────────────────────────────────


def test_three_beat_timing_todo_then_scene_then_slot(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="three-beat")
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn + 1,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )

    # beat0: 未到期
    _settle_empty_month(db, state, content)
    assert db.list_next_audience_todos() == []
    assert not list_due_review_scenes(db, state)

    # beat1: settle 写 todo
    _settle_empty_month(db, state, content)
    todos = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    assert len(todos) == 1
    # 落格尚未发生
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] in ("", None)
    # beat2: 召对场面可读
    scenes = list_due_review_scenes(db, state)
    assert len(scenes) == 1
    assert "复命" in scenes[0]["scene_text"]

    # beat3: 下一 settle 落格 + 消费
    _settle_empty_month(db, state, content)
    assert db.get_decree_dossier(dossier_id)["execution_outcome"]
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []


def test_extraction_modules_cardinality_unchanged():
    # #633：relations（关系档房）并入既有并发装配（五模块同一 executor）；
    # 本测试原意是钉 due_review 未增删 extractor 槽，随 #633 授权扩为五模块。
    assert EXTRACTION_MODULES == (
        "internal", "military_external", "issues", "personnel_secret", "relations",
    )
    assert len(EXTRACTION_MODULES) == 5


def test_due_review_settle_does_not_pause_or_decision(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="no-decision")
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    report1 = _settle_empty_month(db, state, content)
    assert "<<DECISION>>" not in report1
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    report2 = _settle_empty_month(db, state, content)
    assert "<<DECISION>>" not in report2
    assert state.turn_phase == TurnPhase.SUMMONING.value
    assert db.list_pending_decisions(state.turn) == []
    assert db.list_pending_decisions(state.turn - 1) == []


def test_input_closed_set_degrades_when_sources_missing(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(db, state, content, stages=stages)
    write_due_staged_commitment_todos(db, state)
    todo = db.list_next_audience_todos(status=TODO_STATUS_PENDING)[0]
    inp = build_due_review_input(db, todo)
    # 缺源降级：催办空列表不崩；监督史无在场行时亦为空（#625 建轨后仍可空）
    assert inp["urge_history"] == []
    assert inp["supervision_history"] == []  # 本夹具未挂稽核链
    assert inp["progress_reports"] == []
    assert inp.get("transformation_tendency_facts", {}).get("exposure_count", 0) == 0
    scene = project_due_review_scene(db, todo, review_input=inp)
    assert scene["scene_text"]


def test_formal_review_blocks_extractor_second_terminal(game):
    """接管：到期目标同月仅正式复核写终值；extractor 重复终值拒收。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="takeover")
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)
    first = db.get_decree_dossier(dossier_id)
    assert first["execution_outcome"] in {
        "fulfilled", "degraded", "failed", "transformed", "executing",
    }
    outcome_before = first["execution_outcome"]
    note_before = first["execution_note"]

    # 若已终值结案，extractor 重写应拒；若仍 executing（单段终裁应已结），强制终值路径：
    if first["status"] == "closed":
        # 重开 executing 模拟 extractor 抢写
        db.conn.execute(
            "UPDATE decree_dossiers SET status='executing' WHERE id=?",
            (dossier_id,),
        )
        db.conn.commit()

    # 放回一条 pending due-review 标记（接管窗）
    db.conn.execute(
        """
        UPDATE next_audience_todos
        SET status='pending', created_turn=?
        WHERE commitment_ref IN (
            SELECT id FROM issues WHERE origin_ref=?
        )
        """,
        (state.turn - 1, f"dossier:{dossier_id}"),
    )
    db.conn.commit()

    result = issue_engine.apply_score_extraction(
        db, state,
        {
            "dossier_executions": [{
                "dossier_id": dossier_id,
                "outcome": "transformed",
                "note": "extractor 抢写第二真源",
            }]
        },
        content=content,
    )
    item = result["dossier_executions"][0]
    assert item.get("rejected") is True

    # 正式复核终值不被 extractor 覆盖（若仍 closed 则 outcome 不变；重开后亦拒写）
    dossier = db.get_decree_dossier(dossier_id)
    if outcome_before in {"fulfilled", "degraded", "failed", "transformed"}:
        # 拒收后不应变成 extractor 的 transformed（除非本来就是）
        if outcome_before != "transformed":
            assert dossier["execution_outcome"] != "transformed" or dossier["execution_note"] == note_before


def test_due_month_extractor_blocked_before_todo_write(game):
    """C2：到期当月 extract（todo 尚未写）亦不得抢写终值——正式复核唯一终值写口。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="due-month-takeover")
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    # 故意不写 todo：模拟 settle 内 extract 早于 write_due 的窗
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []
    owned = dossiers_with_pending_due_review(db, state)
    assert dossier_id in owned

    before = db.get_decree_dossier(dossier_id)
    assert before["status"] == "executing"
    assert before["execution_outcome"] in ("", None)

    result = issue_engine.apply_score_extraction(
        db, state,
        {
            "dossier_executions": [{
                "dossier_id": dossier_id,
                "outcome": "fulfilled",
                "note": "extractor 到期月抢写终值",
            }]
        },
        content=content,
    )
    item = result["dossier_executions"][0]
    assert item.get("rejected") is True
    assert "正式复核" in str(item.get("reason") or "")

    after = db.get_decree_dossier(dossier_id)
    assert after["status"] == "executing"
    assert after["execution_outcome"] in ("", None)


def test_takeover_guard_fail_closed_on_ownership_error(game, monkeypatch):
    """C3：所有权查询抛错不得 fail-open 放行 extractor 终值。"""
    db, state, content = game
    dossier_id = _executing_policy_dossier(db, state, token="fail-closed")

    def _boom(*_a, **_k):
        raise RuntimeError("ownership lookup boom")

    monkeypatch.setattr(
        "ming_sim.due_review.dossiers_with_pending_due_review", _boom,
    )
    with pytest.raises(RuntimeError, match="ownership lookup boom"):
        issue_engine.apply_score_extraction(
            db, state,
            {
                "dossier_executions": [{
                    "dossier_id": dossier_id,
                    "outcome": "failed",
                    "note": "应被守卫响亮挡住",
                }]
            },
            content=content,
        )
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["status"] == "executing"
    assert dossier["execution_outcome"] in ("", None)


def test_fulfilled_with_prior_durable_effect_zero_double_post(game):
    """生根：履行期已逐月落完 → 复核零重复落账。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="rooted")
    # 预先落一笔带 origin 的 durable 效果
    db.record_issue_economy_move(
        state, "国库", -3, "清丈经费", "履行期逐月已落",
        origin_ref=f"dossier:{dossier_id}", commit=True,
    )
    before_moves = db.list_economy_moves_for_dossier(dossier_id)
    assert before_moves
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    write_due_staged_commitment_todos(db, state)
    db.conn.execute(
        "UPDATE next_audience_todos SET created_turn=?",
        (state.turn - 1,),
    )
    db.conn.commit()
    apply_pending_due_reviews(db, state, commit=True)

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["execution_outcome"] == "fulfilled"
    after_moves = db.list_economy_moves_for_dossier(dossier_id)
    assert after_moves == before_moves


def test_p6_gap_visible_cause_not_auto(game):
    """0118 最小玩家面：果可见、因不自动。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="gap")
    db.record_dossier_progress(
        dossier_id, state.turn, "在办", "臣工奏称已办十之七八",
        is_terminal=False, commit=True,
    )
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    write_due_staged_commitment_todos(db, state)
    scene = list_due_review_scenes(db, state)[0]
    gap_text = scene.get("gap_text")
    statement_text = scene.get("statement_text")
    # 0118：缺口 + 陈词双到位（真值非空，缺席/None 不得靠 or "" 蒙混）
    assert isinstance(gap_text, str) and gap_text.strip()
    assert isinstance(statement_text, str) and statement_text.strip()
    # 因不自动：不得出现机械归因定论词
    for banned in ("真没办", "被吞", "欺瞒坐实", "归因="):
        assert banned not in scene["scene_text"]
        assert banned not in statement_text
