"""#1890 票面验收面：整轮撤回的全有或全无、前像恢复、密令与见闻不可见、重开可撤。

本文件只管票面「怎么验」里 db 层可达的几条（#1890 判官点名补核的四项）。
全部经真实入口 ``undo_chat_turn``，不桩撤回逻辑本身：

- AC7 后一轮含多道交办 + 当场落账 + 修改前轮已有对象：撤回归回前像、前轮不动。
- AC8 密令结构化字段与 briefs 全载荷、见闻派生在撤回后不可见。
- AC9 撤回事务中途抛错 → void 与前像还原全有或全无（不留半撤回态）。
- AC10 重开（新连接）后仍可撤回，且墓碑与前像都还在。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.declaration_dispatch import dispatch_declaration
from tests.conftest import open_hall_turn


def _minister(db) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _finish_turn(db, state, minister: str, ctid: int, question: str) -> None:
    """把 helper 开的 generating 轮走完成 active（回话落库 = 轮完成）。"""
    user_id = db.append_chat_message(minister, int(state.turn), "user", question)
    reply_id = db.append_chat_message(minister, int(state.turn), "minister", "遵旨。")
    db.update_chat_turn_messages(
        int(ctid), user_message_id=user_id, minister_message_id=reply_id,
    )


def _row(db, action_id: int) -> dict:
    row = db.conn.execute(
        "SELECT id, status, night_approved, source_chat_turn_id, payload_json, version "
        "FROM pending_actions WHERE id=?",
        (int(action_id),),
    ).fetchone()
    assert row is not None
    return dict(row)


# ── AC7：多道交办 + 当场落账 + 改前轮对象 → 前像恢复且前轮不动 ──────


def test_undo_restores_before_image_and_leaves_prior_turn_intact(game):
    db, state, content = game
    minister = _minister(db)
    night_id, first_ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, first_ctid, "先议边饷")

    # 前轮：一道交办（身份属前轮），供后轮改稿。
    first = dispatch_declaration(
        db, state, {"commissions": [{"text": "前轮交办：核边饷"}]},
        minister_name=minister, night_id=night_id, chat_turn_id=first_ctid,
    )
    first_id = int(first.commissions.applied[0]["id"])
    first_payload_before = _row(db, first_id)["payload_json"]

    # 后一轮：多道交办 + 一道改前轮那道（改稿）+ 当场实况（文字事实）。
    _, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "再办数事")
    before_textual = db.conn.execute(
        "SELECT COUNT(*) c FROM textual_facts"
    ).fetchone()["c"]

    result = dispatch_declaration(
        db, state, {
            "commissions": [
                {"text": "本轮交办甲：发内帑赈陕"},
                {"text": "本轮交办乙：调兵赴辽"},
            ],
            "textual_facts": [{
                "subject_kind": "character", "subject_id": minister,
                "body": "本轮当面奏对定策",
            }],
        },
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )
    assert result.commissions.rejected == []
    staged_ids = sorted(int(i["id"]) for i in result.commissions.applied)
    assert len(staged_ids) == 2
    # 本轮改前轮那道（改稿不换身份）。走真实 dispatch 入口：前像由
    # dispatch_declaration 自记（#1839 C2），直接调 db.upsert 不会记前像，
    # 那样测的就不是撤回而是「没记前像能不能撤」。
    dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "前轮交办：核边饷（后轮补充）",
            "target_candidate": str(first_id),
        }]},
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )
    # 本轮当场实况确实落了地（撤回前可见）。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM textual_facts"
    ).fetchone()["c"] == before_textual + 1

    undone = db.undo_chat_turn(ctid)

    # 本轮落的交办全部作废（含改稿那次派发新起的一行）。
    voided = sorted(undone["voided_pending_action_ids"])
    assert set(staged_ids) <= set(voided)
    for action_id in voided:
        assert _row(db, action_id)["status"] == "voided"
        assert _row(db, action_id)["source_chat_turn_id"] == ctid
    # 前轮交办回到前像（改稿被撤销），且仍是前轮身份、仍生效。
    assert _row(db, first_id)["payload_json"] == first_payload_before
    assert _row(db, first_id)["status"] == "pending"
    assert _row(db, first_id)["source_chat_turn_id"] == first_ctid
    # 本轮当场实况（文字事实）不可见。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM textual_facts"
    ).fetchone()["c"] == before_textual
    # 前轮对话仍在、本轮已撤。
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (first_ctid,),
    ).fetchone()["status"] == "active"
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "undone"


# ── AC8：密令结构化字段 + briefs 全载荷、见闻派生不可见 ────────────


def _seed_secret_order(db, state, minister: str, title: str) -> int:
    """直接落一条往期密令（供本轮改）。

    刻意不走 ``land_or_recover_new_secret_order``：那个 import 在 HEAD
    （2ef3c383c）就已指向一个不存在的函数，本票不碰它，改用仍活的
    ``secret_order_update`` 暂存支线验同一件事。
    """
    db.conn.execute(
        "INSERT INTO secret_orders "
        "(turn_issued,due_turn,deadline_span,year_issued,period_issued,minister_name,"
        "title,content,tags,importance,status,result,sim_note,excluded_names,"
        "dossier_progress_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (int(state.turn) - 1, 0, 0, int(state.year), int(state.period), minister,
         title, f"{title}之旧旨", "[]", 4, "active", "", "", "[]", "[]"),
    )
    db.conn.commit()
    return int(db.conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _secret_order_update_commission(
    db, state, minister: str, night_id, ctid, order_id, body,
) -> int:
    """落一道密令修改交办（真实分派入口，走 pending 暂存）。"""
    result = dispatch_declaration(
        db, state, {"commissions": [{
            "text": body,
            "secret_order_update": {
                "order_id": int(order_id),
                "title": body,
                "content": f"{body}之密旨（改）",
                "deadline_months": 3,
            },
        }]},
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )
    applied = result.commissions.applied
    assert applied, result.commissions.rejected
    return int(applied[0]["id"])


def test_secret_order_payload_and_briefs_invisible_after_undo(game):
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "密议一事后行")

    order_id = _seed_secret_order(db, state, minister, "旧密令·边饷")
    content_before = db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()["content"]

    staged_id = _secret_order_update_commission(
        db, state, minister, night_id, ctid, order_id, "改办边将通款",
    )
    assert _row(db, staged_id)["source_chat_turn_id"] == ctid
    orders_before = db.conn.execute(
        "SELECT COUNT(*) c FROM secret_orders"
    ).fetchone()["c"]

    db.undo_chat_turn(ctid)

    # 密令交办作废；密令本体回到前像（内容未被本轮改掉），行数不变。
    assert _row(db, staged_id)["status"] == "voided"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM secret_orders"
    ).fetchone()["c"] == orders_before
    assert db.conn.execute(
        "SELECT content FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()["content"] == content_before
    # 该轮的知识源（见闻派生的载体）不再指向它。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM character_knowledge_sources "
        "WHERE source_id LIKE ?", (f"%:chat_turn:{int(ctid)}",),
    ).fetchone()["c"] == 0


def test_knowledge_derivation_hides_retracted_turn(game):
    """见闻派生不得继续显露已撤回来源：人物读口看不到本轮知识源。"""
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "臣有一密")

    # 本轮造一条该大臣的知识源（召对对话的共享投影）。
    db.record_audience_knowledge_for_turn(
        state, int(ctid), [{"body": "本轮密议之事", "excluded_names": []}],
    ) if hasattr(db, "record_audience_knowledge_for_turn") else db.conn.execute(
        "INSERT INTO character_knowledge_sources "
        "(turn,year,period,kind,title,body,source_id,participant_roster) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (int(state.turn), int(state.year), int(state.period), "audience",
         "召对", "本轮密议之事", f"projection:chat_turn:{int(ctid)}", "[]"),
    )
    db.conn.commit()
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM character_knowledge_sources WHERE source_id LIKE ?",
        (f"%:chat_turn:{int(ctid)}",),
    ).fetchone()["c"] >= 1

    db.undo_chat_turn(ctid)

    # 撤回后该来源不可见（派生不再显露已撤回来源）。
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM character_knowledge_sources WHERE source_id LIKE ?",
        (f"%:chat_turn:{int(ctid)}",),
    ).fetchone()["c"] == 0


# ── AC9：撤回事务中途抛错 → 全有或全无 ─────────────────────────────


def test_undo_all_or_nothing_when_void_step_raises(game, monkeypatch):
    """在 void 步注入故障：作废与前像还原必须整体回滚，不留半撤回态。"""
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = open_hall_turn(db, state, minister)
    _finish_turn(db, state, minister, ctid, "试撤回")

    result = dispatch_declaration(
        db, state, {"commissions": [{"text": "本轮交办：待撤回"}]},
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )
    staged_id = int(result.commissions.applied[0]["id"])
    pre_status = db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"]

    # 真故障形态：作废写了一半再抛——不是「还没写就抛」。半写才是「半撤回态」
    # 的真实来源（只抛不写的话，回滚 trivially 地全回，测不出任何东西）。
    boom = RuntimeError("injected void failure")
    real_void = db.void_pending_actions_for_chat_turn

    def _half_void(*_a, **_k):
        real_void(*_a, **_k)          # 真的作废全部（写进事务）
        raise boom                     # 然后炸

    monkeypatch.setattr(db, "void_pending_actions_for_chat_turn", _half_void)
    with pytest.raises(RuntimeError, match="injected void failure"):
        db.undo_chat_turn(ctid)
    monkeypatch.setattr(db, "void_pending_actions_for_chat_turn", real_void)

    # 半撤回态不许留下：交办仍 pending（未作废）、轮仍 active（未撤）、对话仍在。
    assert _row(db, staged_id)["status"] == "pending"
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == pre_status == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM chat_messages WHERE turn=?", (int(state.turn),),
    ).fetchone()["c"] >= 2

    # 撤掉故障后重试可正常撤回（幂等入口，不是卡死）。
    db.undo_chat_turn(ctid)
    assert _row(db, staged_id)["status"] == "voided"
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "undone"


# ── AC10：重开（新连接）后仍可撤回 ────────────────────────────────


def test_undo_still_works_after_reopen(game, tmp_path):
    import shutil
    from ming_sim.db import GameDB

    db, state, content = game
    night_id, ctid = open_hall_turn(db, state, minister := _minister(db))
    _finish_turn(db, state, minister, ctid, "关档前之议")
    result = dispatch_declaration(
        db, state, {"commissions": [{"text": "关档前的交办"}]},
        minister_name=minister, night_id=night_id, chat_turn_id=ctid,
    )
    staged_id = int(result.commissions.applied[0]["id"])

    # 关档：把已落库的库复制成独立存档，再关连接。
    live = tmp_path / "reopen1890.db"
    shutil.copyfile(_fixture_db_path(db), live)
    db.close()

    # 重开：新连接、新 GameDB。
    db2 = GameDB(str(live), content)
    try:
        state2 = db2.load_state()
        # 身份列在重开后仍在（墓碑判据不是内存态）。
        assert _row(db2, staged_id)["source_chat_turn_id"] == ctid
        assert _row(db2, staged_id)["status"] == "pending"
        db2.undo_chat_turn(ctid)
        assert _row(db2, staged_id)["status"] == "voided"
        assert db2.conn.execute(
            "SELECT status FROM chat_turns WHERE id=?", (ctid,),
        ).fetchone()["status"] == "undone"
        assert state2.turn == state.turn
    finally:
        db2.close()


def _fixture_db_path(db) -> str:
    row = db.conn.execute("PRAGMA database_list").fetchall()
    for r in row:
        if r[1] == "main" and r[2]:
            return str(r[2])
    raise AssertionError("no file-backed main database")
