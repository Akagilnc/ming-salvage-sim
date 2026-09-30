"""#1891 三饷由皇帝批，不自动置已准——交接、绑定与请旨答复落账。

覆盖面（本票授权的最小纵切）：
- 到点不自行置结局：账上零终局行，事件进 petition-due 名单。
- 交接：具资格、尚未呈过的请饷／议停事件进名单，随世界段消息交给 #1843 既有
  月末 run（不新增调用、不造分拣代理人）。首次到点应呈请；已留中过的由大臣自决
  是否再上疏（#1891 权限分层）。
- 绑定：交接时把案头身份钉进问题本身并随月链持久化（ADR 0115）。恢复复用当次
  已存身份与奏疏，不按实时资格重解、不依赖模型回显补绑定。
- 答复落账：亲笔批语只按事实持久化，终局不由这条路径判定（ADR 0142 / P6）。

本文件只钉契约行为：真实供料、真实交接、真实绑定与真实答复落账。结局置定与跨月
读端在 tests/test_levy_petition_month_chain_1891.py 走真实过月链端到端证明。
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issues
import ming_sim.month_chain as month_chain
from ming_sim.content import GameContent
from ming_sim.db import GameDB
from ming_sim.issues import (
    FISCAL_LEVY_RESCRIPT_SOURCE, list_fiscal_levy_petitions_due,
)
from ming_sim.month_chain import (
    _LEVY_PETITION_PREFIX, _materialize_rescript_desk, _pin_world_question_identities,
)
from ming_sim.rescript_actions import _record_levy_petition_answer
from ming_sim.settlement_payload import parse_decision_blocks


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


def _world_with_levy_petition(event_id="liao_levy_rise_1631"):
    """拟批措辞是自由文：只由 label/hint 承载，不带任何结局类型键。"""
    return "关外告急，户部请加辽饷。" + _decision_block(
        event_id,
        [
            {"label": "准行加派", "hint": "边饷稍续"},
            {"label": "不准，仍照九厘", "hint": "民力已困"},
        ],
    )


def _prepare_due(db, state, content, year=1631, period=1):
    issues.bind_content(content)
    state.year = year
    state.period = period
    db.save_state(state)


# ---------------------------------------------------------------- 交接面


def test_petition_due_lists_liao_rise_at_historical_timepoint(game):
    db, state, content = game
    _prepare_due(db, state, content)

    due = list_fiscal_levy_petitions_due(state, db)

    assert [item["event_id"] for item in due] == ["liao_levy_rise_1631"]
    assert due[0]["terminal_reason_labels"] == ["已准", "已驳"]
    # 首次到点：应呈请，不是大臣自决的再呈。
    assert due[0]["re_presentation"] is False
    assert "prior_petition" not in due[0]


def test_petition_due_carries_first_presentation_duty_as_fact(game):
    """#1891 J4：首次到点应呈请是名单上的**权限事实**，不是提示措辞。

    留中后的再呈才由大臣自决。断言落在数据字段上，措辞改动不影响本判据。
    """
    db, state, content = game
    _prepare_due(db, state, content)

    due = list_fiscal_levy_petitions_due(state, db)
    assert due[0]["presentation_due"] is True
    assert due[0]["re_presentation"] is False


def test_petition_due_withdraws_presentation_duty_after_hold(game):
    """#1891 J4：已呈过、被留中的原事件不再带呈请义务，改由大臣自决是否再上疏。"""
    db, state, content = game
    _prepare_due(db, state, content)
    _record_levy_petition_answer(
        db, state, event_id="liao_levy_rise_1631",
        choice={"label": "", "note": "留中，俟再议"},
    )
    db.save_pending_decisions(int(state.turn), [{
        "event_id": f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",
        "title": "辽饷升至一分二厘", "context": "边镇欠饷日深，户部请加辽饷。",
        "options": [{"label": "准行加派", "hint": ""}],
    }])
    db.conn.execute(
        "UPDATE pending_decisions SET status='decided' WHERE turn=? AND event_id=?",
        (int(state.turn), f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"),
    )
    db.conn.commit()

    due = list_fiscal_levy_petitions_due(state, db)

    assert due[0]["presentation_due"] is False
    assert due[0]["re_presentation"] is True


def test_petition_due_is_empty_before_the_gate_and_after_verdict(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)
    assert list_fiscal_levy_petitions_due(state, db) == []

    _prepare_due(db, state, content)
    assert [i["event_id"] for i in list_fiscal_levy_petitions_due(state, db)] == ["liao_levy_rise_1631"]

    # 一事件一终局裁断：已裁过的不再回名单。
    db.mark_event_triggered(
        state, "liao_levy_rise_1631", source=FISCAL_LEVY_RESCRIPT_SOURCE, terminal_reason="已准",
    )
    assert list_fiscal_levy_petitions_due(state, db) == []


def test_petition_due_skips_event_already_awaiting_verdict_on_desk(game):
    """#1891：已呈上批红页待裁的，本月不重触发为首次事件。"""
    db, state, content = game
    _prepare_due(db, state, content)
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
    _prepare_due(db, state, content)

    message = month_chain._world_segment_message(db, state, "")
    payload = json.loads(message)

    assert [p["event_id"] for p in payload["levy_petitions"]] == ["liao_levy_rise_1631"]
    # 拟批措辞之外不夹带任何结局载荷：结局只由转译按闭集声明。
    assert "levy_terminal_reason" not in json.dumps(payload, ensure_ascii=False)
    assert all(
        set(p) == {
            "event_id", "title", "summary", "audiences",
            "terminal_reason_labels", "re_presentation", "presentation_due",
        }
        for p in payload["levy_petitions"]
    )


def test_world_segment_message_is_plain_when_no_petition_due(game):
    """无待呈事件时消息不加壳、不夹带请饷载荷（既有世界段契约不变）。

    判据是行为（没有 petition 壳、没有名单），不是指令原句——措辞是呈现层自由。
    """
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)

    message = month_chain._world_segment_message(db, state, "")

    assert "levy_petitions" not in message
    with pytest.raises(json.JSONDecodeError):
        json.loads(message)


# ---------------------------------------------------------------- 绑定面


def test_world_petition_binds_to_real_event_identity_at_handoff(game):
    """交接时按名单快照把案头身份钉进问题，随月链持久化（ADR 0115）。"""
    db, state, content = game
    _prepare_due(db, state, content)
    offered = list_fiscal_levy_petitions_due(state, db)
    questions = parse_decision_blocks(_world_with_levy_petition())

    pinned = _pin_world_question_identities(offered, questions)

    assert pinned[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    # 拟批措辞原样透传，呈现仍只读 label/hint。
    assert [o["label"] for o in pinned[0]["options"]] == ["准行加派", "不准，仍照九厘"]


def test_handoff_does_not_bind_event_outside_offered_snapshot(game):
    """不在本月交接名单内的回显 id 不绑：照旧走普通世界段案头身份。"""
    db, state, content = game
    _prepare_due(db, state, content)
    offered = list_fiscal_levy_petitions_due(state, db)
    questions = parse_decision_blocks(_world_with_levy_petition("some_other_event"))

    pinned = _pin_world_question_identities(offered, questions)

    assert not pinned[0]["event_id"].startswith(_LEVY_PETITION_PREFIX)


def test_materialized_desk_restores_pinned_identity_after_reopen(game, tmp_path):
    """#1891 J1：关档重开后复用当次已存身份与奏疏，不按实时资格重解。

    交接钉定的身份随月链持久化；重开库后重新物化案头，同一请旨行仍是原事件，
    不会退化成普通世界段案头身份。
    """
    db, state, content = game
    _prepare_due(db, state, content)
    path = str(tmp_path / "restore.db")
    offered = list_fiscal_levy_petitions_due(state, db)
    questions = parse_decision_blocks(_world_with_levy_petition())
    chain = {
        "levy_petitions": offered,
        "world_questions": _pin_world_question_identities(offered, questions),
    }

    desk = _materialize_rescript_desk(db, state, chain)
    assert desk[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
    first_title = desk[0]["title"]
    # 真关档重开：把库文件搬出去再开一份，读同一份已存月链相位。
    db.conn.commit()
    db.close()
    import shutil

    shutil.copyfile(db.path, path)
    reopened = GameDB(path, content)
    try:
        issues.bind_content(content)
        state2 = reopened.load_state()
        # 名单此刻已因「已呈待裁」而不在 due 名单里——若按实时资格重解，身份即丢。
        assert list_fiscal_levy_petitions_due(state2, reopened) == []
        desk_again = _materialize_rescript_desk(reopened, state2, chain)
        assert desk_again[0]["event_id"] == f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"
        assert desk_again[0]["title"] == first_title
    finally:
        reopened.close()


def test_world_question_without_event_id_stays_world_question(game):
    """未回显事件 id 的世界段请旨不受影响（既有行为不变）。"""
    db, state, content = game
    _prepare_due(db, state, content)
    offered = list_fiscal_levy_petitions_due(state, db)
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
    chain = {
        "levy_petitions": offered,
        "world_questions": _pin_world_question_identities(
            offered, parse_decision_blocks(text),
        ),
    }

    desk = _materialize_rescript_desk(db, state, chain)

    assert desk[0]["event_id"].startswith(month_chain._WORLD_QUESTION_PREFIX)


# ---------------------------------------------------------------- 答复落账


def test_emperor_answer_records_rescript_verbatim_without_setting_outcome(game):
    """#1891 J2：亲笔批语只按事实落账，终局不由答复路径判定（ADR 0142 / P6）。"""
    db, state, content = game
    _prepare_due(db, state, content)
    before = _settle_p(db)["p"]["三饷应征"]

    _record_levy_petition_answer(
        db, state,
        event_id="liao_levy_rise_1631",
        choice={"label": "准行加派", "note": "着户部行文各省"},
    )

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source, choice_json FROM event_triggers "
        "WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    # 拟批措辞是自由文，不得写进 terminal_reason 当结局（旧「已选未终态」污染面）。
    assert row["terminal_state"] == ""
    assert row["terminal_reason"] == ""
    assert row["source"] == FISCAL_LEVY_RESCRIPT_SOURCE
    # 亲笔批语与拟批措辞原样持久化。
    assert json.loads(row["choice_json"]) == {
        "label": "准行加派", "note": "着户部行文各省",
    }
    assert _settle_p(db)["p"]["三饷应征"] == before


def test_held_answer_records_note_and_leaves_event_undecided(game):
    """留中：本次奏疏已答、事件未裁定、征收不变，且原疏与批语可被读回。"""
    db, state, content = game
    _prepare_due(db, state, content)
    before = _settle_p(db)["p"]["三饷应征"]

    _record_levy_petition_answer(
        db, state, event_id="liao_levy_rise_1631",
        choice={"label": "", "note": "留中，俟户部再议"},
    )
    db.save_pending_decisions(int(state.turn), [{
        "event_id": f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",
        "title": "辽饷升至一分二厘",
        "context": "边镇欠饷日深，户部请加辽饷。",
        "options": [{"label": "准行加派", "hint": "边饷稍续"}],
    }])
    db.conn.execute(
        "UPDATE pending_decisions SET status='decided', choice_json=? "
        "WHERE turn=? AND event_id=?",
        (json.dumps({"label": "", "note": "留中，俟户部再议"}, ensure_ascii=False),
         int(state.turn), f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631"),
    )
    db.conn.commit()

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, choice_json FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert row["terminal_state"] == row["terminal_reason"] == ""
    assert "留中" in row["choice_json"]
    issues.apply_historical_fiscal_rates(state, db)
    assert _settle_p(db)["p"]["三饷应征"] == before

    # 读端闭环：下月世界段名单带回原事件、原疏与亲笔批语，由大臣自决是否再上疏。
    due = list_fiscal_levy_petitions_due(state, db)
    assert [item["event_id"] for item in due] == ["liao_levy_rise_1631"]
    assert due[0]["re_presentation"] is True
    assert due[0]["prior_petition"]["context"] == "边镇欠饷日深，户部请加辽饷。"
    assert "留中" in json.dumps(due[0]["prior_petition"]["rescript"], ensure_ascii=False)


def test_declared_outcome_outside_closed_label_set_fails_loud(game):
    """转译声明的结局不在闭集内＝响亮失败，绝不写脏串（ADR 0020 落位 1）。"""
    from ming_sim.exceptions import SettlementAbort
    from ming_sim.issues import _apply_fiscal_levy_declared_outcomes

    db, state, content = game
    _prepare_due(db, state, content)
    _record_levy_petition_answer(
        db, state, event_id="liao_levy_rise_1631", choice={"label": "准行加派"},
    )
    db.save_pending_decisions(int(state.turn), [{
        "event_id": f"{_LEVY_PETITION_PREFIX}liao_levy_rise_1631",
        "title": "辽饷升至一分二厘", "context": "军费窟窿",
        "options": [{"label": "准行加派", "hint": ""}],
    }])
    db.conn.commit()

    with pytest.raises(SettlementAbort, match="结局标签无法归一"):
        _apply_fiscal_levy_declared_outcomes(
            db, state, content,
            {"事件结局": {"liao_levy_rise_1631": "胡乱"}},
            commit=False,
        )

    row = db.conn.execute(
        "SELECT terminal_state FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert row["terminal_state"] == ""


def test_outcome_cannot_be_declared_for_event_never_presented(game):
    """没呈过的请饷事件不接受凭空声明的结局——没有御批可译。"""
    from ming_sim.issues import _fiscal_levy_presented_event_ids

    db, state, content = game
    _prepare_due(db, state, content)

    assert "liao_levy_rise_1631" not in _fiscal_levy_presented_event_ids(db)


def test_jiao_stop_verdict_uses_its_own_closed_label_set(game):
    """议停事件的结局取它自己的闭集（已停／仍征），不串开征事件的值。"""
    from ming_sim.exceptions import SettlementAbort
    from ming_sim.issues import _apply_fiscal_levy_declared_outcomes

    db, state, content = game
    _prepare_due(db, state, content, year=1640, period=1)
    db.mark_event_triggered(
        state, "jiao_levy_start_1637", source="test", terminal_reason="已准",
    )
    _record_levy_petition_answer(
        db, state, event_id="jiao_levy_stop_1640", choice={"label": "准停"},
    )
    db.save_pending_decisions(int(state.turn), [{
        "event_id": f"{_LEVY_PETITION_PREFIX}jiao_levy_stop_1640",
        "title": "剿饷议停", "context": "剿饷已畅",
        "options": [{"label": "准停", "hint": ""}],
    }])
    db.conn.commit()

    _apply_fiscal_levy_declared_outcomes(
        db, state, content, {"事件结局": {"jiao_levy_stop_1640": "已停"}}, commit=False,
    )
    assert db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("jiao_levy_stop_1640",),
    ).fetchone()["terminal_reason"] == "已停"

    with pytest.raises(SettlementAbort, match="结局标签无法归一"):
        _apply_fiscal_levy_declared_outcomes(
            db, state, content, {"事件结局": {"jiao_levy_stop_1640": "已准"}}, commit=False,
        )


def test_declared_outcome_ignores_non_levy_events(game):
    """非饷率事件的结局声明不经本路径处置（各归其既有写口）。"""
    from ming_sim.issues import _apply_fiscal_levy_declared_outcomes

    db, state, content = game
    _prepare_due(db, state, content)

    applied = _apply_fiscal_levy_declared_outcomes(
        db, state, content, {"事件结局": {"jisi_lubian": "入塞被遏"}}, commit=False,
    )

    assert applied == []
    assert db.event_terminal_state("jisi_lubian") is None


def test_content_declares_closed_label_sets_for_levy_events():
    """配置面：每个饷率事件都声明了结局闭集，否则请旨无闭集可归一。"""
    content = GameContent.load()
    levy = [
        ev for ev in content.events
        if getattr(ev, "category", "") == "fiscal_levy"
    ]
    assert levy, "内容里应至少有一个饷率事件"
    for ev in levy:
        assert getattr(ev, "terminal_reason_labels", None), (
            f"饷率事件 {ev.id} 缺 terminal_reason_labels 白名单"
        )
