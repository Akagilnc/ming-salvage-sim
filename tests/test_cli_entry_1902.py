"""#1902 CLI 入口接缝：拟诏台手写入口退役 + 批红等皇帝亲裁。

法源：#1902 票面「CLI 手拟新旨也不保留，但共享抽取核若仍有现役消费者则搬为其能力」、
「CLI 批红须等皇帝亲裁，不自动选第一项」；#1812 待拍第 6、9 项；ADR 0152（后出第 6 项
已批准整体删拟诏台，前置不阻止已批准删除）。

本文件只测入口适配层行为：审阅界面不再新增/改写旨意，批红由 input() 逐案取皇帝所选，
choice 投影只经 ``rescript_actions.project_hitl_option`` 一个真源。
"""

from __future__ import annotations

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


def _wire_gate(monkeypatch, session):
    """替身案：把 CLI 唯一 write gate 换成可断言的哨兵（真核案不得走这条）。"""
    gate = object()
    monkeypatch.setattr(term, "_cli_write_gate", lambda _session: gate)
    session.gate = gate
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


def test_adjudication_takes_emperor_pick_not_first_option(monkeypatch, capsys):
    """批红按皇帝所选编号提交；不取首选项。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row()]))
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


def _ordinary_row(decision_key: str = "decision:3:0") -> dict:
    """普通 decision 案头行（核内要求实选项，回车不成立）。"""
    return {
        "decision_key": decision_key,
        "kind": "decision",
        "source_turn": 3,
        "idx": 0,
        "title": "毛文龙裁断",
        "context": "东江事急，须御前亲裁。",
        "options": [
            {"label": "斩", "hint": "严肃军纪"},
            {"label": "留", "hint": "暂稳东江"},
        ],
    }


def test_adjudication_blank_pick_on_urgent_leaves_choice_to_core(monkeypatch):
    """急务回车＝不另批：入口只交 decision_key，动作由核内机械处置（hold）。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    term._adjudicate_cli_decisions(session, result)

    assert session.submitted == [[{"decision_key": "rescript_draft:3:0"}]]


def test_adjudication_blank_on_ordinary_decision_reprompts(monkeypatch, capsys):
    """普通 decision 回车不是核内认的留中：入口重问，不代造空 choice。

    核内 validate_all 对缺 action 的 decision 行既不默认 hold 也拒收（"decision 选项
    不在当前 options"），入口若替皇帝交空 pick 会让整批被拒、连同已答的案作废。
    """
    session = _wire_gate(monkeypatch, _AdjudicateSession([_ordinary_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    answers = iter(["", "  ", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices == [{
        "decision_key": "decision:3:0",
        "label": "留",
        "hint": "暂稳东江",
    }]
    out = capsys.readouterr().out
    assert out.count("此案须择定一条（不另批请择案上标注留中的那条）。") == 2


def test_adjudication_reprompts_on_out_of_range_number(monkeypatch, capsys):
    """越界编号不落 choice：留在本案重问，案头与核都不动（非编号输入是朱笔批语，另一条）。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row()]))
    result = SimpleNamespace(awaiting=True, report="", decisions=session.pending_decisions())
    answers = iter(["9", "0", "3", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    term._adjudicate_cli_decisions(session, result)

    (choices,) = session.submitted
    assert choices[0]["label"] == "先发半饷"
    assert choices[0]["draft_capability"] == "cap-a"
    assert capsys.readouterr().out.count("请输入本案列出的编号。") == 3


def test_adjudication_uses_desk_readback_when_result_has_no_decisions(monkeypatch):
    """result.decisions 空时回读同一案头（session.pending_decisions），入口不另读库。"""
    session = _wire_gate(monkeypatch, _AdjudicateSession([_draft_row("decision:4:1")]))
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


# ── 经真核的 tracer：入口产出的 choices 必须被生产 submit_hitl_choices 收下 ──
# #1902：这组用例此前把 GameSession.submit_hitl_choices 换成测试自写的
# validate→apply 链，生产提交入口整个坏掉也照样绿。现改为走真编排，只中和
# 最外层 LLM 缝（与 tests/test_cli_play_turn.py 的 play_turn tracer 同一手法）。


def _real_submit_session(monkeypatch, db, state, content, *, candidate_ids=()):
    """真 GameSession 壳 + 真 submit_hitl_choices；只中和外部 LLM 缝。

    本回合暂存上下文照真实 phase1 形状落一份（phase2 要读它续跑）。``candidate_ids``
    给本回合候选快照：核内 ``bind_decisions_to_candidate_events`` 只在快照非空时按
    快照重绑 event_id，故请旨等非事件身份那几条不传（它们的身份不是 events 表事件）。
    """
    from ming_sim.models import TurnPhase
    from tests.month_chain_helpers import make_light_session

    state.turn_phase = TurnPhase.AWAITING_DECISION.value
    db.save_state(state)
    simulator_payload = {
        "candidate_events": [{"id": cid, "title": ""} for cid in candidate_ids],
        "transit_semantics": [],
    } if candidate_ids else None
    db.save_resolve_context(
        int(state.turn), "测试诏书", {"simulator_payload": simulator_payload},
    )
    db.save_turn_report(state, "邸报已成")
    session = make_light_session(db, state, content)
    # 最外层 LLM 缝：世界段推演与月链转译。中和它们，核内编排与领域写全走真逻辑。
    monkeypatch.setattr("ming_sim.month_chain.run_world_segment_text", lambda *a, **k: "")
    monkeypatch.setattr(
        "ming_sim.month_translate.translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    return session


def test_cli_blank_pick_on_urgent_reaches_core_hold(game, monkeypatch):
    """急务回车 → 经真 submit_hitl_choices 机械 hold，案卷落 decided（外部可见）。"""
    from ming_sim import rescript_actions as ra

    db, state, content = game
    db.save_rescript_drafts(int(state.turn), [{
        "title": "陕西告饥", "context": "秦地赤旱",
        "options": [{"label": "发饷", "hint": "照拟", "draft_capability": "cap-1"}],
    }])
    db.conn.commit()
    session = _real_submit_session(monkeypatch, db, state, content)
    desk_row = db.list_rescript_desk(int(state.turn))[0]
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    term._adjudicate_cli_decisions(
        session, SimpleNamespace(
            awaiting=True, report="", decisions=session.pending_decisions(),
        ),
    )

    # 核侧事实：空 pick 只在急务上落机械 hold（default_hold_missing）。
    assert ra.validate_all(
        [desk_row], [{"decision_key": desk_row["decision_key"]}],
    ).default_hold_keys == [desk_row["decision_key"]]
    # 外部可见：经真编排落库即 decided + hold。
    stored = db.list_rescript_drafts()[0]
    assert stored["status"] == "decided"
    assert stored["choice"]["action"] == "hold"


def test_cli_blank_pick_on_ordinary_decision_is_rejected_by_core(game, monkeypatch):
    """回车语义只在急务成立：若入口交空 pick，真核整批拒（此钉核侧事实）。"""
    from ming_sim import rescript_actions as ra

    db, state, _content = game
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "mao_wenlong", "title": "毛文龙裁断", "context": "东江事急",
        "options": [{"label": "斩", "hint": "严肃军纪"}, {"label": "留", "hint": "暂稳东江"}],
    }])
    db.conn.commit()
    desk_row = db.list_rescript_desk(int(state.turn))[0]
    with pytest.raises(ValueError, match="decision 选项不在当前 options"):
        ra.validate_all([desk_row], [{"decision_key": desk_row["decision_key"]}])


def test_cli_chosen_option_reaches_core_and_lands_decision(game, monkeypatch):
    """按编号择定 → 真编排收下并落 decided，落库 choice 就是皇帝所选那条（非首选项）。"""
    db, state, content = game
    turn_before = int(state.turn)
    db.save_pending_decisions(turn_before, [{
        "event_id": "mao_wenlong", "title": "毛文龙裁断", "context": "东江事急",
        "options": [{"label": "斩", "hint": "严肃军纪"}, {"label": "留", "hint": "暂稳东江"}],
    }])
    db.conn.commit()
    session = _real_submit_session(
        monkeypatch, db, state, content, candidate_ids=("mao_wenlong",),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    term._adjudicate_cli_decisions(
        session, SimpleNamespace(
            awaiting=True, report="", decisions=session.pending_decisions(),
        ),
    )

    # 真编排跑完了整条亲裁续推（月份已推进），断言落在本回合那一行上。
    assert int(state.turn) > turn_before
    stored = db.list_pending_decisions(turn_before)[0]
    assert stored["choice"]["label"] == "留"
    assert stored["status"] == "decided"


def test_cli_imperial_note_reaches_core_for_question(game, monkeypatch):
    """#1902：请旨只交亲笔批语 → 经真编排落库，批语不被改写成某条票拟。

    资格判定只在核内（``rescript_actions.validate_all`` 的 note-only 通道，与 Web
    decisionModal 同一口径）；入口只负责把皇帝的原话透传过去。
    """
    db, state, content = game
    turn_before = int(state.turn)
    db.save_pending_decisions(turn_before, [{
        "event_id": "decree-question:ref-1:0", "title": "是否加赈",
        "context": "灾民待哺",
        "options": [{"label": "准", "hint": "出仓"}, {"label": "驳", "hint": "缓"}],
    }])
    db.conn.commit()
    # 请旨身份不是 events 表事件（核内 apply 已按前缀豁免 event 账），故不给候选快照。
    session = _real_submit_session(monkeypatch, db, state, content)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "着户部另议")

    term._adjudicate_cli_decisions(
        session, SimpleNamespace(
            awaiting=True, report="", decisions=session.pending_decisions(),
        ),
    )

    stored = db.list_pending_decisions(turn_before)[0]
    assert stored["status"] == "decided"
    assert stored["choice"]["note"] == "着户部另议"
    assert stored["choice"].get("label", "") == ""


def test_cli_imperial_note_on_non_question_decision_is_refused_by_core(game, monkeypatch):
    """非请旨的普通裁断不给 note-only：核整批拒，案卷仍 pending（入口不代造票拟）。"""
    db, state, content = game
    db.save_pending_decisions(int(state.turn), [{
        "event_id": "mao_wenlong", "title": "毛文龙裁断", "context": "东江事急",
        "options": [{"label": "斩", "hint": "严肃军纪"}, {"label": "留", "hint": "暂稳东江"}],
    }])
    db.conn.commit()
    session = _real_submit_session(monkeypatch, db, state, content)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "着户部另议")

    with pytest.raises(ValueError, match="decision 选项不在当前 options"):
        term._adjudicate_cli_decisions(
            session, SimpleNamespace(
                awaiting=True, report="", decisions=session.pending_decisions(),
            ),
        )

    stored = db.list_pending_decisions(int(state.turn))[0]
    assert stored["status"] == "pending"


def test_cli_runner_forwarders_are_gone_single_dispatch():
    """#1902：七条一行转发退役，分派点唯一落在 _run_cli_runner。"""
    from ming_sim import cli_backend as cb

    for runner in ("agy", "codex", "claude", "cursor", "kimi", "grok", "pi"):
        assert not hasattr(cb, f"_run_{runner}"), f"_run_{runner} 转发应已退役"
    assert hasattr(cb, "_run_cli_runner") and hasattr(cb, "_dispatch_cli_runner")
    # 准入名单只此一份：分派点认的谓词就是 _CLI_BACKENDS 那个真源（#1902 同形第二份已删）。
    assert not hasattr(cb, "_CLI_RUNNER_NAMES"), "准入名单副本应已删"
    assert all(
        cb.is_supported_cli_runner(runner)
        for runner in ("agy", "codex", "claude", "cursor", "kimi", "grok", "pi")
    )
    assert not cb.is_supported_cli_runner("new-host")
