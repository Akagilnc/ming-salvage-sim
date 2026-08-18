"""#624 / ADR 0078 催双刃拉杆＋反催谏言。

Seams:
- rush_staged_commitment_stage → issues.stages_json[].due_turn（真加速唯一写口）
- pending_actions(action=催办, status=committed) → urge_history 史源
- build_due_review_input.urge_history / distortion_tendency（读时派生）
- decide_due_review_verdict 受失真档可观察调制
- ENTRY_KIND_RUSH_REMONSTRANCE / ENTRY_KIND_GRACE_PLEA + payload_json 真伪底
- 四缝单一白名单（仅 ENTRY_KIND_STAGED）
"""

from __future__ import annotations

import json

import pytest

from ming_sim.due_review import (
    DUE_REVIEW_ENTRY_KIND_WHITELIST,
    apply_due_review_for_todo,
    apply_pending_due_reviews,
    build_due_review_input,
    decide_due_review_verdict,
    dossiers_with_pending_due_review,
    list_due_review_scenes,
    project_due_review_scene,
)
from ming_sim.issues import apply_score_extraction
from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
    ENTRY_KIND_STAGED,
    TODO_STATUS_PENDING,
    normalize_commitment_stages,
    write_due_staged_commitment_todos,
)
from ming_sim.urge_lever import (
    collect_urge_history,
    dare_speak_passes,
    derive_distortion_tendency,
    derive_grace_truth,
    derive_opportunity_band,
    is_deadline_unreasonable,
    person_integrity_archetype,
    rush_staged_commitment_stage,
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


def _executing_policy_dossier(db, state, *, token: str = "urge-624", host: str = "倪元璐"):
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈差务·{token}",
        target_kind="issue",
        target_id=token,
        participants=[
            {"character_id": host, "tier": "主办", "role": "清丈"},
            {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        ],
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    assert db.get_decree_dossier(dossier_id)["status"] == "executing"
    return dossier_id


def _insert_staged_commitment(
    db, state, content, *, stages, title="催办分段之诺", origin_ref: str = "",
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


def _set_integrity(db, name: str, integrity: int, *, courage: int | None = None):
    if courage is None:
        db.conn.execute(
            "UPDATE characters SET integrity=? WHERE name=?",
            (int(integrity), name),
        )
    else:
        db.conn.execute(
            "UPDATE characters SET integrity=?, courage=? WHERE name=?",
            (int(integrity), int(courage), name),
        )
    db.conn.commit()


def _seed_stages(state, *, due0: int | None = None, due1: int | None = None):
    d0 = int(state.turn + 36 if due0 is None else due0)
    d1 = int(state.turn + 60 if due1 is None else due1)
    return [
        {
            "stage_idx": 0,
            "due_turn": d0,
            "criterion_text": "火器见眉目",
            "origin_context": "三年火器见眉目",
        },
        {
            "stage_idx": 1,
            "due_turn": d1,
            "criterion_text": "新历成",
            "origin_context": "五年新历成",
        },
    ]


# ── 纯函数：人身 / 可乘之利 / 失真 / 敢言 / 期限 ─────────────────────


def test_person_integrity_archetype_three_way():
    assert person_integrity_archetype(90) == "孤直"
    assert person_integrity_archetype(55) == "庸吏"
    assert person_integrity_archetype(20) == "附势"


def test_distortion_modulated_by_integrity_ac2():
    base = dict(
        urge_count=2,
        urge_tightness=24,
        supervision_history=[],
        opportunity_band="low",
    )
    g = derive_distortion_tendency(integrity=90, **base)
    m = derive_distortion_tendency(integrity=55, **base)
    b = derive_distortion_tendency(integrity=20, **base)
    rank = {"不歪": 0, "微歪": 1, "易歪": 2, "必歪": 3}
    assert rank[g["band"]] < rank[m["band"]] < rank[b["band"]]
    assert g["archetype"] == "孤直"
    assert b["archetype"] == "附势"


def test_distortion_modulated_by_supervision_consume_only_ac3():
    """AC3：仅消费侧——fixture 注入 supervision_history，庸吏歪办倾向差分。"""
    base = dict(
        urge_count=2,
        urge_tightness=18,
        integrity=55,
        opportunity_band="low",
    )
    bare = derive_distortion_tendency(supervision_history=[], **base)
    watched = derive_distortion_tendency(
        supervision_history=[{"kind": "audit", "months_present": 6}],
        **base,
    )
    rank = {"不歪": 0, "微歪": 1, "易歪": 2, "必歪": 3}
    assert rank[watched["band"]] < rank[bare["band"]]


def test_distortion_modulated_by_opportunity_ac4():
    base = dict(
        urge_count=1,
        urge_tightness=6,
        integrity=30,
        supervision_history=[],
    )
    low = derive_distortion_tendency(opportunity_band="low", **base)
    high = derive_distortion_tendency(opportunity_band="high", **base)
    rank = {"不歪": 0, "微歪": 1, "易歪": 2, "必歪": 3}
    assert rank[high["band"]] > rank[low["band"]]


def test_opportunity_band_from_durable_effects():
    assert derive_opportunity_band([]) == "none"
    assert derive_opportunity_band([{"delta": -10}]) == "low"
    assert derive_opportunity_band([
        {"delta": -5000, "account": "国库"},
        {"delta": -3000, "account": "内库"},
        {"delta": 100, "account": "民心"},
    ]) == "high"


def test_deadline_unreasonable_and_dare_speak():
    assert is_deadline_unreasonable(old_due=40, new_due=5, current_turn=1) is True
    assert is_deadline_unreasonable(old_due=40, new_due=38, current_turn=1) is False
    # 高皇威压制敢言；低皇威 + 高 courage 敢言
    assert dare_speak_passes(courage=80, imperial_prestige=90) is False
    assert dare_speak_passes(courage=80, imperial_prestige=20) is True


def test_grace_truth_two_forms_ac6_pure():
    genuine = derive_grace_truth(
        unreasonable=True, archetype="孤直", opportunity_band="none",
    )
    fake = derive_grace_truth(
        unreasonable=False, archetype="附势", opportunity_band="high",
    )
    assert genuine["truth"] == "genuine"
    assert genuine["grace_fake"] is False
    assert fake["truth"] == "pretextual"
    assert fake["grace_fake"] is True


# ── AC1 催拉杆：真加速 + urge_history + 判词可观察影响 ───────────────


def test_rush_staged_commitment_advances_due_and_fills_urge_history(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, host="倪元璐")
    _set_integrity(db, "倪元璐", 30)
    stages = _seed_stages(state)
    issue_id, _ = _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    before = normalize_commitment_stages(
        db.conn.execute(
            "SELECT stages_json FROM issues WHERE id=?", (issue_id,),
        ).fetchone()["stages_json"]
    )
    old_due = int(before[0]["due_turn"])

    result = rush_staged_commitment_stage(
        db, state,
        commitment_ref=issue_id,
        stage_idx=0,
        deadline_months=3,
        reason="着即赶办",
    )
    assert result["due_turn"] < old_due
    assert int(result["due_turn"]) == state.turn + 3

    after = normalize_commitment_stages(
        db.conn.execute(
            "SELECT stages_json FROM issues WHERE id=?", (issue_id,),
        ).fetchone()["stages_json"]
    )
    assert int(after[0]["due_turn"]) == state.turn + 3
    # 真源唯一：stages_json；不写 decree_dossiers.due_turn 作第二源
    dossier = db.get_decree_dossier(dossier_id)
    assert int(dossier.get("due_turn") or 0) == 0 or int(dossier.get("due_turn") or 0) != int(after[0]["due_turn"])

    hist = collect_urge_history(db, commitment_ref=issue_id, dossier_id=dossier_id)
    assert len(hist) >= 1
    assert hist[-1]["old_due"] == old_due
    assert hist[-1]["new_due"] == state.turn + 3

    # build_due_review_input 唯一填充点
    write_due_staged_commitment_todos(db, state)  # may be 0 if due not yet
    # force a staged todo row for input build
    tid = db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=int(after[0]["due_turn"]),
        criterion_text="火器见眉目",
        origin_context="三年火器见眉目",
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_STAGED,
        created_turn=state.turn,
    )
    assert tid > 0
    todo = db.list_next_audience_todos(commitment_ref=issue_id)[0]
    inp = build_due_review_input(db, todo)
    assert inp["urge_history"]
    assert inp["distortion_tendency"]["band"] in {"微歪", "易歪", "必歪", "不歪"}
    assert inp["distortion_tendency"]["archetype"] == "附势"


def test_urge_raises_distortion_and_shifts_verdict_ac1(game):
    """同承诺：无催 vs 催紧 → 失真档升高且确定性判词可观察差分。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, host="倪元璐")
    _set_integrity(db, "倪元璐", 25)
    # 单段末段终裁面（多段会走 mid_stage=executing，遮住失真调制）
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn + 24,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    issue_id, _ = _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
        title="失真对照之诺",
    )
    # 有表报无实账 → 基线 degraded；催紧 + 附势 可推到更重
    db.record_dossier_progress(
        dossier_id, state.turn, "在办", "表报已陈，实绩未充",
        is_terminal=False, commit=True,
    )

    tid = db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=state.turn,
        criterion_text="火器见眉目",
        origin_context="三年火器见眉目",
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_STAGED,
        created_turn=state.turn - 1,
    )
    todo = [t for t in db.list_next_audience_todos() if int(t["id"]) == tid][0]
    base_inp = build_due_review_input(db, todo)
    base_verdict = decide_due_review_verdict(base_inp)

    rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=1, reason="即日复命",
    )
    # second rush for higher urge_count
    rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=0, reason="再催",
    )
    rushed_inp = build_due_review_input(db, todo)
    rushed_verdict = decide_due_review_verdict(rushed_inp)

    rank = {"不歪": 0, "微歪": 1, "易歪": 2, "必歪": 3}
    assert rank[rushed_inp["distortion_tendency"]["band"]] > rank[
        base_inp["distortion_tendency"]["band"]
    ]
    # 可观察：失真升高后判词至少不更宽；附势重催可将 degraded→failed/transformed
    order = {"fulfilled": 0, "executing": 1, "degraded": 2, "transformed": 3, "failed": 4}
    assert order[str(rushed_verdict["outcome"])] >= order[str(base_verdict["outcome"])]
    assert rushed_verdict["outcome"] in {"degraded", "transformed", "failed"}
    assert rushed_inp["distortion_tendency"]["band"] in {"易歪", "必歪"}
    assert base_verdict["outcome"] == "degraded"
    assert rushed_verdict["outcome"] in {"failed", "transformed"}


# ── AC5 操之过急谏幂等 + 敢言对照 ───────────────────────────────────


def test_rush_remonstrance_first_unreasonable_idempotent_ac5(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    state.metrics["皇威"] = 15
    db.conn.execute(
        "UPDATE metrics SET value=? WHERE key='皇威'", (15,),
    )
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, host="倪元璐")
    _set_integrity(db, "倪元璐", 85, courage=90)
    stages = _seed_stages(state)  # far due
    issue_id, _ = _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
        title="谏言对照之诺",
    )

    r1 = rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=1, reason="着一月内了结",
    )
    assert r1.get("remonstrance_written") is True
    todos = db.list_next_audience_todos(commitment_ref=issue_id)
    rem = [t for t in todos if t["entry_kind"] == ENTRY_KIND_RUSH_REMONSTRANCE]
    assert len(rem) == 1

    r2 = rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=0, reason="再催即核",
    )
    assert r2.get("remonstrance_written") is False  # 幂等
    todos2 = db.list_next_audience_todos(commitment_ref=issue_id)
    rem2 = [t for t in todos2 if t["entry_kind"] == ENTRY_KIND_RUSH_REMONSTRANCE]
    assert len(rem2) == 1


def test_high_prestige_suppresses_remonstrance_dare_ac5(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    state.metrics["皇威"] = 95
    db.conn.execute("UPDATE metrics SET value=? WHERE key='皇威'", (95,))
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, host="倪元璐")
    _set_integrity(db, "倪元璐", 85, courage=50)
    stages = _seed_stages(state)
    issue_id, _ = _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
        title="高皇威不敢谏",
    )
    r = rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=1, reason="着一月内了结",
    )
    assert r.get("remonstrance_written") is False
    rem = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if t["entry_kind"] == ENTRY_KIND_RUSH_REMONSTRANCE
    ]
    assert rem == []


# ── AC6 求宽限真伪底落 payload、玩家面零裸露 ─────────────────────────


def test_grace_plea_payload_truth_hidden_from_player_ac6(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    state.metrics["皇威"] = 40
    db.conn.execute("UPDATE metrics SET value=? WHERE key='皇威'", (40,))
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state, host="倪元璐")
    _set_integrity(db, "倪元璐", 25, courage=40)
    stages = _seed_stages(state)
    issue_id, _ = _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
        title="宽限真伪之诺",
    )
    r = rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=6, reason="稍加催促",
    )
    assert r.get("grace_written") is True
    grace = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if t["entry_kind"] == ENTRY_KIND_GRACE_PLEA
    ]
    assert len(grace) == 1
    payload = grace[0].get("payload_json")
    assert isinstance(payload, dict)
    assert payload.get("truth") in {"genuine", "pretextual"}
    assert "grace_fake" in payload

    # 玩家投影路径不读 payload；scene 哨兵
    scenes = list_due_review_scenes(db, state)
    blob = json.dumps(scenes, ensure_ascii=False)
    for token in (
        "truth", "grace_fake", "pretextual", "genuine", "payload_json",
        "distortion_band", "urge_tightness",
    ):
        assert token not in blob
    # 即使把 grace 误塞进 project（不应），origin/criterion/scene 也不得含底
    staged = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if t["entry_kind"] == ENTRY_KIND_STAGED
    ]
    if staged:
        scene = project_due_review_scene(db, staged[0])
        sblob = json.dumps(scene, ensure_ascii=False)
        for token in ("truth", "grace_fake", "pretextual", "payload_json"):
            assert token not in sblob
            assert token not in scene.get("scene_text", "")


# ── AC7 降级与 restore ───────────────────────────────────────────────


def test_missing_urge_and_supervision_fail_closed_ac7(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    issue_id, _ = _insert_staged_commitment(db, state, content, stages=stages)
    tid = db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=state.turn,
        criterion_text="火器见眉目",
        origin_context="三年火器见眉目",
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_STAGED,
        created_turn=state.turn,
    )
    todo = [t for t in db.list_next_audience_todos() if int(t["id"]) == tid][0]
    inp = build_due_review_input(db, todo)
    assert inp["urge_history"] == []
    assert inp["supervision_history"] == []
    # 不 fail-open 成「有催/有监督」
    assert inp["distortion_tendency"]["band"] == "不歪"


def test_urge_history_restore_from_committed_pending_ac7(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = _seed_stages(state)
    issue_id, _ = _insert_staged_commitment(db, state, content, stages=stages)
    rush_staged_commitment_stage(
        db, state, commitment_ref=issue_id, stage_idx=0,
        deadline_months=3, reason="restore-probe",
    )
    path = db.path
    db.conn.close()
    from ming_sim.db import GameDB
    db2 = GameDB(path)
    hist = collect_urge_history(db2, commitment_ref=issue_id)
    assert len(hist) >= 1
    assert hist[0]["reason"] == "restore-probe"


def test_rush_without_issue_fail_closed_no_remonstrance(game):
    """无 issue 承载的催办 fail-closed 不产谏条，禁伪造 issue。"""
    db, state, content = game
    before_issues = db.conn.execute("SELECT COUNT(*) AS c FROM issues").fetchone()["c"]
    # 直接对不存在的 commitment_ref 应响亮失败或 no-op 不造 issue
    with pytest.raises(ValueError):
        rush_staged_commitment_stage(
            db, state, commitment_ref=9_999_999, stage_idx=0,
            deadline_months=1, reason="幽灵",
        )
    after_issues = db.conn.execute("SELECT COUNT(*) AS c FROM issues").fetchone()["c"]
    assert after_issues == before_issues


# ── 四缝白名单 + 接管窗对称 ──────────────────────────────────────────


def test_due_review_whitelist_is_staged_only():
    assert DUE_REVIEW_ENTRY_KIND_WHITELIST == frozenset({ENTRY_KIND_STAGED})


def test_remonstrance_not_projected_applied_or_takeover(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    dossier_id = _executing_policy_dossier(db, state)
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn + 12,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    issue_id, _ = _insert_staged_commitment(
        db, state, content, stages=stages, origin_ref=f"dossier:{dossier_id}",
    )
    # 手工插入谏/宽限 pending（模拟已写出）
    db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=state.turn,
        criterion_text="期限过急",
        origin_context="着即赶办",
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_RUSH_REMONSTRANCE,
        created_turn=state.turn - 1,
        payload_json={"truth": "genuine", "grace_fake": False},
    )
    db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=state.turn,
        criterion_text="求宽限",
        origin_context="着即赶办",
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_GRACE_PLEA,
        created_turn=state.turn - 1,
        payload_json={"truth": "pretextual", "grace_fake": True},
    )

    # 1) 不投影为 due-review 场面
    assert list_due_review_scenes(db, state) == []

    # 2) 不占接管窗
    owned = dossiers_with_pending_due_review(db, state)
    assert dossier_id not in owned

    # 3) apply 不消费、不落格、不连坐
    before_outcome = db.get_decree_dossier(dossier_id)["execution_outcome"]
    results = apply_pending_due_reviews(db, state, commit=True)
    assert results == []
    assert db.get_decree_dossier(dossier_id)["execution_outcome"] == before_outcome
    still = db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    kinds = {t["entry_kind"] for t in still}
    assert ENTRY_KIND_RUSH_REMONSTRANCE in kinds
    assert ENTRY_KIND_GRACE_PLEA in kinds

    # 4) apply_due_review_for_todo 单条亦拒
    rem = [t for t in still if t["entry_kind"] == ENTRY_KIND_RUSH_REMONSTRANCE][0]
    one = apply_due_review_for_todo(db, state, rem, commit=True)
    assert one.get("rejected") is True
    assert db.list_next_audience_todos(status=TODO_STATUS_PENDING)
    # 仍 pending，未被 failed/连坐吞
    costs = list(db.conn.execute(
        "SELECT * FROM decree_cost_events WHERE dossier_id=?", (dossier_id,),
    ).fetchall())
    assert costs == []


def test_payload_json_roundtrip_insert_list_restore(game):
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn + 5,
        "criterion_text": "火器见眉目",
        "origin_context": "三年火器见眉目",
    }]
    issue_id, _ = _insert_staged_commitment(db, state, content, stages=stages)
    payload = {"truth": "genuine", "grace_fake": False, "note": "引擎知底"}
    tid = db.insert_next_audience_todo(
        commitment_ref=issue_id,
        stage_idx=0,
        due_turn=state.turn,
        criterion_text="求宽限",
        origin_context="稍催",
        entry_kind=ENTRY_KIND_GRACE_PLEA,
        created_turn=state.turn,
        payload_json=payload,
    )
    assert tid > 0
    row = [t for t in db.list_next_audience_todos(commitment_ref=issue_id) if int(t["id"]) == tid][0]
    assert row["payload_json"]["truth"] == "genuine"
    path = db.path
    db.conn.close()
    from ming_sim.db import GameDB
    db2 = GameDB(path)
    row2 = [t for t in db2.list_next_audience_todos(commitment_ref=issue_id) if int(t["id"]) == tid][0]
    assert row2["payload_json"]["grace_fake"] is False
