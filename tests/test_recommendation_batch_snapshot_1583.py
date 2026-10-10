"""#1583：同批连续任命 — 批前统一荐人快照校验，批内有序物化。

验收：同一批两份任命案卷，候选为同一在职人物、均携相同批前快照，
目标官职依次不同；经玩家过月入口按序生效，末职=第二条目标，
turn 恰好推进 1；批外真实陈旧快照仍拒。
"""

from __future__ import annotations

from ming_sim.entities.character.store import CharacterStore

import pytest

from tests.test_month_chain_1843 import _prepare_player_month
from ming_sim.decree_forecast import decree_ref_for_dossier
from ming_sim.exceptions import SettlementAbort


def _pick_recommender(content):
    return next(
        c for c in content.characters.values()
        if c.office_type not in ("后宫", "宗藩")
    )


def _stage_recommendation(db, state, recommender_name, row, office, reason, region_id=""):
    payload = {
        "name": row["name"], "office": office,
        "faction": row["faction"], "reason": reason,
        "text": f"准荐{row['name']}任{office}",
        "recommendation": {
            "candidate": dict(row),
            "recommender": recommender_name,
        },
    }
    # Controlled fixture: local seats (e.g. 河道总督) carry typed 任所.
    seat = str(region_id or "").strip() or {
        "河道总督": "henan",
        "陕西巡抚": "shaanxi",
    }.get(str(office or "").strip(), "")
    if seat:
        payload["region_id"] = seat
    return db.stage_pending_action(
        state.turn,
        kind="office",
        action="任命",
        minister_name=recommender_name,
        target_id=None,
        payload=payload,
    )


def _proposed_appointment_dossier_id(db, pending_id):
    return next(
        row["id"] for row in db.dossiers.list_dossiers(status="proposed")
        if row["action_type"] == "appointment"
        and int(row.get("pending_action_id") or 0) == int(pending_id)
    )




