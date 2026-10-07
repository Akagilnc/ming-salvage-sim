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


class _Snap:
    deaths_this_turn = []


class _Sess:
    """play_turn 所需最小协作面：begin/phase/resolve/advance/end + 调用录音。"""
    previous_summary = ""

    def __init__(self, fail_exc):
        self.calls = []
        self._fail = fail_exc
        # 结算差集共核要求真实协作面 list_pending_actions；禁 db=None 空回落。
        self.db = SimpleNamespace(list_pending_actions=lambda *_a, **_k: [])
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
    # #1902：批红不再代选第一项，CLI 逐案问皇帝——本案只有一条票拟，回「1」即依拟。
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    term.play_turn(session)

    # 验证月份已真实推进，且 end_turn 已被调用将 turn_phase 重置为 summoning
    assert int(session.state.turn) == turn_before + 1
    assert session.current_phase() == TurnPhase.SUMMONING
    assert db.load_state().turn_phase == TurnPhase.SUMMONING.value

