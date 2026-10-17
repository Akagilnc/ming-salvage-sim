from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation
from ming_sim.session_write_queue import get_session_write_queue
import json
from types import SimpleNamespace
import pytest
import ming_sim.audience_translate as audience_translate
from ming_sim.audience_night import (
    close_night,
    engine_command_mingfa_publication_ids,
    list_ledger,
    open_night,
)
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.decree_forecast import decree_ref_for_dossier
from tests.conftest import (
    offline_empty_audience_translate,
    persist_and_schedule_scene,
    stub_audience_translate,
)
"""#1837 C1a：召对转译——交办载荷与应允。

Seams:
- translate_audience_turn / apply_audience_round_translation（转译 → C0 分派）
- GameSession.scene_chat（回话后转译；退役并行分类器）
- close_night 收夜成案 → 过月落账
"""






def _sess(db, state, content, monkeypatch, *, llm_config=None, translate_fn=None):
    from tests.month_chain_helpers import make_light_session
    sess = make_light_session(db, state, content)
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    stub_audience_translate(monkeypatch, translate_fn)
    return sess


def _scene_turn(sess, db, state, message: str, *, night_id: int | None = None):
    """生产同形：建轮 → scene_chat(ctid) → persist + schedule → join。"""
    from ming_sim.audience_night import get_open_night
    nid = int(night_id or 0)
    if nid <= 0:
        open_n = get_open_night(db)
        nid = int(open_n["id"]) if open_n else 0
    ctid = db.create_chat_turn(
        state, "殿上", "test-sess", 0, night_id=nid or None,
    )
    result = sess.scene_chat(message, chat_turn_id=ctid, write_gate=sess._write_gate)
    fut = persist_and_schedule_scene(sess, db, result)
    if fut is not None:
        fut.result(timeout=30)
    assert get_session_write_queue(sess).wait_idle()
    return result, ctid


def _region_id(db, preferred: str = "shaanxi") -> str:
    row = db.conn.execute(
        "SELECT id FROM regions WHERE id=? LIMIT 1", (preferred,),
    ).fetchone()
    if row is not None:
        return str(row["id"])
    row = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def _hong_name(db, content) -> str:
    if "洪承畴" in getattr(content, "characters", {}):
        return "洪承畴"
    row = db.conn.execute(
        "SELECT name FROM characters WHERE name='洪承畴' LIMIT 1"
    ).fetchone()
    if row is not None:
        return str(row["name"])
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND power_id='ming' ORDER BY name LIMIT 1"
    ).fetchone()
    assert row is not None
    return str(row["name"])


def _persist_night_chat(db, state, night_id: int, user_text: str, reply: str) -> int:
    """把一轮皇帝/回话落到 chat_messages + chat_turns（真表形）。"""
    speaker = "殿上"
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'user', ?)",
        (speaker, int(state.turn), user_text),
    )
    uid = int(cur.lastrowid)
    cur = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (speaker, int(state.turn), reply),
    )
    mid = int(cur.lastrowid)
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name, turn, year, period, user_message_id, minister_message_id, "
        " status, night_id, night_seq) "
        "VALUES (?, ?, ?, ?, ?, ?, 'active', ?, "
        "COALESCE((SELECT MAX(night_seq) + 1 FROM chat_turns WHERE night_id=?), 1))",
        (
            speaker, int(state.turn), int(state.year), int(state.period),
            uid, mid, int(night_id), int(night_id),
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


@pytest.mark.parametrize("timing", ["before_close", "after_close", "undo"])
def test_pending_round_approval_endorsed_before_close_or_after_month_join(
    game, monkeypatch, timing,
):
    """#1842：应允+背书由转译声明；撤回、收夜成案或迟到直写案卷。"""
    from ming_sim.session_write_queue import SessionWriteQueue

    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    action = dispatch_declaration(
        db, state, {"commissions": [{"text": "着户部备赈济"}]},
        minister_name="", night_id=nid,
    )
    aid = int(action.commissions.applied[0]["id"])
    if timing != "after_close":
        class FakeAgent:
            def run(self, message):
                return SimpleNamespace(content="臣愿为此旨会签。", tools=[])

        monkeypatch.setattr(
            "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
        )

        def declared_translation(prompt, llm_config):
            return {
                **offline_empty_audience_translate(prompt, llm_config),
                "promises": [{"action_id": aid, "decision": "应允"}],
                "endorsements": [{
                    "action_id": aid, "form": "御笔手敕", "endorser_id": "",
                }],
            }

        sess = _sess(db, state, content, monkeypatch, translate_fn=declared_translation)
        _, ctid = _scene_turn(sess, db, state, "朕亲笔担此旨")
        if timing == "undo":
            payload = json.loads(db.conn.execute(
                "SELECT payload_json FROM pending_actions WHERE id=?", (aid,),
            ).fetchone()["payload_json"])
            assert len(payload["endorsements"]) == 1
            db.undo_chat_turn(ctid)
            restored = db.conn.execute(
                "SELECT payload_json, night_approved FROM pending_actions WHERE id=?", (aid,),
            ).fetchone()
            assert not json.loads(restored["payload_json"]).get("endorsements")
            assert not restored["night_approved"]
            close_night(db, state, content=content)
            assert db.conn.execute(
                "SELECT COUNT(*) FROM decree_dossiers WHERE pending_action_id=?", (aid,),
            ).fetchone()[0] == 0
            return
    else:
        def failed_translation(prompt, llm_config):
            raise RuntimeError("translation unavailable")

        class FakeAgent:
            def run(self, message):
                return SimpleNamespace(content="臣领旨。", tools=[])

        monkeypatch.setattr(
            "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
        )
        sess = _sess(db, state, content, monkeypatch, translate_fn=failed_translation)
        # 真召对入口：回话先落库、后台转译失败，留下待补轮。
        ctid = db.create_chat_turn(state, "殿上", "test-sess", 0, night_id=nid)
        result = sess.scene_chat("准", chat_turn_id=ctid, write_gate=sess._write_gate)
        future = persist_and_schedule_scene(sess, db, result)
        assert future is not None
        with pytest.raises(RuntimeError):
            future.result(timeout=30)

    write_queue = SessionWriteQueue()
    close_kwargs = dict(
        content=content, llm_config=object(),
        write_gate=write_queue.write_gate, write_queue=write_queue,
    )
    if timing == "before_close":
        close_night(db, state, **close_kwargs)
    else:
        # 回话已持久化而转译失败；收夜补跑也失败，过月入口才补齐。
        close_night(db, state, **close_kwargs)

        def recovered_translation(prompt, llm_config):
            return {
                **offline_empty_audience_translate(prompt, llm_config),
                "promises": [{"action_id": aid, "decision": "应允"}],
                "endorsements": [{
                    "action_id": aid, "form": "御笔手敕", "endorser_id": "",
                }],
            }

        stub_audience_translate(monkeypatch, recovered_translation)
        sess = _sess(db, state, content, monkeypatch, translate_fn=recovered_translation)
        sess.await_translations_before_month()

    row = db.conn.execute(
        "SELECT status, night_approved "
        "FROM pending_actions WHERE id=?", (aid,),
    ).fetchone()
    assert row["status"] == "committed"
    assert int(row["night_approved"] or 0) == 1
    did = int(db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (aid,),
    ).fetchone()["id"])
    ends = db.dossiers.endorsements(did)
    assert len(ends) == 1
    assert ends[0]["form"] == "御笔手敕"
    assert ends[0]["source_chat_turn_id"] == ctid
    directive_id = int(db.conn.execute(
        "SELECT id FROM turn_directives WHERE source_pending_action_id=?", (aid,),
    ).fetchone()["id"])
    pubs = engine_command_mingfa_publication_ids(list_ledger(db, nid))
    assert directive_id in pubs


def test_translation_entry_preserves_unknown_rejection(
    game, monkeypatch,
):
    """真实转译入口必要拒收负向：未知 section、坏形状。

    不宣称证明源轮截止；截止属生产契约，测试缺陷不得指控生产截止错误。
    """
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    _persist_night_chat(db, state, night_id, "第一问", "第一答")
    source = _persist_night_chat(db, state, night_id, "本轮问", "本轮答")
    night_said = audience_translate.build_night_said_so_far(
        db, night_id, until_chat_turn_id=source,
    )

    declaration = {
        "commissions": [{"text": "拟旨赈济"}],
        "commisssions": [{"text": "拼错交办"}],
        "scene_facts": [
            {"body": "提及未在册者", "role": "scene", "person_names": ["未在册者"]},
        ],
    }

    from ming_sim.audience_translation import apply_audience_round_translation
    stub_audience_translate(monkeypatch, lambda prompt, config: {
        **offline_empty_audience_translate(prompt, config), **declaration,
    })
    decl = audience_translate.translate_audience_turn(
        emperor_message="本轮问",
        reply="本轮答",
        night_said=night_said,
        pending_summaries=audience_translate.build_pending_summaries(
            db, int(state.turn), night_id=night_id,
        ),
    )
    applied = apply_audience_round_translation(
        db, state, decl,
        night_id=night_id, chat_turn_id=source,
        minister_name=_hong_name(db, content),
    )

    pending = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE status='pending' ORDER BY id"
    ).fetchall()
    pending_payloads = [json.loads(row["payload_json"]) for row in pending]
    assert any(
        isinstance(payload, dict) and payload.get("text") == "拟旨赈济"
        for payload in pending_payloads
    )
    rejected = db.conn.execute(
        "SELECT section, category FROM rejection_reports WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    assert any(
        row["section"] == "commisssions" and row["category"] == "invalid_shape"
        for row in rejected
    )
    assert db.conn.execute(
        "SELECT COUNT(*) FROM story_ledger_entries WHERE night_id=? AND id=?",
        (night_id, applied.scene_facts.applied[0]["id"]),
    ).fetchone()[0] == 1
    malformed = dispatch_declaration(
        db, state,
        {"scene_facts": [{"body": "坏形状", "role": ["scene"], "person_names": []}]},
        minister_name="", night_id=night_id,
    )
    assert len(malformed.scene_facts.rejected) == 1


def test_summons_translation_does_not_apply_monthly_effects_at_night(game):
    """召对夜只接当场实况；旨意办理效果只能在过月时落账。"""
    db, state, _ = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    chat_turn_id = _active_chat_turn(db, state, night_id)
    army_row = db.conn.execute("SELECT id, morale FROM armies ORDER BY id LIMIT 1").fetchone()
    assert army_row is not None
    army_id, morale_before = str(army_row["id"]), int(army_row["morale"])

    from ming_sim.audience_translation import apply_audience_round_translation
    result = apply_audience_round_translation(
        db, state,
        {"effects": {"army_delta": {
            army_id: {"origin_ref": "夜里预推", "morale": 1},
        }}},
        night_id=night_id,
        chat_turn_id=chat_turn_id,
    )

    assert result.effects.applied == []
    assert len(result.effects.rejected) == 1
    assert int(db.conn.execute(
        "SELECT morale FROM armies WHERE id=?", (army_id,),
    ).fetchone()[0]) == morale_before
    rejection = db.conn.execute(
        "SELECT section, category, reason FROM rejection_reports "
        "WHERE turn=? AND section='effects' ORDER BY id DESC LIMIT 1",
        (int(state.turn),),
    ).fetchone()
    assert rejection is not None
    assert rejection["category"] == "invalid_state"


def make_commissions_then_approve_translate(db, *commission_rounds):
    """共享转译协议：若干轮 commissions 后，下一轮批量应允本夜 pending。

    1837 分条装夹与 1861 任免预推共用，禁各案另写一份同形协议。
    可先塞旧候选轮再落本轮分条（同向复用前置）。
    """
    rounds = [list(r) for r in commission_rounds] or [[]]
    calls = {"n": 0}

    def translate_fn(prompt, llm_config, _rounds=rounds, _db=db):
        calls["n"] += 1
        if calls["n"] <= len(_rounds):
            return {
                **offline_empty_audience_translate(prompt, llm_config),
                "commissions": list(_rounds[calls["n"] - 1]), "promises": [],
            }
        rows = _db.conn.execute(
            "SELECT id FROM pending_actions WHERE status='pending' ORDER BY id"
        ).fetchall()
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "commissions": [],
            "promises": [
                {"action_id": int(r["id"]), "decision": "应允"} for r in rows
            ],
        }

    return translate_fn


def _appoint_grant_through_scene_chat(
    db, state, content, monkeypatch, *,
    person: str, office: str, edict: str, grant: dict, mode: str = "ordinary",
    region_id: str = "",
    appointment_text: str | None = None,
    grant_text: str | None = None,
    affair_declaration: dict | None = None,
    prior_appointment_text: str | None = None,
):
    """共用装夹：scene_chat 两条独立交办（任免+拨帑）→ 应允 → 收夜。

    #1928：一道一声明，不再同条合挂；正向案从契约要求的两条声明进入。
    属地任免由声明自带 region_id，不从拨帑抄。
    每道 commission.text 默认按本道旨意正文分供，不再把完整多旨原句复用为每道正文。
    prior_appointment_text：可选同向旧候选前置，本轮复用同一 office id。
    返回 (pending_by_kind, appt, grant, appt_body, grant_body, prior_office_id)。
    """

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    open_night(db, state, location="乾清宫", time_of_day="夜")
    appointment = {
        "name": person, "office": office, "appoint_action": "任命",
    }
    if region_id:
        appointment["region_id"] = region_id
    appt_body = (
        appointment_text if appointment_text is not None else f"任命{person}为{office}"
    )
    grant_body = grant_text if grant_text is not None else (
        f"{grant.get('grant_action') or '拨款'}"
        f"{grant.get('amount') or ''}万两"
    )
    appt_item = {
        "text": appt_body,
        "mode": mode,
        "appointment": dict(appointment),
    }
    grant_item = {
        "text": grant_body,
        "mode": mode,
        "grant": grant,
    }
    if affair_declaration is not None:
        appt_item["affair_declaration"] = dict(affair_declaration)
        grant_item["affair_declaration"] = dict(affair_declaration)
    commissions = [appt_item, grant_item]
    rounds: list = []
    if prior_appointment_text:
        rounds.append([{
            "text": prior_appointment_text,
            "mode": mode,
            "appointment": dict(appointment),
        }])
    rounds.append(commissions)
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=make_commissions_then_approve_translate(db, *rounds),
    )
    prior_office_id = 0
    if prior_appointment_text:
        _scene_turn(sess, db, state, prior_appointment_text)
        prior_row = db.conn.execute(
            "SELECT id FROM pending_actions "
            "WHERE status='pending' AND kind='office' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert prior_row is not None
        prior_office_id = int(prior_row["id"])
    _scene_turn(sess, db, state, edict)
    pending = [
        dict(r) for r in db.conn.execute(
            "SELECT id, kind, action, payload_json, night_approved, version "
            "FROM pending_actions WHERE status='pending' ORDER BY id"
        ).fetchall()
    ]
    assert len(pending) == 2, pending
    assert sorted(p["kind"] for p in pending) == ["directive", "office"], pending
    by_kind = {p["kind"]: p for p in pending}
    if prior_office_id:
        assert int(by_kind["office"]["id"]) == prior_office_id
        assert int(by_kind["office"].get("version") or 1) >= 2
    _scene_turn(sess, db, state, "准")
    approved = db.conn.execute(
        "SELECT id, night_approved FROM pending_actions "
        "WHERE id IN ({})".format(",".join(str(p["id"]) for p in pending))
    ).fetchall()
    assert all(int(r["night_approved"] or 0) == 1 for r in approved), approved
    close_night(db, state, content=content)
    for p in pending:
        row = db.conn.execute(
            "SELECT status FROM pending_actions WHERE id=?", (int(p["id"]),),
        ).fetchone()
        assert row["status"] == "committed", (p["kind"], row["status"])
    appt_id_row = db.conn.execute(
        "SELECT id FROM decree_dossiers "
        "WHERE action_type='appointment' AND target_id=? "
        "ORDER BY id DESC LIMIT 1",
        (person,),
    ).fetchone()
    grant_id_row = db.conn.execute(
        "SELECT id FROM decree_dossiers "
        "WHERE action_type='grant_allocation' AND pending_action_id=? "
        "ORDER BY id DESC LIMIT 1",
        (int(by_kind["directive"]["id"]),),
    ).fetchone()
    assert appt_id_row is not None and grant_id_row is not None
    appt = db.dossiers.get(int(appt_id_row["id"]))
    grant_row = db.dossiers.get(int(grant_id_row["id"]))
    assert appt is not None and grant_row is not None
    assert int(appt["pending_action_id"]) == int(by_kind["office"]["id"])
    assert int(appt["pending_action_id"]) != int(grant_row["pending_action_id"])
    return by_kind, appt, grant_row, appt_body, grant_body, prior_office_id


def test_split_appoint_grant_scene_readers(game, monkeypatch):
    """#1928 分条任免+拨帑：最小输入表，每行场景一次，读者集中断言。

    覆盖：独立身份/模式、共享与不共享事务、本道正文、落账、同向复用
    （旧候选前置→同一 id 新正文）；不同输入行各执行一次全链，不另搭平行场景。
    """
    db, state, content = game
    person = _hong_name(db, content)
    region = _region_id(db)
    cases = (
        {
            "label": "shared_midzhi_relief",
            "office": "陕西巡抚",
            "mode": "midzhi",
            "region_id": region,
            "appt_text": f"任命{person}为陕西巡抚",
            "grant_text": "调银三十万两赈灾",
            "prior_appointment_text": None,
            "affair": {
                "attach": "new",
                "identity": "one-undertaking",
                "name": "陕西巡抚兼赈灾",
                "origin": "召对分条",
            },
            "grant": {
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "cadence": "一次性", "execution_surface": "immediate",
            },
            "grant_target_id": region,
            "ledger_target_id": region,
            "ledger_delta": -30,
            "same_affair": True,
            "promulgate": True,
        },
        {
            "label": "reuse_then_shared_affair",
            # 同向旧候选前置：本轮新正文+共享 identity 须落同一 office id。
            "office": "兵部右侍郎",
            "mode": "ordinary",
            "region_id": "",
            "prior_appointment_text": f"任命{person}为兵部右侍郎",
            "appt_text": f"改任{person}为兵部右侍郎专办边饷",
            "grant_text": "再拨银十五万两给陕西",
            "affair": {
                "attach": "new",
                "identity": "reuse-one",
                "name": "兵部右侍郎兼陕西",
                "origin": "同向复用",
            },
            "grant": {
                "grant_action": "赈灾", "amount": 15, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
            "grant_target_id": region,
            "ledger_target_id": region,
            "ledger_delta": -15,
            "same_affair": True,
            "promulgate": True,
        },
        {
            "label": "separate_ordinary_reward",
            # 换中央职，避免首案落职后同职任命被 noop 吞掉；region_id='' 咬幂等键。
            "office": "户部右侍郎",
            "mode": "ordinary",
            "region_id": "",
            "prior_appointment_text": None,
            "appt_text": f"任命{person}为户部右侍郎",
            "grant_text": "赏银二十万两",
            "affair": {
                "attach": "new",
                "name": "各自新事务",
                "origin": "无共享 identity",
            },
            "grant": {
                "grant_action": "赏赉", "amount": 20, "account": "国库",
                "target_kind": "character", "target_id": person,
                "execution_surface": "immediate",
            },
            "grant_target_id": person,
            "ledger_target_id": person,
            "ledger_delta": -20,
            "same_affair": False,
            "promulgate": True,
        },
    )

    for case in cases:
        edict = f"{case['appt_text']}，{case['grant_text']}"
        by_kind, appt, grant_row, appt_body, grant_body, prior_office_id = (
            _appoint_grant_through_scene_chat(
                db, state, content, monkeypatch,
                person=person, office=case["office"], edict=edict,
                grant=case["grant"], mode=case["mode"],
                region_id=case["region_id"],
                appointment_text=case["appt_text"],
                grant_text=case["grant_text"],
                affair_declaration=case["affair"],
                prior_appointment_text=case.get("prior_appointment_text"),
            )
        )
        if case.get("prior_appointment_text"):
            assert prior_office_id == int(by_kind["office"]["id"]), case["label"]
            assert int(by_kind["office"].get("version") or 1) >= 2, case["label"]
        office_payload = json.loads(by_kind["office"]["payload_json"])
        grant_payload = json.loads(by_kind["directive"]["payload_json"])
        assert grant_payload["grant_action"] == case["grant"]["grant_action"], case["label"]
        assert int(grant_payload["amount"]) == int(case["grant"]["amount"]), case["label"]
        assert str(grant_payload.get("appoint_action") or "") == "", case["label"]
        assert office_payload["name"] == person, case["label"]
        assert office_payload["office"] == case["office"], case["label"]
        assert office_payload["appoint_action"] == "任命", case["label"]
        assert office_payload.get("mode") == case["mode"], case["label"]
        assert grant_payload.get("mode") == case["mode"], case["label"]
        assert str(grant_row.get("target_id") or "") == case["grant_target_id"], case[
            "label"
        ]

        appt_ref = decree_ref_for_dossier(db, appt)
        grant_ref = decree_ref_for_dossier(db, grant_row)
        assert appt_ref != grant_ref, case["label"]
        assert appt_ref.startswith("pending-action:"), case["label"]
        assert grant_ref.startswith("pending-action:"), case["label"]
        assert str(appt.get("mode") or "") == case["mode"], case["label"]
        assert str(grant_row.get("mode") or "") == case["mode"], case["label"]

        # 本道正文运输
        assert str(appt["decree_text"] or "") == appt_body, case["label"]
        assert str(grant_row["decree_text"] or "") == grant_body, case["label"]
        appt_payload = json.loads(str(appt.get("payload_json") or "{}"))
        grant_dossier_payload = json.loads(str(grant_row.get("payload_json") or "{}"))
        assert str(appt_payload.get("text") or "") == appt_body, case["label"]
        assert str(grant_dossier_payload.get("text") or "") == grant_body, case["label"]

        # 事务共享 / 不归并
        assert int(appt["affair_id"] or 0) > 0, case["label"]
        assert int(grant_row["affair_id"] or 0) > 0, case["label"]
        if case["same_affair"]:
            assert int(appt["affair_id"]) == int(grant_row["affair_id"]), case["label"]
        else:
            assert int(appt["affair_id"]) != int(grant_row["affair_id"]), case["label"]

        if not case["promulgate"]:
            continue
        state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 100)
        db.reign.save_game_state(state)
        apply_dossier_promulgation(
            db, state, int(grant_row["id"]), decision="promulgated", content=content,
        )
        if str(appt["status"]) == "proposed":
            apply_dossier_promulgation(
                db, state, int(appt["id"]), decision="promulgated", content=content,
            )

        char = db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (person,),
        ).fetchone()
        assert case["office"] in str(char["office"] or ""), case["label"]
        moved = db.conn.execute(
            "SELECT delta FROM economy_ledger WHERE account='国库' "
            "AND target_id=? AND delta < 0 ORDER BY id DESC LIMIT 1",
            (case["ledger_target_id"],),
        ).fetchone()
        assert moved is not None and int(moved["delta"]) == case["ledger_delta"], (
            case["label"], moved,
        )


def test_reject_grant_only_appointment_lands_without_rescript(game, monkeypatch):
    """#1928：外廷只打回拨款——任命落职且不进批红；拨款 rejected+rescript。

    与落账正向不同判向，必要单独场景；不重复事务/正文读者。
    """
    db, state, content = game
    person = _hong_name(db, content)
    region = _region_id(db)
    edict = f"任{person}为户部右侍郎，再拨银三十万两给陕西"
    _by_kind, appt, grant, _appt_body, _grant_body, _prior = (
        _appoint_grant_through_scene_chat(
            db, state, content, monkeypatch,
            person=person, office="户部右侍郎", edict=edict,
            grant={
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        )
    )

    state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 100)
    db.reign.save_game_state(state)
    apply_dossier_promulgation(
        db, state, int(appt["id"]), decision="promulgated", content=content,
    )
    apply_dossier_promulgation(
        db, state, int(grant["id"]), decision="rejected",
        blocked_layer="six_offices", reason="库银不足", content=content,
    )

    char = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (person,),
    ).fetchone()
    assert "户部右侍郎" in str(char["office"] or "")
    appt_row = db.dossiers.get(int(appt["id"]))
    grant_row = db.dossiers.get(int(grant["id"]))
    assert str(appt_row["promulgation_decision"] or "") == "promulgated"
    assert not bool(appt_row.get("rescript_pending"))
    assert str(grant_row["promulgation_decision"] or "") == "rejected"
    assert bool(grant_row.get("rescript_pending"))


def test_emperor_准_via_scene_chat_approves_no_reply_stays_unapproved(game, monkeypatch):
    """AC2：经 scene_chat 转译，「准」应允；不声明 promises 则默认不应允。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "着户部备赈灾银"}]},
        minister_name="", night_id=int(
            db.conn.execute(
                "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
        ),
    )
    staged_id = int(staged.commissions.applied[0]["id"])

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣在。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )

    # 不表态：空 promises
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=offline_empty_audience_translate,
    )
    _scene_turn(sess, db, state, "边事如何？")
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 0

    # 「准」
    def approve_fn(prompt, cfg):
        return {
            **offline_empty_audience_translate(prompt, cfg),
            "commissions": [],
            "promises": [{"action_id": staged_id, "decision": "应允"}],
        }

    stub_audience_translate(monkeypatch, approve_fn)
    _scene_turn(sess, db, state, "准")
    row = db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert int(row["night_approved"] or 0) == 1

    close_night(
        db, state, content=content,
        write_gate=sess._write_gate, write_queue=sess._write_queue,
        llm_config=sess.llm_config,
    )
    pa = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (staged_id,),
    ).fetchone()
    assert pa["status"] == "committed"
    assert db.conn.execute(
        "SELECT 1 FROM turn_directives WHERE source_pending_action_id=?", (staged_id,),
    ).fetchone() is not None


@pytest.mark.parametrize("message", ["留下听着", "今日就到这里吧"])
def test_scene_chat_cli_and_api_same_translation_shape(game, monkeypatch, message):
    """AC3：CLI 与 API 通道产出同一形状，不再前缀+二次分类两套路。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    region = _region_id(db)
    person = _hong_name(db, content)
    edict = f"任命{person}为陕西巡抚，调银三十万两赈灾"
    # #1928：CLI/API 同形亦从两条独立声明进入，不保留同条合挂夹具；
    # 每道 text 为本道旨意正文，不把完整多旨原句复用为两道正文。
    declaration = {
        "commissions": [
            {
                "text": f"任命{person}为陕西巡抚",
                "appointment": {
                    "name": person, "office": "陕西巡抚", "appoint_action": "任命",
                    "region_id": region,
                },
            },
            {
                "text": "调银三十万两赈灾",
                "grant": {
                    "grant_action": "赈灾", "amount": 30, "account": "国库",
                    "target_kind": "region", "target_id": region,
                    "execution_surface": "immediate",
                },
            },
        ],
        "promises": [],
    }

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    payloads = []
    for channel in ("api", "cli"):
        # 通道间清 pending，避免同向任免撞上上一通道候选而改写既有行。
        db.conn.execute("DELETE FROM pending_actions WHERE status='pending'")
        db.conn.commit()

        def translate_fn(prompt, llm_config, _decl=declaration):
            return {**offline_empty_audience_translate(prompt, llm_config), **_decl}

        sess = _sess(
            db, state, content, monkeypatch,
            llm_config=SimpleNamespace(channel=channel),
            translate_fn=translate_fn,
        )
        before_id = db.conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS mid FROM pending_actions"
        ).fetchone()["mid"]
        before = db.conn.execute(
            "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"]
        result, _ = _scene_turn(sess, db, state, message)
        after = db.conn.execute(
            "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
        ).fetchone()["c"]
        assert after - before == 2, (channel, before, after)
        rows = [
            dict(row)
            for row in db.conn.execute(
                "SELECT kind, payload_json FROM pending_actions "
                "WHERE status='pending' AND id > ? ORDER BY kind, id",
                (before_id,),
            ).fetchall()
        ]
        assert [r["kind"] for r in rows] == ["directive", "office"], channel
        payloads.append([r["payload_json"] for r in rows])

    assert len(payloads) == 2
    assert payloads[0] == payloads[1]


def test_unhandleable_commission_rejected_as_fact_no_forced_ask(game):
    """AC4：查无此人 / 幻影地区 → 拒收当事实；不强制追问。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    missing_person = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "任命子虚乌有为陕西巡抚",
            "appointment": {
                "name": "子虚乌有某某", "office": "陕西巡抚", "appoint_action": "任命",
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert missing_person.commissions.applied == []
    assert missing_person.commissions.rejected
    assert any(
        getattr(r, "category", "") == "hallucinated_id"
        for r in missing_person.commissions.rejected
    )

    missing_region = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "着拨银赈济无此州",
            "grant": {
                "grant_action": "赈灾",
                "amount": 10,
                "account": "国库",
                "target_kind": "region",
                "target_id": "no-such-region-xyz",
                "execution_surface": "immediate",
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert missing_region.commissions.applied == []
    assert missing_region.commissions.rejected
    assert any(
        getattr(r, "category", "") == "hallucinated_id"
        for r in missing_region.commissions.rejected
    )


def test_translate_call_failure_is_not_empty_success_dispatch(game, monkeypatch):
    """转译调用失败 ≠ 成功空声明：不进分派、真因经 story_extract pending 水位回场。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    before = db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
    ).fetchone()["c"]

    def boom(prompt, llm_config):
        raise RuntimeError("simulated translate transport failure")

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣在。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )
    sess = _sess(db, state, content, monkeypatch, translate_fn=boom)
    ctid = db.create_chat_turn(state, "殿上", "test-sess", 0, night_id=None)
    # 开夜由 scene_chat 内部 ensure
    result = sess.scene_chat("边饷如何？", chat_turn_id=ctid, write_gate=sess._write_gate)
    fut = persist_and_schedule_scene(sess, db, result)
    assert fut is not None
    with pytest.raises(RuntimeError, match="simulated translate transport failure"):
        fut.result(timeout=30)
    assert result.answer == "臣在。"
    after = db.conn.execute(
        "SELECT COUNT(*) c FROM pending_actions WHERE status='pending'"
    ).fetchone()["c"]
    assert after == before  # 失败不得当分派成功写库
    # 后台失败 → 待补水位，不洗成成功空声明
    assert db.reign.get_story_extract_status(ctid) == "pending"


def test_appointment_without_text_is_rejected_not_templated(game):
    """P7：任免缺正文拒收；坏项不入 pending 账。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    person = _hong_name(db, content)
    before_pending = {
        int(r["id"])
        for r in db.conn.execute(
            "SELECT id FROM pending_actions WHERE status='pending'"
        ).fetchall()
    }
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
        }]},
        minister_name="", night_id=int(night["id"]),
    )
    assert result.commissions.applied == []
    assert result.commissions.rejected
    after_pending = {
        int(r["id"])
        for r in db.conn.execute(
            "SELECT id FROM pending_actions WHERE status='pending'"
        ).fetchall()
    }
    assert after_pending == before_pending


def _active_chat_turn(db, state, night_id: int) -> int:
    """建可撤回的存活轮（status=active；挂夜默认 generating 不可 undo）。"""
    return db.create_chat_turn(
        state, "殿上", "s", 0, night_id=int(night_id), status="active",
    )


def test_translation_pending_create_approve_reject_undo_via_real_chat_turn(
    game, monkeypatch,
):
    """源轮贯穿 scene_chat→转译链：pending 新增/应允/拒绝三向真 undo 可逆。

    不另造平行快照；ctid 下传 dispatch_declaration 入口自记前像（#1839 C2）。
    """
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    class FakeAgent:
        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent(),
    )

    # ── 1) 新增：转译落 pending → undo 按来源轮作废 ──
    # #1890：本轮首次落下的交办按 source_chat_turn_id 整轮作废（voided 墓碑），
    # 不再删行——ADR 0038 的硬删除只对「已落账逆转」仍有效，暂存交办按
    # 2026-09-29 owner 裁定改作废标记。行留着，迟到的写入读它只会看到 voided。
    ctid_create = _active_chat_turn(db, state, night_id)
    create_text = "着户部备陕西赈灾银UNIQUE-CREATE"
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=lambda p, c: {
            **offline_empty_audience_translate(p, c),
            "commissions": [{"text": create_text}],
            "promises": [],
        },
    )
    r = sess.scene_chat("拟赈灾", chat_turn_id=ctid_create, write_gate=sess._write_gate)
    # #1902 T6：ChatTurnResult 不再挂 pending_action_id；前台不等后台转译由落库后查证。
    persist_and_schedule_scene(sess, db, r)
    sess._write_queue.barrier(lambda: None)
    created_id = None
    for row in db.conn.execute(
        "SELECT id, payload_json FROM pending_actions ORDER BY id DESC",
    ).fetchall():
        payload = json.loads(row["payload_json"] or "{}")
        if payload.get("text") == create_text:
            created_id = int(row["id"])
            break
    assert created_id is not None
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM pending_actions WHERE id=? AND status='pending'",
        (created_id,),
    ).fetchone()["n"] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM chat_turn_rollback_items WHERE chat_turn_id=?",
        (ctid_create,),
    ).fetchone()["n"] > 0
    db.undo_chat_turn(ctid_create)
    # 墓碑在行上，但不再是活暂存：读口（pending 集 / 本轮交办读口）都看不到它。
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (created_id,),
    ).fetchone()["status"] == "voided"
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM pending_actions WHERE id=? AND status='pending'",
        (created_id,),
    ).fetchone()["n"] == 0

    # ── 2) 应允：night_approved 0→1 → undo 回 0 ──
    baseline = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "旧暂存待应允UNIQUE-APPROVE"}]},
        minister_name="", night_id=night_id,
    )
    approve_id = int(baseline.commissions.applied[0]["id"])
    assert int(db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (approve_id,),
    ).fetchone()["night_approved"] or 0) == 0

    ctid_approve = _active_chat_turn(db, state, night_id)
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=lambda p, c: {
            **offline_empty_audience_translate(p, c),
            "commissions": [],
            "promises": [{"action_id": approve_id, "decision": "应允"}],
        },
    )
    r_approve = sess.scene_chat("准", chat_turn_id=ctid_approve, write_gate=sess._write_gate)
    persist_and_schedule_scene(sess, db, r_approve)
    sess._write_queue.barrier(lambda: None)
    assert int(db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (approve_id,),
    ).fetchone()["night_approved"] or 0) == 1
    db.undo_chat_turn(ctid_approve)
    assert int(db.conn.execute(
        "SELECT night_approved FROM pending_actions WHERE id=?", (approve_id,),
    ).fetchone()["night_approved"] or 0) == 0

    # ── 3) 拒绝：删 pending 行 → undo 复原 ──
    reject_base = dispatch_declaration(
        db, state,
        {"commissions": [{"text": "旧暂存待拒绝UNIQUE-REJECT"}]},
        minister_name="", night_id=night_id,
    )
    reject_id = int(reject_base.commissions.applied[0]["id"])
    before_payload = db.conn.execute(
        "SELECT payload_json, kind, action, status FROM pending_actions WHERE id=?",
        (reject_id,),
    ).fetchone()
    assert before_payload is not None

    ctid_reject = _active_chat_turn(db, state, night_id)
    sess = _sess(
        db, state, content, monkeypatch,
        translate_fn=lambda p, c: {
            **offline_empty_audience_translate(p, c),
            "commissions": [],
            "promises": [{"action_id": reject_id, "decision": "拒绝"}],
        },
    )
    r_reject = sess.scene_chat("不准", chat_turn_id=ctid_reject, write_gate=sess._write_gate)
    persist_and_schedule_scene(sess, db, r_reject)
    sess._write_queue.barrier(lambda: None)
    assert db.conn.execute(
        "SELECT COUNT(*) n FROM pending_actions WHERE id=?", (reject_id,),
    ).fetchone()["n"] == 0
    db.undo_chat_turn(ctid_reject)
    restored = db.conn.execute(
        "SELECT payload_json, kind, action, status FROM pending_actions WHERE id=?",
        (reject_id,),
    ).fetchone()
    assert restored is not None
    assert restored["status"] == before_payload["status"]
    assert restored["kind"] == before_payload["kind"]
    assert restored["action"] == before_payload["action"]
    assert restored["payload_json"] == before_payload["payload_json"]


def test_pure_office_dossier_uses_payload_text_not_template(game):
    """纯任免成案核消费 payload 原样 text，不拼「任命X为Y」模板。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    person = _hong_name(db, content)
    edict = f"  着以{person}巡抚陕西，专办边饷UNIQUE-OFFICE-TEXT\n"
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": edict,
            "appointment": {
                "name": person, "office": "陕西巡抚", "appoint_action": "任命",
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert len(staged.commissions.applied) == 1
    pa = staged.commissions.applied[0]
    assert pa["kind"] == "office"
    pending_id = int(pa["id"])

    payload = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?",
            (pending_id,),
        ).fetchone()["payload_json"]
    )
    # 输入 edict 原样进 pending payload.text（#1897 T1 运输）
    assert payload["text"] == edict

    db.mark_pending_night_approved([pending_id], night_id=night_id)
    close_night(db, state, content=content)

    dossier = db.conn.execute(
        "SELECT action_type, status, decree_text, payload_json "
        "FROM decree_dossiers WHERE pending_action_id=? "
        "AND action_type='appointment' ORDER BY id DESC LIMIT 1",
        (pending_id,),
    ).fetchone()
    assert dossier is not None, "纯任免应收夜成 appointment 案卷"
    assert dossier["action_type"] == "appointment"
    assert dossier["decree_text"] == edict
    dossier_payload = json.loads(dossier["payload_json"] or "{}")
    assert dossier_payload.get("text") == edict


def test_appointment_region_id_stages_into_pending_payload(game):
    """地方任命声明带 region_id 时原样进 office pending，不从官名推断。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    person = _hong_name(db, content)
    region = _region_id(db)
    edict = f"着以{person}巡抚陕西 UNIQUE-REGION-SEAT"
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": edict,
            "appointment": {
                "name": person,
                "office": "陕西巡抚",
                "appoint_action": "任命",
                "region_id": region,
            },
        }]},
        minister_name="", night_id=night_id,
    )
    assert len(staged.commissions.applied) == 1
    pa = staged.commissions.applied[0]
    assert pa["kind"] == "office"
    payload = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?",
            (int(pa["id"]),),
        ).fetchone()["payload_json"]
    )
    assert payload.get("text") == edict
    assert payload.get("region_id") == region


@pytest.mark.parametrize("scene_name,record_speaker", [("殿上", True), ("", False)])
def test_strategy_selection_actor_bound_to_minister_not_scene(game, scene_name, record_speaker):
    """The declared proposer owns the strategy, independent of scene metadata."""
    db, state, content = game
    from ming_sim.audience_translation import apply_audience_round_translation
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    minister = _hong_name(db, content)
    ctid1 = _persist_night_chat(db, state, nid, "卿有何策？", "臣请平辽。")
    decl1 = {
        "scene_facts": [{
            "body": "臣请平辽。",
            "role": "minister",
            "person_names": [minister],
            "tags": [],
        }]
    }
    apply_audience_round_translation(
        db, state, decl1 if record_speaker else {},
        night_id=nid, chat_turn_id=ctid1, minister_name=scene_name,
    )
    ctid2 = _persist_night_chat(db, state, nid, "准卿平辽之策", "谢皇上。")
    decl2 = {
        "commissions": [{
            "text": "准卿平辽之策",
            "strategy_selection": {
                "target_id": "policy_pingliao",
                "source_chat_turn_id": ctid1,
                "proposer": minister,
            },
        }]
    }
    res = apply_audience_round_translation(
        db, state, decl2, night_id=nid, chat_turn_id=ctid2, minister_name=scene_name,
    )
    assert len(res.commissions.applied) == 1
    assert not res.commissions.rejected
    aid = int(res.commissions.applied[0]["id"])
    row = db.conn.execute(
        "SELECT minister_name, payload_json FROM pending_actions WHERE id=?",
        (aid,),
    ).fetchone()
    assert row is not None
    assert row["minister_name"] == minister
    payload = json.loads(row["payload_json"])
    assert payload.get("actor") == minister
    assert payload.get("source_chat_turn_id") == ctid1


@pytest.mark.parametrize("proposer,category", [
    ("查无此人_虚构大臣", "hallucinated_id"),
    ("殿上", "hallucinated_id"),
    (None, "invalid_shape"),
])
def test_strategy_selection_invalid_proposer_rejected(game, proposer, category):
    """Invalid identities are durably rejected without staging a directive."""
    db, state, _ = game
    from ming_sim.audience_translation import apply_audience_round_translation
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    ctid1 = _persist_night_chat(db, state, nid, "卿有何策？", "臣有一策。")
    ctid2 = _persist_night_chat(db, state, nid, "准所奏", "谢皇上。")
    decl2 = {
        "commissions": [{
            "text": "准所奏",
            "strategy_selection": {
                "target_id": "policy_pingliao",
                "source_chat_turn_id": ctid1,
                "proposer": proposer,
            },
        }]
    }
    res = apply_audience_round_translation(
        db, state, decl2, night_id=nid, chat_turn_id=ctid2, minister_name="殿上",
    )
    assert len(res.commissions.applied) == 0
    assert len(res.commissions.rejected) == 1
    assert res.commissions.rejected[0].category == category
    assert db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == 0
    reports = db.conn.execute("SELECT category FROM rejection_reports").fetchall()
    assert [row["category"] for row in reports] == [category]
