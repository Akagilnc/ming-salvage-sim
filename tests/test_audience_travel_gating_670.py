"""#670 召对 travel-gating 的公开 admission 与 fresh seed 契约。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ming_sim.session import AudienceAdmission, ChatTurnResult, GameSession
from ming_sim import audience_night as an
from ming_sim.decree import force_transit_arrivals
from ming_sim.simulation import build_simulator_payload


def _session(game):
    db, _state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db, sess.content, sess.temporary_characters = db, content, {}
    return sess


def _set_place(game, name, *, location, transit_to=""):
    db, _state, content = game
    db.conn.execute(
        "UPDATE characters SET location=?, transit_to=? WHERE name=?",
        (location, transit_to, name),
    )
    db.conn.commit()
    return content.characters[name]


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
    assert any("赴京" in line and "不能入殿" in line for line in notices)


def test_in_transit_summon_origin_is_idempotent_and_restorable(game):
    db, state, _content = game
    night_id = int(an.open_night(db, state)["id"])

    first = an.record_summon_in_transit(
        db, night_id, "洪承畴", origin_id="command:42",
    )
    again = an.record_summon_in_transit(
        db, night_id, "洪承畴", origin_id="command:42",
    )

    assert again == first
    assert an.list_unsettled_summons(db) == [{
        "entry_id": first,
        "night_id": night_id,
        "person_name": "洪承畴",
        "origin_id": "command:42",
        "kind": "in_transit",
    }]
    # The projection is rebuilt exclusively from the durable story ledger.
    assert an.list_unsettled_summons(db) == an.list_unsettled_summons(db)

    assert an.settle_summon_origin(db, "command:42") is True
    assert an.settle_summon_origin(db, "command:42") is False
    assert an.list_unsettled_summons(db) == []


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
    assert an.list_unsettled_summons(db) == []

    # Closed-night replay is a no-op and cannot reset the canonical departure clock.
    started = db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (person.name,)
    ).fetchone()["transit_start_turn"]
    assert an.close_night(db, state, night_id=night_id, content=content)["already"] is True
    assert db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (person.name,)
    ).fetchone()["transit_start_turn"] == started


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
    assert an.list_unsettled_summons(db) == []


def test_monthly_judge_receives_arrived_unsettled_summon_facts(game):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="shaanxi", transit_to="henan")
    db.conn.execute(
        "UPDATE characters SET transit_start_turn=0 WHERE name=?", (person.name,)
    )
    db.conn.commit()
    night_id = int(an.open_night(db, state)["id"])
    entry_id = an.record_summon_in_transit(
        db, night_id, person.name, origin_id="command:arrived-1",
    )

    assert force_transit_arrivals(db, state, content) == [
        {"name": person.name, "location": "henan"}
    ]
    payload = build_simulator_payload(state, db, "", "")

    assert payload["unsettled_arrived_summons"] == [{
        "person_name": person.name,
        "original_destination": "henan",
        "origin_id": "command:arrived-1",
        "source_entry_id": entry_id,
        "required_fact": "抵原地后续赴京",
    }]


def test_arrived_summon_settles_only_after_canonical_applier_success(game):
    db, state, content = game
    person = _set_place(game, "洪承畴", location="henan")
    night_id = int(an.open_night(db, state)["id"])
    an.record_summon_in_transit(
        db, night_id, person.name, origin_id="command:continue-1",
    )

    # Judge/extractor failure (no accepted person change) preserves the durable retry.
    assert an.settle_applied_arrived_summons(db, {}) == []
    assert [row["origin_id"] for row in an.list_unsettled_summons(db)] == [
        "command:continue-1"
    ]

    from ming_sim.issues import apply_score_extraction
    applied = apply_score_extraction(db, state, {"人物变更": [{
        "name": person.name, "动作": "行止", "transit_to": "beizhili",
        "origin_ref": "盘面自发",
    }]}, content=content)

    assert an.settle_applied_arrived_summons(db, applied) == ["command:continue-1"]
    assert an.list_unsettled_summons(db) == []
    assert an.settle_applied_arrived_summons(db, applied) == []


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
        lambda character, *, origin_id, state=None: GameSession.consume_audience_admission(
            runtime.session, character, origin_id=origin_id, state=state or runtime.session.state,
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

    # 历史已落的双 origin 未结账：按人 apply 一次并结清全部 origin。
    an.append_ledger_entry(
        db, night_id,
        person_names=[person.name],
        audibility=an.AUDIBILITY_PUBLIC,
        body=f"传召{person.name}赴京候见。",
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
    assert an.list_unsettled_summons(db) == []
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
    assert any("赴京" in line and "不能入殿" in line for line in notices)
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
        lambda character, *, origin_id, state=None: GameSession.consume_audience_admission(
            web_game.session, character, origin_id=origin_id,
            state=state or web_game.session.state,
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
