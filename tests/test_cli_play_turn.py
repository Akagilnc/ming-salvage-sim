"""PR #90 R1 gemini medium——issue 分支拒绝后留在回合交互循环（continue 不 return）。

return 会退出 play_turn，外层主循环重进时重印回合引导/在册大臣=刷屏；skip 分支
已是 continue，issue 分支的 ValueError/SettlementAbort 拒绝应同语义：打印指引后
玩家留在同一循环里直接重试/改操作（rule#9：提示后能继续，不再撞同一错）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import ming_sim.cli.terminal as term
import ming_sim.issues as issues_mod
from ming_sim.exceptions import LLMContractError, LLMUnavailable, SettlementAbort
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.session import GameSession, TurnPhase
from ming_sim import audience_night as an
from tests.dossier_test_helpers import TYPED_COVERT_TASK
from tests.month_chain_helpers import make_light_session


def _prepare_play_turn(game, monkeypatch):
    db, state, content = game
    session = make_light_session(db, state, content)
    session.previous_summary = ""
    monkeypatch.setattr(term, "_print_header", lambda s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda _db: None)
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment",
        lambda *a, **k: {"effects": {}},
    )
    return session, db, state, content


def _hitl_ready(db, state):
    turn = int(state.turn)
    db.save_pending_decisions(turn, [{
        "title": "急务亲裁",
        "context": "辽东饷银案卷",
        "options": [{"label": "发饷", "hint": "拨银五万两"}],
    }])
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.save_resolve_context(
        turn, "测试诏书",
        {"candidate_events": [], "transit_semantics": []},
    )
    db.save_turn_report(state, "邸报已成")
    return turn


def _chat_rows(db):
    return list(db.conn.execute(
        "SELECT id, minister_name, turn, role, content FROM chat_messages ORDER BY id"
    ))


def _light_minister_session(db, state, content):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="api")
    sess.previous_summary = ""
    sess.schedule_pending_scene_translation = lambda result: None
    return sess


@pytest.mark.parametrize("exc", [
    ValueError("有 pending 拟旨待处理，请先处理再颁诏。"),
    SettlementAbort("本月结算失败，进度已保存，可重试。", turn=1, stage="extract"),
    LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_error"),
    LLMContractError("simulator 流式无内容且无终结事件"),
])
def test_issue_refusal_stays_in_loop(game, monkeypatch, exc):
    session, db, state, _content = _prepare_play_turn(game, monkeypatch)
    turn_before = _hitl_ready(db, state)
    real_resolve = session.resolve_turn

    def boom_then_real(*args, **kwargs):
        if boom_then_real.armed:
            boom_then_real.armed = False
            raise exc
        return real_resolve(*args, **kwargs)

    boom_then_real.armed = True
    session.resolve_turn = boom_then_real
    actions = iter(["issue", "skip"])
    monkeypatch.setattr(term, "review_directives", lambda _s: next(actions))

    term.play_turn(session)

    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING
    assert db.load_state().turn_phase == TurnPhase.SUMMONING.value


@pytest.mark.parametrize("action", ["issue", "skip"])
def test_cli_does_not_end_unadvanced_turn(game, monkeypatch, action):
    session, db, state, _content = _prepare_play_turn(game, monkeypatch)
    turn_before = _hitl_ready(db, state)
    target = "resolve_turn" if action == "issue" else "advance_without_decree"
    real = getattr(session, target)

    def first_unadvanced(*args, **kwargs):
        if first_unadvanced.armed:
            first_unadvanced.armed = False
            return SimpleNamespace(awaiting=False, advanced=False, decisions=[], report="")
        return real(*args, **kwargs)

    first_unadvanced.armed = True
    setattr(session, target, first_unadvanced)
    actions = iter([action, action])
    monkeypatch.setattr(term, "review_directives", lambda _s: next(actions))

    term.play_turn(session)

    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING
    assert db.load_state().turn_phase == TurnPhase.SUMMONING.value


def test_review_issue_reaches_staged_directive_default_approval(game, monkeypatch):
    """CLI issue 经真实 review_directives 入口回到 end-turn owner 信号。"""
    session, db, state, content = _prepare_play_turn(game, monkeypatch)
    minister = next(iter(content.characters.values())).name
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "cli-review", "actor": minister, "mode": "ordinary",
            "text": "陕西赈灾",
        },
    )
    state.turn_phase = TurnPhase.REVIEWING.value
    db.save_state(state)
    answers = iter(["issue"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.review_directives(session) == "issue"
    pending = [
        row for row in db.list_pending_actions(state.turn)
        if int(row.get("id") or 0) == pending_id
    ]
    assert pending
    assert pending[0]["status"] == "pending"


def test_terminal_minister_chat_persists_messages_before_session_chat(game, monkeypatch):
    """#407: CLI terminal 召对也要落 chat_messages。

    #1842：殿上走 scene_chat；user 行必须在调用前已落库，minister 行在回话后补上。
    """
    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    session = _light_minister_session(db, state, content)
    saw_user_before_reply = {}

    def scene_chat(question, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        rows = _chat_rows(db)
        saw_user_before_reply["user"] = [row for row in rows if row["role"] == "user"]
        saw_user_before_reply["minister"] = [row for row in rows if row["role"] == "minister"]
        return SimpleNamespace(
            answer="臣领密旨，当令东厂暗中护送赈银。",
            proposed_directive=None,
            appointed_minister="",
            registered_minister="",
            displaced_minister="",
            court_action="",
            next_minister="",
        )

    session.scene_chat = scene_chat
    answers = iter(["交给洪承畴督办陕西赈灾，东厂暗助护赈银。", "done"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(session, character) == "dismiss"
    assert saw_user_before_reply["user"]
    assert not saw_user_before_reply["minister"]
    rows = _chat_rows(db)
    assert any(row["role"] == "user" for row in rows)
    assert any(row["role"] == "minister" for row in rows)


def test_terminal_minister_chat_removes_user_message_when_session_chat_fails(game, monkeypatch):
    """失败的 CLI 召对只回滚本轮 user-only 半轮，不清历史。"""
    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    prior_id = db.append_chat_message(
        character.name, int(state.turn), "user", "前一轮召对内容",
    )
    session = _light_minister_session(db, state, content)

    def scene_chat(question, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        raise RuntimeError("LLM down")

    session.scene_chat = scene_chat
    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError):
        term.minister_chat(session, character)

    rows = _chat_rows(db)
    assert [int(row["id"]) for row in rows] == [prior_id]


def test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted(game, monkeypatch):
    """Ctrl-C 中断中的 CLI 召对也不能留下 user-only 半轮。"""
    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    prior_id = db.append_chat_message(
        character.name, int(state.turn), "user", "前一轮召对内容",
    )
    session = _light_minister_session(db, state, content)

    def scene_chat(question, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        raise KeyboardInterrupt()

    session.scene_chat = scene_chat
    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(KeyboardInterrupt):
        term.minister_chat(session, character)

    rows = _chat_rows(db)
    assert [int(row["id"]) for row in rows] == [prior_id]


def test_terminal_minister_chat_preserves_chat_error_when_rollback_fails(game, monkeypatch):
    """回滚删除失败不能盖掉原始 scene_chat/chat 异常。"""
    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    session = _light_minister_session(db, state, content)

    def scene_chat(question, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        raise RuntimeError("LLM down")

    session.scene_chat = scene_chat

    def boom_fail(chat_turn_id):
        raise RuntimeError("rollback failed")

    db.fail_chat_turn = boom_fail
    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError) as caught:
        term.minister_chat(session, character)
    assert str(caught.value) == "LLM down"


def test_terminal_minister_chat_reply_persist_failure_keeps_user_message(game, monkeypatch):
    """大臣已回话后，minister 行落库失败不误删已落 user 行。"""
    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    session = _light_minister_session(db, state, content)

    def scene_chat(question, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        return SimpleNamespace(
            answer="臣领密旨，当令东厂暗中护送赈银。",
            proposed_directive=None,
            appointed_minister="",
            registered_minister="",
            displaced_minister="",
            court_action="",
            next_minister="",
        )

    session.scene_chat = scene_chat

    def boom_persist(*_a, **_k):
        raise RuntimeError("reply persist failed")

    db.persist_minister_reply = boom_persist
    db.fail_chat_turn = lambda *_a, **_k: []
    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError):
        term.minister_chat(session, character)

    rows = _chat_rows(db)
    assert any(row["role"] == "user" for row in rows)
    assert not any(row["role"] == "minister" for row in rows)


def _stage_failed_secret_order(db, state, content):
    minister = next(iter(content.characters.values())).name
    action_id = db.stage_pending_action(
        state.turn, "secret_order", "新建", minister,
        {"title": "护行密令", "content": "护送旧案", "assignee": minister,
         "covert_task": TYPED_COVERT_TASK,
         "dossier_links": [
             {"target_dossier_id": 999999, "relation_type": "护卫", "note": "护送"}
         ]},
    )
    assert db.commit_pending_actions(state, action_ids=[action_id]) == []
    failed = db.list_pending_actions(state.turn, status="failed")
    assert any(int(row["id"]) == action_id and row.get("kind") == "secret_order" for row in failed)
    return action_id


@pytest.mark.parametrize("action", ["skip", "issue"])
def test_play_turn_reports_default_approval_secret_order_failure(game, monkeypatch, action):
    """#415: 退朝默认提交密令失败时，CLI 也必须给出失败 id。"""
    session, db, state, content = _prepare_play_turn(game, monkeypatch)
    action_id = _stage_failed_secret_order(db, state, content)
    turn_before = _hitl_ready(db, state)
    monkeypatch.setattr(term, "review_directives", lambda _s: action)

    term.play_turn(session)

    failed = db.list_pending_actions(turn_before, status="failed")
    assert any(int(row["id"]) == action_id and row.get("kind") == "secret_order" for row in failed)
    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING


def test_play_turn_skip_prints_dossier_settlement_report_and_ends_turn(game, monkeypatch):
    session, db, state, _content = _prepare_play_turn(game, monkeypatch)
    turn_before = _hitl_ready(db, state)
    monkeypatch.setattr(term, "review_directives", lambda _s: "skip")

    term.play_turn(session)

    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING
    assert db.load_state().turn_phase == TurnPhase.SUMMONING.value


@pytest.mark.parametrize("exc", [
    SettlementAbort("退朝结算中止，可重试。", turn=7, stage="settle"),
    LLMContractError("simulator 流式无内容且无终结事件"),
])
def test_play_turn_skip_settlement_abort_stays_in_player_loop(game, monkeypatch, exc):
    session, db, state, _content = _prepare_play_turn(game, monkeypatch)
    turn_before = _hitl_ready(db, state)
    real_advance = session.advance_without_decree

    def boom_then_real(*args, **kwargs):
        if boom_then_real.armed:
            boom_then_real.armed = False
            raise exc
        return real_advance(*args, **kwargs)

    boom_then_real.armed = True
    session.advance_without_decree = boom_then_real
    actions = iter(["skip", "skip"])
    monkeypatch.setattr(term, "review_directives", lambda _s: next(actions))

    term.play_turn(session)

    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING


def test_play_turn_reports_secret_order_failure_when_settlement_aborts(game, monkeypatch):
    """pre_settle 已标 failed 后若后续结算中止，CLI 仍须显示失败 id。"""
    session, db, state, content = _prepare_play_turn(game, monkeypatch)
    action_id = _stage_failed_secret_order(db, state, content)
    turn_before = _hitl_ready(db, state)
    real_resolve = session.resolve_turn

    def boom_then_real(*args, **kwargs):
        if boom_then_real.armed:
            boom_then_real.armed = False
            raise SettlementAbort("结算中止，可重试。", turn=int(state.turn), stage="extract")
        return real_resolve(*args, **kwargs)

    boom_then_real.armed = True
    session.resolve_turn = boom_then_real
    actions = iter(["issue", "skip"])
    monkeypatch.setattr(term, "review_directives", lambda _s: next(actions))

    term.play_turn(session)

    failed = db.list_pending_actions(turn_before, status="failed")
    assert any(int(row["id"]) == action_id and row.get("kind") == "secret_order" for row in failed)
    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_terminal_minister_chat_accepts_retry_reply_command(game, monkeypatch):
    """#1716 CLI：minister_chat「重试回话」成功收夜后返回 court_break，关夜且无 presence。

    入口仍是 minister_chat 的重试命令；不重记问话既有契约一并覆盖。
    """
    import types

    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    night_id = int(night["id"])
    # 中断轮问话为收夜口令——retry 再生后 court_action=court_break。
    question = "退朝"
    ct = db.create_chat_turn(
        state, character.name, f"cli:{character.name}", 0,
        night_id=night_id, status="generating",
    )
    mid = db.append_chat_message(character.name, state.turn, "user", question)
    db.update_chat_turn_messages(ct, user_message_id=mid)
    db.conn.execute("UPDATE chat_turns SET status='interrupted' WHERE id=?", (ct,))
    db.conn.commit()

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="api")

    sess.registry = SimpleNamespace(
        get=lambda _ch, **_kw: SimpleNamespace(
            run=lambda *_a, **_k: SimpleNamespace(content="臣遵旨。", tools=[]),
        ),
        session_ids={},
    )
    sess._audience_prompt_for_message = lambda msg, character=None, chat_turn_id=0, **_kw: msg
    sess.close_night_after_chat_if_needed = types.MethodType(
        GameSession.close_night_after_chat_if_needed, sess,
    )

    # #1842：殿上/场外重试走 scene_chat；标转译水位以免收夜被假 pending 挡住。
    def _scene_chat(message, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        assert chat_turn_id == ct
        assert message == question
        return SimpleNamespace(answer="臣遵旨。", court_action="court_break")

    sess.scene_chat = _scene_chat  # type: ignore[method-assign]
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done' WHERE id=?",
        (ct,),
    )
    db.conn.commit()

    answers = iter(["重试回话"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(sess, character) == "court_break"

    row = db.conn.execute(
        "SELECT status, minister_message_id FROM chat_turns WHERE id=?", (ct,),
    ).fetchone()
    assert row["status"] == "active"
    assert row["minister_message_id"]

    # #1842：回话返回后后台 schedule 封夜；等外部可见 CLOSED（禁假定同步）。
    from tests.wait_utils import wait_until

    wait_until(lambda: an.get_open_night(db) is None)
    night_row = db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert night_row is not None
    assert str(night_row["status"]) == an.NIGHT_STATUS_CLOSED
    # 场外收夜：该人不得入殿 presence/entrance。
    assert character.name not in an.persons_present_tonight(db, night_id)
    assert character.name not in an.persons_entered_tonight(db, night_id)




@pytest.mark.parametrize("action", ["skip", "issue"])
def test_play_turn_hitl_advancement_ends_turn(game, monkeypatch, action):
    """#1843/PR #1876: HITL 续跑实际推进月份后，play_turn 必须调用 end_turn 并结束本回合。"""
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    turn_before = int(state.turn)
    db.save_pending_decisions(turn_before, [{
        "title": "急务亲裁",
        "context": "辽东饷银案卷",
        "options": [{"label": "发饷", "hint": "拨银五万两"}],
    }])
    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    db.save_resolve_context(
        turn_before, "测试诏书",
        {"candidate_events": [], "transit_semantics": []},
    )
    db.save_turn_report(state, "邸报已成")

    session = make_light_session(db, state, content)

    # 中和外部 LLM 边界，推演主链与亲裁续跑全走真实逻辑
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr("ming_sim.month_translate.translate_month_segment", lambda *a, **k: {"effects": {}})

    # 单次操作迭代器：未正确 end_turn + return 时若重入交互循环，next 会抛 StopIteration
    actions = iter([action])
    monkeypatch.setattr(term, "review_directives", lambda _s: next(actions))
    monkeypatch.setattr(term, "_print_header", lambda _s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda _db: None)

    term.play_turn(session)

    # 验证月份已真实推进，且 end_turn 已被调用将 turn_phase 重置为 summoning
    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING
    assert db.load_state().turn_phase == TurnPhase.SUMMONING.value
