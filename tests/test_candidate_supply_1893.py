"""#1893 人物事件与弹劾潮候选：供料 → 世界段挑选 → 既有写口落账的真入口行为。

三个根因类各钉一条行为（不复检内部结构、不锁措辞）：

- **供料到转译不断链**：转译发生在世界段材料目录释放之后，故候选事实必须随
  转译请求送到；本文件经真实 ``dispatch_month_segment`` 入口断言转译请求里
  带着当月合格候选的事实（id 与软判锚）。
- **候选分类合乎分工**：三饷是皇帝亲裁，不进人物候选（该负向契约在
  ``test_event_trigger_gate.py`` 钉）；此处钉合格候选可达、资格门不合格与
  已有终态者不可达。
- **落账只走既有写口**：选中经既有 ``new_issues`` 落一次终态与局势；不选无
  终态；读档续跑不重发。弹劾潮发难才立项、不发难不立。

不替模型判断「该不该发生 / 该不该发难」——那属 P6，只断言供给可达与写口幂等。
"""

from __future__ import annotations

import json

from ming_sim.db import GameDB
from ming_sim.materials import (
    _CANDIDATE_REL,
    candidate_supply,
    list_materials,
    prepare_world_materials,
)

CANDIDATE_REL = _CANDIDATE_REL


def _open_window_event(content, eid="__issue_1893_window_event__"):
    """造一个当前盘面进候选池的 situation 事件（复用 1834 族临时事件手法）。"""
    from ming_sim.models import Event

    ev = Event(
        id=eid,
        title=f"1893 探针事件 {eid}",
        kind="测试",
        summary="候选事实探针",
        urgency=50,
        severity=50,
        credibility=50,
        interests=[],
        audiences=[],
        trigger_year=1,
        trigger_month=1,
        open_window=True,
        trigger_gate={},
        event_type="situation",
    )
    content.events.append(ev)
    content.event_by_id[eid] = ev
    return ev


def _drop_event(content, ev):
    if ev in content.events:
        content.events.remove(ev)
    if content.event_by_id.get(ev.id) is ev:
        content.event_by_id.pop(ev.id, None)


def _read_candidates(db, state, *, exclude_dossier_ids=None):
    """Structured candidate snapshot (same freeze prepare_world uses)."""
    return candidate_supply(db, state, exclude_dossier_ids=exclude_dossier_ids)


# --- 供料侧：合格候选可达，资格门不合格 / 已有终态者不可达 ---


def test_eligible_candidate_event_reaches_world_supply(game, tmp_path, content):
    db, state, _ = game
    ev = _open_window_event(content)
    try:
        prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m")
        assert CANDIDATE_REL in list_materials(prepared.root)
        payload = _read_candidates(db, state)
        assert ev.id in {item["id"] for item in payload["events"]}
        item = next(i for i in payload["events"] if i["id"] == ev.id)
        # 结构化事实：候选 id 入供且不代模型算战果；不锁 summary 自由正文。
        assert item["id"] == ev.id
        assert "effect_on_trigger" not in item
    finally:
        _drop_event(content, ev)


def test_ineligible_and_terminal_events_stay_out_of_supply(game, tmp_path, content):
    """资格门不合格（窗口未开）与已有终态（已避过）者都不进候选目录。"""
    db, state, _ = game
    from ming_sim.models import Event

    later = Event(
        id="__issue_1893_future_event__", title="远年事件", kind="测试",
        summary="窗口未开", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[], trigger_year=int(state.year) + 50,
        trigger_month=1, open_window=False, trigger_gate={}, event_type="situation",
    )
    avoided = _open_window_event(content, "__issue_1893_avoided_event__")
    content.events.append(later)
    content.event_by_id[later.id] = later
    try:
        db.mark_event_avoided(state, avoided.id, reason="探针：前提已被化解")
        prepare_world_materials(db, state, dest_root=tmp_path / "m2")
        ids = {item["id"] for item in _read_candidates(db, state)["events"]}
        assert later.id not in ids
        assert avoided.id not in ids
    finally:
        _drop_event(content, later)
        _drop_event(content, avoided)


def _secret_surge_world(db, state, owner):
    """造一条真密令案卷的旨外变形暴露，产出与普通案卷同口径的弹劾潮候选。"""
    from tests.dossier_test_helpers import create_test_secret_order

    order_id = create_test_secret_order(
        db, state, owner, "密令探针", "密令正文", ["探针"],
    )
    secret_did = db.create_decree_dossier(
        state, action_type="secret_order", decree_text="密查", target_kind="issue",
        target_id="land", executor_kind="character", executor_id=owner,
        secret_order_id=order_id,
        participants=[{"character_id": owner, "tier": "主办"}],
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='closed',execution_outcome='transformed',"
        "execution_note='名实已乖，旨外受益',closed_turn=?,"
        "participant_roster=? WHERE id=?",
        (
            state.turn,
            json.dumps([{"character_id": owner, "tier": "主办"}], ensure_ascii=False),
            secret_did,
        ),
    )
    db.record_issue_economy_move(
        state, account="国库", delta=8, category="地方浮收",
        reason="借密查之名额外加派", origin_ref=f"dossier:{secret_did}",
        beyond_intent=True, commit=False,
    )
    db.conn.commit()
    return secret_did


def test_surge_candidate_offered_by_world_segment_is_declared_and_lands(game, tmp_path):
    """F1：世界段目录里供到的候选，转译就能声明、写口就收——三处同一读侧口径。

    旧断链：世界段材料目录不筛密令案卷，转译请求却无条件排除，于是模型在
    段文里点名的候选到不了声明里。此处走真实世界段目录（prepare_world_materials
    落盘、read_material 读回），再经真实 dispatch_month_segment 入口，对密令
    案卷验「转译请求 → 声明 → 落账」。目录只验证合法路径可取阅，
    人读内容不承担解析契约；目录供料另以真实取阅观察验收。
    """
    from ming_sim.month_translate import dispatch_month_segment
    from tests.test_impeachment_surge_655 import _candidate_world

    db, state, _ = game
    _did, owner, _faction = _candidate_world(db, state)
    secret_did = _secret_surge_world(db, state, owner)

    # 世界段目录：候选路径在册；人读正文不承担解析契约（#1830/#1893）。
    # 行为证明在下方 dispatch→声明→落账，不靠裸 read_material 烟测。
    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    assert CANDIDATE_REL in list_materials(prepared.root)

    def _capture(request, config):
        offered = {
            item["id"]: item for item in request.candidates["impeachment_surge"]
            if int(item["dossier_id"]) == secret_did
        }
        assert offered, "世界段供到的候选未随转译请求送到（供料→转译断链）"
        candidate = next(iter(offered.values()))
        return {"effects": {"new_issues": [{
            "origin_kind": "impeachment_surge",
            "candidate_id": candidate["id"],
            "faction_hint": candidate["faction_id"],
            "target_roster": [candidate["eligible_target_ids"][0]],
            "title": "密令案卷弹劾潮探针",
            "stage_text": "探针案情。",
        }]}}

    dispatch_month_segment(db, state, segment="派系发难", translate_fn=_capture)

    row = db.conn.execute(
        "SELECT origin_ref FROM issues WHERE origin_kind='impeachment_surge'",
    ).fetchone()
    assert row is not None, "供到的候选经声明后未落账（写口口径与供料不一致）"
    assert row["origin_ref"] == f"commitment:{secret_did}:deformation_exposure"


# --- 断链类：候选事实必须随转译请求送到（目录此时已释放）---


def test_translate_request_carries_current_candidate_facts(game, content):
    """经真实 dispatch_month_segment 入口：转译请求里带着当月合格候选事实。"""
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    ev = _open_window_event(content, "__issue_1893_translate_supply__")
    captured = {}
    try:

        def _capture(request, config):
            captured["request"] = request
            return {"effects": {}}

        dispatch_month_segment(db, state, segment="本月无事", translate_fn=_capture)

        request = captured["request"]
        facts = {item["id"]: item for item in request.candidates["events"]}
        assert ev.id in facts, "合格候选未随转译请求送到（供料→转译断链）"
        assert facts[ev.id]["id"] == ev.id
        assert "impeachment_surge" in request.candidates
    finally:
        _drop_event(content, ev)


def test_translate_request_omits_ineligible_candidate(game, content):
    """资格门不合格者既不进供料目录，也不进转译请求（同一读侧硬门两处一致）。"""
    from ming_sim.month_translate import dispatch_month_segment
    from ming_sim.models import Event

    db, state, _ = game
    later = Event(
        id="__issue_1893_unreachable__", title="远年事件", kind="测试",
        summary="窗口未开", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[], trigger_year=int(state.year) + 50,
        trigger_month=1, open_window=False, trigger_gate={}, event_type="situation",
    )
    content.events.append(later)
    content.event_by_id[later.id] = later
    captured = {}
    try:

        def _capture(request, config):
            captured["request"] = request
            return {"effects": {}}

        dispatch_month_segment(db, state, segment="本月无事", translate_fn=_capture)

        assert later.id not in {
            item["id"] for item in captured["request"].candidates["events"]
        }
    finally:
        _drop_event(content, later)


# --- 落账侧：模型选了就只落一次，不选 / 读档续跑不重发 ---


def test_selected_event_lands_once_via_existing_new_issues_write(game, content):
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    ev = _open_window_event(content)
    try:
        declaration = {"effects": {"new_issues": [
            {"origin_kind": "event_pool", "id": ev.id, "title": ev.title},
        ]}}
        result = dispatch_month_segment(
            db, state, segment="探针段文", translate_fn=lambda rq, cfg: declaration,
        )
        applied = result.effects.applied[0]["issue_summary"]["new_issues"]
        assert [item.get("rejected") for item in applied] == [False]
        assert db.conn.execute(
            "SELECT COUNT(*) FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone()[0] == 1
        assert db.event_terminal_state(ev.id) == "triggered"
        # 读档续跑：同一段再落一次不重发（终态已在候选硬门里排掉）。
        again = dispatch_month_segment(
            db, state, segment="探针段文", translate_fn=lambda rq, cfg: declaration,
        )
        assert [
            item.get("rejected")
            for item in again.effects.applied[0]["issue_summary"]["new_issues"]
        ] == [True]
        assert db.conn.execute(
            "SELECT COUNT(*) FROM issues WHERE origin_kind='event_pool' AND origin_ref=?",
            (ev.id,),
        ).fetchone()[0] == 1
    finally:
        _drop_event(content, ev)


def test_not_selected_candidate_leaves_no_terminal_state(game, content):
    db, state, _ = game
    ev = _open_window_event(content)
    try:
        from ming_sim.month_translate import dispatch_month_segment

        dispatch_month_segment(
            db, state, segment="本月无事", translate_fn=lambda rq, cfg: {"effects": {}},
        )
        assert db.event_terminal_state(ev.id) is None
        assert ev.id in {item["id"] for item in candidate_supply(db, state)["events"]}
    finally:
        _drop_event(content, ev)


def test_non_strategic_candidate_effects_land_without_event_id_binding(game, content):
    """F3：非 strategic_foreign 的人物候选不绑 event_id，其效果照样落账。

    战果声明的 event_id 归属只属 strategic_foreign 的 node/ending 既有契约；
    人物候选若照绑会被既有写口整项拒收，故此处钉「不绑也落」。
    """
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    ev = _open_window_event(content, "__issue_1893_plain_person_event__")
    try:
        before = int(state.metrics["民心"])
        declaration = {"effects": {
            "new_issues": [{"origin_kind": "event_pool", "id": ev.id, "title": ev.title}],
            "metric_delta": {"民心": -3},
        }}
        result = dispatch_month_segment(
            db, state, segment="探针段文", translate_fn=lambda rq, cfg: declaration,
        )
        assert [
            item.get("rejected")
            for item in result.effects.applied[0]["issue_summary"]["new_issues"]
        ] == [False]
        assert int(state.metrics["民心"]) == before - 3
    finally:
        _drop_event(content, ev)


def test_supplied_outcome_labels_match_writer_whitelist(game, content):
    """F3：候选事实里的结局标签就是写口那一份，不另立第二张标签表。

    旧断链：指令让模型从 Event.terminal_reason_labels 取标签，而该字段对
    jisi_lubian 为空、真正白名单在 issues 写口侧，模型无从取到合法标签，
    整项被拒。此处钉「供到的标签 = 写口接受的标签」，且写口无标签集者供空集。
    """
    from ming_sim.issues import strategic_event_outcome_labels
    from ming_sim.month_translate import dispatch_month_segment

    db, state, _ = game
    # 推进到有战略战事候选的时点，否则本用例无候选可验（空转）。
    state.year, state.period = 1629, 11
    db.save_state(state)
    captured = {}

    def _capture(request, config):
        captured["request"] = request
        return {"effects": {}}

    dispatch_month_segment(db, state, segment="本月无事", translate_fn=_capture)

    by_id = {item["id"]: item for item in captured["request"].candidates["events"]}
    assert "jisi_lubian" in by_id, "本用例须有战略战事候选可验，否则空转"
    assert set(by_id["jisi_lubian"]["outcome_labels"]) == set(
        strategic_event_outcome_labels("jisi_lubian")
    )
    assert by_id["jisi_lubian"]["outcome_labels"], "写口有白名单却没供到标签"
    # 写口无标签集者一律供空集，不逼模型自造标签。
    for eid, item in by_id.items():
        if not strategic_event_outcome_labels(eid):
            assert item["outcome_labels"] == [], f"{eid} 无白名单却供了标签"


def test_impeachment_surge_lands_only_when_faction_actually_impeaches(game):
    """派系硬门合格时：发难才立项（只一次），不发难则不立。"""
    from tests.test_impeachment_surge_655 import _candidate_world

    db, state, _ = game
    did, owner, faction = _candidate_world(db, state)
    supply = candidate_supply(db, state)["impeachment_surge"]
    candidate = next(item for item in supply if int(item["dossier_id"]) == did)
    assert candidate["id"] in {item["id"] for item in supply}
    assert owner in candidate["eligible_target_ids"]

    from ming_sim.month_translate import dispatch_month_segment

    # 不发难：只给别的效果，不声明该候选 → 不立项。
    dispatch_month_segment(
        db, state, segment="派系按兵不动",
        translate_fn=lambda rq, cfg: {"effects": {"metric_delta": {}}},
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()[0] == 0

    # 发难：声明既有候选 → 走既有 new_issues 写口只立一次，标靶与归因照写。
    declaration = {"effects": {"new_issues": [{
        "origin_kind": "impeachment_surge",
        "candidate_id": candidate["id"],
        "faction_hint": candidate["faction_id"],
        "target_roster": [owner],
        "title": "弹劾潮探针",
        "stage_text": "探针案情。",
    }]}}
    result = dispatch_month_segment(
        db, state, segment="派系发难", translate_fn=lambda rq, cfg: declaration,
    )
    applied = result.effects.applied[0]["issue_summary"]["new_issues"]
    assert [item.get("rejected") for item in applied] == [False]
    row = db.conn.execute(
        "SELECT origin_ref,faction_hint,target_roster FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()
    assert row["origin_ref"] == f"commitment:{did}:deformation_exposure"
    # 发难派系是候选里的 faction（≠ 责任派系），落账须照候选写。
    assert row["faction_hint"] == candidate["faction_id"]
    assert row["faction_hint"] != faction  # 责任派系与发难派系不是同一派
    assert json.loads(row["target_roster"]) == [owner]

    # 再发一次同一候选：同源已立，不重复。
    dispatch_month_segment(
        db, state, segment="派系再奏", translate_fn=lambda rq, cfg: declaration,
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'"
    ).fetchone()[0] == 1


def test_impeachment_surge_candidate_survives_restore(game, content):
    """读档续跑：候选资格与既有立账都从 DB 读，restore 后不重发。"""
    from tests.test_impeachment_surge_655 import _candidate_world
    from ming_sim.month_translate import dispatch_month_segment

    db, state, content_pack = game
    did, owner, _ = _candidate_world(db, state)
    candidate = candidate_supply(db, state)["impeachment_surge"][0]
    declaration = {"effects": {"new_issues": [{
        "origin_kind": "impeachment_surge",
        "candidate_id": candidate["id"],
        "faction_hint": candidate["faction_id"],
        "target_roster": [owner],
        "title": "恢复弹劾潮",
        "stage_text": "关库后仍可读",
    }]}}
    dispatch_month_segment(
        db, state, segment="发难", translate_fn=lambda rq, cfg: declaration,
    )
    path = db.conn.execute("PRAGMA database_list").fetchone()[2]
    db.close()

    restored = GameDB(path, content_pack)
    try:
        state2 = restored.load_state()
        # 已发难的那一派不再进候选（其余未发难的派系候选仍在——硬门只按已立账排）。
        assert candidate["id"] not in {
            item["id"] for item in candidate_supply(restored, state2)["impeachment_surge"]
        }
        dispatch_month_segment(
            restored, state2, segment="续跑", translate_fn=lambda rq, cfg: declaration,
        )
        assert restored.conn.execute(
            "SELECT COUNT(*) FROM issues WHERE origin_kind='impeachment_surge'"
        ).fetchone()[0] == 1
    finally:
        restored.close()
