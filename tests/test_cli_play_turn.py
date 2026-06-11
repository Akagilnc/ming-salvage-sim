"""PR #90 R1 gemini medium——issue 分支拒绝后留在回合交互循环（continue 不 return）。

return 会退出 play_turn，外层主循环重进时重印回合引导/在册大臣=刷屏；skip 分支
已是 continue，issue 分支的 ValueError/SettlementAbort 拒绝应同语义：打印指引后
玩家留在同一循环里直接重试/改操作（rule#9：提示后能继续，不再撞同一错）。
"""

from __future__ import annotations

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
