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

from ming_sim.db import (
    _seed_guilt_storage_value,
    canonical_office_title,
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

    if not db.table_has_rows("office_slots"):
        db.conn.executemany(
            """
            INSERT INTO office_slots
                (office_title, office_type, region_id, jurisdiction, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(*slot, index) for index, slot in enumerate(OFFICE_SLOTS)],
        )

    if not db.table_has_rows("characters"):
        for character in db.content.characters.values():
            office = normalize_office(character.office)
            # 静态名册接档：content 已写好 office_type，表查不中也不逐人现拉 codex
            # （开局 LLM 风暴根因，~28 外藩/宗藩/平民官名 × 串行 codex ≈ 5 分钟）。
            office_type = infer_office_type_from_office(
                office, character.office_type, db.llm_config, use_llm=False
            )
            db.conn.execute(
                """
                INSERT INTO characters
                (name, office, office_type, faction, aliases, personal_skills, loyalty, ability, integrity, courage, style, identity, seed_guilt,
                 birth_year, historical_death_year, historical_death_month, debut_year, debut_month,
                 status, status_reason, reason_code, status_changed_turn, portrait_id, power_id, location, transit_to, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    character.name,
                    office,
                    office_type,
                    character.faction,
                    json.dumps(character.aliases, ensure_ascii=False),
                    json.dumps(character.personal_skills, ensure_ascii=False),
                    character.loyalty,
                    character.ability,
                    character.integrity,
                    character.courage,
                    character.style,
                    character.identity,
                    _seed_guilt_storage_value(character.seed_guilt),
                    character.birth_year,
                    character.historical_death_year,
                    character.historical_death_month,
                    character.debut_year,
                    character.debut_month,
                    character.status,
                    character.status_reason,
                    character.reason_code,
                    0,
                    character.portrait_id,
                    character.power_id,
                    character.location,
                    character.transit_to,
                    character.summary,
                ),
            )
    if not db.table_has_rows("character_offices"):
        for row in db.conn.execute("SELECT name, office, office_type FROM characters").fetchall():
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

    is_fresh_factions_seed = not db.table_has_rows("factions")
    if is_fresh_factions_seed:
        for faction in db.content.factions.values():
            db.conn.execute(
                """
                INSERT INTO factions (name, satisfaction, leverage, agenda)
                VALUES (?, ?, ?, ?)
                """,
                (faction.name, faction.satisfaction, faction.leverage, faction.agenda),
            )
    if not db.table_has_rows("classes"):
        # ADR 0088/#648：classes 首次 seed = 新档 cutover 点，落持久人口单位标「人」。
        # 旧档表已有行（万人口径）不重 seed、不落标 → population_unit 恒判「万人」legacy。
        db._mark_population_unit_persons()
        for cls in db.content.classes.values():
            db.conn.execute(
                """
                INSERT INTO classes (name, region_id, population, satisfaction, leverage, agenda)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (cls.name, cls.region_id, cls.population, cls.satisfaction, cls.leverage, cls.agenda),
            )
    for power in db.content.powers.values():
        db.conn.execute(
            """
            INSERT OR IGNORE INTO powers
            (id, name, kind, leader, stance, leverage, satisfaction, military_strength,
             cohesion, supply, agenda, status, last_action, aliases)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                power.id,
                power.name,
                power.kind,
                power.leader,
                power.stance,
                power.leverage,
                power.satisfaction,
                power.military_strength,
                power.cohesion,
                power.supply,
                power.agenda,
                power.status,
                power.last_action,
                json.dumps(power.aliases, ensure_ascii=False)
                if isinstance(power.aliases, list)
                else power.aliases,
            ),
        )
    for region in db.content.regions.values():
        db.conn.execute(
            """
            INSERT OR IGNORE INTO regions
            (id, name, kind, population, public_support, unrest, natural_disaster, human_disaster,
             registered_land, hidden_land, tax_per_turn, grain_security, gentry_resistance,
             military_pressure, status, controlled_by, fiscal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                region.id,
                region.name,
                region.kind,
                region.population,
                region.public_support,
                region.unrest,
                region.natural_disaster,
                region.human_disaster,
                region.registered_land,
                region.hidden_land,
                region.tax_per_turn,
                region.grain_security,
                region.gentry_resistance,
                region.military_pressure,
                region.status,
                region.controlled_by,
                json.dumps(region.fiscal, ensure_ascii=False),
            ),
        )
    is_fresh_armies_seed = not db.table_has_rows("armies")
    if is_fresh_armies_seed:
        for army in db.content.armies.values():
            db.conn.execute(
                """
                INSERT INTO armies
                (id, name, station, station_region, theater, commander, controller, troop_type, manpower,
                 supply, morale, training, equipment, arrears,
                 province_pay_arrears, central_pay_arrears, pay_source_region,
                 province_pay_share, central_pay_share, is_tusi, self_funded_pay,
                 mobility, loyalty, firearm_equipment, cannon_equipment, salary_rate, status, owner_power)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    army.id,
                    army.name,
                    army.station,
                    army.station_region,
                    army.theater,
                    army.commander,
                    army.controller,
                    army.troop_type,
                    army.manpower,
                    army.supply,
                    army.morale,
                    army.training,
                    army.equipment,
                    army.arrears,
                    army.province_pay_arrears,
                    army.central_pay_arrears,
                    army.pay_source_region,
                    army.province_pay_share,
                    army.central_pay_share,
                    army.is_tusi,
                    army.self_funded_pay,
                    army.mobility,
                    army.loyalty,
                    army.firearm_equipment,   # 新档贯通火器/随军大炮（CMR codexB）
                    army.cannon_equipment,
                    army.salary_rate,         # #44 名义月饷率(两/兵·月)
                    army.status,
                    army.owner_power,
                ),
            )
    if not db.table_has_rows("buildings"):
        for building in db.content.buildings.values():
            db.conn.execute(
                """
                INSERT INTO buildings
                (id, region_id, name, category, level, condition, maintenance, risk,
                 output_metric, output_amount, status, origin, created_turn)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'preset', 0)
                """,
                (
                    building.id,
                    building.region_id,
                    building.name,
                    building.category,
                    building.level,
                    building.condition,
                    building.maintenance,
                    building.risk,
                    building.output_metric,
                    building.output_amount,
                    building.status,
                ),
            )
    db._initialize_army_pay_source_spine(is_fresh_armies_seed)
    # #173：维护费列退役 drop 已上移至 init_schema（每个打开路径都跑，含现存档的纯
    # init_schema 路径，见 cmr drop R1）；此处新档 seed INSERT 后该列本就不存在，无需再 drop。
    db._apply_region_city_levels()  # 新档 region 此时才 INSERT 完，按史实补 city_level
    # #9：派系势力 offset 校准。此刻 factions + characters 均已 INSERT。
    # cmr R3：传 offset 列「本次是否刚 ADD」——首次校准只在建库那次跑，常规 load 不碰 offset。
    db._calibrate_faction_offsets(
        is_fresh_factions_seed, getattr(db, "_leverage_offset_col_added", False)
    )
    db.conn.commit()
