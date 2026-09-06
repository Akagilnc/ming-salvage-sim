"""PR #90 R1 gemini medium——issue 分支拒绝后留在回合交互循环（continue 不 return）。

return 会退出 play_turn，外层主循环重进时重印回合引导/在册大臣=刷屏；skip 分支
已是 continue，issue 分支的 ValueError/SettlementAbort 拒绝应同语义：打印指引后
玩家留在同一循环里直接重试/改操作（rule#9：提示后能继续，不再撞同一错）。
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import ming_sim.cli.terminal as term
import ming_sim.issues as issues_mod
from ming_sim.exceptions import LLMContractError, LLMUnavailable, SettlementAbort
from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE
from ming_sim.session import GameSession, TurnPhase
from ming_sim import audience_night as an


@contextmanager
def _noop_atomic(_db):
    yield


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


@pytest.mark.parametrize("exc", [
    ValueError("有 pending 拟旨待处理，请先处理再颁诏。"),
    SettlementAbort("本月结算失败，进度已保存，可重试。", turn=1, stage="extract"),
    # #1353 fold-in r8：统一重试耗尽的 LLMUnavailable 与结算中止同形——留本回合可重按。
    LLMUnavailable(CLI_RUNNER_PLAYER_MESSAGE, code="pending_extraction"),
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


def test_review_issue_reaches_staged_directive_default_approval(monkeypatch):
    """CLI issue reaches the end-turn owner without reviving decree preview/review."""

    class Db:
        def list_pending_actions(self, turn):
            return [{"kind": "directive", "status": "pending"}]

    class Session:
        def __init__(self):
            self.db = Db()
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


def test_terminal_minister_chat_persists_messages_before_session_chat(monkeypatch):
    """#407: CLI terminal 召对也要落 chat_messages。

    密令短确认依赖 session.chat 内部读取本回合前文；因此 user 行必须在调用
    session.chat 前已落库，minister 行在回话后补上。
    """

    class Db:
        def __init__(self):
            self.messages = []

        def append_chat_message(self, minister_name, turn, role, content):
            self.messages.append((minister_name, turn, role, content))
            return len(self.messages)

    class Session:
        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.content = SimpleNamespace(characters={"魏忠贤": object(), "韩爌": object()})
            self.temporary_characters = set()

        def chat(self, minister_name, question, *, chat_turn_id=0, explicit_secret_order=False):
            assert self.db.messages == [
                ("魏忠贤", 7, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银。")
            ]
            return SimpleNamespace(
                answer="臣领密旨，当令东厂暗中护送赈银。",
                proposed_directive=None,
                appointed_minister="",
                registered_minister="",
                displaced_minister="",
                court_action="",
                next_minister="",
            )

    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。", "done"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    session = Session()

    assert term.minister_chat(session, SimpleNamespace(name="魏忠贤")) == "dismiss"
    assert session.db.messages == [
        ("魏忠贤", 7, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银。"),
        ("魏忠贤", 7, "minister", "臣领密旨，当令东厂暗中护送赈银。"),
    ]


def test_terminal_minister_chat_removes_user_message_when_session_chat_fails(monkeypatch):
    """失败的 CLI 召对只回滚本轮 user-only 半轮，不清历史。"""

    class Db:
        def __init__(self):
            self.messages = [
                ("魏忠贤", 6, "user", "前一轮召对内容"),
            ]

        def append_chat_message(self, minister_name, turn, role, content):
            self.messages.append((minister_name, turn, role, content))
            return len(self.messages)

        def delete_chat_messages(self, message_ids):
            doomed = {int(mid) for mid in message_ids}
            self.messages = [
                msg for idx, msg in enumerate(self.messages, 1)
                if idx not in doomed
            ]

    class Session:
        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.content = SimpleNamespace(characters={"魏忠贤": object(), "韩爌": object()})
            self.temporary_characters = set()

        def chat(self, minister_name, question, *, chat_turn_id=0, explicit_secret_order=False):
            assert self.db.messages == [
                ("魏忠贤", 6, "user", "前一轮召对内容"),
                ("魏忠贤", 7, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银。"),
            ]
            raise RuntimeError("LLM down")

    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    session = Session()

    with pytest.raises(RuntimeError, match="LLM down"):
        term.minister_chat(session, SimpleNamespace(name="魏忠贤"))

    assert session.db.messages == [
        ("魏忠贤", 6, "user", "前一轮召对内容"),
    ]


def test_terminal_minister_chat_removes_user_message_when_session_chat_interrupted(monkeypatch):
    """Ctrl-C 中断中的 CLI 召对也不能留下 user-only 半轮。"""

    class Db:
        def __init__(self):
            self.messages = [
                ("魏忠贤", 6, "user", "前一轮召对内容"),
            ]

        def append_chat_message(self, minister_name, turn, role, content):
            self.messages.append((minister_name, turn, role, content))
            return len(self.messages)

        def delete_chat_messages(self, message_ids):
            doomed = {int(mid) for mid in message_ids}
            self.messages = [
                msg for idx, msg in enumerate(self.messages, 1)
                if idx not in doomed
            ]

    class Session:
        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.content = SimpleNamespace(characters={"魏忠贤": object(), "韩爌": object()})
            self.temporary_characters = set()

        def chat(self, minister_name, question, *, chat_turn_id=0, explicit_secret_order=False):
            assert self.db.messages == [
                ("魏忠贤", 6, "user", "前一轮召对内容"),
                ("魏忠贤", 7, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银。"),
            ]
            raise KeyboardInterrupt()

    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    session = Session()

    with pytest.raises(KeyboardInterrupt):
        term.minister_chat(session, SimpleNamespace(name="魏忠贤"))

    assert session.db.messages == [
        ("魏忠贤", 6, "user", "前一轮召对内容"),
    ]


def test_terminal_minister_chat_preserves_chat_error_when_rollback_fails(monkeypatch):
    """回滚删除失败不能盖掉原始 session.chat 异常。"""

    class Db:
        def append_chat_message(self, minister_name, turn, role, content):
            return 1

        def delete_chat_messages(self, message_ids):
            raise RuntimeError("rollback failed")

    class Session:
        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.content = SimpleNamespace(characters={"魏忠贤": object(), "韩爌": object()})
            self.temporary_characters = set()

        def chat(self, minister_name, question, *, chat_turn_id=0, explicit_secret_order=False):
            raise RuntimeError("LLM down")

    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError, match="LLM down"):
        term.minister_chat(Session(), SimpleNamespace(name="魏忠贤"))


def test_terminal_minister_chat_reply_persist_failure_keeps_user_message(monkeypatch):
    """大臣已回话后，minister 行落库失败不误删已落 user 行。"""

    class Db:
        def __init__(self):
            self.messages = []
            self.deleted = False

        def append_chat_message(self, minister_name, turn, role, content):
            if role == "minister":
                raise RuntimeError("reply persist failed")
            self.messages.append((minister_name, turn, role, content))
            return len(self.messages)

        def delete_chat_messages(self, message_ids):
            self.deleted = True

    class Session:
        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.content = SimpleNamespace(characters={"魏忠贤": object(), "韩爌": object()})
            self.temporary_characters = set()

        def chat(self, minister_name, question, *, chat_turn_id=0, explicit_secret_order=False):
            return SimpleNamespace(
                answer="臣领密旨，当令东厂暗中护送赈银。",
                proposed_directive=None,
                appointed_minister="",
                registered_minister="",
                displaced_minister="",
                court_action="",
                next_minister="",
            )

    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    session = Session()

    with pytest.raises(RuntimeError, match="reply persist failed"):
        term.minister_chat(session, SimpleNamespace(name="魏忠贤"))

    assert session.db.deleted is False
    assert session.db.messages == [
        ("魏忠贤", 7, "user", "命洪承畴督办陕西赈灾，东厂暗助护赈银。"),
    ]


def test_terminal_persistent_chat_finalization_failure_rolls_back_real_turn(game, monkeypatch):
    db, state, content = game
    character = next(c for c in content.characters.values() if c.status == "active")
    marker = "真实 CLI lifecycle 写失败不得留下半轮"
    real_append = db.append_chat_message

    def fail_minister_write(name, turn, role, body, *args, **kwargs):
        if role == "minister":
            raise RuntimeError("finalization write failed")
        return real_append(name, turn, role, body, *args, **kwargs)

    def fail_minister_persist(name, turn, body, chat_turn_id, *args, **kwargs):
        # #542：有 join_chat_turn_scene 时 finalization 走 persist_minister_reply，
        # 与 append_chat_message(minister) 同为回话落盘缝。
        raise RuntimeError("finalization write failed")

    monkeypatch.setattr(db, "append_chat_message", fail_minister_write)
    monkeypatch.setattr(db, "persist_minister_reply", fail_minister_persist)
    answers = iter([marker])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    received_chat_turn_ids = []

    def chat(_name, _question, *, chat_turn_id=0, explicit_secret_order=False):
        assert chat_turn_id > 0
        received_chat_turn_ids.append(chat_turn_id)
        db.persist_return_report(
            state, character.name, "陕西巡抚可有？", chat_turn_id=chat_turn_id,
        )
        assert db.conn.execute(
            "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id LIKE ?",
            (f"%:chat_turn:{chat_turn_id}",),
        ).fetchone()[0] == 1
        return SimpleNamespace(
            answer="臣有本奏。", proposed_directive=None, appointed_minister="",
            registered_minister="", displaced_minister="", court_action="",
            next_minister="", pending_action_failures=[],
        )

    session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        temporary_characters=set(),
        chat=chat,
        # #542 scene lifecycle seams — CLI minister_chat start/join/persist/abandon.
        start_chat_turn_scene=lambda *_a, **_k: None,
        start_chat_turn_exit_scene=lambda *_a, **_k: None,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
    )

    with pytest.raises(RuntimeError, match="finalization write failed"):
        term.minister_chat(session, character)

    turn = db.conn.execute("SELECT id, status FROM chat_turns ORDER BY id DESC LIMIT 1").fetchone()
    assert turn["status"] == "failed"
    assert received_chat_turn_ids == [turn["id"]]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE content=?", (marker,)
    ).fetchone()[0] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id LIKE ?",
        (f"%:chat_turn:{turn['id']}",),
    ).fetchone()[0] == 0


def test_terminal_failure_printer_preserves_zero_id(capsys):
    """失败 id 为 0 时也按显式 id 打印，不用 truthiness 掉成无 id 形态。"""
    term._print_pending_action_failures([{
        "id": 0,
        "kind": "secret_order",
        "action": "新建",
        "message": "密令落库失败。",
    }])

    out = capsys.readouterr().out
    assert "【密令落库失败 #0】" in out


@pytest.mark.parametrize("action", ["skip", "issue"])
def test_play_turn_reports_default_approval_secret_order_failure(monkeypatch, capsys, action):
    """#415: 退朝默认提交密令失败时，CLI 也必须给出失败 id。"""

    class Db:
        def __init__(self):
            self.actions = []

        def list_pending_actions(self, turn, status=None):
            if status == "failed":
                return list(self.actions)
            return []

    class Session:
        previous_summary = ""

        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.calls = []

        def begin_turn(self):
            self.calls.append("begin")
            return _Snap()

        def current_phase(self):
            return TurnPhase.REVIEWING

        def advance_without_decree(self):
            self.calls.append("advance")
            self.db.actions.append({
                "id": 42,
                "kind": "secret_order",
                "action": "新建",
            })

        def resolve_turn(self):
            self.calls.append("resolve")
            self.db.actions.append({
                "id": 42,
                "kind": "secret_order",
                "action": "新建",
            })
            return SimpleNamespace(awaiting=False, report="月报")

        def end_turn(self):
            self.calls.append("end")

    monkeypatch.setattr(term, "review_directives", lambda s: action)
    monkeypatch.setattr(term, "_print_header", lambda s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda db: None)
    session = Session()

    term.play_turn(session)

    out = capsys.readouterr().out
    assert "【密令落库失败 #42】" in out
    if action == "skip":
        assert session.calls == ["begin", "advance"]
    else:
        assert session.calls == ["begin", "resolve", "end"]


def test_play_turn_skip_prints_dossier_settlement_report_and_ends_turn(monkeypatch, capsys):
    session = _Sess(RuntimeError("unused"))
    session.current_phase = lambda: TurnPhase.REVIEWING
    session.advance_without_decree = lambda: SimpleNamespace(
        awaiting=False, report="留中案卷本月重判月报",
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
            self.db = SimpleNamespace(list_pending_actions=lambda *a, **k: [])
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


def test_play_turn_reports_secret_order_failure_when_settlement_aborts(monkeypatch, capsys):
    """pre_settle 已标 failed 后若后续结算中止，CLI 仍须显示失败 id。"""

    class Db:
        def __init__(self):
            self.actions = []

        def list_pending_actions(self, turn, status=None):
            if status == "failed":
                return list(self.actions)
            return []

    class Session:
        previous_summary = ""

        def __init__(self):
            self.db = Db()
            self.state = SimpleNamespace(turn=7)
            self.calls = []

        def begin_turn(self):
            self.calls.append("begin")
            return _Snap()

        def current_phase(self):
            return TurnPhase.REVIEWING

        def resolve_turn(self):
            self.calls.append("resolve")
            self.db.actions.append({
                "id": 42,
                "kind": "secret_order",
                "action": "新建",
            })
            raise SettlementAbort("结算中止，可重试。", turn=7, stage="extract")

        def advance_without_decree(self):
            self.calls.append("advance")

    actions = iter(["issue", "skip"])
    monkeypatch.setattr(term, "review_directives", lambda s: next(actions))
    monkeypatch.setattr(term, "_print_header", lambda s: None)
    monkeypatch.setattr(issues_mod, "show_active_issues", lambda db: None)
    session = Session()

    term.play_turn(session)

    out = capsys.readouterr().out
    assert "结算中止" in out
    assert "【密令落库失败 #42】" in out
    assert session.calls == ["begin", "resolve", "advance"]



@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_terminal_minister_chat_accepts_retry_reply_command(game, monkeypatch):
    """#1716 CLI：minister_chat「重试回话」成功收夜后返回 court_break，关夜且无 presence。

    入口仍是 minister_chat 的重试命令；route 保持、不重记问话既有契约一并覆盖。
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
        route="offsite",
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
    sess.temporary_characters = set()
    sess.registry = SimpleNamespace(
        get=lambda _ch: SimpleNamespace(
            run=lambda *_a, **_k: SimpleNamespace(content="臣遵旨。", tools=[]),
        ),
        session_ids={},
    )
    sess._audience_prompt_for_message = lambda msg, character=None, chat_turn_id=0: msg
    sess._start_cli_action_intent = lambda *_a, **_k: None
    sess._finish_cli_action_intent = lambda *_a, **_k: None
    sess.close_night_after_chat_if_needed = types.MethodType(
        GameSession.close_night_after_chat_if_needed, sess,
    )

    # 尾随抽取不入本契约；标 done 使收夜不被待补抽取挡住。
    def _trail_done(_session, _minister, _reply, chat_turn_id):
        db.conn.execute(
            "UPDATE chat_turns SET extract_status='done', mindreading_status='skip' "
            "WHERE id=?",
            (int(chat_turn_id),),
        )
        db.conn.commit()

    monkeypatch.setattr(term, "_trail_extraction_after_reply_cli", _trail_done)
    monkeypatch.setattr(term, "_dispatch_relation_judge_cli", lambda *_a, **_k: None)

    answers = iter(["重试回话"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(sess, character) == "court_break"

    row = db.conn.execute(
        "SELECT status, minister_message_id, route FROM chat_turns WHERE id=?", (ct,),
    ).fetchone()
    assert row["status"] == "active"
    assert row["minister_message_id"]
    assert str(row["route"] or "") == "offsite"

    assert an.get_open_night(db) is None
    night_row = db.conn.execute(
        "SELECT status FROM audience_nights WHERE id=?", (night_id,),
    ).fetchone()
    assert night_row is not None
    assert str(night_row["status"]) == an.NIGHT_STATUS_CLOSED
    # 场外收夜：该人不得入殿 presence/entrance。
    assert character.name not in an.persons_present_tonight(db, night_id)
    assert character.name not in an.persons_entered_tonight(db, night_id)


def test_cli_write_gate_canonical_session_attr():
    """#1353 fold-in r8：CLI 唯一 write gate 挂 session._write_gate（禁第二锁名分叉）。"""
    import threading

    session = SimpleNamespace()
    gate = term._cli_write_gate(session)
    assert isinstance(gate, type(threading.Lock()))
    assert getattr(session, "_write_gate", None) is gate
    # 二次调用同锁
    assert term._cli_write_gate(session) is gate
