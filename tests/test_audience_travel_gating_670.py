"""#670 召对 travel-gating 的公开 admission 与 fresh seed 契约。"""

from __future__ import annotations

import asyncio
from types import MethodType, SimpleNamespace

import pytest
from fastapi import HTTPException

from ming_sim.db import GameDB
from ming_sim.session import AudienceAdmission, ChatTurnResult, GameSession
from ming_sim import audience_night as an
from ming_sim.decree import force_transit_arrivals
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


def _web_hall_runtime(db, state, content, *, session_chat):
    """#670：常规 Web.chat（gate_already_held=False）殿上入口壳；挂真 admission。"""
    from tests.test_qa_c3_secret_order_path_1357_1376 import (
        webgame_shell_for_secret_order,
    )

    runtime = webgame_shell_for_secret_order(
        db, state, content, session_chat=session_chat,
    )
    runtime.session.admit_audience = MethodType(
        GameSession.admit_audience, runtime.session,
    )
    runtime.session.consume_audience_admission = MethodType(
        GameSession.consume_audience_admission, runtime.session,
    )
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
    assert force_transit_arrivals(db, state, content) == [
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

    # 续赴京并抵京 → waiting 每人 1 条；再结清最后 origin 后清空。
    from ming_sim.decree import settle_with_delta

    settle_with_delta(
        state, db,
        {"人物变更": [{
            "name": person.name, "动作": "行止", "transit_to": "beizhili",
            "origin_ref": "盘面自发",
        }]},
        before_turn=int(state.turn), content=content,
    )
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
        "transit_speed_factor=NULL WHERE name=?",
        ("beizhili", person.name),
    )
    db.conn.commit()
    waiting = an.list_waiting_audience_summons(db)
    assert waiting == [{
        "person_name": person.name,
        "origin_id": origin_tool,
        "source_entry_id": second_entry["entry_id"],
        "location": "beizhili",
    }]
    assert build_simulator_payload(state, db, "", "")["waiting_audience"] == waiting
    # 再补一个同人 waiting origin，投影仍只 1 条；结清其一后另一仍在。
    night = an.get_open_night(db) or an.open_night(db, state)
    extra_origin = "web:chat:9"
    extra_id = an.record_summon_in_transit(
        db, int(night["id"]), person.name, origin_id=extra_origin,
    )
    waiting_two = an.list_waiting_audience_summons(db)
    assert len(an.list_unsettled_summons(db)) == 2
    assert waiting_two == [{
        "person_name": person.name,
        "origin_id": origin_tool,
        "source_entry_id": second_entry["entry_id"],
        "location": "beizhili",
    }]
    assert an.settle_summon_origin(db, origin_tool) is True
    assert an.list_waiting_audience_summons(db) == [{
        "person_name": person.name,
        "origin_id": extra_origin,
        "source_entry_id": extra_id,
        "location": "beizhili",
    }]
    assert an.settle_summon_origin(db, extra_origin) is True
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
    real_apply = issues.apply_score_extraction
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected canonical applier failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(issues, "apply_score_extraction", fail_once)

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
       行止仍 henan/空 transit。
    3. 续启成功月：canonical 行止更新，但 origin **仍未结**（结清只在宣入/非 active）。
    三段均禁止手推 turn、禁止手调结清 helper。
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

    assert force_transit_arrivals(db, state, content) == [
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

    # 续启成功月：行止更新但 origin 保持未结，直至抵京+宣入。
    settle_with_delta(
        state, db, continuation, before_turn=int(state.turn), content=content,
    )
    unsettled = an.list_unsettled_summons(db)
    assert [row["origin_id"] for row in unsettled] == [origin]
    assert unsettled[0]["kind"] == "in_transit"
    after = _travel_row(db, person.name)
    assert after["location"] == "henan"
    assert after["transit_to"] == "beizhili"
    # 在途赴京期间不得再投「抵原地后续赴京」。
    assert build_simulator_payload(state, db, "", "")["unsettled_arrived_summons"] == []
    assert attempts == 3


def test_fresh_seed_closes_ticket_670_named_locations(content):
    expected = {
        **{name: "beizhili" for name in "韩爌 张瑞图 来宗道 施凤来 黄立极 王绍徽 毕自严 郭允厚 杨嗣昌 温体仁 钱龙锡 刘鸿训 钱谦益 李标 孙承宗 崔呈秀 王在晋 徐光启 徐应秋 袁可立 周延儒 倪元璐 黄道周 曹化淳 王体乾 王承恩 魏忠贤 田尔耕 许显纯 李若琏 客氏 周皇后 周贵人 田贵妃 袁贵妃 慧妃 懿安皇后 高起潜 孙元化 许誉卿 乔允升 韩一良".split()},
        "袁崇焕": "guangdong",
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

    def _session_chat(minister_name, message, *, chat_turn_id=0):
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
    """#670 T2：同人多通道 origin 收夜只一段启程；applier 失败后同输入可重试。"""
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi")
    night_id = int(an.open_night(db, state)["id"])

    first = an.record_summon_fresh(
        db, night_id, person.name, origin_id="web:chat:1:洪承畴",
    )
    second = an.record_summon_fresh(
        db, night_id, person.name, origin_id="cli:initial:1:洪承畴",
    )
    assert second == first
    assert an.list_unsettled_summons(db) == [{
        "entry_id": first,
        "night_id": night_id,
        "person_name": person.name,
        "origin_id": "web:chat:1:洪承畴",
        "kind": "fresh",
    }]

    # 历史已落的双 origin 未结账：按人 apply 一次后全部标在途，origin 仍未结。
    an.append_ledger_entry(
        db, night_id,
        person_names=[person.name],
        audibility=an.AUDIBILITY_PUBLIC,
        body="",
        tags=[
            an.METHOD_CHUANZHAO,
            an.TAG_SUMMON_UNSETTLED,
            an._summon_origin_tag("cli:initial:1:洪承畴"),
        ],
    )
    assert len(an.list_unsettled_summons(db)) == 2

    from ming_sim import issues
    real_apply = issues.apply_score_extraction
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected multi-origin applier failure")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(issues, "apply_score_extraction", fail_once)
    with pytest.raises(RuntimeError, match="injected multi-origin applier failure"):
        an.close_night(db, state, night_id=night_id, content=content)

    assert len(an.list_unsettled_summons(db)) == 2
    failed = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert (failed["location"], failed["transit_to"]) == ("shaanxi", "")

    result = an.close_night(db, state, night_id=night_id, content=content)
    after = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (person.name,)
    ).fetchone()
    assert result["closed"] is True
    assert (after["location"], after["transit_to"]) == ("shaanxi", "beizhili")
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 2
    assert {row["kind"] for row in unsettled} == {"in_transit"}
    assert {row["origin_id"] for row in unsettled} == {
        "web:chat:1:洪承畴", "cli:initial:1:洪承畴",
    }
    # apply 一次（失败）+ 一次（成功）；不得按 origin 二次 apply。
    assert attempts == 2


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
        for row in an.list_unsettled_summons(db)
    )

    # web stream tool 路：复用既有 _chat_stream_payload 真入口夹具。
    for row in list(an.list_unsettled_summons(db)):
        an.settle_summon_origin(db, row["origin_id"])
    agent = _FakeAgent(
        tools=[ToolExec("summon_minister", f"__summon__{remote.name}")],
        chunks=[model_answer],
    )
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
        lambda character, *, origin_id, state=None, origin_chat_turn_id=0: (
            GameSession.consume_audience_admission(
                web_game.session, character, origin_id=origin_id,
                state=state or web_game.session.state,
                origin_chat_turn_id=origin_chat_turn_id,
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
        for row in an.list_unsettled_summons(db)
    )


def test_web_chat_hall_admission_allows_capital_and_blocks_offsite(game):
    """#670 T-A：Web.chat 真入口——blank/beizhili 即时开殿；场外/在途 409 且不调回话。"""
    db, state, content = game
    capital = _set_place(game, "毕自严", location="beizhili")
    remote = _set_place(game, "洪承畴", location="shaanxi")
    moving = _set_place(
        game, "孙传庭", location="shaanxi", transit_to="henan", transit_start_turn=2,
    )
    moving_before = _travel_row(db, moving.name)
    chat_calls: list[str] = []

    def _session_chat(minister_name, message, *, chat_turn_id=0):
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
    with pytest.raises(HTTPException) as remote_exc:
        runtime.chat(remote.name, "传洪承畴来。")
    assert remote_exc.value.status_code == 409
    # 成功记召 detail 只带结构化枚举，无固定承旨中文。
    assert remote_exc.value.detail == AudienceAdmission.SUMMON_FRESH.value
    assert "赴京" not in str(remote_exc.value.detail)
    assert "不能入殿" not in str(remote_exc.value.detail)
    assert chat_calls == [capital.name, capital.name]

    with pytest.raises(HTTPException) as moving_exc:
        runtime.chat(moving.name, "传孙传庭来。")
    assert moving_exc.value.status_code == 409
    assert moving_exc.value.detail == AudienceAdmission.SUMMON_IN_TRANSIT.value
    assert "在途" not in str(moving_exc.value.detail)
    assert "不能入殿" not in str(moving_exc.value.detail)
    assert chat_calls == [capital.name, capital.name]
    assert _chat_message_count(db) == allowed_msgs
    assert _travel_row(db, moving.name) == moving_before

    by_origin = {row["origin_id"]: row for row in an.list_unsettled_summons(db)}
    assert by_origin[f"web:chat:{state.turn}:{remote.name}"]["kind"] == "fresh"
    assert by_origin[f"web:chat:{state.turn}:{moving.name}"]["kind"] == "in_transit"


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

    def _session_chat(minister_name, message, *, chat_turn_id=0):
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


def test_continuation_arrival_projects_waiting_then_consume(game):
    """#670：抵非京 arrived → 续程 beizhili → 再抵京 waiting → 宣入结清。"""
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    sess = _session(game)
    person = _set_place(
        game, "洪承畴", location="shaanxi", transit_to="henan", transit_start_turn=0,
    )
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:continue-wait-1"
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id=origin,
    )
    assert force_transit_arrivals(db, state, content) == [
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
    assert an.list_unsettled_summons(db)[0]["kind"] == "in_transit"

    db.conn.execute(
        "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
        "transit_speed_factor=NULL WHERE name=?",
        ("beizhili", person.name),
    )
    db.conn.commit()
    waiting = an.list_unsettled_summons(db)
    assert len(waiting) == 1
    assert waiting[0]["kind"] == "waiting"
    assert waiting[0]["origin_id"] == origin
    assert an.list_arrived_unsettled_summons(db) == []
    assert build_simulator_payload(state, db, "", "")["waiting_audience"] == [{
        "person_name": person.name,
        "origin_id": origin,
        "source_entry_id": entry_id,
        "location": "beizhili",
    }]

    decision = sess.consume_audience_admission(
        person, origin_id="web:continue-xuanru", state=state,
    )
    assert decision.allowed is True
    assert an.list_unsettled_summons(db) == []


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


def test_non_capital_location_aliases_are_not_migrated_on_reopen(game):
    """#670：非京旧档 location 不被 capital alias 迁移改写。"""
    db, _state, content = game
    samples = {
        "洪承畴": "南京",
        "孙传庭": "江南",
        "曹文诏": "西安",
        "卢象升": "荆楚",
        "袁崇焕": "闽地",
        "祖大寿": "粤地",
        "赵率教": "桂地",
    }
    for name, alias in samples.items():
        _set_place(game, name, location=alias)

    path = db.path
    db.close()
    restored = GameDB(path, content)
    try:
        for name, alias in samples.items():
            row = restored.conn.execute(
                "SELECT location FROM characters WHERE name=?", (name,)
            ).fetchone()
            # 旧档值原样保留；迁移不得批量改写非京 alias。
            assert row["location"] == alias, name
    finally:
        restored.close()


def test_shuntian_zhili_aliases_are_not_migrated_on_reopen(game):
    """#670：顺天/直隶 可作匹配别名，但旧档 location 迁移不得写回。"""
    from ming_sim.matching import is_capital_location, location_alias_rewrites

    assert location_alias_rewrites() == [
        ("京师", "beizhili"),
        ("北京", "beizhili"),
        ("beijing", "beizhili"),
        ("北直隶", "beizhili"),
    ]
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
        for name, alias in samples.items():
            row = restored.conn.execute(
                "SELECT location FROM characters WHERE name=?", (name,)
            ).fetchone()
            assert row["location"] == alias, name
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
    assert force_transit_arrivals(db, state, content) == [
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
