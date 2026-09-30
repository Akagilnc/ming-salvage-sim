"""#1893 人物事件与弹劾潮候选进入过月供料目录（现行材料写手断链的补回）。

真源断链：月末世界段经 ``prepare_world_materials`` 起调，而修前该目录不写任何
候选——历史大事件与弹劾潮在现行流程里模型一次也读不到（ADR 0014 / 0091 的
候选供给无写侧）。本文件钉：

- 供料侧：合格候选进 ``盘面/候选事件与弹劾潮.txt``，资格门不合格 / 已有终态者
  不进（硬门仍只由既有 gather 判，代码不代选）；
- 落账侧：模型在 C0 effects 里声明 event_pool / impeachment_surge 后，仍走既有
  ``new_issues`` 写口，只落一次；不选则无终态、读档续跑不重发。

不替模型判断「该不该发生 / 该不该发难」——那属 P6，只断言供给可达与写口幂等。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.db import GameDB
from ming_sim.materials import (
    _CANDIDATE_REL,
    candidate_supply,
    list_materials,
    prepare_world_materials,
    read_material,
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


def _read_candidates(prepared):
    return json.loads(read_material(prepared.root, CANDIDATE_REL))


# --- 供料侧：合格候选可达，资格门不合格 / 已有终态者不可达 ---


def test_eligible_candidate_event_reaches_world_supply(game, tmp_path, content):
    db, state, _ = game
    ev = _open_window_event(content)
    try:
        prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m")
        assert CANDIDATE_REL in list_materials(prepared.root)
        payload = _read_candidates(prepared)
        assert ev.id in {item["id"] for item in payload["events"]}
        item = next(i for i in payload["events"] if i["id"] == ev.id)
        # 结构化事实：软判锚（历史结果 + 成因）在，不代模型算战果。
        assert item["summary"] == ev.summary
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
        prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m2")
        ids = {item["id"] for item in _read_candidates(prepared)["events"]}
        assert later.id not in ids
        assert avoided.id not in ids
    finally:
        _drop_event(content, later)
        _drop_event(content, avoided)


def test_supply_excludes_impeachment_candidates_of_secret_dossiers(game):
    """密令案卷不向供料侧露弹劾潮候选（读侧既有 secret_order_dossier_ids 口径）。"""
    db, state, _ = game
    from ming_sim.materials import secret_order_dossier_ids

    secret = secret_order_dossier_ids(db)
    for item in candidate_supply(db, state)["impeachment_surge"]:
        assert int(item.get("dossier_id") or 0) not in secret


def test_supply_is_frozen_once_per_prepare(game, monkeypatch):
    """一次 prepare 只取一次候选：目录写入与 opening 共用同一份冻结结果。"""
    db, state, content = game
    from ming_sim import materials as materials_mod

    calls = {"n": 0}
    real = materials_mod.candidate_supply

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(materials_mod, "candidate_supply", counting)
    prepared = prepare_world_materials(db, state)
    assert calls["n"] == 1
    index = read_material(prepared.root, "INDEX.txt")
    assert CANDIDATE_REL in index
    # 开场只报条数并指路，不复制候选正文（P7：不为模型拼装第二份真源）。
    assert CANDIDATE_REL in prepared.opening
    assert "人物事件" in prepared.opening


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


def test_translate_prompt_names_the_candidate_contract():
    """转译契约须写清两条声明形状（代码不代选，形状由 prompt 交给模型）。"""
    from ming_sim.month_translate import build_month_segment_translate_prompt, MonthTranslationInput

    prompt = build_month_segment_translate_prompt(MonthTranslationInput(
        segment="段文", target_grounding="", decree_payload={},
    ))
    assert '"origin_kind": "event_pool"' in prompt
    assert '"origin_kind": "impeachment_surge"' in prompt
    assert "eligible_target_ids" in prompt


@pytest.mark.parametrize("turn_unit", ["月", "回合"])
def test_world_segment_agent_instructions_point_at_candidate_file(turn_unit):
    """世界段 agent 指令须指向候选文件（正向表述，不塞固定叙事文本）。"""
    from ming_sim.agents import create_world_segment_agent

    class _Model:
        materials_dir = ""

    captured = {}

    def _fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    import ming_sim.agents as agents_mod

    class _Cfg:
        base_url = "http://localhost:1"
        model = "x"

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(agents_mod, "create_chat_model", lambda *a, **k: _Model())
        monkey.setattr(agents_mod, "_llm_for_role", lambda *a, **k: _Cfg())
        monkey.setattr(agents_mod, "Agent", _fake_agent)
        monkey.setattr(agents_mod, "material_tools", lambda root: [], raising=False)
        create_world_segment_agent(_Cfg(), type("P", (), {"root": "", "opening": ""})())
    finally:
        monkey.undo()
    joined = "\n".join(str(line) for line in captured["instructions"])
    assert CANDIDATE_REL in joined
