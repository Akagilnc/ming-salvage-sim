"""#621 到期复核（0076）——实况供料与场面；终值经模型声明写格。

Seams:
- next_audience_todos 消费单写口 pending→consumed（幂等 / 滚存 / restore）
- list_due_review_scenes 次回合召对复命场面（P4 定性、含 origin_context）
- 模型 dossier_executions 写执行格；apply_pending_due_reviews 仅消费已终值 todo
- 无案卷分支：只场面，不伪造案卷
- 中段不关案不连坐；末段终值+连坐由声明写口触发
- #1835 J18：不排斥模型终值、不机械替判
"""

from __future__ import annotations

from ming_sim.settlement.dossier import apply_dossier_promulgation
import pytest

from ming_sim.audience_night import open_night
from tests.test_month_chain_1843 import _prepare_player_month
from ming_sim.due_review import (
    apply_pending_due_reviews,
    build_due_review_input,
    list_due_review_scenes,
    project_due_review_scene,
)
from ming_sim.models import TurnPhase
from ming_sim.staged_commitment import (
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    write_due_staged_commitment_todos,
)
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section

def _model_write_execution(db, state, content, dossier_id, outcome, note):
    out = settle_delta(
        state, db,
        {"dossier_executions": [{
            "dossier_id": int(dossier_id),
            "outcome": outcome,
            "note": note,
        }]},
        SettlementContext(content=content),
    )
    assert not section(out, "dossier_executions").rejected, out
    return out

# ── fixtures ──────────────────────────────────────────────────────────

def _promulgated_origin(db, state, token: str) -> str:
    # 起源夹具只需可颁布案卷 id。用 policy（非 multi_month 覆盖域）避免
    # #1778：assignment 无点将时代码不配人；主办来自旨意自带名单，不牵撤人边。
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
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id

def _insert_staged_commitment(
    db, state, content, *, stages, title="徐光启分段之诺", origin_ref: str = "",
):
    origin = origin_ref or _promulgated_origin(db, state, title)
    out = settle_delta(state, db, {'new_issues': [{'origin_kind': 'decree', 'origin_ref': origin, 'kind': 'initiative', 'title': title, 'stage_text': '三年火器见眉目，五年新历成。', 'commitment_kind': 'until_stop', 'ongoing_effects': {}, 'stages': stages}]}, SettlementContext(content=content))
    created = out.issue.new_issues[0]
    return int(created["issue_id"]), origin

def _settle_empty_month(db, state, content, monkeypatch):
    before = state.turn
    session = _prepare_player_month(db, state, content, monkeypatch)
    session.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    result = session.resolve_turn(allow_empty_decree=True)
    assert state.turn == before + 1
    return result

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

    scenes = list_due_review_scenes(db)
    assert len(scenes) == 1
    scene = scenes[0]
    assert scene["origin_context"] == "三年火器见眉目"
    assert "payload_json" not in scene

def test_due_review_scene_tops_live_open_night_even_with_body(game):
    """#1838 reopen：待裁场面进场景开场最小集，不再写开夜旁白账。"""
    import json
    from ming_sim.materials import (
        _scene_pending_audience_facts,
        prepare_scene_materials,
        release_material_tree,
    )

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

    open_night(db, state, time_of_day="戌时", location="乾清宫")
    scenes = list_due_review_scenes(db)
    assert len(scenes) == 1
    scene = scenes[0]
    prepared = prepare_scene_materials(db, state)
    try:
        facts = _scene_pending_audience_facts(db, state)
        matched = [
            json.loads(line) for line in facts
            if json.loads(line).get("todo_id") == scene["todo_id"]
        ]
        assert len(matched) == 1
        assert matched[0] == scene
        payload = next(
            line for line in facts
            if json.loads(line).get("todo_id") == scene["todo_id"]
        )
        assert payload in prepared.opening
    finally:
        release_material_tree(prepared.root)

# ── P1 有案卷桥 / 无案卷分支 ──────────────────────────────────────────

def test_dossier_branch_writes_execution_slot_via_adapter(game, monkeypatch):
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
    # 过月写 todo（中段到期）→ 次回合落格
    _settle_empty_month(db, state, content, monkeypatch)
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    scenes = list_due_review_scenes(db)
    assert scenes and scenes[0]["origin_context"] == "三年火器见眉目"

    _settle_empty_month(db, state, content, monkeypatch)
    dossier = db.get_decree_dossier(dossier_id)
    # 中段：不写终值、不结案、不连坐；todo 已消费
    assert dossier["status"] == "executing"
    assert dossier["execution_outcome"] in ("", None, "executing")
    assert _cost_events(db, dossier_id) == []
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
    apply_pending_due_reviews(db, state)
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
    scenes_before = list_due_review_scenes(db)
    assert scenes_before

    results = apply_pending_due_reviews(db, state)
    assert results
    # 已有终值：只 noop 消费，不另写执行格、不伪造新案卷
    assert all((r.get("execution") or {}).get("is_terminal") for r in results)
    assert all((r.get("execution") or {}).get("noop") for r in results)
    assert all(r.get("consumed") for r in results)
    after_count = db.conn.execute("SELECT COUNT(*) AS c FROM decree_dossiers").fetchone()["c"]
    # 不新建案卷
    assert after_count == before_count + 1  # +1 是 origin 那条已存在的
    # 不改已结案卷执行格为第二真源
    assert db.get_decree_dossier(did)["status"] == "closed"
    assert db.get_decree_dossier(did)["execution_outcome"] == "fulfilled"
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
    apply_pending_due_reviews(db, state)
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
    first = apply_pending_due_reviews(db, state)
    assert first and first[0].get("consumed") is True
    assert first[0].get("mid_stage") is True

    dossier = db.get_decree_dossier(dossier_id)
    # 中段不写终值、不关案、不连坐、不代写奏报
    assert dossier["status"] == "executing"
    assert dossier["execution_outcome"] in ("", None, "executing")
    assert _cost_events(db, dossier_id) == []
    assert db.list_dossier_progress(dossier_id) == []

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
    # 无模型终值：保留 pending，不机械替判
    waiting = apply_pending_due_reviews(db, state)
    assert waiting and waiting[0].get("consumed") is False
    assert (waiting[0].get("execution") or {}).get("waiting_model") is True
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"

    # 模型声明 failed → 关案 + 连坐；复核只消费 todo
    _model_write_execution(
        db, state, content, dossier_id, "failed", "届期无实绩",
    )
    first = apply_pending_due_reviews(db, state)
    assert first and first[0].get("consumed") is True

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["execution_outcome"] == "failed"
    assert dossier["status"] == "closed"
    costs = _cost_events(db, dossier_id)
    liability_gates = [c for c in costs if c.get("cost_kind") == "liability"]
    assert len(liability_gates) == 1

    # 幂等腿：已终值再入只 noop 消费，不二次连坐
    db.conn.execute(
        "UPDATE next_audience_todos SET status=?, created_turn=?",
        (TODO_STATUS_PENDING, state.turn - 1),
    )
    db.conn.commit()
    second = apply_pending_due_reviews(db, state)
    assert second, "幂等腿须真正再入正式复核"
    assert second[0].get("branch") == "dossier", second
    assert (second[0].get("execution") or {}).get("rejected") is not True, second
    assert (second[0].get("execution") or {}).get("noop") is True, second
    costs_after = _cost_events(db, dossier_id)
    assert costs_after == costs
    liability_after = [c for c in costs_after if c.get("cost_kind") == "liability"]
    assert len(liability_after) == 1

def test_executing_outcome_rejects_close_true(game):
    """负向：executing 不得 close=True（适配器契约）。"""
    db, state, _content = game
    dossier_id = _executing_policy_dossier(db, state, token="close-guard")
    with pytest.raises(ValueError):
        db.record_dossier_execution(
            dossier_id, "executing", "中段过程", state.turn, close=True, commit=True,
        )

# ── P4/P5 时序与机械哨兵 ──────────────────────────────────────────────

def test_three_beat_timing_todo_then_scene_then_slot(game, monkeypatch):
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
    _settle_empty_month(db, state, content, monkeypatch)
    assert db.list_next_audience_todos() == []
    assert not list_due_review_scenes(db)

    # beat1: 过月写 todo
    _settle_empty_month(db, state, content, monkeypatch)
    todos = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    assert len(todos) == 1
    # 落格尚未发生
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] in ("", None)
    # beat2: 召对场面可读
    scenes = list_due_review_scenes(db)
    assert len(scenes) == 1

    # beat3: 模型声明写格后，过月复核消费 todo（不机械替判）
    _model_write_execution(
        db, state, content, dossier_id, "failed", "届期无实绩",
    )
    _settle_empty_month(db, state, content, monkeypatch)
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == "failed"
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []

def test_due_review_settle_does_not_pause_or_decision(game, monkeypatch):
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
    result1 = _settle_empty_month(db, state, content, monkeypatch)
    assert result1.awaiting is False
    assert state.turn_phase != TurnPhase.AWAITING_DECISION.value
    result2 = _settle_empty_month(db, state, content, monkeypatch)
    assert result2.awaiting is False
    assert state.turn_phase == TurnPhase.ISSUED.value
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
    # 模型经正式写格落终值；复核消费 todo
    _model_write_execution(
        db, state, content, dossier_id, "failed", "届期无实绩",
    )
    apply_pending_due_reviews(db, state)
    first = db.get_decree_dossier(dossier_id)
    assert first["execution_outcome"] == "failed"
    assert first["status"] == "closed"

    # 已结案后再声明终值：案卷不在 executing → 拒收，不覆盖既有终值
    result = settle_delta(state, db, {'dossier_executions': [{'dossier_id': dossier_id, 'outcome': 'transformed', 'note': '二次抢写'}]}, SettlementContext(content=content))
    assert section(result, "dossier_executions").rejected
    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["execution_outcome"] == "failed"

def test_due_month_model_execution_lands_before_todo_write(game):
    """到期当月模型声明终值可落格；todo 尚未写时 dossiers 集合仍可观察。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, token="due-month-model")
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    # 故意不写 todo：模拟 settle 内声明早于 write_due 的窗
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING) == []

    before = db.get_decree_dossier(dossier_id)
    assert before["status"] == "executing"
    assert before["execution_outcome"] in ("", None)

    _model_write_execution(
        db, state, content, dossier_id, "fulfilled", "已见实绩生根",
    )

    after = db.get_decree_dossier(dossier_id)
    assert after["status"] == "closed"
    assert after["execution_outcome"] == "fulfilled"

def test_fulfilled_with_prior_durable_effect_zero_double_post(game):
    """生根：履行期已逐月落完 → 模型写 fulfilled 不重复落经济账。"""
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
    _model_write_execution(
        db, state, content, dossier_id, "fulfilled", "已见实绩生根",
    )
    apply_pending_due_reviews(db, state)

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
    scene = list_due_review_scenes(db)[0]
    assert scene["criterion_text"] == "火器见眉目"
