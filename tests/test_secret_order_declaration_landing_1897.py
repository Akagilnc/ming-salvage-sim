"""#1897 转译声明新建密令走现役分派入口（不导入已删函数），失败真实可重试。

刀口：``declaration_dispatch._dispatch_commissions`` 的 ``secret_order`` 支路。
此前它导入 ``action_materialize.land_or_recover_new_secret_order``（已随
``e2fc6369d`` 删除），一旦转译声明 ``commissions[].secret_order`` 即 ImportError，
整轮分派炸掉、连同批合法交办一起丢。

本文件只经公开入口验行为，不盯诊断措辞：
- 声明新建密令 → 落一条 secret_order/新建 暂存，应允后案卷真成案（可读回）；
- 差务契约不成立 / 缺具名承办人 / 可选集合字段坏类型 → durable 拒收、零暂存，
  同批合法交办照落（坏项不带走整批）；
- 密令正文原样落库（判空不改存储值），案卷关联说明同守零删改；
- 承办人须是名册具名人物：场景标签与虚构人名都 durable 拒收；
- 补译交办承接源夜：夜收后补译暂存仍属源夜（直接与间接暂存入口 alike），
  应允照常成案；
- 成案真失败不当成功：源轮水位不标 done，原 action 仍 pending，补跑只做未完成的成案。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_translate import AudienceTranslateError
from ming_sim.db import GameDB
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.audience_translation import (
    apply_audience_round_translation,
    catch_up_pending_translations,
    run_turn_translation_job,
)
from ming_sim.session_write_queue import ClassifiedWriteGate
from ming_sim.supervision import ORIGIN_MARK_SAME_FACTION_BLIND, origin_has_mark


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
    # 真实前置：源轮尚未转译承接（extract_status=pending）。迟到转译之所以发生，
    # 正是因为这一轮还待补——is_pending_source_round 以此为判据。
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='pending' WHERE id=?", (ctid,),
    )
    db.conn.commit()
    return ctid


def _dispatch(db, state, minister, declaration, ctid, night_id):
    return dispatch_declaration(
        db, state, declaration,
        minister_name=minister, night_id=int(night_id), chat_turn_id=int(ctid),
    )


def _translate(db, state, minister, declaration, night_id, ctid):
    return apply_audience_round_translation(
        db, state, declaration, minister_name=minister, night_id=night_id,
        chat_turn_id=ctid,
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


def _summonable_name(db, content) -> str:
    """任免候选要一个名册里的具名人物（场景标签/虚构人名会被 durable 拒收）。"""
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩','未仕') AND name<>? ORDER BY name LIMIT 1",
        (_minister(db),),
    ).fetchone()
    assert row is not None
    return str(row["name"])


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
    # 反向：名册里的具名承办人照常成案（身份闸不得把真承办人也拒掉）。
    assert order["minister_name"] == minister


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


@pytest.mark.parametrize("declared_assignee", ["", "殿上", "不存在的人1897"])
def test_non_roster_assignee_is_not_made_into_a_minister(game, declared_assignee):
    """ADR 0153:5 + ADR 0053：承办人是名册人物主键引用。

    场景标签（「殿上」）与模型编出的不存在人名都不得成为正式承办身份——上一轮
    名册检查只挂在缺省回退上，显式声明的假身份一路暂存、成案写进 order_minister。
    """
    db, state, _ = game
    speaker = an.SCENE_CHAT_SPEAKER
    night_id, ctid = _open_night(db, state, speaker)

    result = _dispatch(
        db, state, speaker,
        _secret_order_declaration(assignee=declared_assignee), ctid, night_id,
    )
    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_state"
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


@pytest.mark.parametrize("label", ["assignment", "punishment"])
def test_late_translated_indirect_staging_keeps_its_source_night(game, monkeypatch, label):
    """源夜补译新增→应允→正式成案；正文/题名连过月差务均原样读回。"""
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)
    approval_ctid = _hall_turn(db, state, minister, night_id=night_id)
    an.close_night(db, state, night_id=night_id)
    assert an.get_open_night(db) is None
    body = "\n  密查粮科私卖。  \n"
    title = "\n  密查粮科  \n"

    cases = {
        "punishment": {"punishment": {
            "text": "罚俸三月。", "target_id": minister,
            "punish_action": "罚俸", "amount": 3,
        }},
        "assignment": {"assignment": {"title": title, "text": body, "assignee": minister}},
    }
    payload = cases[label]
    result = _translate(
        db, state, minister, {"commissions": [{"text": body, **payload}]}, night_id, ctid,
    )
    assert result.commissions.rejected == [], (label, result.commissions.rejected)
    assert len(result.commissions.applied) == 1, label
    staged_id = int(result.commissions.applied[0]["id"])
    staged = db.conn.execute(
        "SELECT id, night_id, payload_json FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    # 源夜承接：不是 0（接不回源夜），是本夜。
    assert int(staged["night_id"]) == int(night_id), (label, dict(staged))
    if label == "assignment":
        assert json.loads(staged["payload_json"])["title"] == title

    approved = _translate(db, state, minister, {"promises": [{
        "action_id": staged_id, "decision": "应允",
    }]}, night_id, approval_ctid)
    assert approved.promises.rejected == [], (label, approved.promises.rejected)
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"]) == 1, (label, dict(row))
    an.commit_late_night_approved(db, state, content=content)
    dossier = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (staged_id,),
    ).fetchone()
    assert dossier is not None, label
    case = db.get_decree_dossier(int(dossier["id"]))
    assert case is not None
    assert case["decree_text"] == body, (label, case)
    if label == "assignment":
        assert case["target_id"] == title.strip()
        assert case["payload"]["title"] == title
        from tests.test_audience_translate_1837_reopen import _player_month
        _player_month(db, state, content, monkeypatch, int(dossier["id"]))
        issue = db.conn.execute(
            "SELECT title, stage_text FROM issues WHERE origin_ref=?",
            (f"dossier:{dossier['id']}",),
        ).fetchone()
        assert issue is not None
        assert issue["title"] == title
        assert issue["stage_text"] == body
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"] == "committed"


def test_late_translated_indirect_update_keeps_its_source_night(game):
    """同上，但走**改草**分支：命中既有待办的间接更新也不得把归属迁到 night_id=0。

    ``stage_assignment_candidate`` 命中 target_candidate 时走
    ``update_directive_candidate``，该分支原本无条件按「当前开着的夜」改归属——
    夜已收时当前开夜为 0，改草就把补译交办从源夜迁走，随后应允 missing_ref。
    """
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    # 开夜期间先落一条待办责成交办，作为后续补译改草的目标。
    first = _translate(
        db, state, minister, {"commissions": [{"text": "依旨办理。", "assignment": {
            "title": "密查粮科", "text": "密查粮科私卖。", "assignee": minister,
        }}]}, night_id, ctid,
    )
    assert first.commissions.rejected == [], first.commissions.rejected
    staged_id = int(first.commissions.applied[0]["id"])

    revision_ctid = _hall_turn(db, state, minister, night_id=night_id)
    approval_ctid = _hall_turn(db, state, minister, night_id=night_id)
    an.close_night(db, state, night_id=int(night_id))
    assert an.get_open_night(db) is None

    # 夜收后补译：点名改那一稿（target_candidate 命中既有待办 → 改草分支）。
    body = "\n  再查得细些。  \n"
    revised = _translate(
        db, state, minister, {"commissions": [{"text": body, "assignment": {
            "title": "密查粮科", "text": "密查粮科私卖，并追赃银。", "assignee": minister,
            "target_candidate": str(staged_id),
        }}]}, night_id, revision_ctid,
    )
    assert revised.commissions.rejected == [], revised.commissions.rejected
    assert int(revised.commissions.applied[0]["id"]) == staged_id

    row = db.conn.execute(
        "SELECT night_id, payload_json FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    assert int(row["night_id"]) == int(night_id), dict(row)
    assert json.loads(row["payload_json"])["text"] == body
    approved = _translate(db, state, minister, {"promises": [{
        "action_id": staged_id, "decision": "应允",
    }]}, night_id, approval_ctid)
    assert approved.promises.rejected == []
    an.commit_late_night_approved(db, state, content=content)
    dossiers = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (staged_id,),
    ).fetchall()
    assert len(dossiers) == 1
    case = db.get_decree_dossier(int(dossiers[0]["id"]))
    assert case is not None
    assert case["decree_text"] == body


def test_secret_order_link_note_is_stored_verbatim(game):
    """P6 零删改：案卷关联说明一视同仁——暂存与正式关联都存原文。

    暂存侧上一轮已保真，消费者 ``add_dossier_links`` 这里仍 strip 一次，
    正式关联读回少了前后空白与换行（verbatim=false）。
    """
    db, state, _ = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    _dispatch(db, state, minister, _secret_order_declaration(assignee=minister),
              ctid, night_id)
    old_order_id = int(
        _approve(db, state, minister, ctid, night_id,
                 int(_staged_secret_order_rows(db, state.turn)[0]["id"]))
        .promises.applied[0]["secret_order_id"]
    )
    old_dossier_id = int(db.get_dossier_for_secret_order(old_order_id)["id"])
    raw_note = "\n  并案同查。  \n"

    result = _dispatch(
        db, state, minister, _secret_order_declaration(
            assignee=minister, title="再查一桩",
            dossier_links=[{"target_dossier_id": old_dossier_id,
                            "relation_type": "稽核", "note": raw_note}],
        ), ctid, night_id,
    )
    assert result.commissions.rejected == [], result.commissions.rejected
    staged = json.loads(_staged_secret_order_rows(db, state.turn)[-1]["payload_json"])
    assert staged["dossier_links"][0]["note"] == raw_note

    staged_id = int(_staged_secret_order_rows(db, state.turn)[-1]["id"])
    order_id = int(
        _approve(db, state, minister, ctid, night_id, staged_id)
        .promises.applied[0]["secret_order_id"]
    )
    new_dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    stored = db.list_dossier_links(new_dossier_id)
    assert [link["note"] for link in stored] == [raw_note]
    # R2：合法关联保持可消费——不被当脏数据整条拒收，关系型别丢。
    assert [(int(link["target_dossier_id"]), link["relation_type"])
            for link in stored] == [(old_dossier_id, "稽核")]


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


def test_failed_landing_keeps_the_original_pending_action_retryable(game):
    """真实成案失败不把源轮标 done。原暂存仍 pending，补跑只完成这一次成案。"""
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    result = _dispatch(
        db, state, minister, _secret_order_declaration(assignee=minister), ctid, night_id,
    )
    assert result.commissions.rejected == []
    staged_id = int(_staged_secret_order_rows(db, state.turn)[0]["id"])
    reply = "臣领旨。"

    def _translate(_prompt, _config):
        return {
            "promises": [{"action_id": staged_id, "decision": "应允"}],
            "scene_facts": [{
                "body": reply,
                "role": "minister",
                "audibility": "殿上公开",
                "person_names": [minister],
            }],
        }

    # 进行中密令已满时，新建在内层事务之前失败。提交方接住这次失败，
    # 源轮不得因此标 done；腾出空额后，原暂存仍可补跑成案。
    db.conn.executemany(
        "INSERT INTO secret_orders "
        "(turn_issued, year_issued, period_issued, minister_name, title) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (int(state.turn), int(state.year), int(state.period), minister, f"占额{i}")
            for i in range(20)
        ],
    )
    db.conn.commit()
    with pytest.raises(AudienceTranslateError):
        run_turn_translation_job(
            db, state,
            emperor_message="此事要密办，卿去查来。",
            reply=reply,
            night_id=night_id,
            chat_turn_id=ctid,
            minister_name=minister,
            translate_fn=_translate,
            write_gate=ClassifiedWriteGate(),
        )
    assert db.get_story_extract_status(ctid) != "done"
    assert all(
        order["title"] != "查办粮科私卖" for order in db.list_secret_orders()
    )
    status = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"]
    assert status == "pending", status
    pack = db.conn.execute(
        "SELECT error_pack_path FROM chat_turns WHERE id=?", (ctid,),
    ).fetchone()["error_pack_path"]
    assert str(pack or "").strip()
    manifest = json.loads((Path(pack) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.get("kind") == "translation"
    assert int((manifest.get("detail") or {}).get("chat_turn_id") or 0) == ctid
    db.conn.execute("DELETE FROM secret_orders WHERE title LIKE '占额%'")
    db.conn.commit()

    reopened = GameDB(db.path, content)
    try:
        waiting = reopened.list_unextracted_replies(night_id=night_id)
        assert any(int(row["chat_turn_id"]) == ctid for row in waiting)
        caught = catch_up_pending_translations(
            reopened, state,
            chat_turn_id=ctid,
            translate_fn=_translate,
            write_gate=ClassifiedWriteGate(),
            within_barrier=True,
        )
        assert caught["extracted"] == 1
        assert caught["pending"] == 0
        assert reopened.get_story_extract_status(ctid) == "done"
        landed = reopened.list_secret_orders(status="active", minister_name=minister)
        assert len(landed) == 1
        assert landed[0]["minister_name"] == minister
    finally:
        reopened.close()


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

    before_due = int(db.get_secret_order(order_id)["due_turn"] or 0)
    approved = _approve(db, state, minister, ctid, night_id, staged_id)
    assert approved.promises.rejected == [], approved.promises.rejected
    assert len(approved.promises.applied) == 1
    status = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"]
    assert status == "committed", status
    after = db.get_secret_order(order_id)
    assert int(after["due_turn"] or 0) == int(state.turn) + 1
    assert int(after["due_turn"] or 0) < before_due
    assert str(after["result"] or "") == ""
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    rush_rows = [
        row for row in db.list_dossier_progress(dossier_id)
        if str(row["origin"]) == db.DOSSIER_REPORT_ORIGIN_RUSH
    ]
    assert [row["memorial_text"] for row in rush_rows] == ["着即催办"]

    # 已成功落库的催办不再执行一遍：同一 id 不在 pending 清单里。
    again = _approve(db, state, minister, ctid, night_id, staged_id)
    assert again.promises.applied == [], again.promises.applied


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


@pytest.mark.parametrize("seal", ["closing", "closed"])
def test_late_translated_appointment_hit_keeps_its_source_night(game, seal):
    """补译既有任免：收夜窗口与已封夜都落在源夜源轮，应允后成案，撤回不复活。"""
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)
    appointee = _summonable_name(db, content)

    first = _translate(db, state, minister, {"commissions": [{
        "text": "着即擢用。",
        "appointment": {"name": appointee, "office": "巡抚", "action": "任命"},
    }]}, night_id, ctid)
    assert first.commissions.rejected == [], first.commissions.rejected
    staged_id = int(db.conn.execute(
        "SELECT id FROM pending_actions WHERE turn=? AND kind='office' ORDER BY id",
        (int(state.turn),),
    ).fetchone()["id"])

    revision_ctid = _hall_turn(db, state, minister, night_id=night_id)
    approval_ctid = _hall_turn(db, state, minister, night_id=night_id)
    revision = {"commissions": [{
        "text": "改中旨径发。",
        "appointment": {
            "name": appointee, "office": "巡抚", "action": "任命", "mode": "midzhi",
        },
    }]}

    def _revise():
        return _translate(db, state, minister, revision, night_id, revision_ctid)

    if seal == "closing":
        an.close_night(
            db, state, night_id=int(night_id), content=content, on_closing=_revise,
        )
    else:
        an.close_night(db, state, night_id=int(night_id), content=content)
        assert _revise().commissions.rejected == []
    assert an.get_open_night(db) is None

    row = db.conn.execute(
        "SELECT night_id, night_approved FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    assert int(row["night_id"]) == int(night_id), dict(row)
    assert int(row["night_approved"] or 0) == 0, dict(row)

    revision_seq = int(db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (revision_ctid,),
    ).fetchone()["night_seq"])
    approval_seq = int(db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (approval_ctid,),
    ).fetchone()["night_seq"])
    ledger = db.conn.execute(
        "SELECT night_id, source_chat_turn_id, origin_chat_turn_id, order_key "
        "FROM story_ledger_entries WHERE origin_chat_turn_id=?",
        (revision_ctid,),
    ).fetchall()
    assert len(ledger) == 1, [dict(item) for item in ledger]
    entry = ledger[0]
    assert int(entry["night_id"]) == int(night_id)
    assert int(entry["source_chat_turn_id"]) == revision_ctid
    assert int(entry["origin_chat_turn_id"]) == revision_ctid
    assert float(entry["order_key"]) == float(revision_seq)
    assert revision_seq != approval_seq

    approved = _translate(db, state, minister, {"promises": [{
        "action_id": staged_id, "decision": "应允",
    }]}, night_id, approval_ctid)
    assert approved.promises.rejected == [], approved.promises.rejected
    an.commit_late_night_approved(db, state, content=content)
    cases = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?",
        (staged_id,),
    ).fetchall()
    assert len(cases) == 1

    db.fail_chat_turn(revision_ctid)
    gone = db.conn.execute(
        "SELECT COUNT(*) AS n FROM story_ledger_entries "
        "WHERE source_chat_turn_id=? OR origin_chat_turn_id=?",
        (revision_ctid, revision_ctid),
    ).fetchone()["n"]
    assert int(gone) == 0
    with pytest.raises(an.AudienceNightError):
        _revise()
    still_gone = db.conn.execute(
        "SELECT COUNT(*) AS n FROM story_ledger_entries "
        "WHERE source_chat_turn_id=? OR origin_chat_turn_id=?",
        (revision_ctid, revision_ctid),
    ).fetchone()["n"]
    assert int(still_gone) == 0


def test_secret_order_progress_is_stored_verbatim(game):
    """进展与月度密奏共用奏报轨：原文、空白、换行原样留下，正文日期不另立月份。"""
    db, state, content = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)

    _dispatch(db, state, minister, _secret_order_declaration(assignee=minister),
              ctid, night_id)
    order_id = int(
        _approve(db, state, minister, ctid, night_id,
                 int(_staged_secret_order_rows(db, state.turn)[0]["id"]))
        .promises.applied[0]["secret_order_id"]
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    state.turn = int(state.turn) + 1
    state.period = 4
    db.save_state(state)
    raw_note = f"\n  已查得线索，仍须密访。  \n〔{int(state.year)}年1月〕旧报未结。\n"
    other = _summonable_name(db, content)
    stolen = _dispatch(db, state, other, {"commissions": [{
        "text": "据实以闻。", "secret_order_progress": {"order_id": order_id, "note": raw_note},
    }]}, ctid, night_id)
    assert stolen.commissions.applied == []
    assert _rejection_rows(db, state.turn)[-1]["category"] == "invalid_state"

    db.conn.execute(
        "UPDATE chat_turns SET minister_name=? WHERE id=?", ("殿上", ctid),
    )
    db.conn.commit()
    progressed = _dispatch(db, state, "", {"commissions": [{
        "text": "据实以闻。", "secret_order_progress": {"order_id": order_id, "note": raw_note},
    }]}, ctid, night_id)
    assert progressed.commissions.rejected == [], progressed.commissions.rejected
    staged_name = db.conn.execute(
        "SELECT minister_name FROM pending_actions WHERE id=?",
        (int(progressed.commissions.applied[0]["id"]),),
    ).fetchone()["minister_name"]
    assert staged_name == minister
    assert _approve(
        db, state, minister, ctid, night_id,
        int(progressed.commissions.applied[0]["id"]),
    ).promises.rejected == []

    def _open_reports(conn_db):
        return [
            row for row in conn_db.list_dossier_progress(dossier_id)
            if not row["is_terminal"]
        ]

    first = _open_reports(db)
    assert len(first) == 1, first
    assert first[0]["memorial_text"] == raw_note
    assert int(first[0]["turn"]) == int(state.turn)
    assert str(db.get_secret_order(order_id)["result"] or "") == ""
    assert db.sum_dossier_actual_progress_units(dossier_id) == 0

    corrected = "\n  同月更正：线索有误，仍须密访。  \n"
    monthly = dispatch_declaration(
        db, state,
        {"effects": {"dossier_progress_reports": [{
            "dossier_id": dossier_id,
            "progress_band": "在办",
            "memorial_text": corrected,
        }]}},
        minister_name=minister,
        night_id=0,
    )
    assert monthly.effects.rejected == [], monthly.effects.rejected
    live = _open_reports(db)
    assert len(live) == 1, live
    assert live[0]["memorial_text"] == corrected
    assert raw_note not in str(live[0]["memorial_text"])
    assert int(live[0]["turn"]) == int(state.turn)
    assert str(db.get_secret_order(order_id)["result"] or "") == ""
    assert db.sum_dossier_actual_progress_units(dossier_id) == 0

    marked = f"{db.DOSSIER_REPORT_ORIGIN_MONTHLY}+{ORIGIN_MARK_SAME_FACTION_BLIND}"
    db.record_dossier_progress(
        dossier_id, int(state.turn), "在办", corrected, origin=marked, commit=True,
    )
    marked_rows = _open_reports(db)
    assert len(marked_rows) == 1, marked_rows
    assert marked_rows[0]["memorial_text"] == corrected
    assert origin_has_mark(marked_rows[0]["origin"], ORIGIN_MARK_SAME_FACTION_BLIND)
    assert int(marked_rows[0]["turn"]) == int(state.turn)

    reopened = GameDB(db.path, content)
    try:
        reread = _open_reports(reopened)
        assert len(reread) == 1
        assert reread[0]["memorial_text"] == corrected
        assert int(reread[0]["turn"]) == int(state.turn)
        assert str(reopened.get_secret_order(order_id)["result"] or "") == ""
    finally:
        reopened.close()


def test_scene_review_claim_lands_on_the_review_rail(game):
    """提交核议走现役暂存与应允。陈词进核议轨，不冒充月报。"""
    db, state, _content = game
    minister = _minister(db)
    night_id, ctid = _open_night(db, state, minister)
    _dispatch(db, state, minister, _secret_order_declaration(assignee=minister), ctid, night_id)
    order_id = int(
        _approve(db, state, minister, ctid, night_id,
                 int(_staged_secret_order_rows(db, state.turn)[0]["id"]))
        .promises.applied[0]["secret_order_id"]
    )
    claim = "\n  臣已办结，请予核议。  \n"
    db.conn.execute(
        "UPDATE chat_turns SET minister_name=? WHERE id=?", ("殿上", ctid),
    )
    db.conn.commit()
    staged = _dispatch(db, state, "", {"commissions": [{
        "text": "请核议。",
        "secret_order_review": {"order_id": order_id, "claim": claim},
    }]}, ctid, night_id)
    assert staged.commissions.rejected == [], staged.commissions.rejected
    action_id = int(staged.commissions.applied[0]["id"])
    row = db.conn.execute(
        "SELECT action, minister_name, payload_json FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    assert row["action"] == "提交核议"
    assert row["minister_name"] == minister
    assert json.loads(row["payload_json"])["claim"] == claim
    approved = _approve(db, state, "", ctid, night_id, action_id)
    assert approved.promises.rejected == [], approved.promises.rejected
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    reviews = [
        item for item in db.list_dossier_progress(dossier_id)
        if str(item["origin"]) == db.DOSSIER_REPORT_ORIGIN_REVIEW
    ]
    assert [item["memorial_text"] for item in reviews] == [claim]
    monthly = [
        item for item in db.list_dossier_progress(dossier_id)
        if not item["is_terminal"]
        and str(item["origin"]).startswith(db.DOSSIER_REPORT_ORIGIN_MONTHLY)
    ]
    assert monthly == []
