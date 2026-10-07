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
from ming_sim.audience_translation import (
    catch_up_pending_translations,
    run_turn_translation_job,
)
from ming_sim.session_write_queue import ClassifiedWriteGate


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


def _emit(db, state, content, monkeypatch, declaration, *, minister, words="此事要密办，卿去查来。", close_before_translation=False):
    """经 scene_chat 落一条声明。说话人是源轮 minister_name。"""
    from tests.test_audience_translate_1837_reopen import _scene_declaration

    return _scene_declaration(
        db, state, content, monkeypatch, words, declaration,
        minister_name=minister,
        close_before_translation=close_before_translation,
    )


def _approve(db, state, content, monkeypatch, action_id, *, minister):
    return _emit(
        db, state, content, monkeypatch,
        {"promises": [{"action_id": int(action_id), "decision": "应允"}]},
        minister=minister,
    )


def _scene_payload(declaration):
    body = declaration() if callable(declaration) else declaration
    return {
        **body,
        "scene_facts": [{
            "body": "殿上应对。", "role": "scene",
            "audibility": "殿上公开", "person_names": [],
        }],
    }


def _emit_late_pair(db, state, content, monkeypatch, first, second, *, minister, words=("先补这一句。", "再补下一句。")):
    """两轮都在开夜时发出。第一轮转译放行时才封夜，第二轮仍挂源夜。"""
    import threading

    from tests.conftest import persist_and_schedule_scene, stub_audience_translate
    from tests.test_audience_translate_1837_reopen import _close_offline
    from tests.test_audience_translation_1838 import _scene_session

    sess = _scene_session(db, state, content, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}
    night_id = {"v": 0}

    def translate(prompt, config):
        n = calls["n"]
        calls["n"] += 1
        if n == 0:
            entered.set()
            if not release.wait(8):
                raise TimeoutError("迟到转译未被放行")
            _close_offline(db, state, content, night_id["v"])
            decl = first
        else:
            decl = second
        return _scene_payload(decl)

    stub_audience_translate(monkeypatch, translate)
    night = an.open_night(db, state)
    night_id["v"] = int(night["id"])
    futures = []
    for text in words:
        ctid = db.create_chat_turn(
            state, minister, "s", 0, night_id=night_id["v"], status="active",
        )
        mid = db.append_chat_message(minister, state.turn, "user", text)
        db.update_chat_turn_messages(ctid, user_message_id=mid)
        reply = sess.scene_chat(text, chat_turn_id=int(ctid), minister_name=minister)
        fut = persist_and_schedule_scene(sess, db, reply, speaker=minister)
        assert fut is not None
        futures.append(fut)
        if len(futures) == 1:
            assert entered.wait(8)
    release.set()
    return (
        futures[0].result(timeout=10),
        futures[1].result(timeout=10),
        night_id["v"],
    )


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


def test_declared_new_secret_order_lands_through_live_dispatch_and_becomes_a_case(game, monkeypatch):
    """票面「怎么验」正路：声明新建密令不 ImportError，落暂存、应允成案、可读回。"""
    db, state, content = game
    minister = _minister(db)

    result = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister), minister=minister,
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
    approved = _approve(
        db, state, content, monkeypatch, staged_id, minister=minister,
    )
    assert approved.promises.rejected == []
    applied_row = approved.promises.applied[0]
    assert applied_row["kind"] == "secret_order" and applied_row["action"] == "新建"
    order_id = int(applied_row["secret_order_id"])
    assert order_id > 0

    order = db.get_secret_order(order_id)
    assert order is not None
    assert order["status"] == "active"
    assert db.get_dossier_for_secret_order(order_id) is not None
    # 反向：名册里的具名承办人照常成案（身份闸不得把真承办人也拒掉）。
    assert order["minister_name"] == minister


def test_blank_secret_order_title_is_rejected_not_staged(game, monkeypatch):
    """判空仍按副本做：纯空白标题拒收，不暂存、不成案。"""
    db, state, content = game
    minister = _minister(db)

    result = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister, title="   \n  "),
        minister=minister,
    )
    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_shape"
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


def test_bad_secret_order_is_rejected_without_staging_or_landing(game, monkeypatch):
    """真失败不当成功：契约缺交付身份 → durable 拒收 + 零暂存（不留注定落不了库的交办）。"""
    db, state, content = game
    minister = _minister(db)

    bad_task = {"kind": "查案", "axes": ["实务事功"], "direction": 1,
                "delivery": {"unit": "人犯", "target_units": 2.0}}
    result = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister, covert_task=bad_task),
        minister=minister,
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
def test_non_roster_assignee_is_not_made_into_a_minister(game, monkeypatch, declared_assignee):
    """ADR 0153:5 + ADR 0053：承办人是名册人物主键引用。

    场景标签（「殿上」）与模型编出的不存在人名都不得成为正式承办身份——上一轮
    名册检查只挂在缺省回退上，显式声明的假身份一路暂存、成案写进 order_minister。
    """
    db, state, content = game
    speaker = an.SCENE_CHAT_SPEAKER

    result = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=declared_assignee), minister=speaker,
    )
    assert result.commissions.applied == []
    assert len(result.commissions.rejected) == 1
    assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_state"
    assert _staged_secret_order_rows(db, state.turn) == []
    assert db.list_secret_orders() == []


def _late_revision_and_approval(
    db, state, content, monkeypatch, revision, approval, *, minister, seal,
):
    """补译轮与应允轮都在封夜前建好。closing 在收夜回调里跑补译；closed 在封死后跑。

    应允仍用封夜前那一轮，不另开一场冒充源夜。
    """
    import threading
    from types import SimpleNamespace

    from tests.conftest import persist_and_schedule_scene, stub_audience_translate
    from tests.test_audience_translation_1838 import _scene_session

    sess = _scene_session(db, state, content, monkeypatch)
    night = an.open_night(db, state)
    night_id = int(night["id"])
    entered = threading.Event()
    release = threading.Event()
    calls = {"n": 0}
    decls = [revision, approval]

    def translate(prompt, config):
        n = calls["n"]
        calls["n"] += 1
        if n == 0:
            entered.set()
            if not release.wait(8):
                raise TimeoutError("收夜窗口未放行补译")
        return _scene_payload(decls[n])

    stub_audience_translate(monkeypatch, translate)

    def _turn(words):
        ctid = int(db.create_chat_turn(
            state, minister, "s", 0, night_id=night_id, status="active",
        ))
        reply = sess.scene_chat(words, chat_turn_id=ctid, minister_name=minister)
        return ctid, reply

    revision_ctid, revision_reply = _turn("改中旨径发。")
    revision_fut = persist_and_schedule_scene(
        sess, db, revision_reply, speaker=minister,
    )
    assert revision_fut is not None
    assert entered.wait(8)
    approval_ctid, approval_reply = _turn("应允此任。")
    db.persist_minister_reply(
        minister, int(state.turn), str(approval_reply.answer or ""), approval_ctid,
    )

    def _finish_revision():
        release.set()
        return revision_fut.result(timeout=10)

    def _close(on_closing=None):
        # #1838 reopen：收夜不再接夜级背书 extractor；背书随转译走。
        an.close_night(
            db, state, night_id=night_id, content=content,
            on_closing=on_closing,
        )

    if seal == "closing":
        _close(on_closing=_finish_revision)
    else:
        _close()
        _finish_revision()
    assert an.get_open_night(db) is None

    def _approve_held():
        fut = sess.schedule_pending_scene_translation(approval_reply)
        assert fut is not None
        return fut.result(timeout=10)

    return night_id, revision_ctid, approval_ctid, _approve_held


@pytest.mark.parametrize("label", ["assignment", "punishment"])
def test_late_translated_indirect_staging_keeps_its_source_night(game, monkeypatch, label):
    """源夜补译新增→应允→正式成案；正文/题名连过月差务均原样读回。"""
    db, state, content = game
    minister = _minister(db)
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

    def _approval():
        staged_id = int(db.conn.execute(
            "SELECT id FROM pending_actions WHERE turn=? ORDER BY id DESC LIMIT 1",
            (int(state.turn),),
        ).fetchone()["id"])
        return {"promises": [{"action_id": staged_id, "decision": "应允"}]}

    result, approved, night_id = _emit_late_pair(
        db, state, content, monkeypatch,
        {"commissions": [{"text": body, **payload}]},
        _approval,
        minister=minister,
    )
    assert an.get_open_night(db) is None
    assert result.commissions.rejected == [], (label, result.commissions.rejected)
    assert len(result.commissions.applied) == 1, label
    staged_id = int(result.commissions.applied[0]["id"])
    staged = db.conn.execute(
        "SELECT id, night_id, payload_json FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    assert int(staged["night_id"]) == int(night_id), (label, dict(staged))
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
    if label == "assignment":
        assert case["target_id"] == title.strip()
        from tests.test_audience_translate_1837_reopen import _player_month
        _player_month(db, state, content, monkeypatch, int(dossier["id"]))
        issue = db.conn.execute(
            "SELECT title, stage_text FROM issues WHERE origin_ref=?",
            (f"dossier:{dossier['id']}",),
        ).fetchone()
        assert issue is not None
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()["status"] == "committed"


def test_late_translated_indirect_update_keeps_its_source_night(game, monkeypatch):
    """改草分支：命中既有待办的间接更新不得把归属迁出源夜。"""
    db, state, content = game
    minister = _minister(db)
    first = _emit(
        db, state, content, monkeypatch,
        {"commissions": [{"text": "依旨办理。", "assignment": {
            "title": "密查粮科", "text": "密查粮科私卖。", "assignee": minister,
        }}]},
        minister=minister, words="依旨办理。",
    )
    assert first.commissions.rejected == [], first.commissions.rejected
    staged_id = int(first.commissions.applied[0]["id"])
    body = "\n  再查得细些。  \n"

    revised, approved, night_id = _emit_late_pair(
        db, state, content, monkeypatch,
        {"commissions": [{"text": body, "assignment": {
            "title": "密查粮科", "text": "密查粮科私卖，并追赃银。", "assignee": minister,
            "target_candidate": str(staged_id),
        }}]},
        {"promises": [{"action_id": staged_id, "decision": "应允"}]},
        minister=minister,
    )
    assert an.get_open_night(db) is None
    assert revised.commissions.rejected == [], revised.commissions.rejected
    assert int(revised.commissions.applied[0]["id"]) == staged_id
    row = db.conn.execute(
        "SELECT night_id, payload_json FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()
    assert int(row["night_id"]) == int(night_id), dict(row)
    assert approved.promises.rejected == []
    an.commit_late_night_approved(db, state, content=content)
    dossiers = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (staged_id,),
    ).fetchall()
    assert len(dossiers) == 1
    case = db.get_decree_dossier(int(dossiers[0]["id"]))
    assert case is not None


def test_secret_order_link_note_is_stored_verbatim(game, monkeypatch):
    """案卷关联说明暂存与正式关联都存原文。"""
    db, state, content = game
    minister = _minister(db)
    raw_note = "\n  并案同查。  \n"

    first = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister), minister=minister,
    )
    assert first.commissions.rejected == []
    old_order_id = int(
        _approve(
            db, state, content, monkeypatch,
            int(_staged_secret_order_rows(db, state.turn)[0]["id"]),
            minister=minister,
        ).promises.applied[0]["secret_order_id"]
    )
    old_dossier_id = int(db.get_dossier_for_secret_order(old_order_id)["id"])

    result = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(
            assignee=minister, title="再查一桩",
            dossier_links=[{"target_dossier_id": old_dossier_id,
                            "relation_type": "稽核", "note": raw_note}],
        ),
        minister=minister, words="再查一桩。",
    )
    assert result.commissions.rejected == [], result.commissions.rejected
    staged = json.loads(_staged_secret_order_rows(db, state.turn)[-1]["payload_json"])

    staged_id = int(_staged_secret_order_rows(db, state.turn)[-1]["id"])
    order_id = int(
        _approve(
            db, state, content, monkeypatch, staged_id, minister=minister,
        ).promises.applied[0]["secret_order_id"]
    )
    new_dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    stored = db.list_dossier_links(new_dossier_id)
    assert [(int(link["target_dossier_id"]), link["relation_type"])
            for link in stored] == [(old_dossier_id, "稽核")]


@pytest.mark.parametrize("bad_tags", [7, [7]], ids=["whole_field", "element"])
def test_bad_optional_list_field_rejects_only_its_own_item(game, monkeypatch, bad_tags):
    """可选集合字段类型错只拒该项，同批合法交办照落。"""
    db, state, content = game
    minister = _minister(db)
    result = _emit(
        db, state, content, monkeypatch,
        {"commissions": [
            {"text": "此事要密办，卿去查来。",
             "secret_order": _secret(assignee=minister, tags=bad_tags)},
            {"text": "此事要密办，卿去查来。", "secret_order": _secret(assignee=minister)},
        ]},
        minister=minister,
    )
    assert len(result.commissions.rejected) == 1, result.commissions.rejected
    assert result.commissions.rejected[0].category == "invalid_shape"
    assert len(result.commissions.applied) == 1
    rows = _staged_secret_order_rows(db, state.turn)
    assert len(rows) == 1, [dict(r) for r in rows]
    assert json.loads(rows[0]["payload_json"])["covert_task"]["kind"] == "查案"


def test_late_translation_staged_secret_order_still_lands_under_its_source_night(game, monkeypatch):
    """迟到转译在过月前补齐，暂存承接源夜，应允照常成案。"""
    db, state, content = game
    minister = _minister(db)

    def _approval():
        staged_id = int(_staged_secret_order_rows(db, state.turn)[0]["id"])
        return {"promises": [{"action_id": staged_id, "decision": "应允"}]}

    result, approved, night_id = _emit_late_pair(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister),
        _approval,
        minister=minister,
    )
    assert an.get_open_night(db) is None
    assert result.commissions.rejected == [], result.commissions.rejected
    rows = _staged_secret_order_rows(db, state.turn)
    assert len(rows) == 1, [dict(r) for r in rows]
    assert int(rows[0]["night_id"]) == int(night_id)
    assert approved.promises.rejected == [], approved.promises.rejected
    order_id = int(approved.promises.applied[0]["secret_order_id"])
    assert db.get_secret_order(order_id)["status"] == "active"


@pytest.mark.parametrize("fault", ["sqlite", "missing_dossier"])
def test_failed_landing_keeps_the_original_pending_action_retryable(game, monkeypatch, fault):
    """成案失败不把源轮标 done。原暂存仍 pending，补跑只完成这一次成案。"""
    db, state, content = game
    minister = _minister(db)
    staged = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister, dossier_links=[]), minister=minister,
    )
    assert staged.commissions.rejected == []
    staged_id = int(_staged_secret_order_rows(db, state.turn)[0]["id"])
    night_id = int(an.open_night(db, state)["id"])

    import sqlite3

    def deny_order_insert(action, table, column, database, trigger):
        if action == sqlite3.SQLITE_INSERT and table == "secret_orders":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    if fault == "sqlite":
        db.conn.set_authorizer(deny_order_insert)
    else:
        # A real DB invariant failure, not a mocked commit or a domain rejection.
        db.conn.execute(
            "CREATE TEMP TRIGGER lose_dossier AFTER INSERT ON decree_dossiers "
            "BEGIN UPDATE decree_dossiers SET secret_order_id=NULL WHERE id=NEW.id; END"
        )

    from tests.conftest import persist_and_schedule_scene, stub_audience_translate
    from tests.test_audience_translation_1838 import _scene_session

    sess = _scene_session(db, state, content, monkeypatch)

    def translate(prompt, config):
        return _scene_payload(
            {"promises": [{"action_id": staged_id, "decision": "应允"}]},
        )

    stub_audience_translate(monkeypatch, translate)
    ctid = int(db.create_chat_turn(
        state, minister, "s", 0, night_id=night_id, status="active",
    ))
    reply = sess.scene_chat("应允查办。", chat_turn_id=ctid, minister_name=minister)
    fut = persist_and_schedule_scene(sess, db, reply, speaker=minister)
    assert fut is not None
    with pytest.raises(sqlite3.DatabaseError if fault == "sqlite" else ValueError):
        fut.result(timeout=10)
    assert db.get_story_extract_status(ctid) != "done"
    assert db.list_secret_orders() == []
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
    db.conn.set_authorizer(None)
    if fault == "missing_dossier":
        db.conn.execute("DROP TRIGGER lose_dossier")

    reopened = GameDB(db.path, content)
    try:
        waiting = reopened.list_unextracted_replies(night_id=night_id)
        assert any(int(row["chat_turn_id"]) == ctid for row in waiting)
        caught = catch_up_pending_translations(
            reopened, state,
            chat_turn_id=ctid,
            translate_fn=translate,
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


def test_approved_rush_reports_success_and_is_not_repeated(game, monkeypatch):
    """密令催办应允成功即成功，不再把同一条催办写一遍。"""
    db, state, content = game
    minister = _minister(db)
    opened = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister), minister=minister,
    )
    assert opened.commissions.rejected == []
    order_id = int(
        _approve(
            db, state, content, monkeypatch,
            int(_staged_secret_order_rows(db, state.turn)[0]["id"]),
            minister=minister,
        ).promises.applied[0]["secret_order_id"]
    )
    rushed = _emit(
        db, state, content, monkeypatch,
        {"rushes": [{
            "target_kind": "secret_order", "target_id": order_id,
            "deadline_months": 1, "reason": "着即催办",
        }]},
        minister=minister, words="着即催办。",
    )
    assert rushed.rushes.rejected == [], rushed.rushes.rejected
    staged_id = int(rushed.rushes.applied[0]["id"])
    before_due = int(db.get_secret_order(order_id)["due_turn"] or 0)
    approved = _approve(
        db, state, content, monkeypatch, staged_id, minister=minister,
    )
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
    assert len(rush_rows) == 1

    again = _approve(
        db, state, content, monkeypatch, staged_id, minister=minister,
    )
    assert again.promises.applied == [], again.promises.applied


@pytest.mark.parametrize("bad_case", [
    "whole_field", "element", "missing", "forward", "relation", "note", "foreign", "vassal", "capacity",
])
def test_bad_dossier_links_reject_only_their_own_item(game, monkeypatch, bad_case):
    """声明及应允的领域拒收逐项留痕，合法同行照常成案。"""
    db, state, content = game
    minister = _minister(db)
    bad = {"assignee": minister}
    if bad_case in {"whole_field", "element"}:
        bad["dossier_links"] = 7 if bad_case == "whole_field" else [7]
    elif bad_case in {"foreign", "vassal"}:
        from ming_sim.models import is_vassal_prince
        bad["assignee"] = next(
            c.name for c in content.characters.values()
            if (db.resolve_power_id(c) != "ming" if bad_case == "foreign"
                else is_vassal_prince(c))
        )
    elif bad_case == "capacity":
        for _ in range(19):
            db.create_secret_order(state, minister, "密查", "查办", [], covert_task=_covert_task())
    else:
        target = 999999
        if bad_case in {"relation", "note"}:
            opened = _emit(db, state, content, monkeypatch,
                           _secret_order_declaration(assignee=minister), minister=minister)
            approved = _approve(db, state, content, monkeypatch,
                                _staged_secret_order_rows(db, state.turn)[-1]["id"], minister=minister)
            target = db.get_dossier_for_secret_order(
                approved.promises.applied[0]["secret_order_id"],
            )["id"]
        elif bad_case == "forward":
            # The first new dossier would refer to itself.
            target = db.conn.execute("SELECT COALESCE(MAX(id),0)+1 FROM decree_dossiers").fetchone()[0]
        bad["dossier_links"] = [{
            "target_dossier_id": target,
            "relation_type": "非法" if bad_case == "relation" else "稽核",
            "note": " " if bad_case == "note" else "查账",
        }]
    before = len(db.list_secret_orders())
    result = _emit(
        db, state, content, monkeypatch,
        {"commissions": [
            {"text": "此事要密办，卿去查来。",
             "secret_order": _secret(**bad)},
            {"text": "此事要密办，卿去查来。",
             "secret_order": _secret(assignee=minister)},
        ]},
        minister=minister,
    )
    if bad_case in {"whole_field", "element"}:
        assert len(result.commissions.rejected) == 1
        assert _rejection_rows(db, state.turn)[0]["category"] == "invalid_shape"
        assert len(_staged_secret_order_rows(db, state.turn)) == 1
        return
    ids = [int(r["id"]) for r in _staged_secret_order_rows(db, state.turn)
           if r["status"] == "pending"]
    assert len(ids) == 2
    approved = _emit(db, state, content, monkeypatch, {
        "promises": [{"action_id": aid, "decision": "应允"}
                     for aid in (ids[::-1] if bad_case == "capacity" else ids)],
    }, minister=minister)
    assert len(approved.promises.rejected) == 1
    assert approved.promises.rejected[0].category == {
        "missing": "hallucinated_id", "relation": "invalid_enum", "note": "invalid_shape",
        "capacity": "active_cap", "vassal": "ineligible_vassal", "foreign": "ineligible_power",
    }.get(bad_case, "invalid_state")
    assert len(approved.promises.applied) == 1
    assert len(db.list_secret_orders()) == before + 1
    statuses = [db.conn.execute("SELECT status FROM pending_actions WHERE id=?", (aid,)).fetchone()[0]
                for aid in ids]
    assert statuses == ["failed", "committed"]
    assert len(_rejection_rows(db, state.turn, "promises")) == 1
    if "dossier_links" in bad:
        assert len(db.list_dossier_link_rejections(pending_action_id=ids[0])) == 1
    ctid = db.conn.execute("SELECT MAX(id) FROM chat_turns").fetchone()[0]
    assert db.get_story_extract_status(ctid) == "done"


def test_late_translated_rush_lands_under_its_source_night(game, monkeypatch):
    """夜收后补译的密令催办承接源夜，随后应允接得上。"""
    db, state, content = game
    minister = _minister(db)
    opened = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister), minister=minister,
    )
    assert opened.commissions.rejected == []
    order_id = int(
        _approve(
            db, state, content, monkeypatch,
            int(_staged_secret_order_rows(db, state.turn)[0]["id"]),
            minister=minister,
        ).promises.applied[0]["secret_order_id"]
    )

    def _approval():
        staged_id = int(db.conn.execute(
            "SELECT id FROM pending_actions WHERE turn=? AND kind='secret_order' "
            "AND action<>'新建' ORDER BY id DESC LIMIT 1",
            (int(state.turn),),
        ).fetchone()["id"])
        return {"promises": [{"action_id": staged_id, "decision": "应允"}]}

    rushed, approved, night_id = _emit_late_pair(
        db, state, content, monkeypatch,
        {"rushes": [{
            "target_kind": "secret_order", "target_id": order_id,
            "deadline_months": 1, "reason": "补译催办",
        }]},
        _approval,
        minister=minister,
    )
    assert an.get_open_night(db) is None
    assert rushed.rushes.rejected == [], rushed.rushes.rejected
    staged = db.conn.execute(
        "SELECT id, night_id FROM pending_actions WHERE id=?",
        (int(rushed.rushes.applied[0]["id"]),),
    ).fetchone()
    assert int(staged["night_id"]) == int(night_id)
    assert approved.promises.rejected == [], approved.promises.rejected
    assert len(approved.promises.applied) == 1


@pytest.mark.parametrize("seal", ["closing", "closed"])
def test_late_translated_appointment_hit_keeps_its_source_night(game, monkeypatch, seal):
    """补译既有任免：收夜窗口与已封夜都落在源夜源轮，应允后成案，撤回不复活。"""
    db, state, content = game
    minister = _minister(db)
    appointee = _summonable_name(db, content)
    first = _emit(
        db, state, content, monkeypatch,
        {"commissions": [{
            "text": "着即擢用。",
            "appointment": {"name": appointee, "office": "巡抚", "action": "任命"},
        }]},
        minister=minister, words="着即擢用。",
    )
    assert first.commissions.rejected == [], first.commissions.rejected
    staged_id = int(db.conn.execute(
        "SELECT id FROM pending_actions WHERE turn=? AND kind='office' ORDER BY id",
        (int(state.turn),),
    ).fetchone()["id"])
    revision = {"commissions": [{
        "text": "改中旨径发。",
        "appointment": {
            "name": appointee, "office": "巡抚", "action": "任命", "mode": "midzhi",
        },
    }]}
    night_id, revision_ctid, approval_ctid, approve_held = _late_revision_and_approval(
        db, state, content, monkeypatch,
        revision,
        {"promises": [{"action_id": staged_id, "decision": "应允"}]},
        minister=minister, seal=seal,
    )
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
    keyed = [item for item in ledger if item["order_key"] is not None]
    assert len(keyed) == 1, [dict(item) for item in ledger]
    entry = keyed[0]
    assert int(entry["night_id"]) == int(night_id)
    assert int(entry["source_chat_turn_id"]) == revision_ctid
    assert int(entry["origin_chat_turn_id"]) == revision_ctid
    assert float(entry["order_key"]) == float(revision_seq)
    assert revision_seq != approval_seq

    approved = approve_held()
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
    with pytest.raises(AudienceTranslateError):
        run_turn_translation_job(
            db, state,
            emperor_message="改中旨径发。",
            reply="殿上应对。",
            night_id=night_id,
            chat_turn_id=revision_ctid,
            minister_name=minister,
            translate_fn=lambda prompt, config: _scene_payload(revision),
            write_gate=ClassifiedWriteGate(),
        )
    still_gone = db.conn.execute(
        "SELECT COUNT(*) AS n FROM story_ledger_entries "
        "WHERE source_chat_turn_id=? OR origin_chat_turn_id=?",
        (revision_ctid, revision_ctid),
    ).fetchone()["n"]
    assert int(still_gone) == 0


def test_secret_order_progress_is_stored_verbatim(game, monkeypatch):
    """进展与月度密奏共用奏报轨：原文、空白、换行原样留下。"""
    from tests.test_audience_translate_1837_reopen import _close_offline

    db, state, content = game
    minister = _minister(db)
    opened = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister), minister=minister,
    )
    assert opened.commissions.rejected == []
    order_id = int(
        _approve(
            db, state, content, monkeypatch,
            int(_staged_secret_order_rows(db, state.turn)[0]["id"]),
            minister=minister,
        ).promises.applied[0]["secret_order_id"]
    )
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    _close_offline(db, state, content, int(an.open_night(db, state)["id"]))
    state.turn = int(state.turn) + 1
    state.period = 4
    db.save_state(state)
    raw_note = f"\n  已查得线索，仍须密访。  \n〔{int(state.year)}年1月〕旧报未结。\n"
    other = _summonable_name(db, content)
    progress = {
        "commissions": [{
            "text": "据实以闻。",
            "secret_order_progress": {"order_id": order_id, "note": raw_note},
        }],
    }
    stolen = _emit(
        db, state, content, monkeypatch, progress,
        minister=other, words="据实以闻。",
    )
    assert stolen.commissions.applied == []
    assert _rejection_rows(db, state.turn)[-1]["category"] == "invalid_state"

    progressed = _emit(
        db, state, content, monkeypatch, progress,
        minister=an.SCENE_CHAT_SPEAKER, words="再据实以闻。",
    )
    assert progressed.commissions.rejected == [], progressed.commissions.rejected
    staged_id = int(progressed.commissions.applied[0]["id"])
    staged_name = db.conn.execute(
        "SELECT minister_name FROM pending_actions WHERE id=?",
        (staged_id,),
    ).fetchone()["minister_name"]
    assert staged_name == minister
    assert _approve(
        db, state, content, monkeypatch, staged_id, minister=minister,
    ).promises.rejected == []

    def _open_reports(conn_db):
        return [
            row for row in conn_db.list_dossier_progress(dossier_id)
            if not row["is_terminal"]
        ]

    first = _open_reports(db)
    assert len(first) == 1, first
    assert int(first[0]["turn"]) == int(state.turn)
    assert str(db.get_secret_order(order_id)["result"] or "") == ""
    assert db.sum_dossier_actual_progress_units(dossier_id) == 0

    corrected = "\n  同月更正：线索有误，仍须密访。  \n"
    from tests.test_audience_translate_1837_reopen import _player_month
    monkeypatch.setattr("ming_sim.month_chain.run_secret_orders_supply", lambda *a: {
        "dossier_progress_reports": [{
            "dossier_id": dossier_id, "progress_band": "在办", "memorial_text": corrected,
        }],
        "covert_exec_selections": [{"order_id": order_id, "fidelity": "忠实"}],
    })
    reported_turn = int(state.turn)
    _player_month(db, state, content, monkeypatch, dossier_id)
    live = _open_reports(db)
    assert len(live) == 1, live
    assert int(live[0]["turn"]) == reported_turn
    assert str(db.get_secret_order(order_id)["result"] or "") == ""
    assert db.sum_dossier_actual_progress_units(dossier_id) == 0

    reopened = GameDB(db.path, content)
    try:
        reread = _open_reports(reopened)
        assert len(reread) == 1
        assert int(reread[0]["turn"]) == reported_turn
        assert str(reopened.get_secret_order(order_id)["result"] or "") == ""
    finally:
        reopened.close()


def test_scene_review_claim_lands_on_the_review_rail(game, monkeypatch):
    """提交核议走现役暂存与应允。陈词进核议轨，不冒充月报。"""
    db, state, content = game
    minister = _minister(db)
    opened = _emit(
        db, state, content, monkeypatch,
        _secret_order_declaration(assignee=minister), minister=minister,
    )
    assert opened.commissions.rejected == []
    order_id = int(
        _approve(
            db, state, content, monkeypatch,
            int(_staged_secret_order_rows(db, state.turn)[0]["id"]),
            minister=minister,
        ).promises.applied[0]["secret_order_id"]
    )
    claim = "\n  臣已办结，请予核议。  \n"
    staged = _emit(
        db, state, content, monkeypatch,
        {"commissions": [{
            "text": "请核议。",
            "secret_order_review": {"order_id": order_id, "claim": claim},
        }]},
        minister=an.SCENE_CHAT_SPEAKER, words="请核议。",
    )
    assert staged.commissions.rejected == [], staged.commissions.rejected
    action_id = int(staged.commissions.applied[0]["id"])
    row = db.conn.execute(
        "SELECT action, minister_name, payload_json FROM pending_actions WHERE id=?",
        (action_id,),
    ).fetchone()
    assert row["action"] == "提交核议"
    assert row["minister_name"] == minister
    approved = _approve(
        db, state, content, monkeypatch, action_id, minister=minister,
    )
    assert approved.promises.rejected == [], approved.promises.rejected
    dossier_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    reviews = [
        item for item in db.list_dossier_progress(dossier_id)
        if str(item["origin"]) == db.DOSSIER_REPORT_ORIGIN_REVIEW
    ]
    assert len(reviews) == 1
    monthly = [
        item for item in db.list_dossier_progress(dossier_id)
        if not item["is_terminal"]
        and str(item["origin"]).startswith(db.DOSSIER_REPORT_ORIGIN_MONTHLY)
    ]
    assert monthly == []
