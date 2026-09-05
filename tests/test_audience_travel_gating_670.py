"""#670 召对 travel-gating 的公开 admission 与 fresh seed 契约。"""

from __future__ import annotations

import asyncio
import json
import threading
from types import MethodType, SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ming_sim.db import GameDB
from ming_sim.session import AudienceAdmission, ChatTurnResult, GameSession
from ming_sim import audience_night as an
from ming_sim.simulation import build_simulator_payload


def _session(game):
    db, _state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db, sess.content, sess.temporary_characters = db, content, {}
    return sess


def _set_place(game, name, *, location, transit_to="", transit_start_turn=None):
    db, _state, content = game
    if transit_start_turn is None:
        db.conn.execute(
            "UPDATE characters SET location=?, transit_to=? WHERE name=?",
            (location, transit_to, name),
        )
    else:
        db.conn.execute(
            "UPDATE characters SET location=?, transit_to=?, transit_start_turn=? WHERE name=?",
            (location, transit_to, transit_start_turn, name),
        )
    db.conn.commit()
    return content.characters[name]


def _arrive_at_destination(game, name):
    """Test helper: complete current transit via the unique write seam (no banned symbols)."""
    db, _state, content = game
    row = db.conn.execute(
        "SELECT transit_to FROM characters WHERE name=?", (name,),
    ).fetchone()
    dest = str(row["transit_to"] or "")
    assert dest, f"expected in-transit destination for {name!r}"
    db.set_character_transit(name, location=dest, content=content, commit=True)
    return [{"name": name, "location": dest}]


def _travel_row(db, name):
    row = db.conn.execute(
        "SELECT location, transit_to, transit_start_turn FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    return {
        "location": row["location"],
        "transit_to": row["transit_to"],
        "transit_start_turn": row["transit_start_turn"],
    }


def _chat_message_count(db):
    return int(db.conn.execute("SELECT COUNT(*) AS n FROM chat_messages").fetchone()["n"])


def _chat_turn_count(db):
    return int(db.conn.execute("SELECT COUNT(*) AS n FROM chat_turns").fetchone()["n"])


def _run_offsite_chat(runtime, minister_name, message, *, stream):
    """#1566：非流式/流式共用同一断口——统一读出机面 payload，供 sync/stream 参数化塌缩复用。"""
    if stream:
        events = list(runtime.chat_stream(minister_name, message))
        assert [ev.get("type") for ev in events] == ["done", "end"]
        return events[0].get("payload") or {}
    return runtime.chat(minister_name, message)


def _web_hall_runtime(db, state, content, *, session_chat):
    """#670：常规 Web.chat（gate_already_held=False）殿上入口壳；挂真 admission。

    #1566：同壳挂场外 scene 物化，经 beat generator seam 注入测试替身。
    WebGame 类方法经 __new__ 实例可直接解析，不再手绑类方法。
    """
    from tests.test_qa_c3_secret_order_path_1357_1376 import (
        webgame_shell_for_secret_order,
    )

    runtime = webgame_shell_for_secret_order(
        db, state, content, session_chat=session_chat,
    )
    s = runtime.session
    s.admit_audience = MethodType(GameSession.admit_audience, s)
    s.consume_audience_admission = MethodType(GameSession.consume_audience_admission, s)
    s._beat_generator = lambda _inputs: "generated offsite summon scene"
    return runtime


def test_audience_admission_distinguishes_capital_fresh_and_existing_transit(game):
    sess = _session(game)
    capital = _set_place(game, "毕自严", location="beizhili")
    fresh = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(game, "孙传庭", location="shaanxi", transit_to="henan")

    assert sess.admit_audience(capital).result is AudienceAdmission.IN_CAPITAL
    assert sess.admit_audience(fresh).result is AudienceAdmission.SUMMON_FRESH
    admitted = sess.admit_audience(moving)
    assert admitted.result is AudienceAdmission.SUMMON_IN_TRANSIT
    assert admitted.location == "shaanxi"
    assert admitted.transit_to == "henan"


def test_audience_admission_keeps_blank_fail_open_and_reuses_basic_qualification(game):
    blank = _set_place(game, "毕自严", location="")
    sess = _session(game)
    assert sess.admit_audience(blank).result is AudienceAdmission.IN_CAPITAL

    dead = _set_place(game, "洪承畴", location="shaanxi")
    db, state, _content = game
    db.set_character_status(state, dead.name, "dead", reason="测试")
    decision = sess.admit_audience(dead)
    assert decision.result is None
    assert "已故" in decision.reason


def test_audience_admission_records_offsite_summon_before_allowing_audience(game):
    sess = _session(game)
    db, state, _content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(game, "孙传庭", location="shaanxi", transit_to="henan")

    fresh = sess.consume_audience_admission(remote, origin_id="web:request-1", state=state)
    transit = sess.consume_audience_admission(moving, origin_id="cli:switch-1", state=state)

    assert fresh.result is AudienceAdmission.SUMMON_FRESH
    assert transit.result is AudienceAdmission.SUMMON_IN_TRANSIT
    assert fresh.allowed is False and transit.allowed is False
    assert {row["origin_id"]: row["kind"] for row in an.list_unsettled_summons(db)} == {
        "web:request-1": "fresh",
        "cli:switch-1": "in_transit",
    }


def test_audience_admission_records_nothing_for_capital_or_disqualified_person(game):
    sess = _session(game)
    db, state, _content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    dead = _set_place(game, "洪承畴", location="shaanxi")
    db.set_character_status(state, dead.name, "dead", reason="测试")

    assert sess.consume_audience_admission(
        capital, origin_id="web:capital", state=state,
    ).allowed is True
    assert sess.consume_audience_admission(
        dead, origin_id="web:dead", state=state,
    ).allowed is False
    assert an.list_unsettled_summons(db) == []


def test_cli_initial_selection_records_remote_summon_without_returning_minister(game, monkeypatch):
    from ming_sim.cli import terminal

    sess = _session(game)
    db, state, _content = game
    sess.state = state
    _set_place(game, "洪承畴", location="shaanxi")
    answers = iter(["洪承畴", "quit"])
    notices = []
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    monkeypatch.setattr("builtins.print", lambda *args, **_k: notices.append(" ".join(map(str, args))))

    assert terminal.choose_minister(sess) is None
    assert [(row["person_name"], row["origin_id"]) for row in an.list_unsettled_summons(db)] == [
        ("洪承畴", f"cli:initial:{state.turn}:洪承畴"),
    ]
    # 成功记召不喷固定承旨句；资格失败仍可经 reason 打印。
    joined = "\n".join(notices)
    assert "赴京" not in joined and "不能入殿" not in joined
    assert "已传召" not in joined


def test_cli_initial_selection_rejects_unknown_unregistered_person(game, monkeypatch):
    """#670：CLI 初选未知人物不得临时旁路入殿，须 ADR 0038 持久入册后再 admission。"""
    from ming_sim.cli import terminal

    sess = _session(game)
    db, state, _content = game
    sess.state = state
    unknown = "乌有先生甲"
    assert unknown not in sess.content.characters
    answers = iter([unknown, "quit"])
    notices: list[str] = []
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    monkeypatch.setattr(
        "builtins.print", lambda *args, **_k: notices.append(" ".join(map(str, args))),
    )

    assert terminal.choose_minister(sess) is None
    assert unknown not in sess.temporary_characters
    assert an.list_unsettled_summons(db) == []
    assert _chat_turn_count(db) == 0
    assert _chat_message_count(db) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM characters WHERE name=?", (unknown,),
    ).fetchone()["n"] == 0
    joined = "\n".join(notices)
    assert "临时传" not in joined
    assert "入殿" not in joined


def test_in_transit_summon_origin_is_idempotent_and_restorable(game):
    """#670 T-B：在途 admission 不改道/不重置；关库重开投影一致；同 origin 仍幂等。"""
    db, state, content = game
    sess = _session(game)
    sess.state = state
    person = _set_place(
        game, "洪承畴", location="shaanxi", transit_to="henan", transit_start_turn=3,
    )
    before_travel = _travel_row(db, person.name)
    origin = "command:42"
    open_before = an.get_open_night(db)
    expected_night_id = int(open_before["id"]) if open_before is not None else None

    first = sess.consume_audience_admission(person, origin_id=origin, state=state)
    again = sess.consume_audience_admission(person, origin_id=origin, state=state)
    assert first.result is AudienceAdmission.SUMMON_IN_TRANSIT
    assert again.result is AudienceAdmission.SUMMON_IN_TRANSIT
    assert _travel_row(db, person.name) == before_travel

    night = an.get_open_night(db)
    assert night is not None
    if expected_night_id is None:
        expected_night_id = int(night["id"])
    else:
        assert int(night["id"]) == expected_night_id

    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    assert unsettled[0] == {
        "entry_id": unsettled[0]["entry_id"],
        "night_id": expected_night_id,
        "person_name": person.name,
        "origin_id": origin,
        "kind": "in_transit",
    }
    entry_id = int(unsettled[0]["entry_id"])
    before_close = list(unsettled)

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        assert an.list_unsettled_summons(restored) == before_close
        assert _travel_row(restored, person.name) == before_travel

        night = an.get_open_night(restored) or an.open_night(restored, state)
        again_id = an.record_summon_in_transit(
            restored, int(night["id"]), person.name, origin_id=origin,
        )
        assert again_id == entry_id
        assert an.list_unsettled_summons(restored) == before_close

        assert an.settle_summon_origin(restored, origin) is True
        assert an.settle_summon_origin(restored, origin) is False
        assert an.list_unsettled_summons(restored) == []
    finally:
        restored.close()


def test_fresh_summon_origin_is_idempotent_and_projects_kind(game):
    db, state, _content = game
    night_id = int(an.open_night(db, state)["id"])

    first = an.record_summon_fresh(
        db, night_id, "洪承畴", origin_id="command:43",
    )
    again = an.record_summon_fresh(
        db, night_id, "洪承畴", origin_id="command:43",
    )

    assert again == first
    assert an.list_unsettled_summons(db) == [{
        "entry_id": first,
        "night_id": night_id,
        "person_name": "洪承畴",
        "origin_id": "command:43",
        "kind": "fresh",
        "travel_tone": "常行",
    }]


def test_multi_origin_same_person_dedupes_consumer_projections_not_ledger(game):
    """#670：同人多 origin ledger 独立保留；arrived/waiting 消费端每人一份。"""
    db, state, content = game
    sess = _session(game)
    sess.state = state
    person = _set_place(
        game, "洪承畴", location="shaanxi", transit_to="henan", transit_start_turn=0,
    )
    origin_chat = "web:chat:1"
    origin_tool = "web:tool:2"

    first = sess.consume_audience_admission(
        person, origin_id=origin_chat, state=state,
    )
    second = sess.consume_audience_admission(
        person, origin_id=origin_tool, state=state,
    )
    assert first.result is AudienceAdmission.SUMMON_IN_TRANSIT
    assert second.result is AudienceAdmission.SUMMON_IN_TRANSIT
    # 成功记召无固定承旨句。
    assert first.reason == "" and second.reason == ""

    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 2
    assert {row["origin_id"] for row in unsettled} == {origin_chat, origin_tool}
    first_entry = next(row for row in unsettled if row["origin_id"] == origin_chat)
    second_entry = next(row for row in unsettled if row["origin_id"] == origin_tool)

    # 抵非京 → arrived 每人 1 条（最早 origin），ledger 仍 2 行。
    assert _arrive_at_destination(game, person.name) == [
        {"name": person.name, "location": "henan"},
    ]
    arrived = an.list_arrived_unsettled_summons(db)
    assert arrived == [{
        "person_name": person.name,
        "original_destination": "henan",
        "origin_id": origin_chat,
        "source_entry_id": first_entry["entry_id"],
        "required_fact": "抵原地后续赴京",
    }]
    payload = build_simulator_payload(state, db, "", "")
    assert payload["unsettled_arrived_summons"] == arrived
    assert len(an.list_unsettled_summons(db)) == 2

    # 结清其一 origin 后另一仍未结，投影仍 1 人份。
    assert an.settle_summon_origin(db, origin_chat) is True
    remaining = an.list_unsettled_summons(db)
    assert [row["origin_id"] for row in remaining] == [origin_tool]
    arrived_after = an.list_arrived_unsettled_summons(db)
    assert arrived_after == [{
        "person_name": person.name,
        "original_destination": "henan",
        "origin_id": origin_tool,
        "source_entry_id": second_entry["entry_id"],
        "required_fact": "抵原地后续赴京",
    }]

    # 续赴京成功 → 同人全部 in_transit origin 结清（含尚未手结的 origin_tool）。
    from ming_sim.decree import settle_with_delta

    settle_with_delta(
        state, db,
        {"人物变更": [{
            "name": person.name, "动作": "行止", "transit_to": "beizhili",
            "origin_ref": "盘面自发",
        }]},
        before_turn=int(state.turn), content=content,
    )
    assert an.list_unsettled_summons(db) == []
    assert an.list_arrived_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []

    # waiting 消费端 dedupe：直接 capital 在途账（不依赖续程后残留 origin）。
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
        "transit_speed_factor=NULL WHERE name=?",
        ("beizhili", person.name),
    )
    db.conn.commit()
    night = an.get_open_night(db) or an.open_night(db, state)
    wait_a = "web:chat:wait-a"
    wait_b = "web:chat:wait-b"
    id_a = an.record_summon_in_transit(
        db, int(night["id"]), person.name, origin_id=wait_a,
    )
    id_b = an.record_summon_in_transit(
        db, int(night["id"]), person.name, origin_id=wait_b,
    )
    assert len(an.list_unsettled_summons(db)) == 2
    waiting = an.list_waiting_audience_summons(db)
    assert waiting == [{
        "person_name": person.name,
        "origin_id": wait_a,
        "source_entry_id": id_a,
        "location": "beizhili",
    }]
    assert build_simulator_payload(state, db, "", "")["waiting_audience"] == waiting
    assert an.settle_summon_origin(db, wait_a) is True
    assert an.list_waiting_audience_summons(db) == [{
        "person_name": person.name,
        "origin_id": wait_b,
        "source_entry_id": id_b,
        "location": "beizhili",
    }]
    assert an.settle_summon_origin(db, wait_b) is True
    assert an.list_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []


def test_fresh_summon_departs_via_canonical_applier_only_when_night_closes(game):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_fresh(db, night_id, person.name, origin_id="command:close-1")

    before = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (before["location"], before["transit_to"]) == ("shaanxi", "")

    an.close_night(db, state, night_id=night_id, content=content)

    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    # 启程成功不结清：origin 保持未结，kind 投影为在途（候见关联 durable）。
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    assert unsettled[0]["origin_id"] == "command:close-1"
    assert unsettled[0]["kind"] == "in_transit"
    assert unsettled[0]["night_id"] == night_id

    # Closed-night replay is a no-op and cannot reset the canonical departure clock.
    started = db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (person.name,)
    ).fetchone()["transit_start_turn"]
    assert an.close_night(db, state, night_id=night_id, content=content)["already"] is True
    assert db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (person.name,)
    ).fetchone()["transit_start_turn"] == started
    assert an.list_unsettled_summons(db) == unsettled


def test_fresh_summon_applier_failure_rolls_back_and_close_retry_is_safe(game, monkeypatch):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_fresh(db, night_id, person.name, origin_id="command:retry-1")

    from ming_sim import issues
    real_apply = issues.apply_person_changes_only
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected canonical applier failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(issues, "apply_person_changes_only", fail_once)

    try:
        an.close_night(db, state, night_id=night_id, content=content)
    except RuntimeError as exc:
        assert str(exc) == "injected canonical applier failure"
    else:
        raise AssertionError("canonical applier failure must abort close")

    failed = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (failed["location"], failed["transit_to"]) == ("shaanxi", "")
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [
        "command:retry-1"
    ]

    result = an.close_night(db, state, night_id=night_id, content=content)
    retried = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert result["closed"] is True
    assert (retried["location"], retried["transit_to"]) == ("shaanxi", "beizhili")
    unsettled = an.list_unsettled_summons(db)
    assert [row["origin_id"] for row in unsettled] == ["command:retry-1"]
    assert unsettled[0]["kind"] == "in_transit"


def test_arrived_summon_continuation_survives_failed_apply_across_months(game, monkeypatch):
    """#670 T-D：抵原地 payload 见抵达 → 失败月 / 无续启成功月 / 续启成功月三段 settle_with_delta。

    1. 失败月：续启 delta 经 settle_with_delta 触发 SettlementAbort；turn 不变；origin/抵达/行止未动。
    2. 无续启成功月：空 delta 经 settle_with_delta 推进一月；未结 origin 与抵达事实仍在，
       行止仍 henan/空 transit。若 settle_applied_arrived_summons 在任一成功月无视
       applied_person_changes 清掉在途 origin，本段必须失败。
    3. 续启成功月：canonical 行止 delta 经 settle_with_delta 才自动结清 origin。
    三段均禁止手推 turn、禁止手调 settle_applied_arrived_summons。
    """
    import ming_sim.decree as decree_mod
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    person = _set_place(
        game, "洪承畴", location="shaanxi", transit_to="henan", transit_start_turn=0,
    )
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:arrived-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )

    assert _arrive_at_destination(game, person.name) == [
        {"name": person.name, "location": "henan"}
    ]
    arrived_fact = {
        "person_name": person.name,
        "original_destination": "henan",
        "origin_id": origin,
        "source_entry_id": entry_id,
        "required_fact": "抵原地后续赴京",
    }
    payload = build_simulator_payload(state, db, "", "")
    assert payload["unsettled_arrived_summons"] == [arrived_fact]
    assert _travel_row(db, person.name)["location"] == "henan"
    assert _travel_row(db, person.name)["transit_to"] == ""

    real_apply = decree_mod.apply_score_extraction
    attempts = 0
    continuation = {"人物变更": [{
        "name": person.name, "动作": "行止", "transit_to": "beizhili",
        "origin_ref": "盘面自发",
    }]}

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected continuation applier failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(decree_mod, "apply_score_extraction", fail_once)
    failed_turn = int(state.turn)
    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort) as excinfo:
        settle_with_delta(
            state, db, continuation, before_turn=failed_turn, content=content,
        )
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert "injected continuation applier failure" in str(excinfo.value.__cause__)

    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]
    assert _travel_row(db, person.name)["location"] == "henan"
    assert _travel_row(db, person.name)["transit_to"] == ""
    assert int(state.turn) == failed_turn

    # 无续启成功月：公开生产缝空 delta 推进一月；不得手推 turn / 手调结清。
    noop_turn = int(state.turn)
    settle_with_delta(state, db, {}, before_turn=noop_turn, content=content)
    assert int(state.turn) == noop_turn + 1
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]
    next_payload = build_simulator_payload(state, db, "", "")
    assert next_payload["unsettled_arrived_summons"] == [arrived_fact]
    assert _travel_row(db, person.name)["location"] == "henan"
    assert _travel_row(db, person.name)["transit_to"] == ""

    # 续启成功月：只经 settle_with_delta；结清证明不得手调 helper。
    settle_with_delta(
        state, db, continuation, before_turn=int(state.turn), content=content,
    )
    assert an.list_unsettled_summons(db) == []
    after = _travel_row(db, person.name)
    assert after["location"] == "henan"
    assert after["transit_to"] == "beizhili"
    # 在途赴京期间不得再投「抵原地后续赴京」。
    assert build_simulator_payload(state, db, "", "")["unsettled_arrived_summons"] == []
    assert attempts == 3


def test_fresh_seed_closes_ticket_670_named_locations(content):
    expected = {
        **{name: "beizhili" for name in "韩爌 张瑞图 来宗道 施凤来 黄立极 王绍徽 毕自严 郭允厚 杨嗣昌 温体仁 钱龙锡 刘鸿训 钱谦益 李标 孙承宗 崔呈秀 王在晋 徐光启 徐应秋 周延儒 倪元璐 黄道周 曹化淳 王体乾 王承恩 魏忠贤 田尔耕 许显纯 李若琏 客氏 周皇后 周贵人 田贵妃 袁贵妃 慧妃 懿安皇后 高起潜 孙元化 许誉卿 乔允升 韩一良".split()},
        "袁崇焕": "guangdong",
        "袁可立": "henan",
        **{name: "shaanxi" for name in "曹文诏 洪承畴 孙传庭 李从心".split()},
        **{name: "liaodong" for name in "祖大寿 赵率教 王之臣 阎鸣泰".split()},
        "满桂": "shanxi", "毛文龙": "dongjiang_area", "卢象升": "nanzhili",
    }
    assert {name: content.characters[name].location for name in expected} == expected
    # #670：别名已清理——种子人物 location 不得残留 京师/beijing。
    leftover = {
        name: ch.location
        for name, ch in content.characters.items()
        if str(getattr(ch, "location", "") or "") in {"京师", "beijing"}
    }
    assert leftover == {}


def test_secret_order_path_does_not_consume_audience_admission(game, monkeypatch):
    """#670 T1：场外密疏只受 can_summon，不落传召账、不因 location 409。"""
    import web_app
    from fastapi import HTTPException
    from tests.test_qa_c3_secret_order_path_1357_1376 import (
        webgame_shell_for_secret_order,
    )

    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    before = an.list_unsettled_summons(db)

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        return ChatTurnResult(answer="臣领密旨。", pending_action_id=0, secret_order_id=0)

    runtime = webgame_shell_for_secret_order(
        db, state, content, session_chat=_session_chat,
    )
    # 壳须挂真 consume，以便若密疏误入闸可被观测（落账/异常），而非 AttributeError 假绿。
    runtime.session.consume_audience_admission = (
        lambda character, *, origin_id, state=None, origin_chat_turn_id=0: (
            GameSession.consume_audience_admission(
                runtime.session, character, origin_id=origin_id,
                state=state or runtime.session.state,
                origin_chat_turn_id=origin_chat_turn_id,
            )
        )
    )
    monkeypatch.setattr(web_app, "web_game", runtime)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    try:
        result = asyncio.run(web_app.api_create_secret_order(
            remote.name,
            web_app.SecretOrderRequest(
                title="密询军情", content="速报陕西军情。", tags=[],
            ),
        ))
    except HTTPException as exc:
        raise AssertionError(
            f"场外密疏不得因 admission/location 拒绝：{exc.status_code} {exc.detail}"
        ) from exc

    assert result["answer"] == "臣领密旨。"
    assert an.list_unsettled_summons(db) == before


def test_multi_origin_fresh_closes_once_per_person_and_retries(game, monkeypatch):
    """#670 T2：同人多 origin 各留 ledger 行；收夜按人只一段启程；applier 失败可重试。"""
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])
    origin_web = "web:chat:1:洪承畴"
    origin_cli = "cli:initial:1:洪承畴"

    first = an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_web, travel_tone="加急",
    )
    second = an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_cli, travel_tone="星夜兼程",
    )
    # 不同 origin 各一行；同 origin 再消费才幂等复用。
    assert second != first
    assert an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_web,
    ) == first
    unsettled_before = an.list_unsettled_summons(db)
    assert len(unsettled_before) == 2
    assert {row["origin_id"] for row in unsettled_before} == {origin_web, origin_cli}
    assert {row["kind"] for row in unsettled_before} == {"fresh"}
    assert {row["entry_id"] for row in unsettled_before} == {first, second}

    from ming_sim import issues
    real_apply = issues.apply_person_changes_only
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected multi-origin applier failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(issues, "apply_person_changes_only", fail_once)
    with pytest.raises(RuntimeError, match="injected multi-origin applier failure"):
        an.close_night(db, state, night_id=night_id, content=content)

    assert len(an.list_unsettled_summons(db)) == 2
    failed = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (failed["location"], failed["transit_to"]) == ("shaanxi", "")

    result = an.close_night(db, state, night_id=night_id, content=content)
    after = db.conn.execute(
        "SELECT location, transit_to, transit_speed_factor, transit_distance_remaining "
        "FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert result["closed"] is True
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    assert after["transit_speed_factor"] == 2.0
    assert after["transit_distance_remaining"] > 0
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 2
    assert {row["kind"] for row in unsettled} == {"in_transit"}
    assert {row["origin_id"] for row in unsettled} == {origin_web, origin_cli}
    # apply 一次（失败）+ 一次（成功）；不得按 origin 二次 apply。
    assert attempts == 2


def test_multi_origin_fresh_independent_retract_and_single_departure(game, monkeypatch):
    """#670：同人两 fresh 源轮独立撤回；两轮都存活收夜只一次行止。"""
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])
    origin_a = "web:tool:first"
    origin_b = "web:tool:second"

    # 两源轮绑各自 chat_turn，模拟 fail_chat_turn 按 origin_chat_turn_id 独立清理。
    _n1, turn_a = an.attach_chat_turn_to_night(db, state, "毕自严")
    _n2, turn_b = an.attach_chat_turn_to_night(db, state, "毕自严")
    entry_a = an.record_summon_fresh(
        db, night_id, person.name,
        origin_id=origin_a, origin_chat_turn_id=int(turn_a),
    )
    entry_b = an.record_summon_fresh(
        db, night_id, person.name,
        origin_id=origin_b, origin_chat_turn_id=int(turn_b),
    )
    assert entry_a != entry_b
    assert {
        row["origin_id"] for row in an.list_unsettled_summons(db)
    } == {origin_a, origin_b}

    # 撤/失败清理首轮：第二轮事实仍在。
    db.fail_chat_turn(int(turn_a))
    remaining = an.list_unsettled_summons(db)
    assert len(remaining) == 1
    assert remaining[0]["origin_id"] == origin_b
    assert remaining[0]["entry_id"] == entry_b
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM story_ledger_entries WHERE id=?", (entry_a,)
    ).fetchone()["n"] == 0

    # 再清另一轮才空。
    db.fail_chat_turn(int(turn_b))
    assert an.list_unsettled_summons(db) == []

    # 两轮都存活时收夜只产生一次行止（一次 apply）。
    entry_a2 = an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_a,
    )
    entry_b2 = an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_b,
    )
    assert entry_a2 != entry_b2
    from ming_sim import issues
    real_apply = issues.apply_person_changes_only
    apply_calls = 0

    def count_apply(*args, **kwargs):
        nonlocal apply_calls
        apply_calls += 1
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(issues, "apply_person_changes_only", count_apply)
    result = an.close_night(db, state, night_id=night_id, content=content)
    assert result["closed"] is True
    assert apply_calls == 1
    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 2
    assert {row["kind"] for row in unsettled} == {"in_transit"}
    assert {row["origin_id"] for row in unsettled} == {origin_a, origin_b}


def test_cli_midflow_summon_consumes_admission_without_entering(game, monkeypatch):
    """#670 T3：夜内「传X来」场外只打印闸文，不返 summon:、不入殿。"""
    from ming_sim.cli import terminal

    sess = _session(game)
    db, state, content = game
    sess.state = state
    current = _set_place(game, "毕自严", location="beizhili")
    _set_place(game, "洪承畴", location="shaanxi")
    notices: list[str] = []
    monkeypatch.setattr(
        "builtins.print", lambda *args, **_k: notices.append(" ".join(map(str, args))),
    )

    outcome = terminal._handle_court_command(sess, "传洪承畴来", current)

    assert outcome == "handled"
    # 成功记召不喷固定承旨句，仍 handled 不入殿。
    joined = "\n".join(notices)
    assert "赴京" not in joined and "不能入殿" not in joined
    assert "已传召" not in joined
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [
        f"cli:midflow:{state.turn}:洪承畴",
    ]


def test_cli_midflow_summon_rejects_unknown_unregistered_person(game, monkeypatch):
    """#670：CLI 夜内换人未知人物不得 summon-temp 旁路，须 ADR 0038 持久入册后再 admission。"""
    from ming_sim.cli import terminal

    sess = _session(game)
    db, state, _content = game
    sess.state = state
    current = _set_place(game, "毕自严", location="beizhili")
    unknown = "乌有先生乙"
    assert unknown not in sess.content.characters
    notices: list[str] = []
    monkeypatch.setattr(
        "builtins.print", lambda *args, **_k: notices.append(" ".join(map(str, args))),
    )

    outcome = terminal._handle_court_command(sess, f"传{unknown}来", current)

    assert outcome == "handled"
    assert unknown not in sess.temporary_characters
    assert an.list_unsettled_summons(db) == []
    assert _chat_turn_count(db) == 0
    assert _chat_message_count(db) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM characters WHERE name=?", (unknown,),
    ).fetchone()["n"] == 0
    joined = "\n".join(notices)
    assert "summon" not in outcome
    assert "临时传" not in joined
    assert "未建档" in joined or "补档" in joined


def test_tool_summon_does_not_splice_gate_reason_into_llm_answer(game, monkeypatch):
    """#670 T4：session/web tool 拒入殿后 answer 保持模型原文，无闸文后缀。"""
    import ming_sim.session as session_mod
    from tests.test_audience_background import ToolExec, _FakeAgent, _web_game

    db, state, content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    remote = _set_place(game, "洪承畴", location="shaanxi")
    model_answer = "臣请传洪承畴入对。"

    class _Agent:
        def run(self, _message):
            return SimpleNamespace(
                content=model_answer,
                tools=[SimpleNamespace(
                    tool_name="summon_minister",
                    result=f"__summon__{remote.name}",
                    arguments={"name": remote.name, "行程语气": "加急"},
                )],
            )

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.temporary_characters = {}
    sess.registry = SimpleNamespace(
        get=lambda _character: _Agent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="api")
    sess._retrieve_memories_for_message = lambda text: text
    sess._audience_prompt_for_message = lambda message, *a, **k: message
    sess._start_cli_action_intent = lambda *_a, **_k: None
    sess._finish_cli_action_intent = lambda *_a, **_k: None
    sess._recognize_audience_command_verdict = lambda *_a, **_k: None
    sess._apply_audience_command_verdict = lambda *a, **k: None
    sess._confirmation_intent_for_preexisting_pending = (
        lambda *a, **k: None
    )
    sess._scene_registry = SimpleNamespace(
        start_open_enter=lambda *a, **k: None,
        start_exit=lambda *a, **k: None,
        join=lambda *_a, **_k: [],
        abandon=lambda *_a, **_k: None,
    )
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)

    result = sess.chat(capital.name, "传洪承畴来")
    assert result.answer == model_answer
    assert "本回合不能入殿" not in result.answer
    assert not result.court_action and not result.next_minister
    assert any(
        row["person_name"] == remote.name and row["kind"] == "fresh"
        and row["travel_tone"] == "加急"
        for row in an.list_unsettled_summons(db)
    )

    # web stream tool 路：复用既有 _chat_stream_payload 真入口夹具。
    for row in list(an.list_unsettled_summons(db)):
        an.settle_summon_origin(db, row["origin_id"])
    tool_exec = ToolExec("summon_minister", f"__summon__{remote.name}")
    tool_exec.arguments = {"name": remote.name, "行程语气": "星夜兼程"}
    agent = _FakeAgent(tools=[tool_exec], chunks=[model_answer])
    web_game = _web_game(db, state, content, agent)
    web_game.session.summon_character = (
        lambda name, current, allow_temporary=True: GameSession.summon_character(
            web_game.session, name, current, allow_temporary=allow_temporary,
        )
    )
    web_game.session.admit_audience = (
        lambda character: GameSession.admit_audience(web_game.session, character)
    )
    web_game.session.can_summon = (
        lambda character: GameSession.can_summon(web_game.session, character)
    )
    web_game.session.consume_audience_admission = (
        lambda character, *, origin_id, state=None, origin_chat_turn_id=0, travel_tone="常行": (
            GameSession.consume_audience_admission(
                web_game.session, character, origin_id=origin_id,
                state=state or web_game.session.state,
                origin_chat_turn_id=origin_chat_turn_id,
                travel_tone=travel_tone,
            )
        )
    )
    payload = web_game._chat_stream_payload(
        capital.name,
        "再请传洪承畴。",
        chat_turn_id=0,
        before_snapshot={},
        accepted_turn=state.turn,
        emit_delta=lambda _chunk: None,
    )
    assert payload["answer"] == model_answer
    assert "本回合不能入殿" not in payload["answer"]
    assert not payload.get("court_action") and not payload.get("next_minister")
    assert any(
        row["person_name"] == remote.name and row["kind"] == "fresh"
        and row["travel_tone"] == "星夜兼程"
        for row in an.list_unsettled_summons(db)
    )



def test_session_register_unlisted_summon_after_uses_admission(game, monkeypatch):
    """#670：非流式补档 summon_after 落 DB 后走共享 admission；不可召 office_type 不换人。"""
    import json
    import ming_sim.session as session_mod

    db, state, content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    eligible_name = "补档可召甲"
    ineligible_name = "补档宗藩乙"
    assert eligible_name not in content.characters
    assert ineligible_name not in content.characters

    def _make_sess(tool_name, payload):
        class _Agent:
            def run(self, _message):
                return SimpleNamespace(
                    content="臣请补档。",
                    tools=[SimpleNamespace(
                        tool_name=tool_name,
                        result=f"__pending_unlisted_person__{payload}",
                        arguments=json.loads(payload),
                    )],
                )

        sess = GameSession.__new__(GameSession)
        sess.db = db
        sess.state = state
        sess.content = content
        sess.temporary_characters = {}
        sess.registry = SimpleNamespace(
            get=lambda _character: _Agent(),
            build_draft_line=lambda: "无",
            register=lambda _ch: None,
        )
        sess.llm_config = SimpleNamespace(channel="api")
        sess._retrieve_memories_for_message = lambda text: text
        sess._audience_prompt_for_message = lambda message, *a, **k: message
        sess._start_cli_action_intent = lambda *_a, **_k: None
        sess._finish_cli_action_intent = lambda *_a, **_k: None
        sess._recognize_audience_command_verdict = lambda *_a, **_k: None
        sess._apply_audience_command_verdict = lambda *a, **k: None
        sess._confirmation_intent_for_preexisting_pending = lambda *a, **k: None
        sess._scene_registry = SimpleNamespace(
            start_open_enter=lambda *a, **k: None,
            start_exit=lambda *a, **k: None,
            join=lambda *_a, **_k: [],
            abandon=lambda *_a, **_k: None,
        )
        return sess

    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)

    # 可召 office_type：admission 时 DB 行须已存在，且 allowed → 换人。
    eligible_payload = json.dumps({
        "name": eligible_name,
        "office": "兵部主事",
        "office_type": "文官",
        "summon_after": True,
    }, ensure_ascii=False)
    sess = _make_sess("register_unlisted_person", eligible_payload)
    seen_db: list[bool] = []
    real_consume = GameSession.consume_audience_admission

    def _spy(self, character, *, origin_id, state=None, origin_chat_turn_id=0):
        row = self.db.conn.execute(
            "SELECT name, office_type, location FROM characters WHERE name=?",
            (character.name,),
        ).fetchone()
        seen_db.append(row is not None and str(row["name"]) == character.name)
        return real_consume(
            self, character, origin_id=origin_id, state=state,
            origin_chat_turn_id=origin_chat_turn_id,
        )

    monkeypatch.setattr(GameSession, "consume_audience_admission", _spy)
    result = sess.chat(capital.name, f"补档{eligible_name}")
    assert result.registered_minister == eligible_name
    assert seen_db == [True], "admission 调用时补档 DB 行须已落下"
    assert result.court_action == "summon"
    assert result.next_minister == eligible_name
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM characters WHERE name=?", (eligible_name,),
    ).fetchone()["n"] == 1

    # 不可召 office_type（宗藩）：仍落档，admission 见 DB 行，但不换人。
    ineligible_payload = json.dumps({
        "name": ineligible_name,
        "office": "秦王",
        "office_type": "宗藩",
        "summon_after": True,
    }, ensure_ascii=False)
    sess2 = _make_sess("register_unlisted_person", ineligible_payload)
    seen_db.clear()
    result2 = sess2.chat(capital.name, f"补档{ineligible_name}")
    assert result2.registered_minister == ineligible_name
    assert seen_db == [True], "不可召补档 admission 时 DB 行亦须已存在"
    assert not result2.court_action
    assert not result2.next_minister
    assert db.conn.execute(
        "SELECT office_type FROM characters WHERE name=?", (ineligible_name,),
    ).fetchone()["office_type"] == "宗藩"


def test_web_register_unlisted_summon_after_uses_admission(game, monkeypatch):
    """#670：流式补档 summon_after 落 DB 后走共享 admission；不可召 office_type 不换人。"""
    import json
    from tests.test_audience_background import ToolExec, _FakeAgent, _web_game

    db, state, content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    eligible_name = "流式补档可召丙"
    ineligible_name = "流式补档宗藩丁"
    assert eligible_name not in content.characters
    assert ineligible_name not in content.characters

    def _bind_real_admission(web_game):
        # FakeSession 用 set；生产补档路径 temporary_characters.pop 需要 mapping。
        web_game.session.temporary_characters = {}
        web_game.session._proposal_blocked = GameSession._proposal_blocked
        # FakeRegistry 仅有 get/refresh；补档路径会 registry.register。
        web_game.session.registry.register = lambda _ch: None
        web_game.session._apply_unlisted_person_registration = (
            lambda payload: GameSession._apply_unlisted_person_registration(
                web_game.session, payload,
            )
        )
        web_game.session.can_summon = (
            lambda character: GameSession.can_summon(web_game.session, character)
        )
        web_game.session.admit_audience = (
            lambda character: GameSession.admit_audience(web_game.session, character)
        )
        seen_db: list[bool] = []

        def _consume(character, *, origin_id, state=None, origin_chat_turn_id=0):
            row = web_game.session.db.conn.execute(
                "SELECT name FROM characters WHERE name=?", (character.name,),
            ).fetchone()
            seen_db.append(row is not None and str(row["name"]) == character.name)
            return GameSession.consume_audience_admission(
                web_game.session, character, origin_id=origin_id,
                state=state or web_game.session.state,
                origin_chat_turn_id=origin_chat_turn_id,
            )

        web_game.session.consume_audience_admission = _consume
        return seen_db

    # 可召：admission 见 DB 行且换人。
    eligible_payload = json.dumps({
        "name": eligible_name,
        "office": "户部主事",
        "office_type": "文官",
        "summon_after": True,
    }, ensure_ascii=False)
    agent = _FakeAgent(
        tools=[ToolExec("register_unlisted_person", f"__pending_unlisted_person__{eligible_payload}")],
        chunks=["臣请补档。"],
    )
    web_game = _web_game(db, state, content, agent)
    seen_db = _bind_real_admission(web_game)
    interpreted = web_game._chat_stream_interpret_tools(
        capital.name,
        f"补档{eligible_name}",
        capital,
        "臣请补档。",
        SimpleNamespace(tools=agent.tools),
        None,
        0,
    )
    assert interpreted["registered"] == eligible_name
    assert seen_db == [True], "流式 admission 调用时补档 DB 行须已落下"
    assert interpreted["court_action"] == "summon"
    assert interpreted["next_minister"] == eligible_name

    # 不可召宗藩：落档、admission 见行、不换人。
    ineligible_payload = json.dumps({
        "name": ineligible_name,
        "office": "秦王",
        "office_type": "宗藩",
        "summon_after": True,
    }, ensure_ascii=False)
    agent2 = _FakeAgent(
        tools=[ToolExec(
            "register_unlisted_person",
            f"__pending_unlisted_person__{ineligible_payload}",
        )],
        chunks=["臣请补档。"],
    )
    web_game2 = _web_game(db, state, content, agent2)
    seen_db2 = _bind_real_admission(web_game2)
    interpreted2 = web_game2._chat_stream_interpret_tools(
        capital.name,
        f"补档{ineligible_name}",
        capital,
        "臣请补档。",
        SimpleNamespace(tools=agent2.tools),
        None,
        0,
    )
    assert interpreted2["registered"] == ineligible_name
    assert seen_db2 == [True], "流式不可召补档 admission 时 DB 行亦须已存在"
    assert not interpreted2["court_action"]
    assert not interpreted2["next_minister"]
    assert db.conn.execute(
        "SELECT office_type FROM characters WHERE name=?", (ineligible_name,),
    ).fetchone()["office_type"] == "宗藩"


def test_web_chat_hall_admission_allows_capital_and_blocks_offsite(game):
    """#670 T-A：Web.chat——blank/beizhili 开殿；场外/在途成功记召静默 200，不调回话。"""
    db, state, content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    remote = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(
        game, "孙传庭", location="shaanxi", transit_to="henan", transit_start_turn=2,
    )
    moving_before = _travel_row(db, moving.name)
    chat_calls: list[str] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        chat_calls.append(minister_name)
        return ChatTurnResult(answer=f"{minister_name}入对。", pending_action_id=0, secret_order_id=0)

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)

    beizhili_payload = runtime.chat(capital.name, "户部钱粮如何？")
    assert beizhili_payload["answer"] == f"{capital.name}入对。"
    assert chat_calls == [capital.name]

    _set_place(game, capital.name, location="")
    blank_payload = runtime.chat(capital.name, "再问一句。")
    assert blank_payload["answer"] == f"{capital.name}入对。"
    assert chat_calls == [capital.name, capital.name]

    allowed_msgs = _chat_message_count(db)
    allowed_turns = _chat_turn_count(db)
    # #1566：成功记召：200 静默载荷，不 409、不调回话、不建轮/消息；枚举仅机面字段。
    # 同一 ledger 行须有自由 scene body；canonical scroll 可见，仍无 chat turn。
    remote_payload = runtime.chat(remote.name, "传洪承畴来。")
    assert remote_payload["admission"] == AudienceAdmission.SUMMON_FRESH.value
    assert remote_payload["answer"] == ""
    assert remote_payload["chat_turn_id"] == 0
    assert chat_calls == [capital.name, capital.name]

    moving_payload = runtime.chat(moving.name, "传孙传庭来。")
    assert moving_payload["admission"] == AudienceAdmission.SUMMON_IN_TRANSIT.value
    assert moving_payload["answer"] == ""
    assert moving_payload["chat_turn_id"] == 0
    assert chat_calls == [capital.name, capital.name]
    assert _chat_message_count(db) == allowed_msgs
    assert _chat_turn_count(db) == allowed_turns
    assert _travel_row(db, moving.name) == moving_before

    by_origin = {row["origin_id"]: row for row in an.list_unsettled_summons(db)}
    remote_origin = f"web:chat:{state.turn}:{remote.name}"
    moving_origin = f"web:chat:{state.turn}:{moving.name}"
    assert by_origin[remote_origin]["kind"] == "fresh"
    assert by_origin[moving_origin]["kind"] == "in_transit"
    # #1566：scene 已物化的结构化证据——scroll summon beat + speaker 锚定（空 body 不进卷轴）。
    # 断言 ledger origin/kind/tags、scroll 非 entrance beat、零 chat turn、travel 状态。
    # 禁盯 body/content 散文。
    night_id = int(by_origin[remote_origin]["night_id"])
    scroll = an.read_night_scroll(db, night_id)
    summon_speakers = {
        m.get("speaker")
        for m in scroll
        if m.get("beat") == "summon" and m.get("speaker")
    }
    assert remote.name in summon_speakers
    assert moving.name in summon_speakers


def test_web_chat_stream_summon_success_exits_error_channel(game):
    """#670：chat_stream 成功记召 yield done+end，无 error，不调回话。

    #1566：同一 ledger 行持久化自由 scene；仍无 chat turn / 回话。
    """
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(
        game, "孙传庭", location="shaanxi", transit_to="henan", transit_start_turn=3,
    )
    chat_calls: list[str] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        chat_calls.append(minister_name)
        return ChatTurnResult(answer="不应到达。", pending_action_id=0, secret_order_id=0)

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)
    before_msgs = _chat_message_count(db)
    before_turns = _chat_turn_count(db)

    def _collect(name, text):
        events = list(runtime.chat_stream(name, text))
        types = [ev.get("type") for ev in events]
        assert "error" not in types
        assert types == ["done", "end"]
        payload = events[0].get("payload") or {}
        assert payload.get("answer") == ""
        assert payload.get("chat_turn_id") == 0
        return payload

    remote_payload = _collect(remote.name, "传洪承畴来。")
    assert remote_payload["admission"] == AudienceAdmission.SUMMON_FRESH.value

    moving_payload = _collect(moving.name, "传孙传庭来。")
    assert moving_payload["admission"] == AudienceAdmission.SUMMON_IN_TRANSIT.value

    assert chat_calls == []
    assert _chat_message_count(db) == before_msgs
    assert _chat_turn_count(db) == before_turns
    by_origin = {row["origin_id"]: row for row in an.list_unsettled_summons(db)}
    remote_origin = f"web:stream:{state.turn}:{remote.name}"
    moving_origin = f"web:stream:{state.turn}:{moving.name}"
    assert by_origin[remote_origin]["kind"] == "fresh"
    assert by_origin[moving_origin]["kind"] == "in_transit"
    # #1566：结构化 scroll 投影证明 scene 物化（禁盯 body 散文）。
    night_id = int(by_origin[remote_origin]["night_id"])
    summon_speakers = {
        m.get("speaker")
        for m in an.read_night_scroll(db, night_id)
        if m.get("beat") == "summon" and m.get("speaker")
    }
    assert remote.name in summon_speakers
    assert moving.name in summon_speakers


def test_web_chat_offsite_summon_scene_generator_failure_is_loud(game):
    """#1566：场外记召 scene 生成失败须响亮上抛，不得空白成功载荷。

    真实入口 WebGame.chat；admission 已落传召账；generator 抛错后：
    - 请求以异常失败（非 200 空 answer/SUMMON_* done）
    - ledger 仍在且 body 仍空（未伪装已生成）
    - 零 chat turn
    """
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    before_turns = _chat_turn_count(db)

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        raise AssertionError("scene 失败路径不得调回话")

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)

    def _boom(_inputs):
        raise RuntimeError("injected offsite summon scene failure")

    runtime.session._beat_generator = _boom

    with pytest.raises(RuntimeError, match="injected offsite summon scene failure"):
        runtime.chat(remote.name, "传洪承畴来。")

    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    assert unsettled[0]["origin_id"] == f"web:chat:{state.turn}:{remote.name}"
    assert unsettled[0]["kind"] == "fresh"
    assert _chat_turn_count(db) == before_turns
    # #1566：生成失败不得写入/伪装 scene body；这是持久化原子性，
    # 不约束任何成功生成正文。
    entry = db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE id=?",
        (int(unsettled[0]["entry_id"]),),
    ).fetchone()
    assert entry is not None
    assert entry["body"] == ""
    night_id = int(unsettled[0]["night_id"])
    summon_speakers = {
        m.get("speaker")
        for m in an.read_night_scroll(db, night_id)
        if m.get("beat") == "summon" and m.get("speaker")
    }
    assert remote.name not in summon_speakers


def test_web_chat_offsite_summon_generator_receives_structured_travel_facts(game):
    """#1566 r4：真实 generator 须收到正向场外事实，而非仅场景节点=summon。"""
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    captured: list = []

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        raise AssertionError("场外记召不得调回话")

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)

    def _capture(inputs):
        captured.append(inputs)
        return "generated offsite summon scene"

    runtime.session._beat_generator = _capture
    payload = runtime.chat(remote.name, "传洪承畴来。")
    assert payload["admission"] == AudienceAdmission.SUMMON_FRESH.value
    assert len(captured) == 1
    inputs = captured[0]
    assert inputs.beat_kind == "summon"
    assert inputs.audience_scenes
    facts = json.loads(inputs.audience_scenes[0])
    assert facts["decree_issued"] is True
    assert facts["courier_traveling"] is True
    assert facts["courier_arrived"] is False
    assert facts["person_entered_court"] is False


@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_web_chat_offsite_scene_keeps_pending_until_settled(game, stream):
    """#1566 r4：场外 scene 生成期间既有 pending ticket 不得提前消失（sync/stream 参数化同缝）。"""
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        raise AssertionError("场外记召不得调回话")

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)
    started = threading.Event()
    release = threading.Event()
    close_entered = threading.Event()

    def _slow(_inputs):
        started.set()
        release.wait()
        return "generated offsite summon scene"

    runtime.session._beat_generator = _slow
    results: list = []
    error: list = []

    def _run():
        try:
            results.append(
                _run_offsite_chat(runtime, remote.name, "传洪承畴来。", stream=stream)
            )
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    started.wait()
    q = runtime._runtime_write_queue()
    wait_prior_entered = threading.Event()
    real_wait_prior = q.wait_prior

    def observe_wait_prior(ticket):
        wait_prior_entered.set()
        return real_wait_prior(ticket)

    q.wait_prior = observe_wait_prior  # type: ignore[method-assign]
    close_worker = threading.Thread(
        target=lambda: q.barrier(close_entered.set),
        daemon=True,
    )
    close_worker.start()
    # Prove close reached wait_prior while scene ticket still open — not claim-only has_open_barrier.
    wait_prior_entered.wait()
    assert not close_entered.is_set(), "close barrier crossed an unfinished scene"
    release.set()
    worker.join()
    close_worker.join()
    assert not error, error
    assert results and results[0]["admission"] == AudienceAdmission.SUMMON_FRESH.value
    assert close_entered.is_set(), "close barrier did not drain after scene completion"


@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_web_chat_offsite_scene_failure_releases_close_barrier(game, stream):
    """#1566 r4：场外 scene 失败后既有关闭屏障须可继续（sync/stream 参数化同缝）。"""
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        raise AssertionError("场外记召不得调回话")

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)
    started = threading.Event()
    release = threading.Event()
    close_entered = threading.Event()
    chat_error: list[BaseException] = []

    def _boom(_inputs):
        started.set()
        release.wait()
        raise RuntimeError("injected offsite summon scene failure")

    runtime.session._beat_generator = _boom

    def _run():
        try:
            _run_offsite_chat(runtime, remote.name, "传洪承畴来。", stream=stream)
        except BaseException as exc:  # noqa: BLE001
            chat_error.append(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    started.wait()
    q = runtime._runtime_write_queue()
    wait_prior_entered = threading.Event()
    real_wait_prior = q.wait_prior

    def observe_wait_prior(ticket):
        wait_prior_entered.set()
        return real_wait_prior(ticket)

    q.wait_prior = observe_wait_prior  # type: ignore[method-assign]
    close_worker = threading.Thread(
        target=lambda: q.barrier(close_entered.set),
        daemon=True,
    )
    close_worker.start()
    wait_prior_entered.wait()
    assert not close_entered.is_set(), "close barrier crossed an unfinished scene"
    release.set()
    worker.join()
    close_worker.join()
    assert len(chat_error) == 1
    assert isinstance(chat_error[0], RuntimeError)
    assert str(chat_error[0]) == "injected offsite summon scene failure"
    assert close_entered.is_set(), "close barrier did not drain after scene failure"


def test_hot_replace_409_while_offsite_scene_ticket_open(game, monkeypatch):
    """#1566：load 在 open ticket 时立即 409，不等 LLM、不关旧库。
    #1732：局内销毁式 reset 已删，热替换并发门只测 load。"""
    import web_app

    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    runtime = _web_hall_runtime(
        db, state, content,
        session_chat=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("场外记召不得调回话"),
        ),
    )
    started = threading.Event()
    release = threading.Event()

    def _slow(_inputs):
        started.set()
        release.wait()
        return "generated offsite summon scene"

    runtime.session._beat_generator = _slow
    replacements: list[str] = []
    runtime.load_save = lambda _name: replacements.append("load")
    runtime.state_payload = lambda: {"ok": True}
    runtime.favorites = set()
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)

    chat_error: list[BaseException] = []

    def _run():
        try:
            runtime.chat(remote.name, "传洪承畴来。")
        except BaseException as exc:  # noqa: BLE001
            chat_error.append(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    started.wait()
    db.conn.execute("SELECT 1").fetchone()

    path = "/api/saves/存档/load"

    busy = TestClient(web_app.app).post(path)
    assert busy.status_code == 409
    assert replacements == []
    db.conn.execute("SELECT 1").fetchone()

    release.set()
    worker.join()
    assert not chat_error, chat_error

    retried = TestClient(web_app.app).post(path)
    assert retried.status_code == 200
    assert replacements == ["load"]
    state_response = TestClient(web_app.app).get("/api/game/state")
    assert state_response.status_code == 200
    assert state_response.json() == {"ok": True}
    minister = next(iter(content.characters))
    write_response = TestClient(web_app.app).post(f"/api/favorites/{minister}")
    assert write_response.status_code == 200


def test_offsite_scene_assembles_under_gate_generates_without_gate(game):
    """#1566：组装持 gate、生成不持 gate、ticket 在 provider 终态前仍 open。"""
    from ming_sim import beat_orchestration as bo

    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    runtime = _web_hall_runtime(
        db, state, content,
        session_chat=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("场外记召不得调回话"),
        ),
    )
    assemble_held: list[bool] = []
    generate_held: list[bool] = []
    generate_inflight: list[int] = []
    orig_assemble = bo.assemble_beat_inputs

    def _assemble(*args, **kwargs):
        assemble_held.append(runtime._runtime_write_gate().locked())
        return orig_assemble(*args, **kwargs)

    started = threading.Event()
    release = threading.Event()

    def _boom(_inputs):
        generate_held.append(runtime._runtime_write_gate().locked())
        generate_inflight.append(runtime._pending_writes_count)
        started.set()
        release.wait()
        raise RuntimeError("injected offsite summon scene failure")

    runtime.session._beat_generator = _boom
    bo.assemble_beat_inputs = _assemble
    chat_error: list[BaseException] = []

    def _run():
        try:
            runtime.chat(remote.name, "传洪承畴来。")
        except BaseException as exc:  # noqa: BLE001
            chat_error.append(exc)

    try:
        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        started.wait()
        release.set()
        worker.join()
    finally:
        bo.assemble_beat_inputs = orig_assemble

    assert assemble_held == [True]
    assert generate_held == [False]
    assert generate_inflight and generate_inflight[0] > 0
    assert len(chat_error) == 1
    assert str(chat_error[0]) == "injected offsite summon scene failure"
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    entry = db.conn.execute(
        "SELECT body FROM story_ledger_entries WHERE id=?",
        (int(unsettled[0]["entry_id"]),),
    ).fetchone()
    assert entry["body"] == ""


def _install_secret_order_agent(runtime, *, stream: bool = False) -> None:
    """#1566：在既有 hall 壳上只换 LLM 边界 agent + 密令落地真方法。

    复用 tests/test_audience_background._FakeAgent 流式形态；channel=api 走 #344
    前缀密令 resolve 路。WebGame._chat_stream_payload 经类实例解析，不手绑。
    """
    from tests.test_audience_background import RunContent, RunOutput, ToolExec, _FakeAgent

    class _SyncAgent(_FakeAgent):
        def run(self, *_a, **_k):
            return SimpleNamespace(content="".join(self.chunks), tools=self.tools)

        def get_last_run_output(self):
            return None

    agent: Any
    # #1566：密令 route 须吞 summon+dismiss court actions，仍只 stage 密令。
    non_secret_tools = [
        ToolExec("propose_directive", "__pending_directive__不得物化的普通旨意"),
        ToolExec(
            "rush_staged_commitment",
            '__commitment_rush__{"issue_id": 1, "stage_idx": 0, "deadline_months": 1}',
        ),
        ToolExec("summon_minister", "__summon__杨嗣昌"),
        ToolExec("dismiss_minister", "__dismiss__"),
    ]
    if stream:
        agent = _FakeAgent(tools=non_secret_tools, chunks=["臣", "领密旨。"])
    else:
        agent = _SyncAgent(tools=non_secret_tools, chunks=["臣领密旨。"])

    s = runtime.session
    s.registry = SimpleNamespace(get=lambda _ch: agent, session_ids={})
    s.llm_config = SimpleNamespace(channel="api")
    s._audience_prompt_for_message = (
        lambda msg, character=None, chat_turn_id=0: msg
    )
    s._start_cli_action_intent = lambda *_a, **_k: None
    s._finish_cli_action_intent = lambda *_a, **_k: None
    s.start_exit_scene_from_dismiss_tools = lambda *_a, **_k: False
    # 密令落库唯一真源：apply_cli_conversation_actions 及其 chat 入口。
    for name in (
        "chat",
        "_cli_backend_fallback_actions",
        "apply_cli_conversation_actions",
        "_confirmation_intent_for_preexisting_pending",
        "_apply_audience_command_verdict",
        "_recognize_audience_command_verdict",
        "_merge_staged_new_secret_order_content",
    ):
        setattr(s, name, MethodType(getattr(GameSession, name), s))


def _patch_secret_order_extract(monkeypatch, *, title: str) -> None:
    """#1565/0142：密令题名只认抽取器显式「标题」；测试灌入结构化 title，禁 [:14] 散文 oracle。"""
    import ming_sim.cli_backend as cb

    def _stub(
        player_command, minister_reply, default_assignee="", llm_config=None, **_kw,
    ):
        return {
            "title": title,
            "content": str(player_command or "").strip(),
            "assignee": default_assignee or "",
            "tags": [],
            "deadline_months": 0,
            "excluded_names": [],
            "excluded_offices": [],
            "dossier_links": [],
        }

    monkeypatch.setattr(cb, "_extract_secret_order", _stub)


def _assert_secret_order_pending(
    db, state, *, minister_name: str, pid: int, edict: str, title: str,
) -> None:
    assert pid > 0, f"密令须落入 pending 管线，got pending_action_id={pid}"
    row = next(
        (p for p in db.list_pending_actions(state.turn) if int(p["id"]) == pid),
        None,
    )
    assert row is not None
    assert row["kind"] == "secret_order"
    assert row["action"] == "新建"
    assert row["minister_name"] == minister_name
    assert row["status"] == "pending"
    payload = json.loads(row["payload_json"])
    assert payload["content"] == edict
    # 题名=显式结构化字段，非 content/edict 散文截取
    assert payload["title"] == title
    assert str(payload["title"]).strip()
    # extractor 未冻合同时仍须暂存；禁止 staging 合成 covert_task
    assert "covert_task" not in payload


def _secret_order_runtime(db, state, content, *, stream: bool):
    """hall 壳 + 密令 agent 一次装配（chat/stream 共用）。"""
    import web_app
    runtime = _web_hall_runtime(
        db, state, content,
        session_chat=lambda *_a, **_k: ChatTurnResult(answer="不应到达。"),
    )
    _install_secret_order_agent(runtime, stream=stream)
    runtime._start_chat_turn = web_app.WebGame._start_chat_turn.__get__(runtime)
    runtime._minister_agno_session_id = (
        web_app.WebGame._minister_agno_session_id.__get__(runtime)
    )
    return runtime


def _formal_secret_order_payload(runtime, minister_name, message, *, stream):
    if stream:
        events = list(runtime.chat_stream(minister_name, message, "secret_order"))
        types = [ev.get("type") for ev in events]
        assert "error" not in types, f"stream secret order errored: {events!r}"
        done_events = [ev for ev in events if ev.get("type") == "done"]
        assert done_events, f"expected done, got types={types!r}"
        return done_events[0].get("payload") or {}
    return runtime.chat(minister_name, message, "secret_order")


def _http_typed_secret_order_payload(client, minister_name, message, *, stream):
    """#1566：经真实 FastAPI POST 读出机面 payload（sync JSON / stream SSE done）。"""
    body = {"message": message, "intent": "secret_order"}
    path = (
        f"/api/ministers/{minister_name}/chat/stream"
        if stream
        else f"/api/ministers/{minister_name}/chat"
    )
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    if not stream:
        return response.json()
    events: list[tuple[str, dict]] = []
    for block in response.text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev_name = ""
        data_raw = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                ev_name = line[7:].strip()
            elif line.startswith("data: "):
                data_raw += line[6:]
        if ev_name and data_raw:
            events.append((ev_name, json.loads(data_raw)))
    assert not any(name == "error" for name, _ in events), f"stream errored: {events!r}"
    done = [data for name, data in events if name == "done"]
    assert done, f"expected done SSE, got {events!r}"
    return done[0]


@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_web_chat_formal_secret_order_hangs_night_without_enter(game, stream, monkeypatch):
    """#1566：场外正式密令挂当前夜轮，不 consume 传召、不入殿；

    summon+dismiss tool 与 typed 退朝均不得派 court_action / 换人 / exit / 留侍 / 收夜。
    """
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    before_summons = list(an.list_unsettled_summons(db))
    before_n = sum(
        1 for p in db.list_pending_actions(state.turn) if p.get("kind") == "secret_order"
    )

    secret_title = "陕北赈抚探报"
    _patch_secret_order_extract(monkeypatch, title=secret_title)
    runtime = _secret_order_runtime(db, state, content, stream=stream)
    old_pending_id = int(db.stage_pending_action(
        state.turn,
        "directive",
        "新建",
        remote.name,
        {"decree_text": "既存候选", "mode": "special_decree"},
    ))
    old_pending = next(
        p for p in db.list_pending_actions(state.turn)
        if int(p["id"]) == old_pending_id
    )
    edict = "陕北赈抚探报\n速报陕西军情。"
    payload = _formal_secret_order_payload(
        runtime, remote.name, edict,
        stream=stream,
    )
    assert not payload.get("admission"), (
        f"正式密令不得被 SUMMON_* admission 截获，got admission={payload.get('admission')!r}"
    )
    # #1566：密令 route 吞 court actions（agent 带 summon+dismiss）。
    assert not payload.get("court_action"), (
        f"密令不得派 court_action，got {payload.get('court_action')!r}"
    )
    assert not payload.get("next_minister"), (
        f"密令不得换人，got next_minister={payload.get('next_minister')!r}"
    )
    pid = int(payload.get("pending_action_id") or 0)
    _assert_secret_order_pending(
        db, state, minister_name=remote.name, pid=pid, edict=edict, title=secret_title,
    )
    assert an.list_unsettled_summons(db) == before_summons
    assert sum(
        1 for p in db.list_pending_actions(state.turn) if p.get("kind") == "secret_order"
    ) == before_n + 1
    after_pending = db.list_pending_actions(state.turn)
    assert next(
        p for p in after_pending if int(p["id"]) == old_pending_id
    ) == old_pending
    assert sum(p.get("kind") == "directive" for p in after_pending) == 1
    assert sum(p.get("kind") == "commitment" for p in after_pending) == 0
    chat_turn_id = int(payload.get("chat_turn_id") or 0)
    assert chat_turn_id > 0
    turn = db.conn.execute(
        "SELECT night_id, status, route FROM chat_turns WHERE id=?",
        (chat_turn_id,),
    ).fetchone()
    assert turn is not None
    assert int(turn["night_id"] or 0) > 0
    # 场外密令 route 须 durable 落 secret_order_offsite。
    assert str(turn["route"] or "") == "secret_order_offsite"
    scroll = an.read_night_scroll(db, int(turn["night_id"]))
    assert not any(
        m.get("beat") == "entrance" and m.get("speaker") == remote.name
        for m in scroll
    )
    owned = [m for m in scroll if int(m.get("chat_turn_id") or 0) == chat_turn_id]
    roles = {m.get("role") for m in owned}
    assert "user" in roles
    assert "minister" in roles

    # #1566：typed 退朝在密令 intent 下不得收夜/留侍/court_break。
    before_nights = db.conn.execute(
        "SELECT COUNT(*) AS c FROM audience_nights"
    ).fetchone()["c"]
    break_payload = _formal_secret_order_payload(
        runtime, remote.name, "退朝", stream=stream,
    )
    assert not break_payload.get("court_action"), (
        f"typed 退朝+密令 intent 不得 court_action，got {break_payload.get('court_action')!r}"
    )
    after_nights = db.conn.execute(
        "SELECT COUNT(*) AS c FROM audience_nights"
    ).fetchone()["c"]
    assert after_nights == before_nights
    open_night = an.get_open_night(db)
    assert open_night is not None
    assert str(open_night.get("status") or "") == "open"


@pytest.mark.parametrize("stream", [False, True], ids=["sync", "stream"])
def test_http_typed_secret_order_intent_forwards_to_webgame(game, stream, monkeypatch):
    """#1566：HTTP typed-intent 接缝——ChatRequest.intent 经真实 FastAPI 入口到 WebGame。

    场外大臣 + 无密令前缀正文；删 api_chat / api_chat_stream 的 request.intent 转发须转红
    （远人 SUMMON admission 截获，密令 pending 不落）。
    """
    import web_app

    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    secret_title = "陕北赈抚探报"
    _patch_secret_order_extract(monkeypatch, title=secret_title)
    runtime = _secret_order_runtime(db, state, content, stream=stream)
    monkeypatch.setattr(web_app, "get_game", lambda: runtime)
    monkeypatch.setattr(web_app, "web_game", runtime)

    # 无 _SECRET_PREFIXES 前缀：仅靠 JSON intent 入密令路（禁前缀自救掩盖转发洞）。
    edict = "陕北赈抚探报\n速报陕西军情。"
    payload = _http_typed_secret_order_payload(
        TestClient(web_app.app), remote.name, edict, stream=stream,
    )
    assert not payload.get("admission"), (
        f"typed intent 须走密令路，不得 SUMMON admission，got {payload!r}"
    )
    pid = int(payload.get("pending_action_id") or 0)
    _assert_secret_order_pending(
        db, state, minister_name=remote.name, pid=pid, edict=edict, title=secret_title,
    )


def test_web_chat_ledger_append_failure_has_no_side_effects(game, monkeypatch):
    """#670 T-C：故事账 append 失败 → 零 chat turn/消息、零殿账、零行止写、不调回话。"""
    db, state, content = game
    remote = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(
        game, "孙传庭", location="shaanxi", transit_to="henan", transit_start_turn=4,
    )
    remote_before = _travel_row(db, remote.name)
    moving_before = _travel_row(db, moving.name)
    an.open_night(db, state)  # 先开夜，使失败落在 summon recorder 而非 open_night
    before_msgs = _chat_message_count(db)
    before_turns = _chat_turn_count(db)
    chat_calls: list[str] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0, explicit_secret_order=False):
        chat_calls.append(minister_name)
        return ChatTurnResult(answer="不应到达。", pending_action_id=0, secret_order_id=0)

    runtime = _web_hall_runtime(db, state, content, session_chat=_session_chat)

    def boom(*_a, **_k):
        raise RuntimeError("injected ledger append failure")

    monkeypatch.setattr(an, "append_ledger_entry", boom)

    with pytest.raises(RuntimeError, match="injected ledger append failure"):
        runtime.chat(remote.name, "传洪承畴。")
    with pytest.raises(RuntimeError, match="injected ledger append failure"):
        runtime.chat(moving.name, "传孙传庭。")

    assert chat_calls == []
    assert an.list_unsettled_summons(db) == []
    assert _chat_message_count(db) == before_msgs
    assert _chat_turn_count(db) == before_turns
    assert _travel_row(db, remote.name) == remote_before
    assert _travel_row(db, moving.name) == moving_before


def test_summon_recorder_default_body_is_empty_and_tags_carry_facts(game):
    """#670 P7：传召账默认无固定玩家文案；机器事实只在 tags。"""
    db, state, _content = game
    night_id = int(an.open_night(db, state)["id"])
    fresh_id = an.record_summon_fresh(
        db, night_id, "洪承畴", origin_id="command:body-fresh",
    )
    transit_id = an.record_summon_in_transit(
        db, night_id, "孙传庭", origin_id="command:body-transit",
    )
    by_id = {int(e["id"]): e for e in an.list_ledger(db, night_id)}
    assert by_id[fresh_id]["body"] == ""
    assert by_id[transit_id]["body"] == ""
    assert an.TAG_SUMMON_UNSETTLED in by_id[fresh_id]["tags"]
    assert an.TAG_IN_TRANSIT in by_id[transit_id]["tags"]
    scroll = an.read_night_scroll(db, night_id)
    scene_text = "\n".join(str(row.get("body") or "") for row in scroll)
    assert "赴京候见" not in scene_text
    assert "在途未至" not in scene_text


def test_consume_open_night_and_recorder_share_one_transaction(game, monkeypatch):
    """#670：recorder 失败不得留下空 OPEN 夜或未结传召。"""
    db, state, _content = game
    sess = _session(game)
    sess.state = state
    remote = _set_place(game, "洪承畴", location="shaanxi")
    before_nights = int(
        db.conn.execute("SELECT COUNT(*) AS n FROM audience_nights").fetchone()["n"]
    )
    real_fresh = an.record_summon_fresh

    def boom(*_a, **_k):
        raise RuntimeError("injected summon recorder failure")

    monkeypatch.setattr(an, "record_summon_fresh", boom)
    with pytest.raises(RuntimeError, match="injected summon recorder failure"):
        sess.consume_audience_admission(
            remote, origin_id="web:atomic-1", state=state,
        )
    assert int(
        db.conn.execute("SELECT COUNT(*) AS n FROM audience_nights").fetchone()["n"]
    ) == before_nights
    assert an.list_unsettled_summons(db) == []
    assert an.get_open_night(db) is None

    # 成功路径：一夜一账
    monkeypatch.setattr(an, "record_summon_fresh", real_fresh)
    decision = sess.consume_audience_admission(
        remote, origin_id="web:atomic-ok", state=state,
    )
    assert decision.result is AudienceAdmission.SUMMON_FRESH
    night = an.get_open_night(db)
    assert night is not None
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    assert unsettled[0]["night_id"] == int(night["id"])
    assert unsettled[0]["origin_id"] == "web:atomic-ok"


def test_legacy_capital_aliases_admit_in_capital_and_migrate_on_reopen(game):
    """#670：旧档 京师/北京/beijing/北直隶 按 beizhili 在京；重开写回 canonical。"""
    db, state, content = game
    sess = _session(game)
    for alias in ("京师", "北京", "beijing", "北直隶"):
        person = _set_place(game, "毕自严", location=alias)
        decision = sess.admit_audience(person)
        assert decision.result is AudienceAdmission.IN_CAPITAL, alias
        assert decision.allowed is True
        assert decision.location == "beizhili"
        consumed = sess.consume_audience_admission(
            person, origin_id=f"web:alias:{alias}", state=state,
        )
        assert consumed.allowed is True
        assert an.list_unsettled_summons(db) == []

    _set_place(game, "毕自严", location="京师")
    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        row = restored.conn.execute(
            "SELECT location FROM characters WHERE name=?", ("毕自严",)
        ).fetchone()
        assert row["location"] == "beizhili"
        assert content.characters["毕自严"].location == "beizhili"
        rsess = GameSession.__new__(GameSession)
        rsess.db, rsess.content, rsess.temporary_characters = restored, content, {}
        assert rsess.admit_audience(content.characters["毕自严"]).result is (
            AudienceAdmission.IN_CAPITAL
        )
    finally:
        restored.close()


def test_direct_capital_arrival_does_not_queue_continuation(game):
    """#670：原目的/当前地已是 capital → waiting 投影、无续程、origin 待宣入。"""
    db, state, content = game
    sess = _session(game)
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:already-capital"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    assert an.list_arrived_unsettled_summons(db) == []
    payload = build_simulator_payload(state, db, "", "")
    assert payload["unsettled_arrived_summons"] == []
    waiting_fact = {
        "person_name": person.name,
        "origin_id": origin,
        "source_entry_id": entry_id,
        "location": "beizhili",
    }
    assert payload["waiting_audience"] == [waiting_fact]
    assert an.list_waiting_audience_summons(db) == [waiting_fact]
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    assert unsettled[0]["entry_id"] == entry_id
    assert unsettled[0]["kind"] == "waiting"

    # 宣入结清
    decision = sess.consume_audience_admission(
        person, origin_id="web:xuanru", state=state,
    )
    assert decision.allowed is True
    assert an.list_unsettled_summons(db) == []
    assert build_simulator_payload(state, db, "", "")["waiting_audience"] == []


def test_fresh_departure_arrival_and_capital_consume_lifecycle(game):
    """#670：fresh 收夜 → 抵京 waiting → 宣入结清。"""
    db, state, content = game
    sess = _session(game)
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:lifecycle-1"
    an.record_summon_fresh(db, night_id, person.name, origin_id=origin)
    an.close_night(db, state, night_id=night_id, content=content)

    after_depart = an.list_unsettled_summons(db)
    assert len(after_depart) == 1
    assert after_depart[0]["kind"] == "in_transit"
    assert after_depart[0]["origin_id"] == origin
    assert _travel_row(db, person.name)["transit_to"] == "beizhili"

    # 强制抵京 → 候见投影，不进续程
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
        "transit_speed_factor=NULL WHERE name=?",
        ("beizhili", person.name),
    )
    db.conn.commit()
    assert an.list_arrived_unsettled_summons(db) == []
    payload = build_simulator_payload(state, db, "", "")
    assert payload["unsettled_arrived_summons"] == []
    still = an.list_unsettled_summons(db)
    assert len(still) == 1 and still[0]["origin_id"] == origin
    assert still[0]["kind"] == "waiting"
    assert payload["waiting_audience"] == [{
        "person_name": person.name,
        "origin_id": origin,
        "source_entry_id": still[0]["entry_id"],
        "location": "beizhili",
    }]

    decision = sess.consume_audience_admission(
        person, origin_id="web:audience", state=state,
    )
    assert decision.result is AudienceAdmission.IN_CAPITAL
    assert decision.allowed is True
    assert an.list_unsettled_summons(db) == []
    assert build_simulator_payload(state, db, "", "")["waiting_audience"] == []


def test_continuation_arrival_settles_origin_without_waiting(game):
    """#670：抵非京 arrived → 续程 beizhili 成功即结清 origin，不再形成该 origin 候见。

    fresh→抵京→候见→宣入 独立路径由 test_fresh_departure_arrival_and_capital_consume_lifecycle
    与 test_direct_capital_arrival_does_not_queue_continuation 另钉。
    """
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    person = _set_place(
        game, "洪承畴", location="shaanxi", transit_to="henan", transit_start_turn=0,
    )
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:continue-wait-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    assert _arrive_at_destination(game, person.name) == [
        {"name": person.name, "location": "henan"}
    ]
    assert an.list_arrived_unsettled_summons(db) == [{
        "person_name": person.name,
        "original_destination": "henan",
        "origin_id": origin,
        "source_entry_id": entry_id,
        "required_fact": "抵原地后续赴京",
    }]

    settle_with_delta(
        state, db,
        {"人物变更": [{
            "name": person.name, "动作": "行止", "transit_to": "beizhili",
            "origin_ref": "盘面自发",
        }]},
        before_turn=int(state.turn), content=content,
    )
    assert _travel_row(db, person.name)["transit_to"] == "beizhili"
    assert an.list_unsettled_summons(db) == []
    assert an.list_arrived_unsettled_summons(db) == []

    # 即便再强制抵京，该 origin 已结清，不得复活为候见。
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
        "transit_speed_factor=NULL WHERE name=?",
        ("beizhili", person.name),
    )
    db.conn.commit()
    assert an.list_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []
    assert build_simulator_payload(state, db, "", "")["waiting_audience"] == []


def test_waiting_inactive_retires_on_month(game):
    """#670：候见中 dismiss → 月结 retire 结清。"""
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-inactive-1"
    an.record_summon_in_transit(db, night_id, person.name, origin_id=origin)
    assert an.list_unsettled_summons(db)[0]["kind"] == "waiting"

    db.set_character_status(state, person.name, "dismissed", reason="测试革职")
    assert an.list_arrived_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]
    # inactive 后 kind 不再 waiting（status 非 active），但仍未结直至月结 retire。
    assert an.list_unsettled_summons(db)[0]["kind"] == "in_transit"

    settle_with_delta(state, db, {}, before_turn=int(state.turn), content=content)
    assert an.list_unsettled_summons(db) == []


def test_waiting_active_departure_settles_and_does_not_revive(game):
    """#670：候见中 canonical 行止离京 → origin 结清；抵非京不再续赴京。"""
    from ming_sim.decree import settle_with_delta
    from ming_sim.issues import _apply_person_changes

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-leave-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    assert an.list_unsettled_summons(db) == [{
        "entry_id": entry_id,
        "night_id": night_id,
        "person_name": person.name,
        "origin_id": origin,
        "kind": "waiting",
    }]

    results = _apply_person_changes(
        db, state,
        [{
            "name": person.name, "动作": "行止", "transit_to": "shaanxi",
            "origin_ref": "盘面自发",
        }],
        content=content,
    )
    assert results and not results[0].get("rejected")
    assert _travel_row(db, person.name)["transit_to"] == "shaanxi"
    assert an.list_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []

    # 抵非京后不得复活「续赴京」
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
        "transit_speed_factor=NULL WHERE name=?",
        ("shaanxi", person.name),
    )
    db.conn.commit()
    assert an.list_arrived_unsettled_summons(db) == []
    assert build_simulator_payload(state, db, "", "")["unsettled_arrived_summons"] == []

    # 月结路径同源：再造候见后经 settle_with_delta 行止离京亦结清
    night_id2 = int(an.open_night(db, state)["id"])
    origin2 = "command:waiting-leave-2"
    _set_place(game, person.name, location="beizhili")
    an.record_summon_in_transit(db, night_id2, person.name, origin_id=origin2)
    settle_with_delta(
        state, db,
        {"人物变更": [{
            "name": person.name, "动作": "行止", "transit_to": "henan",
            "origin_ref": "盘面自发",
        }]},
        before_turn=int(state.turn), content=content,
    )
    assert an.list_unsettled_summons(db) == []


def test_waiting_active_departure_settle_failure_rolls_back_all_four_sides(
    game, monkeypatch,
):
    """#670：无外层事务时结清抛错 → 行止/person_log/故事账/内存镜像均恢复前像。"""
    from ming_sim import audience_night as an_mod
    from ming_sim.issues import _apply_person_changes

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-atomic-fail-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    before_travel = _travel_row(db, person.name)
    before_char = content.characters[person.name]
    before_mirror = {
        "location": getattr(before_char, "location", ""),
        "transit_to": getattr(before_char, "transit_to", ""),
        "transit_distance_remaining": getattr(
            before_char, "transit_distance_remaining", None,
        ),
        "transit_speed_factor": getattr(before_char, "transit_speed_factor", None),
        "transit_start_turn": getattr(before_char, "transit_start_turn", 0),
    }
    before_logs = int(
        db.conn.execute(
            "SELECT COUNT(*) AS n FROM person_logs WHERE person_name=?",
            (person.name,),
        ).fetchone()["n"]
    )
    before_tags = db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE id=?",
        (entry_id,),
    ).fetchone()["tags"]
    before_unsettled = an.list_unsettled_summons(db)

    def boom(*_a, **_k):
        raise RuntimeError("injected settle failure")

    monkeypatch.setattr(an_mod, "settle_unsettled_summons_for_person", boom)

    with pytest.raises(RuntimeError, match="injected settle failure"):
        _apply_person_changes(
            db, state,
            [{
                "name": person.name, "动作": "行止", "transit_to": "shaanxi",
                "origin_ref": "盘面自发",
            }],
            content=content,
        )

    assert _travel_row(db, person.name) == before_travel
    after_char = content.characters[person.name]
    assert {
        "location": getattr(after_char, "location", ""),
        "transit_to": getattr(after_char, "transit_to", ""),
        "transit_distance_remaining": getattr(
            after_char, "transit_distance_remaining", None,
        ),
        "transit_speed_factor": getattr(after_char, "transit_speed_factor", None),
        "transit_start_turn": getattr(after_char, "transit_start_turn", 0),
    } == before_mirror
    assert int(
        db.conn.execute(
            "SELECT COUNT(*) AS n FROM person_logs WHERE person_name=?",
            (person.name,),
        ).fetchone()["n"]
    ) == before_logs
    assert db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE id=?",
        (entry_id,),
    ).fetchone()["tags"] == before_tags
    assert an.list_unsettled_summons(db) == before_unsettled
    assert an.TAG_SUMMON_UNSETTLED in before_tags
    assert an.TAG_SUMMON_SETTLED not in before_tags


def test_waiting_active_departure_commits_transit_log_settle_and_mirror(game):
    """#670：无外层事务正常离京 → transit/person_log/结清 tags/内存镜像一并提交。"""
    from ming_sim.issues import _apply_person_changes

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    # 对齐内存镜像，避免 fixture 与 DB 前态漂移干扰断言。
    content.characters[person.name].location = "beizhili"
    content.characters[person.name].transit_to = ""
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-atomic-ok-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    before_logs = int(
        db.conn.execute(
            "SELECT COUNT(*) AS n FROM person_logs WHERE person_name=?",
            (person.name,),
        ).fetchone()["n"]
    )

    results = _apply_person_changes(
        db, state,
        [{
            "name": person.name, "动作": "行止", "transit_to": "shaanxi",
            "origin_ref": "盘面自发",
        }],
        content=content,
    )
    assert results and not results[0].get("rejected")

    travel = _travel_row(db, person.name)
    assert travel["transit_to"] == "shaanxi"
    assert travel["location"] == "beizhili"
    mirror = content.characters[person.name]
    assert getattr(mirror, "transit_to", "") == "shaanxi"
    assert getattr(mirror, "location", "") == "beizhili"
    assert int(
        db.conn.execute(
            "SELECT COUNT(*) AS n FROM person_logs WHERE person_name=?",
            (person.name,),
        ).fetchone()["n"]
    ) == before_logs + 1
    assert db.conn.execute(
        "SELECT 1 AS ok FROM person_logs WHERE person_name=? AND action=? LIMIT 1",
        (person.name, "行止"),
    ).fetchone() is not None
    tags = db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE id=?",
        (entry_id,),
    ).fetchone()["tags"]
    assert an.TAG_SUMMON_SETTLED in tags
    assert an.TAG_SUMMON_UNSETTLED not in tags
    assert an.list_unsettled_summons(db) == []


def test_waiting_active_departure_respects_strategic_preflight_savepoint(game):
    """#670：战略人物预检 SAVEPOINT 内离京不报错；ROLLBACK 后行止与召旨均原样。"""
    from ming_sim.issues import _apply_person_changes

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-preflight-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    before_travel = _travel_row(db, person.name)
    before_unsettled = an.list_unsettled_summons(db)
    assert before_unsettled == [{
        "entry_id": entry_id,
        "night_id": night_id,
        "person_name": person.name,
        "origin_id": origin,
        "kind": "waiting",
    }]

    db.conn.execute("BEGIN")
    db.conn.execute("SAVEPOINT strategic_person_result_preflight")
    results = _apply_person_changes(
        db, state,
        [{
            "name": person.name, "动作": "行止", "transit_to": "henan",
            "origin_ref": "盘面自发",
        }],
        content=content,
        external_transaction=True,
    )
    assert results and not results[0].get("rejected")
    # 预检内可见暂态写，但不得 durable commit 掉 SAVEPOINT。
    assert _travel_row(db, person.name)["transit_to"] == "henan"
    assert an.list_unsettled_summons(db) == []
    db.conn.execute("ROLLBACK TO SAVEPOINT strategic_person_result_preflight")
    db.conn.execute("RELEASE SAVEPOINT strategic_person_result_preflight")
    db.conn.rollback()

    assert _travel_row(db, person.name) == before_travel
    assert an.list_unsettled_summons(db) == before_unsettled
    assert an.list_waiting_audience_summons(db) == [{
        "person_name": person.name,
        "origin_id": origin,
        "source_entry_id": entry_id,
        "location": "beizhili",
    }]


def test_waiting_active_departure_external_rollback_reverts_transit_and_settle(game):
    """#670：显式外层事务 rollback 同时撤销行止与召旨结清。"""
    from ming_sim.issues import _apply_person_changes

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-ext-tx-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    before_travel = _travel_row(db, person.name)
    before_unsettled = an.list_unsettled_summons(db)

    db.conn.execute("BEGIN")
    results = _apply_person_changes(
        db, state,
        [{
            "name": person.name, "动作": "行止", "transit_to": "shaanxi",
            "origin_ref": "盘面自发",
        }],
        content=content,
        external_transaction=True,
    )
    assert results and not results[0].get("rejected")
    assert _travel_row(db, person.name)["transit_to"] == "shaanxi"
    assert an.list_unsettled_summons(db) == []
    db.conn.rollback()

    assert _travel_row(db, person.name) == before_travel
    assert an.list_unsettled_summons(db) == before_unsettled
    assert before_unsettled[0]["entry_id"] == entry_id


def test_waiting_projection_survives_restore(game):
    """#670：waiting 态关库重开，list_unsettled / payload 同形。"""
    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-restore-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    before_unsettled = an.list_unsettled_summons(db)
    before_waiting = an.list_waiting_audience_summons(db)
    before_payload = build_simulator_payload(state, db, "", "")["waiting_audience"]
    assert before_unsettled[0]["kind"] == "waiting"
    assert before_waiting == [{
        "person_name": person.name,
        "origin_id": origin,
        "source_entry_id": entry_id,
        "location": "beizhili",
    }]
    assert before_payload == before_waiting

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        assert an.list_unsettled_summons(restored) == before_unsettled
        assert an.list_waiting_audience_summons(restored) == before_waiting
        assert build_simulator_payload(
            state, restored, "", "",
        )["waiting_audience"] == before_payload
    finally:
        restored.close()


def test_non_capital_location_aliases_migrate_on_reopen(game):
    """#654 G / #670 merge B：非京精确别名重开时写回 canonical region_id。"""
    db, _state, content = game
    samples = {
        "洪承畴": ("南京", "nanzhili"),
        "孙传庭": ("江南", "nanzhili"),
        "曹文诏": ("西安", "shaanxi"),
        "卢象升": ("荆楚", "huguang"),
        "袁崇焕": ("闽地", "fujian"),
        "祖大寿": ("粤地", "guangdong"),
        "赵率教": ("桂地", "guangxi"),
    }
    for name, (alias, _canonical) in samples.items():
        _set_place(game, name, location=alias)

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        for name, (_alias, canonical) in samples.items():
            row = restored.conn.execute(
                "SELECT location FROM characters WHERE name=?", (name,)
            ).fetchone()
            assert row["location"] == canonical, name
            assert content.characters[name].location == canonical, name
    finally:
        restored.close()


def test_shuntian_zhili_aliases_migrate_on_reopen(game):
    """#654 G / #670 merge B：顺天/直隶 匹配为在京，重开写回 beizhili。"""
    from ming_sim.matching import is_capital_location

    # 匹配/在京判断仍认顺天/直隶（REGION_SPECIAL_ALIASES 保留）。
    assert is_capital_location("顺天") is True
    assert is_capital_location("直隶") is True

    db, _state, content = game
    samples = {"洪承畴": "顺天", "孙传庭": "直隶"}
    for name, alias in samples.items():
        _set_place(game, name, location=alias)

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        for name, _alias in samples.items():
            row = restored.conn.execute(
                "SELECT location FROM characters WHERE name=?", (name,)
            ).fetchone()
            assert row["location"] == "beizhili", name
            assert content.characters[name].location == "beizhili", name
    finally:
        restored.close()


def test_inactive_person_skips_continuation_and_retires_on_month(game):
    """#670：非 active 不投续程；月结退役结清 origin。"""
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    person = _set_place(
        game, "洪承畴", location="shaanxi", transit_to="henan", transit_start_turn=0,
    )
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:inactive-1"
    an.record_summon_in_transit(db, night_id, person.name, origin_id=origin)
    assert _arrive_at_destination(game, person.name) == [
        {"name": person.name, "location": "henan"}
    ]
    # ADR 0009：非 active 清 transit；此处直接标 dismissed 并清 transit。
    db.set_character_status(state, person.name, "dismissed", reason="测试革职")
    assert _travel_row(db, person.name)["transit_to"] == ""
    assert an.list_arrived_unsettled_summons(db) == []
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]

    settle_with_delta(state, db, {}, before_turn=int(state.turn), content=content)
    assert an.list_unsettled_summons(db) == []


def test_tool_summon_binds_origin_chat_turn_id_and_undo_deletes(game, monkeypatch):
    """#670：session tool 传召绑 origin_chat_turn_id；undo 删传召账；CLI 仍为 0。"""
    import ming_sim.session as session_mod

    db, state, content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    remote = _set_place(game, "洪承畴", location="shaanxi")
    _set_place(game, "孙传庭", location="shaanxi")

    class _Agent:
        def run(self, _message):
            return SimpleNamespace(
                content="臣请传洪承畴。",
                tools=[SimpleNamespace(
                    tool_name="summon_minister",
                    result=f"__summon__{remote.name}",
                    arguments={"name": remote.name},
                )],
            )

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.temporary_characters = {}
    sess.registry = SimpleNamespace(
        get=lambda _character: _Agent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="api")
    sess._retrieve_memories_for_message = lambda text: text
    sess._audience_prompt_for_message = lambda message, *a, **k: message
    sess._start_cli_action_intent = lambda *_a, **_k: None
    sess._finish_cli_action_intent = lambda *_a, **_k: None
    sess._recognize_audience_command_verdict = lambda *_a, **_k: None
    sess._apply_audience_command_verdict = lambda *a, **k: None
    sess._confirmation_intent_for_preexisting_pending = lambda *a, **k: None
    sess._scene_registry = SimpleNamespace(
        start_open_enter=lambda *a, **k: None,
        start_exit=lambda *a, **k: None,
        join=lambda *_a, **_k: [],
        abandon=lambda *_a, **_k: None,
    )
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)

    # 与生产 web 轮窗口同缝：先建 chat_turn，再把真实 id 传入 chat/tool。
    _night_id, chat_turn_id = an.attach_chat_turn_to_night(db, state, capital.name)
    result = sess.chat(capital.name, "传洪承畴来", chat_turn_id=int(chat_turn_id))
    assert not result.court_action
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    entry_id = int(unsettled[0]["entry_id"])
    row = db.conn.execute(
        "SELECT origin_chat_turn_id, body FROM story_ledger_entries WHERE id=?",
        (entry_id,),
    ).fetchone()
    assert int(row["origin_chat_turn_id"] or 0) == int(chat_turn_id)
    assert str(row["body"] or "") == ""

    # 失败轮 cleanup（generating 亦可）：按 origin_chat_turn_id 删传召账。
    db.fail_chat_turn(int(chat_turn_id))
    assert an.list_unsettled_summons(db) == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM story_ledger_entries WHERE id=?", (entry_id,)
    ).fetchone()["n"] == 0

    # 再跑一轮：回话落库升 active 后 undo 同样按 origin 删账。
    _night_id2, chat_turn_id2 = an.attach_chat_turn_to_night(db, state, capital.name)
    sess.chat(capital.name, "再请传洪承畴", chat_turn_id=int(chat_turn_id2))
    unsettled2 = an.list_unsettled_summons(db)
    assert len(unsettled2) == 1
    entry_id2 = int(unsettled2[0]["entry_id"])
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (capital.name, state.turn, "臣遵旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(int(chat_turn_id2), minister_message_id=int(mid))
    db.undo_chat_turn(int(chat_turn_id2))
    assert an.list_unsettled_summons(db) == []
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM story_ledger_entries WHERE id=?", (entry_id2,)
    ).fetchone()["n"] == 0

    # CLI 入口 origin_chat_turn_id 保持 0
    from ming_sim.cli import terminal

    notices: list[str] = []
    monkeypatch.setattr(
        "builtins.print", lambda *args, **_k: notices.append(" ".join(map(str, args))),
    )
    outcome = terminal._handle_court_command(sess, "传孙传庭来", capital)
    assert outcome == "handled"
    cli_rows = [
        row for row in an.list_unsettled_summons(db) if row["person_name"] == "孙传庭"
    ]
    assert len(cli_rows) == 1
    cli_entry = db.conn.execute(
        "SELECT origin_chat_turn_id FROM story_ledger_entries WHERE id=?",
        (int(cli_rows[0]["entry_id"]),),
    ).fetchone()
    assert int(cli_entry["origin_chat_turn_id"] or 0) == 0


def test_fresh_summon_same_beizhili_journey_attaches_origin_without_reapply(game):
    """#672/#670：真实 apply_dossier_verdicts 同人双 office origin 批内一次消费。

    两宗任命+传召经同一 verdicts 批激活后：durable 行止 person_log 恰一次，
    人物只赴 beizhili 一程，两个 origin 均投影为 in_transit。
    """
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    person.location = "shaanxi"
    person.transit_to = ""
    minister = next(
        ch.name for ch in content.characters.values()
        if db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
        and ch.name != person.name
    )
    night_id = int(an.open_night(db, state, empty_scaffold=True)["id"])
    pids: list[int] = []
    for office in ("三边总督", "蓟辽总督"):
        pid = int(db.stage_pending_action(
            int(state.turn), "office", "任命", minister,
            {"name": person.name, "office": office, "summon_after": "是"},
        ))
        an.ensure_inactive_office_summon(
            db, pid, person.name, night_id=night_id,
        )
        pids.append(pid)
    origins = {f"office:{pid}" for pid in pids}
    db.mark_pending_night_approved(pids, night_id=night_id)
    an.close_night(db, state, night_id=night_id, content=content)
    dossiers = [
        row for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) in set(pids)
    ]
    assert len(dossiers) == 2

    before_logs = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM person_logs "
        "WHERE person_name=? AND action=?",
        (person.name, "行止"),
    ).fetchone()["n"])

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": row["id"], "decision": "promulgated"} for row in dossiers],
        content=content,
    )

    after_logs = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM person_logs "
        "WHERE person_name=? AND action=?",
        (person.name, "行止"),
    ).fetchone()["n"])
    assert after_logs == before_logs + 1
    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,),
    ).fetchone()
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    mirror = content.characters[person.name]
    assert (getattr(mirror, "location", ""), getattr(mirror, "transit_to", "") or "") == (
        "shaanxi", "beizhili",
    )
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 2
    assert {row["kind"] for row in unsettled} == {"in_transit"}
    assert {row["origin_id"] for row in unsettled} == origins


def test_fresh_summon_omitted_content_syncs_db_and_rolls_back_together(game):
    """#672：省略 content 时 runtime_content 同步 DB/content；批内失败两侧同撤。"""
    db, state, content = game
    from ming_sim import issues
    issues.bind_content(content)  # 防他测漂移 _content；省略 content 路 →_ctx()

    # 成功路径：content 默认 None → runtime_content=_ctx() 与绑定 content 同步。
    solo = _set_place(game, "洪承畴", location="shaanxi")
    solo.location = "shaanxi"
    solo.transit_to = ""
    solo_night = int(an.open_night(db, state)["id"])
    an.record_summon_fresh(db, solo_night, solo.name, origin_id="command:omit-ok")
    origins = an.commit_fresh_summons_for_night(db, state, solo_night)
    assert origins == ["command:omit-ok"]
    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (solo.name,),
    ).fetchone()
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    assert (getattr(solo, "location", ""), getattr(solo, "transit_to", "") or "") == (
        "shaanxi", "beizhili",
    )
    an.close_night(db, state, night_id=solo_night, content=content)

    # 回滚路径：先写行止者成功、后写者异目的地在途拒 → 整批 DB/content 同撤。
    first = _set_place(game, "卢象升", location="shaanxi")
    first.location = "shaanxi"
    first.transit_to = ""
    second = _set_place(game, "孙传庭", location="henan", transit_to="shandong")
    second.location = "henan"
    second.transit_to = "shandong"

    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_fresh(db, night_id, first.name, origin_id="command:omit-a")
    an.record_summon_fresh(db, night_id, second.name, origin_id="command:omit-b")

    before_first = _travel_row(db, first.name)
    before_second = _travel_row(db, second.name)
    before_logs = int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM person_logs WHERE person_name=? AND action=?",
        (first.name, "行止"),
    ).fetchone()["n"])

    with pytest.raises(an.AudienceNightError, match="已在途赴 shandong") as ei:
        an.commit_fresh_summons_for_night(db, state, night_id)
    assert ei.value.code == "summon_departure_rejected"

    assert _travel_row(db, first.name) == before_first
    assert _travel_row(db, second.name) == before_second
    assert (getattr(first, "location", ""), getattr(first, "transit_to", "") or "") == (
        "shaanxi", "",
    )
    assert (getattr(second, "location", ""), getattr(second, "transit_to", "") or "") == (
        "henan", "shandong",
    )
    assert int(db.conn.execute(
        "SELECT COUNT(*) AS n FROM person_logs WHERE person_name=? AND action=?",
        (first.name, "行止"),
    ).fetchone()["n"]) == before_logs
    assert {
        (row["origin_id"], row["kind"]) for row in an.list_unsettled_summons(db)
        if row["origin_id"] in {"command:omit-a", "command:omit-b"}
    } == {("command:omit-a", "fresh"), ("command:omit-b", "fresh")}


def test_fresh_summon_rejects_different_destination_in_transit(game):
    """#672/#670：已在异目的地在途，fresh 启程仍拒。"""
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi", transit_to="henan")
    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_fresh(db, night_id, person.name, origin_id="office:diff-dest")
    with pytest.raises(an.AudienceNightError, match="已在途赴 henan") as ei:
        an.commit_fresh_summons_for_night(
            db, state, night_id, content=content, registry=None,
        )
    assert ei.value.code == "summon_departure_rejected"
    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,),
    ).fetchone()
    assert (after["location"], after["transit_to"]) == ("shaanxi", "henan")
    assert [row["kind"] for row in an.list_unsettled_summons(db)] == ["fresh"]
