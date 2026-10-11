"""Laying down the opening world from content.

#1889: 新档初始化（seed）职责从 ``db.py`` 的大块里拆出。Seeding is one
responsibility with one owner: every step here reads content and writes the
tables the engine owns. It runs once per save — each step is guarded by "is
this table still empty", so reopening an existing save seeds nothing.

``db`` is the GameDB, passed in rather than imported: the steps reuse its
seams (person-title guard, pay-source spine, faction calibration), so this
module owns the *sequence*, not a parallel set of writers.
"""

from __future__ import annotations

import json
from typing import Any

from ming_sim.office_rank import canonical_office_title
from ming_sim.db import (
    _seed_guilt_storage_value,
    infer_office_type_from_office,
    normalize_office,
)
from ming_sim.intelligence import OFFICE_SLOTS


def seed_opening_world(db: Any) -> None:
    """Write the opening roster, factions, regions, armies and buildings.

    Every step is conditional on its table being empty, so this is a no-op on
    any save that already has content.
    """
    db._ensure_office_type_parents()
    characters = db.characters

    if not characters.has_any("office_slots"):
        characters.write_seed_opening_world([(*slot, index) for index, slot in enumerate(OFFICE_SLOTS)])

    if not characters.has_any("characters"):
        for character in db.content.characters.values():
            office = normalize_office(character.office)
            # 静态名册接档：content 已写好 office_type，表查不中也不逐人现拉 codex
            # （开局 LLM 风暴根因，~28 外藩/宗藩/平民官名 × 串行 codex ≈ 5 分钟）。
            office_type = infer_office_type_from_office(
                office, character.office_type, db.llm_config, use_llm=False
            )
            db.characters.insert({
                "name": character.name,
                "office": office,
                "office_type": office_type,
                "faction": character.faction,
                "aliases": json.dumps(character.aliases, ensure_ascii=False),
                "personal_skills": json.dumps(character.personal_skills, ensure_ascii=False),
                "loyalty": character.loyalty,
                "ability": character.ability,
                "integrity": character.integrity,
                "courage": character.courage,
                "style": character.style,
                "identity": character.identity,
                "intrigue": int(getattr(character, "intrigue", 50) or 50),
                "seed_guilt": _seed_guilt_storage_value(character.seed_guilt),
                "birth_year": character.birth_year,
                "historical_death_year": character.historical_death_year,
                "historical_death_month": character.historical_death_month,
                "debut_year": character.debut_year,
                "debut_month": character.debut_month,
                "status": character.status,
                "status_reason": character.status_reason,
                "reason_code": character.reason_code,
                "status_changed_turn": 0,
                "portrait_id": character.portrait_id,
                "power_id": character.power_id,
                "location": character.location,
                "transit_to": character.transit_to,
                "summary": character.summary,
            })
    if not characters.has_any("character_offices"):
        for row in characters.read_knowledge_items_for_turn():
            # 同 add_character/set_character_office 走 person-title 守卫接缝：名分不写脏行。
            # Jurisdiction only from explicit content office_region — never location.
            ch = (
                db.content.characters.get(row["name"])
                if getattr(db, "content", None) is not None else None
            )
            seat = str(getattr(ch, "office_region", "") or "").strip() if ch else ""
            # #1889：无现任（罢居/罢免）者 characters.office 为空，备档取 content 的
            # historical_office（历史实职）——历史与现任各归各字段，不再靠 init 时
            # 清洗 office 串里的状态词来反推。备档标题统一走 canonical_office_title：
            # 备档只存实职职衔，「原…革职候勘」这类状态尾属人事状态、不进官职体系。
            archived = str(row["office"] or "") or (
                str(getattr(ch, "historical_office", "") or "") if ch else ""
            )
            if not archived:
                continue
            db._record_character_office(
                row["name"], canonical_office_title(archived), row["office_type"],
                "开局 seed", region_id=seat,
            )

    is_fresh_factions_seed = not db.factions.has_any()
    if is_fresh_factions_seed:
        for faction in db.content.factions.values():
            db.factions.insert(
                name=faction.name,
                satisfaction=faction.satisfaction,
                leverage=faction.leverage,
                agenda=faction.agenda,
            )
    if not db.classes.has_any():
        # 人口一律「人」。classes 首次 seed；已有行不重 seed。
        for cls in db.content.classes.values():
            db.classes.insert(
                name=cls.name,
                region_id=cls.region_id,
                population=cls.population,
                satisfaction=cls.satisfaction,
                leverage=cls.leverage,
                agenda=cls.agenda,
            )
    for power in db.content.powers.values():
        db.powers.insert_ignore({
            "id": power.id,
            "name": power.name,
            "kind": power.kind,
            "leader": power.leader,
            "stance": power.stance,
            "leverage": power.leverage,
            "satisfaction": power.satisfaction,
            "military_strength": power.military_strength,
            "cohesion": power.cohesion,
            "supply": power.supply,
            "agenda": power.agenda,
            "status": power.status,
            "last_action": power.last_action,
            "aliases": (
                json.dumps(power.aliases, ensure_ascii=False)
                if isinstance(power.aliases, list)
                else power.aliases
            ),
        })
    for region in db.content.regions.values():
        db.regions.insert_ignore({
            "id": region.id,
            "name": region.name,
            "kind": region.kind,
            "population": region.population,
            "public_support": region.public_support,
            "unrest": region.unrest,
            "natural_disaster": region.natural_disaster,
            "human_disaster": region.human_disaster,
            "registered_land": region.registered_land,
            "hidden_land": region.hidden_land,
            "tax_per_turn": region.tax_per_turn,
            "grain_security": region.grain_security,
            "gentry_resistance": region.gentry_resistance,
            "military_pressure": region.military_pressure,
            "status": region.status,
            "controlled_by": region.controlled_by,
            "fiscal": json.dumps(region.fiscal, ensure_ascii=False),
        })
    is_fresh_armies_seed = not db.armies.has_any()
    if is_fresh_armies_seed:
        for army in db.content.armies.values():
            db.armies.insert({
                "id": army.id,
                "name": army.name,
                "station": army.station,
                "station_region": army.station_region,
                "theater": army.theater,
                "commander": army.commander,
                "controller": army.controller,
                "troop_type": army.troop_type,
                "manpower": army.manpower,
                "supply": army.supply,
                "morale": army.morale,
                "training": army.training,
                "equipment": army.equipment,
                "province_pay_arrears": army.province_pay_arrears,
                "central_pay_arrears": army.central_pay_arrears,
                "pay_source_region": army.pay_source_region,
                "province_pay_share": army.province_pay_share,
                "central_pay_share": army.central_pay_share,
                "is_tusi": army.is_tusi,
                "self_funded_pay": army.self_funded_pay,
                "mobility": army.mobility,
                "loyalty": army.loyalty,
                "firearm_equipment": army.firearm_equipment,   # 新档贯通火器/随军大炮（CMR codexB）
                "cannon_equipment": army.cannon_equipment,
                "salary_rate": army.salary_rate,         # #44 名义月饷率(两/兵·月)
                "status": army.status,
                "owner_power": army.owner_power,
            })
    if not db.buildings.has_any():
        for building in db.content.buildings.values():
            db.buildings.insert({
                "id": building.id,
                "region_id": building.region_id,
                "name": building.name,
                "category": building.category,
                "level": building.level,
                "condition": building.condition,
                "maintenance": building.maintenance,
                "risk": building.risk,
                "output_metric": building.output_metric,
                "output_amount": building.output_amount,
                "status": building.status,
                "origin": "preset",
                "created_turn": 0,
            })
    db._initialize_army_pay_source_spine(is_fresh_armies_seed)
    # #173/#1889：维护费列已不在 schema CREATE；新档无该列，无需 drop/ALTER。
    db._apply_region_city_levels()  # 新档 region 此时才 INSERT 完，按史实补 city_level
    # #9/#1889：派系势力 offset 校准。此刻 factions + characters 均已 INSERT。
    # 仅 fresh seed 校准一次；常规 load 不碰 offset。
    db._calibrate_faction_offsets(is_fresh_factions_seed)
    db.conn.commit()
