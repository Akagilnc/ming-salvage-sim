"""#1891 端到端：真实过月链上，请饷奏疏由世界段生成、经 #1847 批红页由皇帝亲裁。

不经内部函数直调：走 session.resolve_turn → 世界段 run（外缝打桩）→ 批红页
→ submit_decisions → 事件账终局 → pre_settle 饷率生效。断言实账与事件身份，
不匹配自由文本（ADR 0043 批红页形态、ADR 0115 事件绑定）。
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issues
import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.issues import FISCAL_LEVY_RESCRIPT_SOURCE
from ming_sim.models import LLMConfig
from ming_sim.month_chain import _LEVY_PETITION_PREFIX
from ming_sim.settlement_payload import LEVY_TERMINAL_REASON_KEY
from tests.month_chain_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor


def _settle_p(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _world_text(*, reason: str, label: str = "准行加派") -> str:
    return "关外告急，户部请加辽饷以济边饷。" + (
        "<<DECISION>>"
        + json.dumps(
            {
                "title": "辽饷升至一分二厘",
                "context": "边镇欠饷日深，户部请加辽饷。",
                "event_id": "liao_levy_rise_1631",
                "options": [
                    {"label": label, "hint": "边饷稍续而民间加派更重",
                     LEVY_TERMINAL_REASON_KEY: reason},
                    {"label": "不准，仍照九厘", "hint": "民力已困",
                     LEVY_TERMINAL_REASON_KEY: "已驳"},
                ],
            },
            ensure_ascii=False,
        )
        + "<<END>>"
    )


def _prepare(db, state, content, monkeypatch):
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    _forbid_extractor(monkeypatch)


def _stub_world(monkeypatch, text, *, continue_text="遵旨。"):
    monkeypatch.setattr(
        month_chain, "run_world_segment_text", lambda *a, **k: text,
    )
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text", lambda *a, **k: continue_text,
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    monkeypatch.setattr(
        month_chain, "run_gazette_text", lambda *a, **k: ("邸报", "边情邸报。"),
    )
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")


def test_emperor_approves_levy_petition_through_real_month_chain(game, monkeypatch):
    """世界段上疏 → 同一批红页亲裁「准」→ 事件终局 + 同月账仍按九厘、下月升。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    _stub_world(monkeypatch, _world_text(reason="已准"))
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )

    result = session.resolve_turn(allow_empty_decree=True)

    # 呈上批红页：同一请旨入口，不新增案头、不另起 run。
    assert result.awaiting is True
    assert result.stage == "rescript"
    assert result.advanced is False
    desk = session.pending_decisions()
    assert len(desk) == 1
    row = desk[0]
    assert row["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    assert row["title"] == "辽饷升至一分二厘"
    # 到点但未裁 → 账上无终局行（不再自动置已准）。
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
        ("liao_levy_rise_1631",),
    ).fetchone() is None

    # 皇帝在批红页点「准行加派」。
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision", "label": "准行加派"}],
        write_gate=session._write_gate,
    )

    ledger = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert ledger["terminal_state"] == "triggered"
    assert ledger["terminal_reason"] == "已准"
    assert ledger["source"] == FISCAL_LEVY_RESCRIPT_SOURCE
    # 本月已提交的财政不被回写重跑：仍按九厘。
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_approved_rate_takes_effect_and_then_enters_province_books(game, monkeypatch):
    """本月批准加派，下月唯一财政 tick 才消费新额（本月实账保持原额）。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    target = before * 4.0 / 3.0
    _stub_world(monkeypatch, _world_text(reason="已准"))
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision", "label": "准行加派"}],
        write_gate=session._write_gate,
    )

    # 下月：走真实过月链，唯一财政 tick 消费新额。
    import math

    _stub_world(monkeypatch, "本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True, (second.stage, second.awaiting)

    after = _settle_p(db)
    assert math.isclose(after["p"]["三饷应征"], target, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        after["p"]["起运定额"],
        after["_meta"]["正赋起运基线"] + target,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_emperor_rejects_levy_petition_keeps_nine_li(game, monkeypatch):
    """驳征不加派：辽饷仍九厘，终局一次落「已驳」。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    _stub_world(monkeypatch, _world_text(reason="已准"))
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision", "label": "不准，仍照九厘"}],
        write_gate=session._write_gate,
    )

    assert db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()["terminal_reason"] == "已驳"

    _stub_world(monkeypatch, "本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True, (second.stage, second.awaiting)
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_held_levy_petition_advances_month_without_terminal_state(game, monkeypatch):
    """留中：本次奏疏已答、事件未裁定、征收不变；本月仍能续推推进。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    closed_turn = int(state.turn)
    _stub_world(monkeypatch, _world_text(reason="已准"))
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    # 只批朱笔、不点拟批 = 留中。
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision",
          "label": "", "note": "留中，俟户部再议"}],
        write_gate=session._write_gate,
    )

    ledger = db.conn.execute(
        "SELECT terminal_state, terminal_reason, choice_json FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert ledger["terminal_state"] == ""
    assert ledger["terminal_reason"] == ""
    assert "留中" in ledger["choice_json"]
    # 留中不改征收。
    assert _settle_p(db)["p"]["三饷应征"] == before
    # 留中不阻月份推进：续推后回合能走完。
    _stub_world(monkeypatch, "本月无大事。")
    second = session.resolve_turn(allow_empty_decree=True)
    assert second.advanced is True, (second.stage, second.awaiting)
    assert int(state.turn) > closed_turn


@pytest.mark.parametrize("reason", ["missing", None, "", "   "])
def test_selected_levy_option_without_reason_rejected_before_ledger_write(
    game, monkeypatch, reason,
):
    """缺类型键的拟批当场拒绝；事务不留脏账，仍可留中并续推、再呈。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    before = _settle_p(db)["p"]["三饷应征"]
    payload = json.loads(_world_text(reason="已准").split("<<DECISION>>")[1].split("<<END>>")[0])
    if reason == "missing":
        del payload["options"][0][LEVY_TERMINAL_REASON_KEY]
    else:
        payload["options"][0][LEVY_TERMINAL_REASON_KEY] = reason
    _stub_world(monkeypatch, "<<DECISION>>" + json.dumps(payload, ensure_ascii=False) + "<<END>>")
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    assert session.resolve_turn(allow_empty_decree=True).awaiting is True
    row = session.pending_decisions()[0]
    with pytest.raises(ValueError, match="levy_terminal_reason"):
        session.submit_hitl_choices(
            [{"decision_key": row["decision_key"], "action": "decision", "label": "准行加派"}],
            write_gate=session._write_gate,
        )
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?", ("liao_levy_rise_1631",),
    ).fetchone() is None
    pending = db.conn.execute(
        "SELECT status, choice_json FROM pending_decisions WHERE event_id=?",
        (row["event_id"],),
    ).fetchone()
    assert pending["status"] == "pending"
    assert not json.loads(pending["choice_json"] or "{}")
    assert _settle_p(db)["p"]["三饷应征"] == before

    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision",
          "label": "", "note": "留中，俟再议"}],
        write_gate=session._write_gate,
    )
    ledger = db.conn.execute(
        "SELECT terminal_state, terminal_reason, choice_json FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert ledger["terminal_state"] == ledger["terminal_reason"] == ""
    assert json.loads(ledger["choice_json"])["note"] == "留中，俟再议"
    assert "liao_levy_rise_1631" not in issues._event_pending_choice_records(db)
    due = issues.list_fiscal_levy_petitions_due(state, db)
    assert due[0]["event_id"] == "liao_levy_rise_1631"
    assert due[0]["re_presentation"] is True
    _stub_world(monkeypatch, "本月无大事。")
    assert session.resolve_turn(allow_empty_decree=True).advanced is True
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_no_levy_petition_means_no_extra_ask_and_no_new_run(game, monkeypatch):
    """未到点月份不新增请旨行、不新增模型调用（世界段消息保持原样）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)
    _forbid_extractor(monkeypatch)

    calls = {"world": 0}

    def _world(*a, **k):
        calls["world"] += 1
        return "本月无大事。"

    monkeypatch.setattr(month_chain, "run_world_segment_text", _world)
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text", lambda *a, **k: "。",
    )
    monkeypatch.setattr(
        month_translate, "translate_month_segment", lambda *a, **k: {"effects": {}},
    )
    monkeypatch.setattr(
        month_chain, "run_gazette_text", lambda *a, **k: ("邸报", "边情邸报。"),
    )
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )

    result = session.resolve_turn(allow_empty_decree=True)

    assert calls["world"] == 1
    assert all(
        not str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX)
        for r in session.pending_decisions()
    )
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id LIKE '%levy%' AND terminal_state='triggered'"
    ).fetchone() is None
    assert result.advanced is True


def test_re_presentation_after_hold_still_binds_same_event(game, monkeypatch):
    """留中后大臣再上疏：新疏仍绑原事件，终局裁断只落该事件一次。"""
    db, state, content = game
    _prepare(db, state, content, monkeypatch)
    _stub_world(monkeypatch, _world_text(reason="已准"))
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )

    session.resolve_turn(allow_empty_decree=True)
    row = session.pending_decisions()[0]
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "action": "decision",
          "label": "", "note": "留中"}],
        write_gate=session._write_gate,
    )

    # 下月同一事件带 re_presentation 交回同一世界段 run。
    from ming_sim.issues import list_fiscal_levy_petitions_due

    due = list_fiscal_levy_petitions_due(state, db)
    assert [d["event_id"] for d in due] == ["liao_levy_rise_1631"]
    assert due[0]["re_presentation"] is True

    # 再上疏 → 仍绑原事件（不是新事件、不是首次重触发）。
    _stub_world(monkeypatch, _world_text(reason="已驳", label="罢辽饷加派"))
    session.resolve_turn(allow_empty_decree=True)
    desk = session.pending_decisions()
    petition_rows = [
        r for r in desk if str(r["event_id"]).startswith(_LEVY_PETITION_PREFIX)
    ]
    assert len(petition_rows) == 1
    assert petition_rows[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"

    session.submit_hitl_choices(
        [{"decision_key": petition_rows[0]["decision_key"], "action": "decision",
          "label": "罢辽饷加派"}],
        write_gate=session._write_gate,
    )
    assert db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()["terminal_reason"] == "已驳"
    # 一事件一终局裁断：只一行。
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=? AND terminal_state='triggered'",
        ("liao_levy_rise_1631",),
    ).fetchone()[0] == 1
