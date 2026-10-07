"""#670 召对 travel-gating 的公开 admission 与 fresh seed 契约。"""

from __future__ import annotations
from tests.conftest import open_hall_turn

import pytest
from ming_sim.db import GameDB
from ming_sim.session import AudienceAdmission, GameSession
from ming_sim import audience_night as an


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
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    monkeypatch.setattr("builtins.print", lambda *_a, **_k: None)

    assert terminal.choose_minister(sess) is None
    # 结构化：未入殿大臣记入未结传召；不扫 print 承旨措辞（P7 禁模板负向≠合法盯文）。
    assert [(row["person_name"], row["origin_id"]) for row in an.list_unsettled_summons(db)] == [
        ("洪承畴", f"cli:initial:{state.turn}:洪承畴"),
    ]


def test_cli_initial_selection_rejects_unknown_unregistered_person(game, monkeypatch):
    """#670：CLI 初选未知人物不得临时旁路入殿，须 ADR 0038 持久入册后再 admission。"""
    from ming_sim.cli import terminal

    sess = _session(game)
    db, state, _content = game
    sess.state = state
    unknown = "乌有先生甲"
    assert unknown not in sess.content.characters
    answers = iter([unknown, "quit"])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))
    monkeypatch.setattr("builtins.print", lambda *_a, **_k: None)

    assert terminal.choose_minister(sess) is None
    assert unknown not in sess.temporary_characters
    assert an.list_unsettled_summons(db) == []
    assert _chat_turn_count(db) == 0
    assert _chat_message_count(db) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM characters WHERE name=?", (unknown,),
    ).fetchone()["n"] == 0


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


def test_multi_origin_same_person_dedupes_consumer_projections_not_ledger(game, monkeypatch):
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
    assert first.reason == "" and second.reason == ""

    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 2
    assert {row["origin_id"] for row in unsettled} == {origin_chat, origin_tool}

    # 抵非京后 ledger 仍 2 行（旧 arrived 盘面投影已退役）。
    assert _arrive_at_destination(game, person.name) == [
        {"name": person.name, "location": "henan"},
    ]
    assert len(an.list_unsettled_summons(db)) == 2

    # 结清其一 origin 后另一仍未结，投影仍 1 人份。
    assert an.settle_summon_origin(db, origin_chat) is True
    remaining = an.list_unsettled_summons(db)
    assert [row["origin_id"] for row in remaining] == [origin_tool]

    # 续赴京成功 → 同人全部 in_transit origin 结清（含尚未手结的 origin_tool）。
    from tests.test_month_chain_1843 import _prepare_player_month

    session = _prepare_player_month(
        db, state, content, monkeypatch, world=lambda *_a, **_k: "世界段",
        translate=lambda *_a, **_k: {"effects": {"人物变更": [{
            "name": person.name, "动作": "行止", "transit_to": "beizhili",
            "origin_ref": "盘面自发",
        }]}},
    )
    session.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    session.resolve_turn(allow_empty_decree=True)
    assert an.list_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []

    # waiting 消费端 dedupe：直接 capital 在途账（不依赖续程后残留 origin）。
    # 续程过月已调度机械尾，尾巴与本段写同一连接。open_night 的 SAVEPOINT
    # 必须整段留在该 session 的写闸内，否则尾巴 COMMIT 会清掉保存点栈。
    from ming_sim.session_write_queue import get_session_write_queue

    def plant_waiting_dedupe():
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

    get_session_write_queue(session).run_exclusive(plant_waiting_dedupe)


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
    except RuntimeError:
        pass
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
    """#670 T-D：失败、无续启、续启的三个玩家过月边界均保留召对事实。"""
    from tests.test_month_chain_1843 import _prepare_player_month
    from tests.test_due_review_621 import _settle_empty_month

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
    assert _travel_row(db, person.name)["location"] == "henan"
    assert _travel_row(db, person.name)["transit_to"] == ""

    import ming_sim.issues as issues_mod
    real_apply = issues_mod.apply_score_extraction
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

    # 落账经 declaration_dispatch → issues.apply_score_extraction。
    monkeypatch.setattr(issues_mod, "apply_score_extraction", fail_once)

    def advance_continuation():
        session = _prepare_player_month(
            db, state, content, monkeypatch, world=lambda *_a, **_k: "世界段",
            translate=lambda *_a, **_k: {"effects": continuation},
        )
        session.resolve_turn(allow_empty_decree=True)
        db.save_turn_report(state, "邸报", public_body="邸报")
        session.resolve_turn(allow_empty_decree=True)

    failed_turn = int(state.turn)
    from ming_sim.exceptions import SettlementAbort
    with pytest.raises(SettlementAbort) as excinfo:
        advance_continuation()
    assert isinstance(excinfo.value.__cause__, RuntimeError)

    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]
    assert _travel_row(db, person.name)["location"] == "henan"
    assert _travel_row(db, person.name)["transit_to"] == ""
    assert int(state.turn) == failed_turn

    # 无续启成功月：玩家入口推进一月；不得手推 turn / 手调结清。
    noop_turn = int(state.turn)
    _settle_empty_month(db, state, content, monkeypatch)
    assert int(state.turn) == noop_turn + 1
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]
    assert _travel_row(db, person.name)["location"] == "henan"
    assert _travel_row(db, person.name)["transit_to"] == ""

    # 续启成功月：只经玩家过月；结清证明不得手调 helper。
    advance_continuation()
    assert an.list_unsettled_summons(db) == []
    after = _travel_row(db, person.name)
    assert after["location"] == "henan"
    assert after["transit_to"] == "beizhili"


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
    with pytest.raises(RuntimeError):
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
    _n1, turn_a = open_hall_turn(db, state, "毕自严")
    _n2, turn_b = open_hall_turn(db, state, "毕自严")
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

    # 两轮都存活时收夜得到同一个持久行止。
    entry_a2 = an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_a,
    )
    entry_b2 = an.record_summon_fresh(
        db, night_id, person.name, origin_id=origin_b,
    )
    assert entry_a2 != entry_b2
    departures_before = db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=? AND action='行止'",
        (person.name,),
    ).fetchone()[0]
    result = an.close_night(db, state, night_id=night_id, content=content)
    assert result["closed"] is True
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=? AND action='行止'",
        (person.name,),
    ).fetchone()[0] == departures_before + 1
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
    monkeypatch.setattr("builtins.print", lambda *_a, **_k: None)

    outcome = terminal._handle_court_command(sess, "传洪承畴来", current)

    assert outcome == "handled"
    # 结构化：handled + 未结传召 origin；不扫 print 承旨措辞。
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [
        f"cli:midflow:{state.turn}:洪承畴",
    ]


def test_cli_midflow_summon_rejects_unknown_unregistered_person(game):
    """#670：CLI 夜内换人未知人物不得 summon-temp 旁路，须 ADR 0038 持久入册后再 admission。"""
    from ming_sim.cli import terminal

    sess = _session(game)
    db, state, _content = game
    sess.state = state
    current = _set_place(game, "毕自严", location="beizhili")
    unknown = "乌有先生乙"
    assert unknown not in sess.content.characters

    outcome = terminal._handle_court_command(sess, f"传{unknown}来", current)

    assert outcome == "handled"
    assert unknown not in sess.temporary_characters
    assert an.list_unsettled_summons(db) == []
    assert _chat_turn_count(db) == 0
    assert _chat_message_count(db) == 0
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM characters WHERE name=?", (unknown,),
    ).fetchone()["n"] == 0





















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
    assert not any(row.get("record_id") in {fresh_id, transit_id} for row in scroll)


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
    with pytest.raises(RuntimeError):
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


def test_capital_aliases_admit_in_capital(game):
    """#670：京师/北京/beijing/北直隶 经 canonicalize 按 beizhili 在京（读时归一，非旧档写回）。"""
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








def test_continuation_arrival_settles_origin_without_waiting(game, monkeypatch):
    """#670：抵非京 arrived → 续程 beizhili 成功即结清 origin，不再形成该 origin 候见。

    fresh→抵京→候见→宣入 独立路径由 test_fresh_departure_arrival_and_capital_consume_lifecycle
    与 test_direct_capital_arrival_does_not_queue_continuation 另钉。
    """
    from tests.test_month_chain_1843 import _prepare_player_month

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

    session = _prepare_player_month(
        db, state, content, monkeypatch, world=lambda *_a, **_k: "世界段",
        translate=lambda *_a, **_k: {"effects": {"人物变更": [{
            "name": person.name, "动作": "行止", "transit_to": "beizhili",
            "origin_ref": "盘面自发",
        }]}},
    )
    session.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    session.resolve_turn(allow_empty_decree=True)
    assert _travel_row(db, person.name)["transit_to"] == "beizhili"
    assert an.list_unsettled_summons(db) == []

    # 即便再强制抵京，该 origin 已结清，不得复活为候见。
    # 与上一处相同：推进后的写走本次过月 session 的写闸，不与机械尾交错。
    from ming_sim.session_write_queue import get_session_write_queue

    def force_arrived_capital():
        db.conn.execute(
            "UPDATE characters SET location=?, transit_to='', transit_distance_remaining=NULL, "
            "transit_speed_factor=NULL WHERE name=?",
            ("beizhili", person.name),
        )
        db.conn.commit()

    get_session_write_queue(session).run_exclusive(force_arrived_capital)
    assert an.list_unsettled_summons(db) == []
    assert an.list_waiting_audience_summons(db) == []


def test_waiting_inactive_retires_on_month(game, monkeypatch):
    """#670：候见中 dismiss → 玩家过月 retire 结清。"""
    from tests.test_due_review_621 import _settle_empty_month

    db, state, content = game
    person = _set_place(game, "洪承畴", location="beizhili")
    night_id = int(an.open_night(db, state)["id"])
    origin = "command:waiting-inactive-1"
    an.record_summon_in_transit(db, night_id, person.name, origin_id=origin)
    assert an.list_unsettled_summons(db)[0]["kind"] == "waiting"

    db.set_character_status(state, person.name, "dismissed", reason="测试革职")
    assert an.list_waiting_audience_summons(db) == []
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]
    # inactive 后 kind 不再 waiting（status 非 active），但仍未结直至月结 retire。
    assert an.list_unsettled_summons(db)[0]["kind"] == "in_transit"

    _settle_empty_month(db, state, content, monkeypatch)
    assert an.list_unsettled_summons(db) == []


def test_waiting_active_departure_settles_and_does_not_revive(game):
    """#670：候见中 canonical 行止离京 → origin 结清；抵非京不再续赴京。"""
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

    with pytest.raises(RuntimeError):
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








def test_inactive_person_skips_continuation_and_retires_on_month(game, monkeypatch):
    """#670：非 active 不投续程；玩家过月退役结清 origin。"""
    from tests.test_due_review_621 import _settle_empty_month

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
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [origin]

    _settle_empty_month(db, state, content, monkeypatch)
    assert an.list_unsettled_summons(db) == []




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

    with pytest.raises(an.AudienceNightError) as ei:
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
