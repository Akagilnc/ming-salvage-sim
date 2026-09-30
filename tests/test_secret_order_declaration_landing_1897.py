"""#1897 转译声明新建密令走现役分派入口（不导入已删函数），失败真实可重试。

刀口：``declaration_dispatch._dispatch_commissions`` 的 ``secret_order`` 支路。
此前它导入 ``action_materialize.land_or_recover_new_secret_order``（已随
``e2fc6369d`` 删除），一旦转译声明 ``commissions[].secret_order`` 即 ImportError，
整轮分派炸掉、连同批合法交办一起丢。

本文件只经公开入口验行为，不盯诊断措辞：
- 声明新建密令 → 落一条 secret_order/新建 暂存，应允后案卷真成案（可读回）；
- 差务契约不成立 / 缺具名承办人 / 可选集合字段坏类型 → durable 拒收、零暂存，
  同批合法交办照落（坏项不带走整批）；
- 密令正文原样落库（判空不改存储值）；
- 补译交办承接源夜：夜收后补译暂存仍属源夜，应允照常成案；
- 成案真失败不当成功：原 action_id 保留可重试，故障解除后同一 id 成案。
"""

from __future__ import annotations

import json

import pytest

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


def _secret(**overrides):
    secret = {
        "title": "查办粮科私卖",
        "content": "着即密查京师粮科私卖情弊，限三月内具实以闻。",
        "tags": [],
        "deadline_months": 3,
        "covert_task": _covert_task(),
    }
    secret.update(overrides)
    return secret


def _secret_order_declaration(**overrides):
    return {
        "commissions": [
            {"text": "此事要密办，卿去查来。", "secret_order": _secret(**overrides)},
        ],
    }


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


def _approve(db, state, minister, ctid, night_id, action_id):
    return _dispatch(
        db, state, minister,
        {"promises": [{"action_id": int(action_id), "decision": "应允"}]},
        ctid, night_id,
    )


def _open_night(db, state, minister):
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    return night_id, _hall_turn(db, state, minister, night_id=night_id)


def _staged_secret_order_rows(db, turn):
    return db.conn.execute(
        "SELECT id, kind, action, minister_name, status, night_id, payload_json "
        "FROM pending_actions "
        "WHERE turn=? AND kind='secret_order' AND action='新建' ORDER BY id",
        (int(turn),),
    ).fetchall()


def _rejection_rows(db, turn, section="commissions"):
    return db.conn.execute(
        "SELECT section, reason, category FROM rejection_reports "
        "WHERE turn=? AND section=? ORDER BY id",
        (int(turn), section),
    ).fetchall()


def test_declared_new_secret_order_lands_through_live_dispatch_and_becomes_a_case(game):
    """票面「怎么验」正路：声明新建密令不 ImportError，落暂存、应允成案、可读回。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    result = _dispatch(
        db, state, minister, _secret_order_declaration(assignee=minister), ctid, night_id,
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
    approved = _approve(db, state, minister, ctid, night_id, staged_id)
    assert approved.promises.rejected == []
    applied_row = approved.promises.applied[0]
    assert applied_row["kind"] == "secret_order" and applied_row["action"] == "新建"
    order_id = int(applied_row["secret_order_id"])
    assert order_id > 0

    order = db.get_secret_order(order_id)
    assert order is not None
    assert order["title"] == "查办粮科私卖"
    assert order["status"] == "active"
    assert db.get_dossier_for_secret_order(order_id) is not None


def test_secret_order_free_text_is_stored_verbatim(game):
    """P6 零删改：标题与正文一视同仁，暂存与成案都存原文（含前后空白换行）。

    判空在副本上做，存储值不被改动——上一轮只保住了 content，标题在暂存
    与 ``_apply_pending_action`` 两处各被 strip 一次，本轮一并修净。
    """
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)
    raw_title = "  查办粮科私卖  "
    raw_body = "\n  密查粮科私卖。  \n"

    result = _dispatch(
        db, state, minister,
        _secret_order_declaration(
            assignee=minister, title=raw_title, content=raw_body,
        ),
        ctid, night_id,
    )
    assert result.commissions.rejected == [], result.commissions.rejected
    rows = _staged_secret_order_rows(db, state.turn)
    staged_id = int(rows[0]["id"])
    staged = json.loads(rows[0]["payload_json"])
    # 暂存即原文（未暂存前就被裁）。
    assert staged["title"] == raw_title
    assert staged["content"] == raw_body

    _approve(db, state, minister, ctid, night_id, staged_id)
    order_id = int(db.conn.execute(
        "SELECT secret_order_id FROM decree_dossiers "
        "WHERE pending_action_id=? AND secret_order_id IS NOT NULL",
        (staged_id,),
    ).fetchone()["secret_order_id"])
    order = db.get_secret_order(order_id)
    # 成案仍是原文（apply 路径不再二次 strip）。
    assert order["title"] == raw_title
    assert order["content"] == raw_body


def test_blank_secret_order_title_is_rejected_not_staged(game):
    """判空仍按副本做：纯空白标题拒收，不暂存、不成案。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    result = _dispatch(
        db, state, minister,
        _secret_order_declaration(assignee=minister, title="   \n  "),
        ctid, night_id,
    )
    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_shape"
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


def test_bad_secret_order_is_rejected_without_staging_or_landing(game):
    """真失败不当成功：契约缺交付身份 → durable 拒收 + 零暂存（不留注定落不了库的交办）。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    bad_task = {"kind": "查案", "axes": ["实务事功"], "direction": 1,
                "delivery": {"unit": "人犯", "target_units": 2.0}}
    result = _dispatch(
        db, state, minister,
        _secret_order_declaration(assignee=minister, covert_task=bad_task),
        ctid, night_id,
    )

    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    rejections = _rejection_rows(db, state.turn)
    assert len(rejections) == 1, [dict(r) for r in rejections]
    # 断言分类而非诊断措辞：措辞是给人看的，行为才是契约。
    assert rejections[0]["category"] == "invalid_shape"
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


def test_scene_speaker_without_roster_assignee_is_not_made_into_a_minister(game):
    """ADR 0153:5：场景标签不是人物身份。整场轮无具名承办人 → 拒收，不写 order_minister=殿上。"""
    db, state, _ = game
    speaker = an.SCENE_CHAT_SPEAKER
    night_id, ctid = _open_night(db, state, speaker)

    result = _dispatch(
        db, state, speaker, _secret_order_declaration(assignee=""), ctid, night_id,
    )
    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_state"
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


@pytest.mark.parametrize("bad_tags", [7, [7]], ids=["whole_field", "element"])
def test_bad_optional_list_field_rejects_only_its_own_item(game, bad_tags):
    """ADR 0005:12：可选集合字段类型错只拒该项，同批合法交办照落（不带走整批）。

    整体非序列（``tags=7``）与元素非字符串（``tags=[7]``）都是脏数据：都拒本项，
    都不许 ``str()`` 强转蒙混过关。
    """
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    declaration = {
        "commissions": [
            {"text": "此事要密办，卿去查来。",
             "secret_order": _secret(assignee=minister, tags=bad_tags)},
            {"text": "此事要密办，卿去查来。", "secret_order": _secret(assignee=minister)},
        ],
    }
    result = _dispatch(db, state, minister, declaration, ctid, night_id)

    assert len(result.commissions.rejected) == 1, result.commissions.rejected
    assert result.commissions.rejected[0].category == "invalid_shape"
    assert len(result.commissions.applied) == 1
    # 唯一暂存的那条就是同批合法项——坏项没留下任何东西，也没带走好项。
    rows = _staged_secret_order_rows(db, state.turn)
    assert len(rows) == 1, [dict(r) for r in rows]
    assert json.loads(rows[0]["payload_json"])["covert_task"]["kind"] == "查案"


def test_late_translation_staged_secret_order_still_lands_under_its_source_night(game):
    """ADR 0038 后出注记：迟到的转译在过月前补齐，应允照常成案（暂存承接源夜）。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    # 先把这一夜收掉——补译发生在夜收之后。
    an.close_night(db, state, night_id=int(night_id))
    assert an.get_open_night(db) is None

    result = _dispatch(
        db, state, minister, _secret_order_declaration(assignee=minister), ctid, night_id,
    )
    assert result.commissions.rejected == [], result.commissions.rejected
    rows = _staged_secret_order_rows(db, state.turn)
    assert len(rows) == 1, [dict(r) for r in rows]
    assert int(rows[0]["night_id"]) == int(night_id)

    approved = _approve(db, state, minister, ctid, night_id, int(rows[0]["id"]))
    assert approved.promises.rejected == [], approved.promises.rejected
    order_id = int(approved.promises.applied[0]["secret_order_id"])
    assert db.get_secret_order(order_id)["status"] == "active"


def test_frozen_contract_examples_are_consumable_and_sign_semantics_hold():
    """差务契约真源自身可消费：样例真被 ``build_covert_task_contract`` 收下，
    且钱粮符号语义按实现判定（+1 收入 / -1 支出，收入不得写补饷）。

    #1897 R4：原用例把 prompt 里的字段名、样例序列化文本、措辞逐字断言钉在
    一处（改个等义措辞即红），那是盯文不是对行为负责，已整段删除。此处只对
    真源的消费行为负责——生产 prompt 由 ``describe_covert_task_contract``
    投影这份真源，说明与实现分叉由那里的单一真源保证。
    """
    from ming_sim.covert_progress import (
        _CONTRACT_EXAMPLES, build_covert_task_contract,
    )

    for sample in _CONTRACT_EXAMPLES:
        build_covert_task_contract(covert_task=sample)

    # 收入（+1）不得声明为补饷支出：真源按此拒收，不是 prompt 措辞问题。
    with pytest.raises(Exception):
        build_covert_task_contract(covert_task={
            "kind": "抄家入帑", "axes": ["实务事功"], "direction": 1,
            "delivery": {
                "unit": "万两", "target_units": 1, "effect_sign": 1,
                "purpose": "补饷", "category": "密令差务", "account": "内库",
            },
        })


def test_failed_landing_keeps_the_original_pending_action_retryable(game, monkeypatch):
    """#1897：真实成案失败不当成功，且原待办保留可重试——同一 action_id 故障解除后成案。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    result = _dispatch(
        db, state, minister, _secret_order_declaration(assignee=minister), ctid, night_id,
    )
    assert result.commissions.rejected == []
    staged_id = int(_staged_secret_order_rows(db, state.turn)[0]["id"])

    # 注入一次真实的成案失败：commit_pending_actions 会把该行标 failed。
    from ming_sim.db import GameDB
    real_apply = GameDB._apply_pending_action

    def _boom(self, *args, **kwargs):
        raise RuntimeError("injected landing failure")

    monkeypatch.setattr(GameDB, "_apply_pending_action", _boom)
    try:
        failed = _approve(db, state, minister, ctid, night_id, staged_id)
    finally:
        monkeypatch.setattr(GameDB, "_apply_pending_action", real_apply)

    assert failed.promises.applied == [], failed.promises.applied
    assert len(failed.promises.rejected) == 1
    # 归类按真实失败原因：落库失败不是「实体状态不容许」（R1）。
    assert _rejection_rows(db, state.turn, "promises")[-1]["category"] == "commit_failed"
    assert db.list_secret_orders() == []
    # 原暂存仍是 pending：不是 failed 死行，同一 id 可再应允。
    status = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"]
    assert status == "pending", status

    retried = _approve(db, state, minister, ctid, night_id, staged_id)
    assert retried.promises.rejected == [], retried.promises.rejected
    order_id = int(retried.promises.applied[0]["secret_order_id"])
    assert db.get_secret_order(order_id)["status"] == "active"


def test_approved_rush_reports_success_and_is_not_repeated(game):
    """R1：密令催办应允成功即成功——不因「新建才有」的 order_id 判据被误报失败。

    真实症状：applied=[] / rejected=[invalid_state] / status 被倒回 pending，
    再次应允又把同一条催办写了一遍。
    """
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    _dispatch(db, state, minister, _secret_order_declaration(assignee=minister),
              ctid, night_id)
    order_id = int(
        _approve(db, state, minister, ctid, night_id,
                 int(_staged_secret_order_rows(db, state.turn)[0]["id"]))
        .promises.applied[0]["secret_order_id"]
    )

    def _rush():
        return _dispatch(db, state, minister, {"rushes": [{
            "target_kind": "secret_order", "target_id": order_id,
            "deadline_months": 1, "reason": "着即催办",
        }]}, ctid, night_id)

    rushed = _rush()
    assert rushed.rushes.rejected == [], rushed.rushes.rejected
    staged_id = int(rushed.rushes.applied[0]["id"])

    approved = _approve(db, state, minister, ctid, night_id, staged_id)
    assert approved.promises.rejected == [], approved.promises.rejected
    assert len(approved.promises.applied) == 1
    status = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"]
    assert status == "committed", status

    # 已成功落库的催办不再执行一遍：同一 id 不在 pending 清单里。
    again = _approve(db, state, minister, ctid, night_id, staged_id)
    assert again.promises.applied == [], again.promises.applied


def test_declared_secret_order_keeps_legal_dossier_links(game):
    """R2：合法案卷关联保持可消费——成案后关联真落库，不被当脏数据整条拒收。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    # 先立一个旧案卷供新案卷指向。
    _dispatch(db, state, minister, _secret_order_declaration(assignee=minister),
              ctid, night_id)
    old_order_id = int(
        _approve(db, state, minister, ctid, night_id,
                 int(_staged_secret_order_rows(db, state.turn)[0]["id"]))
        .promises.applied[0]["secret_order_id"]
    )
    old_dossier_id = int(db.get_dossier_for_secret_order(old_order_id)["id"])

    result = _dispatch(db, state, minister, _secret_order_declaration(
        assignee=minister, title="再查一桩", dossier_links=[{
            "target_dossier_id": old_dossier_id,
            "relation_type": "稽核", "note": "并案同查",
        }],
    ), ctid, night_id)
    assert result.commissions.rejected == [], result.commissions.rejected

    staged_id = int(_staged_secret_order_rows(db, state.turn)[-1]["id"])
    order_id = int(
        _approve(db, state, minister, ctid, night_id, staged_id)
        .promises.applied[0]["secret_order_id"]
    )
    new_dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    assert [(int(link["target_dossier_id"]), link["relation_type"])
            for link in db.list_dossier_links(new_dossier_id)] == [
        (old_dossier_id, "稽核"),
    ]


@pytest.mark.parametrize("bad_links", [7, [7]], ids=["whole_field", "element"])
def test_bad_dossier_links_reject_only_their_own_item(game, bad_links):
    """R2 反面：关联字段坏类型只拒本项，同批合法密令照落（ADR 0005:12）。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    declaration = {
        "commissions": [
            {"text": "此事要密办，卿去查来。",
             "secret_order": _secret(assignee=minister, dossier_links=bad_links)},
            {"text": "此事要密办，卿去查来。",
             "secret_order": _secret(assignee=minister)},
        ],
    }
    result = _dispatch(db, state, minister, declaration, ctid, night_id)
    assert len(result.commissions.rejected) == 1
    assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_shape"
    assert len(_staged_secret_order_rows(db, state.turn)) == 1


def test_late_translated_rush_lands_under_its_source_night(game):
    """R3：夜收后补译的密令催办承接源夜，随后应允接得上（同一暂存写口）。"""
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    _dispatch(db, state, minister, _secret_order_declaration(assignee=minister),
              ctid, night_id)
    order_id = int(
        _approve(db, state, minister, ctid, night_id,
                 int(_staged_secret_order_rows(db, state.turn)[0]["id"]))
        .promises.applied[0]["secret_order_id"]
    )

    an.close_night(db, state, night_id=int(night_id))
    assert an.get_open_night(db) is None

    rushed = _dispatch(db, state, minister, {"rushes": [{
        "target_kind": "secret_order", "target_id": order_id,
        "deadline_months": 1, "reason": "补译催办",
    }]}, ctid, night_id)
    assert rushed.rushes.rejected == [], rushed.rushes.rejected
    staged = db.conn.execute(
        "SELECT id, night_id FROM pending_actions WHERE id=?",
        (int(rushed.rushes.applied[0]["id"]),),
    ).fetchone()
    assert int(staged["night_id"]) == int(night_id)

    approved = _approve(db, state, minister, ctid, night_id, int(staged["id"]))
    assert approved.promises.rejected == [], approved.promises.rejected
    assert len(approved.promises.applied) == 1
