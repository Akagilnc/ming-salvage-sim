"""ADR 0009 inventory for current direct writes to ``characters``."""

from __future__ import annotations

import ast


PERSON_WRITE_POINT_INVENTORY = (
    {
        "location": "ming_sim/db.py:seed_static_data",
        "owner": "seed",
        "disposition": "adr0009_exempt",
        "reason": "开局 seed 不产 RejectedItem，ADR 0009 明确豁免。",
    },
    {
        "location": "ming_sim/db.py:set_character_status",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "状态迁移应收口到人物单入口。",
    },
    {
        "location": "ming_sim/db.py:apply_character_power_changes",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "易主应收口到人物单入口。",
    },
    {
        "location": "ming_sim/db.py:set_character_office",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "任命/调任应收口到人物单入口。",
    },
    {
        "location": "ming_sim/db.py:set_portrait_id",
        "owner": "profile_metadata",
        "disposition": "outside_person_archive",
        "reason": "头像字段不是 ADR 0009 人事状态/名分契约。",
    },
    {
        "location": "ming_sim/db.py:add_character",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "运行时建人应收口到人物单入口。",
    },
    {
        "location": "ming_sim/issues.py:apply_office_appointment",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "任官后清状态原因仍是人物状态/名分写入，需随任命核收口。",
    },
    {
        "location": "ming_sim/issues.py:_apply_person_changes",
        "owner": "adr0009_tracer_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "Slice 6 处置 tracer bullet 的过渡写点，后续随 C1 applier 收口。",
    },
    {
        "location": "ming_sim/issues.py:_restore_person_write_state",
        "owner": "adr0009_tracer_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "任官失败局部恢复的过渡写点，后续随 C1 applier 收口。",
    },
    {
        "location": "ming_sim/decree.py:tick_transit_arrivals",
        "owner": "deterministic_settle_path",
        "disposition": "adr0009_exempt",
        "reason": "#668/0095 在途倒数 tick：remaining-=速度后 ≤0 时引擎落抵达（location=transit_to、清四量），属确定性结算逻辑（非 LLM 产 delta），豁免于 ADR 0009 person applier 收口。",
    },

)

_MUTATING_SQL_MARKERS = (
    "UPDATE characters SET",
    "INSERT INTO characters",
    "INSERT OR REPLACE INTO characters",
    "REPLACE INTO characters",
    "DELETE FROM characters",
)
