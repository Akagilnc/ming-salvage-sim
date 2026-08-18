"""#570 P-6：月中 restore — 案卷/进展/标记/名单四面无损。

名单＝案卷参与人名单（0053）。同场景四面：
1. 案卷（状态机 + 颁布/执行两格 + 判据快照）
2. 月度进展档
3. 中旨与破格标
4. 参与人名单
"""

from __future__ import annotations

import json

from ming_sim.db import GameDB
from ming_sim.models import Character
from tests.dossier_test_helpers import rejected_verdict


DOSSIER_REPORT_MONTHLY = "dossier-report:monthly_errand"


def _add(db, state, name, office, office_type="布衣"):
    db.add_character(state, Character(
        name=name, office=office, office_type=office_type, faction="中立",
        aliases=[], personal_skills=[], loyalty=50, ability=50, integrity=50,
        courage=50, style="", power_id="ming",
    ))


def _face(db, dossier_id: int) -> dict:
    row = db.get_decree_dossier(dossier_id)
    assert row is not None
    payload = json.loads(str(row.get("payload_json") or "{}"))
    decisions = db.list_decree_dossier_decisions(dossier_id)
    progress = db.list_dossier_progress(dossier_id)
    roster = row.get("participant_roster")
    if roster is None:
        roster = payload.get("participant_roster") or payload.get("participants")
    return {
        "status": row.get("status"),
        "promulgation_decision": row.get("promulgation_decision"),
        "promulgation_blocked_layer": row.get("promulgation_blocked_layer"),
        "promulgation_reason": row.get("promulgation_reason"),
        "execution_outcome": row.get("execution_outcome") or "",
        "execution_note": row.get("execution_note") or "",
        "mode": row.get("mode"),
        "stigma": row.get("stigma") or [],
        "break_rank": payload.get("break_rank"),
        "participant_roster": roster or [],
        "criteria_snapshots": [
            item.get("criteria_snapshot") for item in decisions
            if item.get("criteria_snapshot")
        ],
        "decisions": [
            {
                "decision": item.get("decision"),
                "blocked_layer": item.get("blocked_layer"),
                "rescript_action": item.get("rescript_action") or "",
                "midzhi_unpromulgatable": bool(item.get("midzhi_unpromulgatable")),
            }
            for item in decisions
        ],
        "progress": [
            {
                "turn": int(item.get("turn") or 0),
                "progress_band": item.get("progress_band"),
                "memorial_text": item.get("memorial_text"),
                "origin": item.get("origin"),
            }
            for item in progress
        ],
    }


def test_mid_month_restore_keeps_dossier_four_faces(game, tmp_path, content):
    db, state, _content = game
    holder = "复测主办甲"
    aide = "复测协办乙"
    _add(db, state, holder, "白身", "布衣")
    _add(db, state, aide, "陕西按察使", "地方")

    # Face A: break-rank appointment + midzhi stigma on reject + roster + criteria.
    appt_id = db.create_decree_dossier(
        state,
        action_type="appointment",
        decree_text="破格授复测主办甲为陕西巡抚",
        target_kind="character",
        target_id=holder,
        executor_kind="character",
        executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办", "role": "赴任"},
            {"character_id": aide, "tier": "协办", "role": "护行"},
        ],
        payload={
            "name": holder, "office": "陕西巡抚", "mode": "midzhi", "任别": "真除",
        },
    )
    appt_payload = json.loads(db.get_decree_dossier(appt_id)["payload_json"])
    assert appt_payload["break_rank"]["is_break_rank"] is True

    appt_verdict = rejected_verdict(appt_id, midzhi=True)
    appt_verdict["criteria_snapshot"] = {
        "imperial_authority_band": "偏弱",
        "appointment_tenure": "真除",
        "authorization_ids": [],
        "endorsement_entry_ids": [],
    }
    appt_verdict["affected_parties"] = [
        {
            "kind": "class", "key": "士绅",
            "direction": "negative", "intensity": "strong",
        },
        {
            "kind": "faction", "key": "东林",
            "direction": "negative", "intensity": "weak",
        },
    ]
    db.apply_dossier_verdicts(state, [appt_verdict])

    # Face B: executing long-errand with monthly progress (0058/566 进展档).
    errand_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="差复测主办甲核陕边饷",
        target_kind="issue",
        target_id="restore-errand-570",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )
    # Direct status path: plant executing surface without full initiative materialize.
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing', promulgation_decision='promulgated', "
        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (int(errand_id),),
    )
    db.conn.commit()
    db.record_dossier_progress(
        errand_id, state.turn, "在途", "已出京赴陕",
        origin=DOSSIER_REPORT_MONTHLY,
    )

    before_appt = _face(db, appt_id)
    before_errand = _face(db, errand_id)

    assert before_appt["status"] == "proposed"
    assert before_appt["promulgation_decision"] == "rejected"
    assert before_appt["promulgation_blocked_layer"] == "six_offices"
    assert before_appt["break_rank"]["is_break_rank"] is True
    assert before_appt["stigma"], "中旨打回须落 stigma 标记"
    assert before_appt["participant_roster"], "参与人名单不得空"
    assert before_appt["criteria_snapshots"], "判据快照须随判决落库"
    assert before_errand["progress"] == [{
        "turn": int(state.turn),
        "progress_band": "在途",
        "memorial_text": "已出京赴陕",
        "origin": DOSSIER_REPORT_MONTHLY,
    }]

    backup = tmp_path / "restore-570.db"
    db.backup_to(str(backup))
    db.close()

    restored = GameDB(str(backup), content=content)
    try:
        assert _face(restored, appt_id) == before_appt
        assert _face(restored, errand_id) == before_errand

        restored.record_dossier_progress(
            errand_id, state.turn + 1, "将结", "已抵西安",
            origin=DOSSIER_REPORT_MONTHLY,
        )
        cont = restored.list_dossier_progress(errand_id)
        assert [row["memorial_text"] for row in cont] == ["已出京赴陕", "已抵西安"]
    finally:
        restored.close()
