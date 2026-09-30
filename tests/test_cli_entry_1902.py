"""#1902 CLI 入口接缝：拟诏台手写入口退役 + 批红等皇帝亲裁。

法源：#1902 票面「CLI 手拟新旨也不保留，但共享抽取核若仍有现役消费者则搬为其能力」、
「CLI 批红须等皇帝亲裁，不自动选第一项」；#1812 待拍第 6、9 项；ADR 0152（后出第 6 项
已批准整体删拟诏台，前置不阻止已批准删除）。

本文件只测入口适配层行为：审阅界面不再新增/改写旨意，批红由 input() 逐案取皇帝所选，
choice 投影只经 ``rescript_actions.project_hitl_option`` 一个真源。
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import ming_sim.cli.terminal as term
from ming_sim.rescript_actions import project_hitl_option


def _draft_row(decision_key: str = "rescript_draft:3:0") -> dict:
    return {
        "decision_key": decision_key,
        "kind": "rescript_draft",
        "source_turn": 3,
        "idx": 0,
        "title": "边饷欠额",
        "context": "辽东饷银已欠两月。",
        "options": [
            {"label": "先发半饷", "hint": "量入为出", "draft_capability": "cap-a"},
            {"label": "照旧额全发", "hint": "不改额", "draft_capability": "cap-b"},
        ],
    }


class _AdjudicateSession:
    """submit_hitl_choices 唯一编排的录音替身（真核由 session 负责）。"""

    def __init__(self, decisions):
        self._decisions = decisions
        self.submitted: list[dict] = []
        self.gate: object | None = None

    def pending_decisions(self):
        return list(self._decisions)

    def submit_hitl_choices(self, choices, *, write_gate):
        assert write_gate is self.gate
        self.submitted.append(choices)
        return "邸报"


@pytest.fixture(autouse=True)
def _cli_write_gate(monkeypatch):
    gate = object()
    monkeypatch.setattr(term, "_cli_write_gate", lambda _session: gate)
    return gate


def _wire_gate(session):
    session.gate = term._cli_write_gate(session)
    return session


def test_review_directives_retires_manual_add_and_edit(monkeypatch, capsys):
    """拟诏台手写新旨/改稿退役：CLI 审阅只剩审阅、颁布与删旧草案。"""

    class Session:
        def __init__(self):
            self.db = SimpleNamespace(list_pending_actions=lambda _turn: [])
            self.state = SimpleNamespace(turn=1, turn_phase="reviewing")
            self.calls: list[str] = []

        def enter_review(self):
            self.calls.append("enter_review")

        def back_to_summoning(self):
            self.calls.append("back_to_summoning")

        def list_directives(self, include_pending=True):
            return [SimpleNamespace(id=7, text="拟旨旧稿", status="draft")]

        def add_directive(self, *args, **kwargs):
            self.calls.append("add_directive")
            raise AssertionError("CLI 不得再新增手写旨意")

        def update_directive(self, *args, **kwargs):
            self.calls.append("update_directive")
            raise AssertionError("CLI 不得再改写旨意")

    answers = iter(["add", "拟一道新旨", "edit 7", "改稿", "back"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    session = Session()

    assert term.review_directives(session) == "back"
    assert session.calls == ["enter_review", "back_to_summoning"]
    out = capsys.readouterr().out
    # 四条都不是现役操作（add / 其后正文 / edit 7 / 其后正文）→ 都不落任何写入。
    assert out.count("未识别操作。") == 4
    assert "add 新增" not in out and "edit N 改" not in out
    assert "capture_manual_directive_payload" not in inspect.getsource(
        term.review_directives,
    )


def test_adjudication_takes_emperor_pick_not_first_option(monkeypatch, capsys):
    """批红按皇帝所选编号提交；不取首选项。"""
    session = _wire_gate(_AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    assert term._adjudicate_cli_decisions(session, result) == "邸报"

    (choices,) = session.submitted
    assert len(choices) == 1
    choice = choices[0]
    assert choice["decision_key"] == "rescript_draft:3:0"
    assert choice["label"] == "照旧额全发"
    assert choice["action"] == "follow_draft"
    assert choice["draft_capability"] == "cap-b"
    out = capsys.readouterr().out
    assert "1. 先发半饷（量入为出）" in out
    assert "2. 照旧额全发（不改额）" in out
    assert "自动取首选项" not in out


def test_adjudication_blank_pick_leaves_choice_to_core(monkeypatch):
    """回车＝不另批：入口只交 decision_key，动作由核内机械处置（急务统一 hold）。"""
    session = _wire_gate(_AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    term._adjudicate_cli_decisions(session, result)

    assert session.submitted == [[{"decision_key": "rescript_draft:3:0"}]]


def test_adjudication_reprompts_on_unknown_number(monkeypatch, capsys):
    """越界编号不落choice：留在本案重问，案头与核都不动。"""
    session = _wire_gate(_AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    answers = iter(["9", "0", "abc", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices[0]["label"] == "先发半饷"
    assert choices[0]["draft_capability"] == "cap-a"
    assert capsys.readouterr().out.count("请输入本案列出的编号，或回车留中。") == 3


def test_adjudication_uses_desk_readback_when_result_has_no_decisions(monkeypatch):
    """result.decisions 空时回读同一案头（session.pending_decisions），入口不另读库。"""
    session = _wire_gate(_AdjudicateSession([_draft_row("decision:4:1")]))
    result = SimpleNamespace(awaiting=True, report="", decisions=[])
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices[0]["decision_key"] == "decision:4:1"


def test_adjudication_skips_when_not_awaiting():
    session = _AdjudicateSession([])
    result = SimpleNamespace(awaiting=False, report="邸报已归档", decisions=[])
    assert term._adjudicate_cli_decisions(session, result) == "邸报已归档"
    assert session.submitted == []


@pytest.mark.parametrize("index,expected_label", [(0, "先发半饷"), (1, "照旧额全发")])
def test_project_hitl_option_is_the_single_projection(index, expected_label):
    """核内投影真源按 index 取案上那条；越界回首 option，不抛。"""
    choice = project_hitl_option(_draft_row(), index)
    assert choice["label"] == expected_label
    assert choice["action"] == "follow_draft"
    assert choice["decision_key"] == "rescript_draft:3:0"
    assert project_hitl_option(_draft_row(), 9)["label"] == "先发半饷"
