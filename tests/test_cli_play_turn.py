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


def _cli_schedule_pending_noop(self, result):
    """#1842：CLI persist 尾必调 schedule_pending_scene_translation；轻壳无 pending 时 no-op。"""
    return None


class _Snap:
    deaths_this_turn = []


class _Sess:
    """play_turn 所需最小协作面：begin/phase/resolve/advance/end + 调用录音。"""
    previous_summary = ""

    def __init__(self, fail_exc):
        self.calls = []
        self._fail = fail_exc
        self.db = None
        self.state = SimpleNamespace(turn=1)

    def begin_turn(self):
        self.calls.append("begin")
        return _Snap()

    def current_phase(self):
        return TurnPhase.SETTLING  # 非 SUMMONING → 直接走 review_directives

    def resolve_turn(self):
        self.calls.append("resolve")
        raise self._fail

    def advance_without_decree(self):
        self.calls.append("advance")

    def end_turn(self):
        self.calls.append("end")



def _active_character(content):
    return next(c for c in content.characters.values() if c.status == "active")


def _cli_minister_session(game, *, scene_chat):
    """真实 GameDB + 开夜；只替 scene 协作面，不复制持久化/回滚。"""
    db, state, content = game
    character = _active_character(content)
    an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess.scene_chat = scene_chat  # type: ignore[method-assign]
    sess.schedule_pending_scene_translation = (  # type: ignore[method-assign]
        lambda result: _cli_schedule_pending_noop(sess, result)
    )
    return sess, character, db, state


def _chat_rows(db, minister_name: str):
    rows = db.conn.execute(
        "SELECT role, content FROM chat_messages WHERE minister_name=? ORDER BY id",
        (minister_name,),
    ).fetchall()
    return [(str(r["role"]), str(r["content"])) for r in rows]


@pytest.mark.parametrize("exc", [
    ValueError("有 pending 拟旨待处理，请先处理再颁诏。"),
    SettlementAbort("本月结算失败，进度已保存，可重试。", turn=1, stage="extract"),
    # 现役 LLM 通路的失败与结算中止同形——留本回合可重按。
    LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="llm_error"),
    # #1700：空 simulator 的 LLMContractError 同形，issue catch 扩员后留本回合。
    LLMContractError("simulator 流式无内容且无终结事件"),
])
def test_issue_refusal_stays_in_loop(monkeypatch, capsys, exc):
    sess = _Sess(exc)
    actions = iter(["issue", "skip"])
    monkeypatch.setattr(term, "review_directives", lambda s: next(actions))
    monkeypatch.setattr(term, "_print_header", lambda s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda db: None)

    term.play_turn(sess)

    # 拒绝后不 return：同一次 play_turn 内续到 skip→advance；begin 只跑一次=不重进刷屏。
    assert sess.calls == ["begin", "resolve", "advance"]
    assert str(exc) in capsys.readouterr().out


@pytest.mark.parametrize("action", ["issue", "skip"])
def test_cli_does_not_end_unadvanced_turn(monkeypatch, action):
    class Session(_Sess):
        def __init__(self):
            super().__init__(None)
            self.step = 0

        def resolve_turn(self):
            self.calls.append("resolve")
            advanced = self.step > 0
            self.step += 1
            if advanced:
                self.state.turn += 1
            return SimpleNamespace(advanced=advanced, report="", awaiting=False)

        def advance_without_decree(self):
            self.calls.append("advance")
            advanced = self.step > 0
            self.step += 1
            if advanced:
                self.state.turn += 1
            return SimpleNamespace(advanced=advanced, report="", awaiting=False)

    sess = Session()
    actions = iter([action, action])
    monkeypatch.setattr(term, "review_directives", lambda _s: next(actions))
    monkeypatch.setattr(term, "_print_header", lambda _s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda _db: None)

    term.play_turn(sess)

    call_name = "resolve" if action == "issue" else "advance"
    # 未推进时留在本回合交互循环不调 end_turn，再次推进后才调 end_turn 退出
    assert sess.calls == ["begin", call_name, call_name, "end"]


def test_review_issue_reaches_staged_directive_default_approval(monkeypatch):
    """CLI issue reaches the end-turn owner without reviving decree preview/review."""

    class Session:
        def __init__(self):
            self.db = SimpleNamespace(
                dossiers=SimpleNamespace(
                    list_pending_actions=lambda turn, status=None: [
                        {"kind": "directive", "status": "pending"}
                    ],
                ),
            )
            self.state = SimpleNamespace(turn=1, turn_phase=TurnPhase.REVIEWING.value)
            self.calls = []

        def enter_review(self):
            self.calls.append("enter_review")

        def list_directives(self, include_pending=False):
            return []


    answers = iter(["issue"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    session = Session()

    assert term.review_directives(session) == "issue"
    assert session.calls == ["enter_review"]



def test_terminal_minister_chat_persists_messages_before_session_chat(game, monkeypatch):
    """#407: CLI terminal 召对也要落 chat_messages（真实 GameDB，不复制持久化）。"""

    seen_before_scene: list[list[tuple[str, str]]] = []

    def scene_chat(question, *, chat_turn_id=0, stream_emit=None, minister_name=""):
        seen_before_scene.append(_chat_rows(sess.db, character.name))
        return SimpleNamespace(
            answer="臣领密旨，当令东厂暗中护送赈银。",
            proposed_directive=None,
            appointed_minister="",
            registered_minister="",
            displaced_minister="",
            court_action="",
            next_minister="",
        )

    sess, character, db, _state = _cli_minister_session(game, scene_chat=scene_chat)
    question = "交给洪承畴督办陕西赈灾，东厂暗助护赈银。"
    answers = iter([question, "done"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(sess, character) == "dismiss"
    assert seen_before_scene == [[("user", question)]]
    assert _chat_rows(db, character.name) == [
        ("user", question),
        ("minister", "臣领密旨，当令东厂暗中护送赈银。"),
    ]


def test_terminal_minister_chat_removes_user_message_when_session_chat_fails(game, monkeypatch):
    """失败的 CLI 召对只回滚本轮 user-only 半轮，不清历史（真实 fail_chat_turn）。"""

    chat_error = RuntimeError("LLM down")
    sess, character, db, state = _cli_minister_session(
        game,
        scene_chat=lambda *a, **k: (_ for _ in ()).throw(chat_error),
    )
    prior = "前一轮召对内容"
    db.chat_messages.insert(
        minister_name=character.name,
        turn=max(1, int(state.turn) - 1),
        role="user",
        content=prior,
    )
    db.conn.commit()
    question = "命洪承畴督办陕西赈灾，东厂暗助护赈银。"
    answers = iter([question])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError) as ei:
        term.minister_chat(sess, character)
    assert ei.value is chat_error

    assert _chat_rows(db, character.name) == [("user", prior)]


def test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted(game, monkeypatch):
    """Ctrl-C 中断中的 CLI 召对也不能留下 user-only 半轮（真实 fail_chat_turn）。"""

    sess, character, db, state = _cli_minister_session(
        game,
        scene_chat=lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    prior = "前一轮召对内容"
    db.chat_messages.insert(
        minister_name=character.name,
        turn=max(1, int(state.turn) - 1),
        role="user",
        content=prior,
    )
    db.conn.commit()
    question = "命洪承畴督办陕西赈灾，东厂暗助护赈银。"
    answers = iter([question])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(KeyboardInterrupt):
        term.minister_chat(sess, character)

    assert _chat_rows(db, character.name) == [("user", prior)]


def test_terminal_minister_chat_preserves_chat_error_when_rollback_fails(game, monkeypatch):
    """回滚删除失败不能盖掉原始 scene_chat/chat 异常。"""
    chat_error = RuntimeError("LLM down")
    rollback_error = RuntimeError("rollback failed")

    sess, character, db, _state = _cli_minister_session(
        game,
        scene_chat=lambda *a, **k: (_ for _ in ()).throw(chat_error),
    )

    def boom_fail(_chat_turn_id):
        raise rollback_error

    monkeypatch.setattr(db, "fail_chat_turn", boom_fail)
    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    # 原故障对象保真：注入异常对象作期望（非散落硬编码措辞）。
    with pytest.raises(RuntimeError) as ei:
        term.minister_chat(sess, character)
    assert ei.value is chat_error
    assert ei.value.__cause__ is rollback_error


def test_terminal_minister_chat_reply_persist_failure_uses_fail_chat_turn(game, monkeypatch):
    """大臣已回话后 minister 落库失败走真实 fail_chat_turn，不走无轮 delete。"""

    fail_calls: list[int] = []
    persist_error = RuntimeError("reply persist failed")

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

    sess, character, db, _state = _cli_minister_session(game, scene_chat=scene_chat)

    def boom_persist(*_a, **_k):
        raise persist_error

    real_fail = db.fail_chat_turn

    def tracking_fail(chat_turn_id):
        fail_calls.append(int(chat_turn_id))
        return real_fail(chat_turn_id)

    monkeypatch.setattr(db, "persist_minister_reply", boom_persist)
    monkeypatch.setattr(db, "fail_chat_turn", tracking_fail)
    monkeypatch.setattr(
        db,
        "delete_chat_messages",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("chat_turn_id 已立时不得走无轮 delete_chat_messages")
        ),
    )
    question = "命洪承畴督办陕西赈灾，东厂暗助护赈银。"
    answers = iter([question])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError) as ei:
        term.minister_chat(sess, character)
    assert ei.value is persist_error

    assert fail_calls and fail_calls[0] > 0
    assert _chat_rows(db, character.name) == []


def test_play_turn_skip_prints_dossier_settlement_report_and_ends_turn(monkeypatch, capsys):
    session = _Sess(RuntimeError("unused"))
    session.current_phase = lambda: TurnPhase.REVIEWING
    session.advance_without_decree = lambda: SimpleNamespace(
        awaiting=False, advanced=True, report="留中案卷本月重判月报",
    )
    monkeypatch.setattr(term, "review_directives", lambda _s: "skip")
    monkeypatch.setattr(term, "_print_header", lambda _s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda _db: None)

    term.play_turn(session)

    assert "留中案卷本月重判月报" in capsys.readouterr().out
    assert session.calls == ["begin", "end"]


@pytest.mark.parametrize("exc", [
    SettlementAbort("退朝结算中止，可重试。", turn=7, stage="settle"),
    # #1700：skip catch 同形纳入 LLMContractError；同 turn 再 skip 成功。
    LLMContractError("simulator 流式无内容且无终结事件"),
])
def test_play_turn_skip_settlement_abort_stays_in_player_loop(monkeypatch, capsys, exc):
    class Session:
        previous_summary = ""

        def __init__(self):
            self.db = SimpleNamespace(
                dossiers=SimpleNamespace(list_pending_actions=lambda *a, **k: []),
            )
            self.state = SimpleNamespace(turn=7)
            self.calls = []

        def begin_turn(self):
            self.calls.append("begin")
            return _Snap()

        def current_phase(self):
            return TurnPhase.REVIEWING

        def advance_without_decree(self):
            self.calls.append("advance")
            if self.calls.count("advance") == 1:
                raise exc
            return None

    actions = iter(["skip", "skip"])
    monkeypatch.setattr(term, "review_directives", lambda s: next(actions))
    monkeypatch.setattr(term, "_print_header", lambda s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda db: None)
    session = Session()

    term.play_turn(session)

    assert str(exc) in capsys.readouterr().out
    assert session.calls == ["begin", "advance", "advance"]
