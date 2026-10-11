"""契约钉 #883·密令源头隔离 + #976 召对写入接缝结构分流。

密令及一切派生只进 ①密令本体表 ②接令者专用密令简报表；
不进任何共享存储；披露事件是唯一公开化通道；
公共产出 LLM 输入构建器永不预读密令。

"""

from __future__ import annotations

import pytest

from ming_sim import issues
from tests.test_month_chain_1843 import _prepare_player_month
from tests.dossier_test_helpers import create_test_secret_order


def _active_ministers(db, content):
    return [
        character
        for character in content.characters.values()
        if character.office_type not in ("后宫", "宗藩")
        and db.get_character_status(character.name)[0] == "active"
    ]


def _shared_source_body(db, source_id: str):
    row = db.conn.execute(
        "SELECT body FROM character_knowledge_sources WHERE source_id=?",
        (source_id,),
    ).fetchone()
    return None if row is None else (row["body"] or "")


def test_883_two_turn_probe_secret_never_enters_shared_archives(game, monkeypatch):
    """两回合探针：T1 下密令 → T2 结算 → 共享档无派生；接令者简报表有。

    结构保证：公共 LLM/结算叙事永不预读密令；brief 不进 knowledge_items。
    不把密令正文注入 raw 邸报再靠文本擦洗——那是被拆除的范式。
    """
    db, state, content = game
    assignee, other = _active_ministers(db, content)[:2]
    marker = "乙巳密查内廷账目883探针"

    oid = create_test_secret_order(db, state, assignee.name, "乙巳密查", marker, [])
    assert oid > 0

    # T1 → T2：月链供料提供合资格案卷完整月报，公开叙事不预读密令。
    reports = [
        {"dossier_id": int(item["dossier_id"]), "progress_band": "持平",
         "memorial_text": "本月密奏已达"}
        for item in db.list_monthly_dossier_progress_nudges(state.turn)
    ]
    player = _prepare_player_month(
        db, state, content, monkeypatch,
        secret_orders_supply=lambda *a, **k: {"dossier_progress_reports": reports},
    )
    player.resolve_turn(allow_empty_decree=True)
    db.save_turn_report(state, "邸报", public_body="邸报")
    player.resolve_turn(allow_empty_decree=True)

    brief = db.conn.execute(
        "SELECT body, minister_name FROM secret_order_briefs WHERE order_id=?", (oid,)
    ).fetchone()
    source_count = db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id LIKE 'secret_order:%'"
    ).fetchone()[0]
    assert brief is not None
    assert brief["minister_name"] == assignee.name
    assert source_count == 0
    assert not any(
        str(item.get("source_id") or "").startswith("secret_order:")
        for item in db.get_character_knowledge(state, other.name)["events"]
    )


def test_883_shared_summary_write_seam_rejects_secret_order_source(game):
    """共享汇总写入接缝单点拒收：secret_order 不得进 character_knowledge_sources。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    marker = "共享源拒收密令正文883"

    raised = False
    try:
        db.register_character_knowledge_source(
            state,
            [{"character_id": assignee.name, "tier": "主办"}],
            "secret_order",
            "密查",
            marker,
            source_id="secret_order:force-shared",
        )
    except ValueError:
        raised = True

    count = db.conn.execute(
        "SELECT COUNT(*) FROM character_knowledge_sources WHERE source_id LIKE 'secret_order:%'"
    ).fetchone()[0]
    # #883 write seam raises ValueError on secret_order kind/source_id (loud reject).
    assert raised
    assert count == 0


def test_883_shared_write_seam_keeps_public_assignee_audience(game):
    """接令者身份不改变公开 audience 行本身的 provenance。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    marker = "已存简报原话不得再入共享883"

    oid = create_test_secret_order(db, state, assignee.name, "密查简报", marker, [])
    assert oid > 0

    db.register_character_knowledge_source(
        state,
        [{"character_id": assignee.name}],
        "audience",
        "召对",
        f"臣复述密旨：{marker}",
        source_id="chat_message:replay-secret",
    )
    assert _shared_source_body(db, "chat_message:replay-secret") == f"臣复述密旨：{marker}"


def test_883_only_explicit_leak_conclusion_promotes_secret_order_to_public(game):
    """泄漏接线：无泄漏结论不公开；显式泄漏结论 → 披露事件 → 进入公共面。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    oid = create_test_secret_order(db, state, assignee.name, "密查盐案", "甲子密查盐案883", [])

    hidden = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [{"order_id": oid, "sim_note": "风声渐起"}]},
        content=content,
    )
    assert hidden["secret_order_updates"][0]["disclosed"] is False
    assert not any(
        str(item.get("source_id") or "").startswith("secret_order_disclosure:")
        for item in db._character_knowledge_events("")
    )

    shown = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [
            {"order_id": oid, "sim_note": "密事已公开883", "disclosed": True},
        ]},
        content=content,
    )
    assert shown["secret_order_updates"][0]["disclosed"] is True
    prefix = f"secret_order_disclosure:{oid}:"
    disclosed = [
        item for item in db._character_knowledge_events("")
        if str(item.get("source_id") or "").startswith(prefix)
    ]
    assert len(disclosed) == 1


def test_883_cross_turn_repeat_disclosed_does_not_mint_duplicate_public_event(game):
    """跨回合幂等：同一密令多次 disclosed=true 只留一条 secret_order_disclosure 事件。"""
    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    oid = create_test_secret_order(db, state, assignee.name, "密查仓案", "丙寅密查仓案883", [])

    first = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [
            {"order_id": oid, "sim_note": "首度公开883", "disclosed": True},
        ]},
        content=content,
    )
    assert first["secret_order_updates"][0]["disclosed"] is True
    prefix = f"secret_order_disclosure:{oid}:"
    after_first = [
        item for item in db._character_knowledge_events("")
        if str(item.get("source_id") or "").startswith(prefix)
    ]
    assert len(after_first) == 1
    assert after_first[0].get("body") == "首度公开883"

    # Advance turn so source_id turn suffix would differ if re-inserted.
    state.turn = int(state.turn) + 1
    second = issues.apply_score_extraction(
        db, state,
        {"secret_order_updates": [
            {"order_id": oid, "sim_note": "再次填写泄漏结论883", "disclosed": True},
        ]},
        content=content,
    )
    assert second["secret_order_updates"][0]["disclosed"] is True
    after_second = [
        item for item in db._character_knowledge_events("")
        if str(item.get("source_id") or "").startswith(prefix)
    ]
    assert len(after_second) == 1
    assert after_second[0]["source_id"] == after_first[0]["source_id"]
    assert after_second[0].get("body") == "首度公开883"


def test_976_non_create_pure_public_not_auto_pinned_as_secret_origin(game):
    """Non-create actions without explicit oral pins do not invent provenance."""
    import json as _json

    db, state, content = game
    speaker, assignee = _active_ministers(db, content)[:2]
    public_q = "近来京营操练如何？先催办前令。"

    for action, payload, same_person in (
        (
            "催办",
            {"deadline_months": 1, "reason": "御限收紧"},
            False,
        ),
        (
            "记进展",
            {"note": "已密访东城典当三处。"},
            True,
        ),
    ):
        minister = assignee.name if same_person else speaker.name
        oid = create_test_secret_order(db,
            state, assignee.name, f"密查-{action}", f"暗访-{action}。", [],
            deadline_months=6,
        )
        assert oid > 0
        db.append_chat_message(minister, state.turn, "user", public_q)
        pid = db.stage_pending_action(
            state.turn, kind="secret_order", action=action,
            minister_name=minister, target_id=oid,
            payload=dict(payload),
        )
        staged = db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
        ).fetchone()
        staged_payload = _json.loads(staged["payload_json"] or "{}")
        # 非新建无显式 pin → 不得把纯公开问话钉成 origin
        assert staged_payload.get("origin_chat_message_id") in (None, "", 0), (
            f"{action}: auto-pinned pure public as origin"
        )

        applied = db.commit_pending_actions(
            state, minister_name=minister, action_ids={pid}, content=content,
        )
        assert applied and applied[0]["kind"] == "secret_order", action


def test_976_rt04_undo_chat_turn_secret_order_brief_consistent(game):
    """红队④ should：undo 含密令口谕 — secret_orders 与 secret_order_briefs 回滚一致。

    真实 undo 删除密令父行后由 FK CASCADE 删除 brief；其它密令不受影响。
    """
    db, state, content = game
    a, b = _active_ministers(db, content)[:2]
    marker = "undo密令正文：密查火器局虚报-UNDO976"
    public_early = "臣报：漕运无阻-先轮公开976"

    ctid_early = db.create_chat_turn(state, b.name, "sess-early-976", 0)
    snap0 = db.capture_chat_rollback_snapshot()
    mid_b_pub = db.append_chat_message(b.name, state.turn, "minister", public_early)
    db.update_chat_turn_messages(ctid_early, minister_message_id=mid_b_pub)
    db.record_chat_turn_rollback_diffs(
        ctid_early, snap0, db.capture_chat_rollback_snapshot(),
    )
    unrelated_oid = create_test_secret_order(db,
        state, b.name, "巡查漕运", "未撤销密令正文-KEEP1026", [],
    )

    ctid = db.create_chat_turn(state, a.name, "sess-secret-undo-976", 0)
    before = db.capture_chat_rollback_snapshot()
    mid_u = db.append_chat_message(a.name, state.turn, "user", marker)
    mid_m = db.append_chat_message(
        a.name, state.turn, "minister", "臣领密旨，即查火器局。",
    )
    db.update_chat_turn_messages(ctid, user_message_id=mid_u, minister_message_id=mid_m)
    oid = create_test_secret_order(
        db, state, a.name, "密查火器局", marker, [],
        origin_chat_message_id=mid_u,
    )
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ctid, before, after)

    assert oid > 0
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone()[0] == 1
    assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    undone = db.undo_chat_turn(ctid)
    assert undone is not None
    assert int(undone.get("id") or 0) == ctid
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["status"] == "undone"

    order_left = db.conn.execute(
        "SELECT COUNT(*) FROM secret_orders WHERE id=?", (oid,),
    ).fetchone()[0]
    brief_left = db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id=?", (oid,),
    ).fetchone()[0]
    msg_u = db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE id=?", (mid_u,),
    ).fetchone()[0]
    msg_m = db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE id=?", (mid_m,),
    ).fetchone()[0]
    msg_b = db.conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE id=?", (mid_b_pub,),
    ).fetchone()[0]

    assert order_left == 0, f"secret_orders survived undo count={order_left}"
    assert brief_left == 0, f"secret_order_briefs orphan after undo count={brief_left}"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM secret_order_briefs WHERE order_id=?", (unrelated_oid,),
    ).fetchone()[0] == 1, "未撤销密令的 brief 不应受级联影响"
    assert msg_u == 0 and msg_m == 0
    assert msg_b == 1, "early B public message wrongly deleted"


@pytest.mark.parametrize("rollback_entry", ["undo_chat_turn", "fail_chat_turn"])
def test_1026_secret_order_update_rollback_restores_existing_brief(game, rollback_entry):
    db, state, content = game
    minister = _active_ministers(db, content)[0]
    old_message_id = db.append_chat_message(
        minister.name, state.turn, "user", "旧令：密查旧案",
    )
    order_id = create_test_secret_order(db,
        state, minister.name, "旧密令", "旧密文", [],
        origin_chat_message_ids=[old_message_id],
    )
    old_brief = dict(db.conn.execute(
        "SELECT title, body, origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (order_id,),
    ).fetchone())

    chat_turn_id = db.create_chat_turn(state, minister.name, f"{rollback_entry}-1026", 0)
    before = db.capture_chat_rollback_snapshot()
    user_message_id = db.append_chat_message(
        minister.name, state.turn, "user", "改令：转查新案",
    )
    minister_message_id = db.append_chat_message(
        minister.name, state.turn, "minister", "臣领修改后的密旨。",
    )
    db.update_chat_turn_messages(
        chat_turn_id,
        user_message_id=user_message_id,
        minister_message_id=minister_message_id,
    )
    assert db.update_secret_order_by_id(
        state, order_id, "新密令", "新密文", [],
        origin_chat_message_id=user_message_id,
    )
    db.record_chat_turn_rollback_diffs(
        chat_turn_id, before, db.capture_chat_rollback_snapshot(),
    )

    getattr(db, rollback_entry)(chat_turn_id)

    restored_order = db.conn.execute(
        "SELECT title, content FROM secret_orders WHERE id=?", (order_id,),
    ).fetchone()
    restored_brief = db.conn.execute(
        "SELECT title, body, origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (order_id,),
    ).fetchone()
    assert dict(restored_order) == {"title": "旧密令", "content": "旧密文"}
    assert dict(restored_brief) == old_brief


def test_976_save_restore_preserves_oral_provenance(game, tmp_path):
    """Save and restore preserve the secret order, brief, and exact oral source pin."""
    import os

    db, state, content = game
    a = _active_ministers(db, content)[0]
    marker = "存档夹心密令：密查驿递虚冒-SAVE976"
    mid_u = db.append_chat_message(a.name, state.turn, "user", marker)
    oid = create_test_secret_order(
        db, state, a.name, "密查驿递", marker, [],
        origin_chat_message_id=mid_u,
    )
    # 备份落本用例私有目录：db.path 在系统共享 temp，同级写文件不留用例隔离（#1901 J6）。
    backup_path = str(tmp_path / "backup976.db")
    db.backup_to(backup_path)
    db.close()

    db2 = __import__("ming_sim.db", fromlist=["GameDB"]).GameDB(backup_path, content)
    try:
        state2 = db2.load_state()
        brief = db2.conn.execute(
            "SELECT body, origin_chat_message_ids FROM secret_order_briefs "
            "WHERE order_id=?",
            (oid,),
        ).fetchone()
        order = db2.conn.execute(
            "SELECT status FROM secret_orders WHERE id=?", (oid,),
        ).fetchone()
        assert order is not None and order["status"] == "active"
        assert brief is not None and (brief["body"] or "") == marker
        import json as _json
        pins = _json.loads(brief["origin_chat_message_ids"] or "[]")
        assert mid_u in pins

        assert state2.turn == state.turn
    finally:
        db2.close()
        if os.path.exists(backup_path):
            os.remove(backup_path)


def test_976_message_level_origin_persisted_on_brief(game):
    """契约：密令分类后 brief.origin_chat_message_ids 持久化消息级血缘。"""
    import json as _json

    db, state, content = game
    assignee = _active_ministers(db, content)[0]
    secret_q = "着尔密访国丈家产虚实，勿使外廷知-provenance976"
    mid = db.append_chat_message(assignee.name, state.turn, "user", secret_q)
    oid = create_test_secret_order(db,
        state, assignee.name, "密查国丈", "暗访国丈家产", [],
        origin_chat_message_id=mid,
    )
    brief = db.conn.execute(
        "SELECT origin_chat_message_ids FROM secret_order_briefs WHERE order_id=?",
        (oid,),
    ).fetchone()
    pins = _json.loads(brief["origin_chat_message_ids"] or "[]")
    assert pins == [mid]
