"""#1897 转译声明新建密令走现役分派入口（不导入已删函数），失败真实可重试。

刀口：``declaration_dispatch._dispatch_commissions`` 的 ``secret_order`` 支路。
此前它导入 ``action_materialize.land_or_recover_new_secret_order``（已随
``e2fc6369d`` 删除），一旦转译声明 ``commissions[].secret_order`` 即 ImportError，
整轮分派炸掉、连同批合法交办一起丢。

本文件只经公开入口 ``dispatch_declaration`` 验：
- 声明新建密令 → 落一条 secret_order/新建 暂存（不是只有一条暂存交办），
  应允后案卷真成案（secret_orders 有行、案卷挂得上）；
- 差务契约不成立 → durable 拒收、零暂存，不当成成功、也不吞掉已受理的交办；
- 拒收后可由下一句重新声明并真正成案（真可重试）。
"""

from __future__ import annotations

import json

from ming_sim import audience_night as an
from ming_sim.declaration_dispatch import dispatch_declaration


def _minister(db) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' AND office_type NOT IN ('后宫','宗藩','未仕') "
        "ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _covert_task(*, target_units=3.0, effect_sign=1):
    return {
        "kind": "查案",
        "axes": ["实务事功"],
        "direction": 1,
        "delivery": {
            "unit": "人犯",
            "target_units": float(target_units),
            "person_action": "处置",
            "effect_sign": int(effect_sign),
        },
    }


def _secret_order_declaration(**overrides):
    secret = {
        "title": "查办粮科私卖",
        "content": "着即密查京师粮科私卖情弊，限三月内具实以闻。",
        "assignee": "",
        "tags": [],
        "deadline_months": 3,
        "covert_task": _covert_task(),
    }
    secret.update(overrides)
    return {"commissions": [{"text": "此事要密办，卿去查来。", "secret_order": secret}]}


def _hall_turn(db, state, minister, *, night_id):
    ctid = int(db.create_chat_turn(state, minister, "t1897", 0, night_id=int(night_id)))
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (minister, state.turn, "此事要密办，卿去查来。"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister, state.turn, "臣领旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(ctid, user_message_id=int(uid), minister_message_id=int(mid))
    return ctid


def _dispatch(db, state, minister, declaration, ctid, night_id):
    return dispatch_declaration(
        db, state, declaration,
        minister_name=minister, night_id=int(night_id), chat_turn_id=int(ctid),
    )


def _staged_secret_order_rows(db, turn):
    return db.conn.execute(
        "SELECT id, kind, action, minister_name, status, payload_json FROM pending_actions "
        "WHERE turn=? AND kind='secret_order' AND action='新建' ORDER BY id",
        (int(turn),),
    ).fetchall()


def _rejection_rows(db, turn):
    return db.conn.execute(
        "SELECT section, reason, category FROM rejection_reports "
        "WHERE turn=? AND section='commissions' ORDER BY id",
        (int(turn),),
    ).fetchall()


def test_declared_new_secret_order_lands_through_live_dispatch_and_becomes_a_case(game):
    """票面「怎么验」正路：声明新建密令不 ImportError，落暂存、应允成案、可读回。"""
    db, state, _ = game
    minister = _minister(db)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    ctid = _hall_turn(db, state, minister, night_id=night_id)

    result = _dispatch(
        db, state, minister, _secret_order_declaration(), ctid, night_id,
    )
    assert result.commissions.rejected == [], result.commissions.rejected
    assert len(result.commissions.applied) == 1

    rows = _staged_secret_order_rows(db, state.turn)
    assert len(rows) == 1, [dict(r) for r in rows]
    staged_id = int(rows[0]["id"])
    assert rows[0]["status"] == "pending"
    assert rows[0]["minister_name"] == minister
    # 口谕源轮被钉死（P6/P1：密令来源要能追到那句圣谕）。
    payload = json.loads(rows[0]["payload_json"])
    assert int(payload["origin_chat_message_id"]) > 0
    assert payload["covert_task"]["kind"] == "查案"

    # 应允即落地（ADR 0038 夜内直写白名单）。
    approved = _dispatch(
        db, state, minister,
        {"promises": [{"action_id": staged_id, "decision": "应允"}]},
        ctid, night_id,
    )
    assert approved.promises.rejected == []
    applied_row = approved.promises.applied[0]
    assert applied_row["kind"] == "secret_order" and applied_row["action"] == "新建"
    order_id = int(applied_row["secret_order_id"])
    assert order_id > 0

    order = db.get_secret_order(order_id)
    assert order is not None
    assert order["title"] == "查办粮科私卖"
    assert order["status"] == "active"
    dossier = db.get_dossier_for_secret_order(order_id)
    assert dossier is not None


def test_declared_secret_order_with_unbuildable_contract_is_rejected_not_staged(game):
    """真失败不当成功：契约缺交付身份 → durable 拒收 + 零暂存（不留注定落不了库的交办）。"""
    db, state, _ = game
    minister = _minister(db)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    ctid = _hall_turn(db, state, minister, night_id=night_id)

    bad_task = {"kind": "查案", "axes": ["实务事功"], "direction": 1,
                "delivery": {"unit": "人犯", "target_units": 2.0}}
    result = _dispatch(
        db, state, minister, _secret_order_declaration(covert_task=bad_task), ctid, night_id,
    )

    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    rejections = _rejection_rows(db, state.turn)
    assert len(rejections) == 1, [dict(r) for r in rejections]
    assert "差务契约不成立" in str(rejections[0]["reason"])
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


def test_rejected_secret_order_can_be_redeclared_and_lands_on_the_next_turn(game):
    """失败保持真实可重试：拒收后由下一句重新声明，真能成案。"""
    db, state, _ = game
    minister = _minister(db)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    ctid = _hall_turn(db, state, minister, night_id=night_id)

    bad_task = {"kind": "查案", "axes": ["实务事功"], "direction": 1,
                "delivery": {"unit": "人犯", "target_units": 2.0}}
    first = _dispatch(
        db, state, minister, _secret_order_declaration(covert_task=bad_task), ctid, night_id,
    )
    assert first.commissions.applied == []

    second = _dispatch(
        db, state, minister, _secret_order_declaration(), ctid, night_id,
    )
    assert second.commissions.rejected == []
    rows = _staged_secret_order_rows(db, state.turn)
    assert len(rows) == 1, [dict(r) for r in rows]

    approved = _dispatch(
        db, state, minister,
        {"promises": [{"action_id": int(rows[0]["id"]), "decision": "应允"}]},
        ctid, night_id,
    )
    order_id = int(approved.promises.applied[0]["secret_order_id"])
    assert db.get_secret_order(order_id)["status"] == "active"
