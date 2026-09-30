"""#1891 三饷由皇帝批，不自动置已准——请旨交接与亲裁落账。

覆盖面（本票授权的最小纵切）：
- 旧 shadow 自动置结局桩退役：到点不写已准／已停，账上零终局行。
- 交接：具资格、尚未呈过的请饷／议停事件进 petition-due 名单，随世界段消息
  交给 #1843 既有月末 run（不新增调用、不造分拣代理人）。
- 绑定：世界段 DECISION 回显的事件 id 只在本月名单内才绑成 levy-petition 案头
  身份（ADR 0115，不从疏文猜配）。
- 亲裁：准／驳经唯一写口落终局；留中不置终局、征收不变、本月可续推。
- 再上疏：留中过的原事件带 re_presentation 回来，由大臣自决；不顶旧疏。
"""

from __future__ import annotations

import json
import math

import pytest

import ming_sim.issues as issues
import ming_sim.month_chain as month_chain
from ming_sim.issues import (
    FISCAL_LEVY_RESCRIPT_SOURCE, list_fiscal_levy_petitions_due,
)
from ming_sim.month_chain import _LEVY_PETITION_PREFIX, _materialize_rescript_desk
from ming_sim.rescript_actions import _apply_levy_petition_verdict
from ming_sim.settlement_payload import LEVY_TERMINAL_REASON_KEY, parse_decision_blocks


def _settle_p(db, region_id="shaanxi"):
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", (region_id,)).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _decision_block(event_id, options, title="请饷"):
    return (
        "<<DECISION>>"
        + json.dumps(
            {"title": title, "context": "军费窟窿", "event_id": event_id, "options": options},
            ensure_ascii=False,
        )
        + "<<END>>"
    )


def _world_with_levy_petition(event_id="liao_levy_rise_1631", reason="已准"):
    return "关外告急，户部请加辽饷。" + _decision_block(
        event_id,
        [
            {"label": "准行加派", "hint": "边饷稍续", LEVY_TERMINAL_REASON_KEY: reason},
            {"label": "不准，仍照九厘", "hint": "民力已困", LEVY_TERMINAL_REASON_KEY: "已驳"},
        ],
    )


# ---------------------------------------------------------------- 交接面


def test_petition_due_lists_liao_rise_at_historical_timepoint(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    due = list_fiscal_levy_petitions_due(state, db)

    assert [item["event_id"] for item in due] == ["liao_levy_rise_1631"]
    assert due[0]["terminal_reason_labels"] == ["已准", "已驳"]
    assert due[0]["re_presentation"] is False


def test_petition_due_is_empty_before_the_gate_and_after_verdict(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)
    assert list_fiscal_levy_petitions_due(state, db) == []

    state.year = 1631
    state.period = 1
    db.save_state(state)
    assert [i["event_id"] for i in list_fiscal_levy_petitions_due(state, db)] == ["liao_levy_rise_1631"]

    # 一事件一终局裁断：已裁过的不再回名单。
    db.mark_event_triggered(
        state, "liao_levy_rise_1631", source=FISCAL_LEVY_RESCRIPT_SOURCE, terminal_reason="已准",
    )
    assert list_fiscal_levy_petitions_due(state, db) == []


def test_petition_due_skips_event_already_awaiting_verdict_on_desk(game):
    """#1891：已呈上批红页待裁的，本月不重触发为首次事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    db.save_pending_decisions(int(state.turn), [{
        "event_id": f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",
        "title": "辽饷升至一分二厘",
        "context": "军费窟窿",
        "options": [{"label": "准行加派", "hint": ""}],
    }])

    assert list_fiscal_levy_petitions_due(state, db) == []


def test_world_segment_message_hands_petitions_to_existing_run(game):
    """交接走 #1843 既有世界段 run：只是消息供料，不新增调用、不另起 run。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    message = month_chain._world_segment_message(db, state, "")

    payload = json.loads(message)
    assert payload["instruction"] == "推演本月世界段。"
    assert [p["event_id"] for p in payload["levy_petitions"]] == ["liao_levy_rise_1631"]
    assert LEVY_TERMINAL_REASON_KEY in payload["levy_petitions_option_contract"]


def test_world_segment_message_is_plain_when_no_petition_due(game):
    """无待呈事件时消息保持原样（不加壳、不改既有世界段契约）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)

    assert month_chain._world_segment_message(db, state, "") == "推演本月世界段。"


# ---------------------------------------------------------------- 绑定面


def test_levy_option_typed_key_survives_decision_parse():
    """类型键随 option 透传：呈现仍只读 label/hint，结局不靠解析文字。"""
    text = _world_with_levy_petition()
    decisions = parse_decision_blocks(text)
    assert len(decisions) == 1
    reasons = {opt[LEVY_TERMINAL_REASON_KEY] for opt in decisions[0]["options"]}
    assert reasons == {"已准", "已驳"}


def test_world_petition_binds_to_real_event_identity(game, monkeypatch):
    """世界段上疏 → 批红页同一请旨行，案头身份剥前缀还原真实事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    chain = {"world_questions": parse_decision_blocks(_world_with_levy_petition())}

    desk = _materialize_rescript_desk(db, state, chain)

    assert desk is not None
    assert desk[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    assert desk[0]["title"] == "请饷"


def test_world_question_with_unknown_event_id_stays_world_question(game):
    """名单外的回显 id 不绑：仍是普通世界段请旨，不冒充请饷事件。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    chain = {"world_questions": parse_decision_blocks(_world_with_levy_petition("some_other_event"))}

    desk = _materialize_rescript_desk(db, state, chain)

    assert desk[0]["event_id"].startswith(month_chain._WORLD_QUESTION_PREFIX)


def test_world_question_without_event_id_stays_world_question(game):
    """未回显事件 id 的世界段请旨不受影响（既有行为不变）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    text = (
        "<<DECISION>>"
        + json.dumps(
            {"title": "是否增援宁远", "context": "袁崇焕请兵", "options": [
                {"label": "准调关宁", "hint": ""}, {"label": "暂缓", "hint": ""},
            ]},
            ensure_ascii=False,
        )
        + "<<END>>"
    )
    chain = {"world_questions": parse_decision_blocks(text)}

    desk = _materialize_rescript_desk(db, state, chain)

    assert desk[0]["event_id"].startswith(month_chain._WORLD_QUESTION_PREFIX)


# ---------------------------------------------------------------- 亲裁落账


def test_emperor_approval_sets_terminal_state_through_single_write_port(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    outcome = _apply_levy_petition_verdict(
        db, state,
        event_id="liao_levy_rise_1631",
        choice={"label": "准行加派", "note": ""},
        execution_option={"label": "准行加派", LEVY_TERMINAL_REASON_KEY: "已准"},
    )

    assert outcome == "approved_or_rejected"
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert row["terminal_state"] == "triggered"
    assert row["terminal_reason"] == "已准"
    assert row["source"] == FISCAL_LEVY_RESCRIPT_SOURCE


def test_emperor_rejection_keeps_rate_at_nine_li(game):
    """驳征不加派：辽饷仍九厘。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_p(db)["p"]["三饷应征"]

    _apply_levy_petition_verdict(
        db, state,
        event_id="liao_levy_rise_1631",
        choice={"label": "不准，仍照九厘", "note": ""},
        execution_option={"label": "不准，仍照九厘", LEVY_TERMINAL_REASON_KEY: "已驳"},
    )
    issues.apply_historical_fiscal_rates(state, db)

    assert math.isclose(_settle_p(db)["p"]["三饷应征"], before)
    row = db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert row["terminal_reason"] == "已驳"


def test_held_petition_records_answer_without_terminal_state(game):
    """留中：本次奏疏已答、事件未裁定、征收不变。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_p(db)["p"]["三饷应征"]

    outcome = _apply_levy_petition_verdict(
        db, state,
        event_id="liao_levy_rise_1631",
        choice={"label": "", "note": "留中，俟户部再议"},
        execution_option=None,
    )

    assert outcome == "held"
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source, choice_json FROM event_triggers "
        "WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert row["terminal_state"] == ""
    assert row["terminal_reason"] == ""
    assert row["source"] == FISCAL_LEVY_RESCRIPT_SOURCE
    assert "留中" in row["choice_json"]
    issues.apply_historical_fiscal_rates(state, db)
    assert math.isclose(_settle_p(db)["p"]["三饷应征"], before)


def test_held_petition_comes_back_as_re_presentation_not_new_event(game):
    """#1891 裁定：留中后由大臣自己决定是否再上疏，代码不代它再顶旧疏。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    _apply_levy_petition_verdict(
        db, state,
        event_id="liao_levy_rise_1631",
        choice={"label": "", "note": "留中"},
        execution_option=None,
    )

    due = list_fiscal_levy_petitions_due(state, db)

    assert [item["event_id"] for item in due] == ["liao_levy_rise_1631"]
    assert due[0]["re_presentation"] is True


def test_levy_outcome_outside_closed_label_set_fails_loud(game):
    """不可归一的结局标签响亮失败，绝不写脏串（ADR 0020 落位 1）。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    with pytest.raises(SettlementAbort, match="结局标签无法归一"):
        _apply_levy_petition_verdict(
            db, state,
            event_id="liao_levy_rise_1631",
            choice={"label": "随便写个批语", "note": ""},
            execution_option={"label": "随便写个批语", LEVY_TERMINAL_REASON_KEY: "胡乱"},
        )

    row = db.conn.execute(
        "SELECT terminal_state FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert row is None or row["terminal_state"] == ""


def test_verdict_for_unknown_event_fails_loud(game):
    db, state, content = game
    issues.bind_content(content)

    with pytest.raises(ValueError, match="请饷请旨指向不存在的事件"):
        _apply_levy_petition_verdict(
            db, state,
            event_id="__no_such_levy_event__",
            choice={"label": "", "note": "留中"},
            execution_option=None,
        )


def test_jiao_stop_verdict_uses_stop_label_set(game):
    """议停事件的结局取它自己的闭集（已停／仍征），不串开征事件的值。"""
    from ming_sim.exceptions import SettlementAbort

    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(
        state, "jiao_levy_start_1637", source="test", terminal_reason="已准",
    )

    _apply_levy_petition_verdict(
        db, state,
        event_id="jiao_levy_stop_1640",
        choice={"label": "准停", "note": ""},
        execution_option={"label": "准停", LEVY_TERMINAL_REASON_KEY: "已停"},
    )
    assert db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("jiao_levy_stop_1640",),
    ).fetchone()["terminal_reason"] == "已停"

    with pytest.raises(SettlementAbort, match="结局标签无法归一"):
        _apply_levy_petition_verdict(
            db, state,
            event_id="jiao_levy_stop_1640",
            choice={"label": "准停", "note": ""},
            execution_option={"label": "准停", LEVY_TERMINAL_REASON_KEY: "已准"},
        )
