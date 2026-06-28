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
from ming_sim.exceptions import SettlementAbort
from ming_sim.session import TurnPhase


class _Snap:
    deaths_this_turn = []


class _Sess:
    """play_turn 所需最小协作面：begin/phase/resolve/advance/end + 调用录音。"""
    previous_summary = ""

    def __init__(self, fail_exc):
        self.calls = []
        self._fail = fail_exc
        self.db = None

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

        def chat(self, minister_name, question):
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

        def chat(self, minister_name, question):
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

        def chat(self, minister_name, question):
            raise RuntimeError("LLM down")

    answers = iter(["命洪承畴督办陕西赈灾，东厂暗助护赈银。"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(RuntimeError, match="LLM down"):
        term.minister_chat(Session(), SimpleNamespace(name="魏忠贤"))
