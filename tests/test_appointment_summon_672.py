import json
from pathlib import Path

import pytest

import ming_sim.cli_backend as cb
import ming_sim.audience_night as audience_night
from ming_sim.audience_night import (
    CLOSE_STEP_COMMIT_OFFICE,
    AudienceNightError,
    list_unsettled_summons,
    open_night,
)
from ming_sim.distance import DistanceMatrix
from ming_sim.exceptions import SettlementAbort
from ming_sim.session import GameSession
from ming_sim.decree import prepare_resolve_front_half, settle_with_delta
from tests.dossier_test_helpers import rejected_verdict
from tests.test_qa_c_p0_1380_1355 import _fake_session, _minister_wang_shaohui

_MATRIX = DistanceMatrix.from_file(
    Path(__file__).resolve().parents[1] / "content/distance_matrix.json"
)


class _FakeRegistry:
    def __init__(self):
        self.refreshed = []

    def refresh(self, name):
        self.refreshed.append(name)


def _stage_yuan_appointment_summon(
    game, monkeypatch, *, summon_after="是", appt_name="袁崇焕",
):
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message=f"起复{appt_name}为辽东巡抚，传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "任命",
            "name": appt_name, "office": "辽东巡抚", "summon_after": summon_after,
        }],
    )
    pending = next(row for row in db.list_pending_actions(state.turn) if row["kind"] == "office")
    return pending, f"office:{pending['id']}"


def _close_office_to_dossier(db, state, content, pending_id):
    db.mark_pending_night_approved(
        [pending_id], night_id=int(audience_night.get_open_night(db)["id"]),
    )
    audience_night.close_night(
        db, state, night_id=int(audience_night.get_open_night(db)["id"]),
        content=content,
    )
    return next(
        row["id"] for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == int(pending_id)
    )


def _yuan_row(db):
    return db.conn.execute(
        "SELECT status, office, location, transit_to, transit_distance_remaining, "
        "transit_speed_factor, transit_start_turn FROM characters WHERE name='袁崇焕'"
    ).fetchone()


@pytest.mark.parametrize("appt_name", ["袁崇焕", "前辽东"])
def test_appointment_summon_activates_only_after_promulgation(
    game, monkeypatch, appt_name,
):
    """主 tracer：stage→close→settle 顺颁→启程当月不扣距→次月首减→waiting；
    registry 仅 outer commit 后刷新。alias 名（前辽东）须落 canonical ledger。"""
    db, state, content = game
    pending, origin = _stage_yuan_appointment_summon(
        game, monkeypatch, appt_name=appt_name,
    )
    ledger = db.conn.execute(
        "SELECT tags, person_names FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchone()
    assert ledger is not None and "传召未结" not in json.loads(ledger["tags"])
    # stage 即写 roster canonical key；alias 不得进入 inactive office origin。
    assert json.loads(ledger["person_names"]) == ["袁崇焕"]
    assert list_unsettled_summons(db) == []
    before = _yuan_row(db)
    assert before["location"] == "guangdong"

    dossier_id = _close_office_to_dossier(db, state, content, pending["id"])
    mid = _yuan_row(db)
    assert (mid["status"], mid["office"], mid["transit_to"]) == (
        before["status"], before["office"], before["transit_to"] or "",
    )
    assert list_unsettled_summons(db) == []

    reg = _FakeRegistry()

    def mid_txn_applier(_db, _state, _extracted, _content, _registry):
        assert reg.refreshed == [], "事务内不得 refresh registry"
        return {}

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        registry=reg,
        dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
        delta_applier=mid_txn_applier,
    )

    assert "袁崇焕" in reg.refreshed
    assert [(x["person_name"], x["origin_id"], x["kind"]) for x in list_unsettled_summons(db)] == [
        ("袁崇焕", origin, "in_transit")
    ]
    after = _yuan_row(db)
    assert (after["status"], after["office"], after["location"], after["transit_to"]) == (
        "active", "辽东巡抚", "guangdong", "beizhili",
    )
    assert after["transit_distance_remaining"] is not None
    departed_remaining = float(after["transit_distance_remaining"])
    departed_start = int(after["transit_start_turn"] or 0)
    # 启程落在 settle 事务内、当月 tick 已过；outer 提交后 turn 已 +1，但尚未跑下月
    # front-half tick → 距离仍为矩阵全值（启程当月不扣）。
    assert departed_start == int(state.turn) - 1
    assert departed_remaining == pytest.approx(
        _MATRIX.travel_time("guangdong", "beizhili")
    )

    # 下一月 canonical tick 首次递减。
    prepare_resolve_front_half(state, db, content=content)
    next_month = _yuan_row(db)
    if next_month["transit_to"]:
        assert float(next_month["transit_distance_remaining"]) < departed_remaining
    else:
        assert next_month["location"] == "beizhili"

    unsettled = []
    for _ in range(60):
        unsettled = list_unsettled_summons(db)
        if unsettled and unsettled[0]["kind"] == "waiting":
            break
        if not unsettled:
            break
        settle_with_delta(
            state, db, {}, before_turn=int(state.turn), content=content,
        )
        prepare_resolve_front_half(state, db, content=content)
        unsettled = list_unsettled_summons(db)
    assert unsettled, "抵京后应仍有未结传召投影"
    assert unsettled[0]["kind"] == "waiting"
    assert unsettled[0]["person_name"] == "袁崇焕"
    assert unsettled[0]["origin_id"] == origin
    assert _yuan_row(db)["location"] == "beizhili"


def test_appointment_summon_staging_rolls_back_both_rows(game, monkeypatch):
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    monkeypatch.setattr(
        audience_night, "ensure_inactive_office_summon",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger failed")),
    )

    try:
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state, content), minister,
            player_message="任命并传召", answer="遵旨。", has_directive=False,
            secret_order_id=None, preclassified_intent=[{
                "kind": "appointment", "appoint_action": "任命",
                "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "是",
            }],
        )
    except RuntimeError as exc:
        assert str(exc) == "ledger failed"
    else:
        raise AssertionError("ledger failure must propagate")
    assert [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"] == []
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref LIKE 'office:%'"
    ).fetchone()[0] == 0


def test_dedup_promotes_existing_appointment_summon(game, monkeypatch):
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    session = _fake_session(db, state, content)
    # First stage by canonical, promote summon_after via roster alias — one origin.
    intents = [
        {"kind": "appointment", "appoint_action": "任命",
         "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "否"},
        {"kind": "appointment", "appoint_action": "任命",
         "name": "前辽东", "office": "辽东巡抚", "summon_after": "是"},
    ]
    for intent in intents:
        GameSession.apply_cli_conversation_actions(
            session, minister, player_message="任命并传召", answer="遵旨。",
            has_directive=False, secret_order_id=None,
            preclassified_intent=[intent],
        )

    rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
    assert len(rows) == 1
    assert json.loads(rows[0]["payload_json"])["summon_after"] == "是"
    origin = f"office:{rows[0]['id']}"
    ledger = db.conn.execute(
        "SELECT person_names FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchone()
    assert ledger is not None
    assert json.loads(ledger["person_names"]) == ["袁崇焕"]


def test_appointment_summon_close_crash_restore_keeps_inactive_origin(game, monkeypatch):
    """收夜 COMMIT_OFFICE 后 crash→续跑：唯一 inactive origin 仍在，顺颁前不启程。"""
    db, state, content = game
    pending, origin = _stage_yuan_appointment_summon(game, monkeypatch)
    night_id = int(audience_night.get_open_night(db)["id"])
    db.mark_pending_night_approved([pending["id"]], night_id=night_id)

    with pytest.raises(AudienceNightError) as ei:
        audience_night.close_night(
            db, state, night_id=night_id, content=content,
            crash_after_step=CLOSE_STEP_COMMIT_OFFICE,
        )
    assert ei.value.code == "close_crash"
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1
    assert list_unsettled_summons(db) == []
    assert (_yuan_row(db)["transit_to"] or "") == ""

    result = audience_night.close_night(db, state, night_id=night_id, content=content)
    assert result["closed"] is True
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1
    assert list_unsettled_summons(db) == []
    assert (_yuan_row(db)["transit_to"] or "") == ""


def test_appointment_summon_rejected_leaves_no_travel(game, monkeypatch):
    """打回：未结传召与行止均为零。"""
    db, state, content = game
    pending, origin = _stage_yuan_appointment_summon(game, monkeypatch)
    dossier_id = _close_office_to_dossier(db, state, content, pending["id"])
    before = _yuan_row(db)

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        dossier_verdicts=[rejected_verdict(dossier_id)],
    )

    assert list_unsettled_summons(db) == []
    after = _yuan_row(db)
    assert (after["status"], after["office"], after["transit_to"] or "") == (
        before["status"], before["office"], before["transit_to"] or "",
    )
    tags = json.loads(db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()["tags"])
    assert "传召未结" not in tags


def test_appointment_summon_office_commit_failure_rolls_back(game, monkeypatch):
    """真实授官核拒收（已故）→ 空 affected：经 settle_with_delta 整批回滚。

    不 mock _commit_office_action；案卷仍 proposed、inactive office origin 唯一且未激活、
    人物官职/行止不变、registry 零调用。
    """
    db, state, content = game
    pending, origin = _stage_yuan_appointment_summon(game, monkeypatch)
    dossier_id = _close_office_to_dossier(db, state, content, pending["id"])

    # 合法入口可产生的真实失败：在册已故 → apply_office_appointment 拒收 → 空 affected。
    db.conn.execute(
        "UPDATE characters SET status='dead', status_reason='测试已故', reason_code='' "
        "WHERE name='袁崇焕'",
    )
    db.conn.commit()
    yuan = content.characters["袁崇焕"]
    yuan.status = "dead"
    yuan.status_reason = "测试已故"
    yuan.reason_code = ""

    before = dict(_yuan_row(db))
    reg = _FakeRegistry()

    with pytest.raises(SettlementAbort):
        settle_with_delta(
            state, db, {}, before_turn=int(state.turn), content=content,
            registry=reg,
            dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
        )

    assert reg.refreshed == []
    assert list_unsettled_summons(db) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"
    rolled = dict(_yuan_row(db))
    assert rolled == before
    ch = content.characters["袁崇焕"]
    assert (ch.status, ch.office or "", getattr(ch, "transit_to", "") or "") == (
        rolled["status"], rolled["office"] or "", rolled["transit_to"] or "",
    )
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1
    tags = json.loads(db.conn.execute(
        "SELECT tags FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()["tags"])
    assert "传召未结" not in tags


def test_appointment_summon_outer_fault_rolls_back_and_retries_once(game, monkeypatch):
    """verdict 已物化后 outer 接缝故障：DB/content 回滚、registry 零调用；重试唯一 origin。"""
    db, state, content = game
    pending, origin = _stage_yuan_appointment_summon(game, monkeypatch)
    dossier_id = _close_office_to_dossier(db, state, content, pending["id"])
    before = dict(_yuan_row(db))
    reg = _FakeRegistry()

    def boom_applier(*_a, **_k):
        raise RuntimeError("outer fault after verdict")

    with pytest.raises(SettlementAbort):
        settle_with_delta(
            state, db, {}, before_turn=int(state.turn), content=content,
            registry=reg,
            dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
            delta_applier=boom_applier,
        )

    assert reg.refreshed == []
    assert list_unsettled_summons(db) == []
    rolled = dict(_yuan_row(db))
    assert rolled == before
    ch = content.characters["袁崇焕"]
    assert (ch.status, ch.office or "", getattr(ch, "transit_to", "") or "") == (
        rolled["status"], rolled["office"] or "", rolled["transit_to"] or "",
    )
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        registry=reg,
        dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
    )
    assert "袁崇焕" in reg.refreshed
    unsettled = list_unsettled_summons(db)
    assert [(x["person_name"], x["origin_id"], x["kind"]) for x in unsettled] == [
        ("袁崇焕", origin, "in_transit")
    ]
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?", (origin,),
    ).fetchone()[0] == 1


@pytest.mark.parametrize(
    ("starting_status", "reason_code", "status_reason", "expected_derive"),
    [
        ("retired", "致仕", "致仕归里", "起复"),
        ("offstage", "", "罢居", "起复"),
        ("dismissed", "获罪削籍", "忤逆案削籍", "昭雪"),
        ("offstage", "丁忧", "丁忧离朝", "夺情"),
    ],
)
def test_appointment_summon_consumes_0009_four_states(
    game, monkeypatch, starting_status, reason_code, status_reason, expected_derive,
):
    """retired/offstage/dismissed·获罪/丁忧 只消费 0009 既有状态机（含 derive 审计）。"""
    db, state, content = game
    yuan = content.characters["袁崇焕"]
    db.conn.execute(
        "UPDATE characters SET status=?, status_reason=?, reason_code=?, office='', "
        "transit_to='', transit_distance_remaining=NULL, transit_speed_factor=NULL, "
        "transit_start_turn=0 WHERE name='袁崇焕'",
        (starting_status, status_reason, reason_code),
    )
    db.conn.commit()
    yuan.status = starting_status
    yuan.status_reason = status_reason
    yuan.reason_code = reason_code
    yuan.office = ""
    yuan.transit_to = ""

    pending, origin = _stage_yuan_appointment_summon(game, monkeypatch)
    dossier_id = _close_office_to_dossier(db, state, content, pending["id"])
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
    )

    row = _yuan_row(db)
    assert (row["status"], row["office"], row["location"], row["transit_to"]) == (
        "active", "辽东巡抚", "guangdong", "beizhili",
    )
    assert [(x["origin_id"], x["kind"]) for x in list_unsettled_summons(db)] == [
        (origin, "in_transit")
    ]
    marks = db.conn.execute(
        "SELECT derived_from FROM person_logs WHERE id > ? AND person_name='袁崇焕' "
        "AND derived_from=?",
        (before_logs, expected_derive),
    ).fetchall()
    assert marks, f"期望 0009 derive={expected_derive!r} 审计落 person_logs"


def test_serial_appointment_fallback_preserves_summon_after(game, monkeypatch):
    """#672：分类器未跑时串行 extract_appointment_action 须保留 catalog summon_after。

    真实 fallback 入口（preclassified_intent=None）同句任命并传召 → 同一 office pending
    + inactive office:<id> origin；字段经 appointment catalog 归一，无第二 schema。
    """
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)

    def _fake_run(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            return (json.dumps({
                "任免动作": "任命",
                "姓名": "袁崇焕",
                "官职": "辽东巡抚",
                "任命后传召": "是",
            }, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _fake_run)
    # intent=None + candidates=None → 分类器未跑 → serial extract_appointment_action
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message="起复袁崇焕为辽东巡抚，传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=None,
    )

    rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"] or "{}")
    assert payload.get("summon_after") == "是"
    assert payload.get("name") == "袁崇焕"
    assert payload.get("office") == "辽东巡抚"
    origin = f"office:{rows[0]['id']}"
    ledger = db.conn.execute(
        "SELECT person_names, tags FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchone()
    assert ledger is not None
    assert json.loads(ledger["person_names"]) == ["袁崇焕"]
    assert "传召未结" not in json.loads(ledger["tags"])


def _office_payload_snapshot(db, pending_id):
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (int(pending_id),),
    ).fetchone()
    return json.loads(row["payload_json"] or "{}")


def _office_origin_count(db, pending_id):
    return int(db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref=?",
        (f"office:{int(pending_id)}",),
    ).fetchone()[0])


@pytest.mark.parametrize(
    "path_intent",
    [
        # 完整人职错配 + 路径/传召：不得改旧 pending；新任命只落自己的 pending/origin
        {
            "kind": "appointment", "appoint_action": "任命",
            "name": "孙传庭", "office": "陕西三边总督",
            "mode": "midzhi", "appointment_tenure": "署理", "summon_after": "是",
        },
        # name-only / office 缺失 + summon：身份字段在场但联合键不全 → 旧 row 零改
        {
            "kind": "appointment", "appoint_action": "无",
            "name": "孙传庭", "office": "",
            "mode": "midzhi", "summon_after": "是",
        },
    ],
    ids=["complete_mismatch", "name_only_partial"],
)
def test_single_pending_identity_mismatch_does_not_corrupt_or_bind_summon(
    game, monkeypatch, path_intent,
):
    """#672：单 pending 身份绕过——错配/缺联合键不得改旧 row，也不得绑旧 origin。"""
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    session = _fake_session(db, state, content)

    GameSession.apply_cli_conversation_actions(
        session, minister,
        player_message="起复袁崇焕为辽东巡抚。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "任命",
            "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "否",
        }],
    )
    old = next(r for r in db.list_pending_actions(state.turn) if r["kind"] == "office")
    old_id = int(old["id"])
    before_payload = _office_payload_snapshot(db, old_id)
    assert before_payload.get("summon_after") in (None, "否", "")
    assert _office_origin_count(db, old_id) == 0

    GameSession.apply_cli_conversation_actions(
        session, minister,
        player_message="特旨署理，并传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[path_intent],
    )

    assert _office_payload_snapshot(db, old_id) == before_payload
    assert _office_origin_count(db, old_id) == 0

    if path_intent.get("appoint_action") == "任命":
        rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
        assert len(rows) == 2
        new = next(r for r in rows if int(r["id"]) != old_id)
        new_payload = json.loads(new["payload_json"] or "{}")
        assert new_payload.get("name") == "孙传庭"
        assert new_payload.get("office") == "陕西三边总督"
        assert new_payload.get("summon_after") == "是"
        assert _office_origin_count(db, int(new["id"])) == 1
    else:
        rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
        assert len(rows) == 1
        assert int(rows[0]["id"]) == old_id


def test_current_office_noop_still_stages_summon_after(game, monkeypatch):
    """#672：summon-only 复用 appointment pending，顺颁不得截掉目标的兼职。"""
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))

    target = content.characters["韩爌"]
    full_office = "兵部尚书,左都御史"
    office = "兵部尚书"
    db.conn.execute(
        "UPDATE characters SET status='active', office=?, location='beizhili' WHERE name=?",
        (full_office, target.name),
    )
    db.conn.commit()

    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message=f"{target.name}仍任{office}，传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "任命",
            "name": target.name, "office": office, "summon_after": "是",
        }],
    )

    rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"] or "{}")
    assert payload.get("name") == target.name
    assert payload.get("office") == full_office
    assert payload.get("summon_after") == "是"
    origin = f"office:{rows[0]['id']}"
    ledger = db.conn.execute(
        "SELECT person_names, tags FROM story_ledger_entries WHERE origin_ref=?",
        (origin,),
    ).fetchone()
    assert ledger is not None
    assert target.name in json.loads(ledger["person_names"])
    assert "传召未结" not in json.loads(ledger["tags"])

    dossier_id = _close_office_to_dossier(db, state, content, rows[0]["id"])
    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
    )
    assert db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (target.name,),
    ).fetchone()["office"] == full_office


def test_unlisted_appointment_summon_rejects_before_staging(game, monkeypatch):
    """#672：册外任命可成案，但无 canonical 行止起点时不得进入传召 batch。"""
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))

    with pytest.raises(ValueError, match="缺少在册行止起点"):
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state, content), minister,
            player_message="任命册外测试臣为待选，并传召入京。", answer="遵旨。",
            has_directive=False, secret_order_id=None,
            preclassified_intent=[{
                "kind": "appointment", "appoint_action": "任命",
                "name": "册外测试臣", "office": "待选", "summon_after": "是",
            }],
        )

    assert [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"] == []
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name='册外测试臣'",
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM story_ledger_entries WHERE origin_ref LIKE 'office:%'",
    ).fetchone() is None


def test_dismiss_with_summon_after_does_not_stage_origin(game, monkeypatch):
    """#672：罢免+summon_after 在物化边界收敛为无传召，不留永久 inactive origin。"""
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))

    target = next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and str(getattr(ch, "office", "") or "").strip()
        and getattr(ch, "office_type", "") not in {"后宫", "宗藩"}
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != minister.name
    )

    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message=f"罢免{target.name}，传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "罢免",
            "name": target.name, "office": "", "summon_after": "是",
        }],
    )

    rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
    assert len(rows) == 1
    assert rows[0]["action"] == "罢免"
    payload = json.loads(rows[0]["payload_json"] or "{}")
    assert payload.get("summon_after") == "否"
    assert _office_origin_count(db, int(rows[0]["id"])) == 0
    assert db.conn.execute(
        "SELECT count(*) FROM story_ledger_entries WHERE origin_ref LIKE 'office:%'"
    ).fetchone()[0] == 0

    # 同类旁路：罢免来意带路径标记命中既有任命时，也不得把 summon 升到旧 row。
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message="起复袁崇焕为辽东巡抚。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "任命",
            "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "否",
        }],
    )
    appointment = next(
        r for r in db.list_pending_actions(state.turn)
        if r["kind"] == "office" and r["action"] == "任命"
    )
    appointment_id = int(appointment["id"])
    before = _office_payload_snapshot(db, appointment_id)
    # 对冲会删除旧任命；在真实 DB 删除边界留 OLD payload，证明反向来意未先污染它。
    db.conn.execute("CREATE TEMP TABLE deleted_office_payload (id INTEGER, payload_json TEXT)")
    db.conn.execute(
        "CREATE TEMP TRIGGER audit_deleted_office BEFORE DELETE ON pending_actions "
        "WHEN OLD.id = %d BEGIN INSERT INTO deleted_office_payload VALUES "
        "(OLD.id, OLD.payload_json); END" % appointment_id
    )

    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state, content), minister,
        player_message="特旨罢免袁崇焕，并传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "罢免",
            "name": "袁崇焕", "office": "辽东巡抚",
            "mode": "midzhi", "summon_after": "是",
        }],
    )

    deleted = db.conn.execute(
        "SELECT payload_json FROM deleted_office_payload WHERE id=?", (appointment_id,),
    ).fetchone()
    assert deleted is not None
    assert json.loads(deleted["payload_json"] or "{}") == before
    assert db.conn.execute(
        "SELECT 1 FROM pending_actions WHERE id=?", (appointment_id,),
    ).fetchone() is None
    yuan_rows = [
        r for r in db.list_pending_actions(state.turn)
        if json.loads(r["payload_json"] or "{}").get("name") == "袁崇焕"
    ]
    assert yuan_rows == []  # 非现职：既有任命与反向罢免按普通管线对冲。
    assert _office_origin_count(db, appointment_id) == 0


def test_path_only_omitted_name_still_promotes_summon_on_single_pending(
    game, monkeypatch,
):
    """#672：单 pending path-only 省略 name 时从 row payload 取人名，summon 随同一 pending。"""
    db, state, content = game
    minister = _minister_wang_shaohui(db, content)
    open_night(db, state, empty_scaffold=True)
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda *a, **k: ("{}", 1))
    session = _fake_session(db, state, content)

    GameSession.apply_cli_conversation_actions(
        session, minister,
        player_message="起复袁崇焕为辽东巡抚。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "任命",
            "name": "袁崇焕", "office": "辽东巡抚", "summon_after": "否",
        }],
    )
    pending = next(r for r in db.list_pending_actions(state.turn) if r["kind"] == "office")
    pending_id = int(pending["id"])

    GameSession.apply_cli_conversation_actions(
        session, minister,
        player_message="特旨署理，并传召入京。", answer="遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{
            "kind": "appointment", "appoint_action": "无",
            "name": "", "office": "",
            "mode": "midzhi", "appointment_tenure": "署理", "summon_after": "是",
        }],
    )

    rows = [r for r in db.list_pending_actions(state.turn) if r["kind"] == "office"]
    assert len(rows) == 1
    assert int(rows[0]["id"]) == pending_id
    payload = json.loads(rows[0]["payload_json"] or "{}")
    assert payload.get("mode") == "midzhi"
    assert payload.get("任别") == "署理"
    assert payload.get("summon_after") == "是"
    assert _office_origin_count(db, pending_id) == 1
    ledger = db.conn.execute(
        "SELECT person_names FROM story_ledger_entries WHERE origin_ref=?",
        (f"office:{pending_id}",),
    ).fetchone()
    assert json.loads(ledger["person_names"]) == ["袁崇焕"]


def test_appointment_summon_already_in_capital_projects_waiting(game, monkeypatch):
    """#672：已在京无在途 → 顺颁后直接 waiting，不调同地行止、不回滚结算。"""
    db, state, content = game
    # 袁崇焕默认广东；先置于京，再走任命+传召全链。
    db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='', "
        "transit_distance_remaining=NULL, transit_speed_factor=NULL, "
        "transit_start_turn=0 WHERE name='袁崇焕'"
    )
    db.conn.commit()
    yuan = content.characters["袁崇焕"]
    yuan.location = "beizhili"
    yuan.transit_to = ""

    pending, origin = _stage_yuan_appointment_summon(game, monkeypatch)
    dossier_id = _close_office_to_dossier(db, state, content, pending["id"])

    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content,
        dossier_verdicts=[{"dossier_id": dossier_id, "decision": "promulgated"}],
    )

    unsettled = list_unsettled_summons(db)
    assert [(x["person_name"], x["origin_id"], x["kind"]) for x in unsettled] == [
        ("袁崇焕", origin, "waiting")
    ]
    after = _yuan_row(db)
    assert (after["location"], after["transit_to"] or "") == ("beizhili", "")
    assert after["office"] == "辽东巡抚"
