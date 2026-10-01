"""#1891 三饷由皇帝批，不自动置已准——资格事实、交接供料与交接身份。

覆盖面（本票授权的最小纵切，且只留不经真实入口就无法表达的契约）：
- 到点不自行置结局：账上零终局行，事件进 petition-due 名单。
- 交接：具资格、尚未呈过的请饷／议停事件进名单，随世界段消息交给 #1843 既有
  月末 run（不新增调用、不造分拣代理人）。首次到点应呈请；已留中过的由大臣自决
  是否再上疏（#1891 权限分层）。
- 配置面：结局闭集齐备。交接绑定走真实过月链，不在本文件用回显键复证。

本文件只钉不经真实入口就无法表达的契约。交接绑定、案头物化、答复落账、结局置定、
跨月读端与持久恢复，全部在 tests/test_levy_petition_month_chain_1891.py 走真实
过月链端到端证明——不在此重复内部 helper 证明。
"""

from __future__ import annotations

import json

import pytest

import ming_sim.issues as issues
import ming_sim.month_chain as month_chain
from ming_sim.content import GameContent
from ming_sim.issues import (
    FISCAL_LEVY_RESCRIPT_SOURCE, list_fiscal_levy_petitions_due,
)
from ming_sim.month_chain import _LEVY_PETITION_PREFIX
from ming_sim.rescript_actions import _record_levy_petition_answer


def _prepare_due(db, state, content, year=1631, period=1):
    issues.bind_content(content)
    state.year = year
    state.period = period
    db.save_state(state)


# ---------------------------------------------------------------- 交接面


def test_petition_due_lists_liao_rise_at_historical_timepoint(game):
    """到点请饷进petition-due 名单，且首次到点的呈请义务是名单上的权限事实。

    留中后的再呈才由大臣自决——两条事实同出一份名单，一次钉住（#1891 J4）。
    """
    db, state, content = game
    _prepare_due(db, state, content)

    due = list_fiscal_levy_petitions_due(state, db)

    assert [item["event_id"] for item in due] == ["liao_levy_rise_1631"]
    assert due[0]["terminal_reason_labels"] == ["已准", "已驳"]
    # 首次到点：应呈请（权限事实），不是大臣自决的再呈；不带旧疏。
    assert due[0]["presentation_due"] is True
    assert due[0]["re_presentation"] is False
    assert "prior_petition" not in due[0]


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
    assert "petition_ref" not in json.dumps(payload, ensure_ascii=False)
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
