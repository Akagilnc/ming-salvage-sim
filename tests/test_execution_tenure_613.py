"""#613 执行侧任别读端：执行格/月末推演号令力 + #611 授权投影共用。"""

import pytest

from ming_sim.appointment_tenure import (
    AUTHORITY_COMMAND_RELIEF,
    COMMAND_POWER_RANK,
    DEFAULT_APPOINTMENT_TENURE,
    command_power_rank,
    execution_distortion_weight,
)
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGES, AUTHORITY_PRIVILEGE_SET
from ming_sim.db import GameDB
import ming_sim.decree as decree_mod
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload
from tests.test_authority_ledger_611 import (
    _eligible_dossier,
    _grant,
    _revoke,
)


VALID_TENURES = ("真除", "兼署", "署理", "加衔")


def _ministers(db, n=4):
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩') ORDER BY name LIMIT ?",
        (n,),
    ).fetchall()
    return [str(row["name"]) for row in rows]


def _set_tenure(db, name, tenure, office=None):
    """Write character_offices.appointment_tenure via the production scope helper."""
    from ming_sim.issues import _appointment_tenure_scope

    row = db.conn.execute(
        "SELECT office, office_type FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    target_office = office or str(row["office"] or name)
    # Keep current office_type parent so set_character_office does not invent classes.
    with _appointment_tenure_scope(db, tenure):
        db.set_character_office(
            name, target_office, office_type="", source="test-613",
        )
    # Direct archive pin: production path already wrote tenure via scope; assert.
    archived = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (name,),
    ).fetchone()
    assert archived is not None
    assert str(archived["appointment_tenure"]) == tenure


def _executing_policy(db, state, holder, *, target_id="清丈田亩-613", roster=None):
    participants = roster or [
        {"character_id": holder, "tier": "主办", "role": "承办"},
    ]
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="清丈畿辅田亩",
        target_kind="issue",
        target_id=target_id,
        executor_kind="character",
        executor_id=holder,
        participants=participants,
        payload={
            # Poison pills: must never become authorization identity.
            "authorization_id": "payload-auth",
            "authorization_ids": ["payload-list"],
            "任别": "加衔",  # dossier payload 任别 ≠ 承办人现职任别
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    row = db.get_decree_dossier(dossier_id)
    assert row["status"] == "executing"
    return row


def _live_exec_side(db, state, dossier):
    """执行侧读端真链：assembly 投影 + execution_side_read_fields 对齐。"""
    projected = decree_mod.project_dossiers_for_simulator(
        [dossier], db=db, state=state,
    )
    hit = next(row for row in projected if int(row["id"]) == int(dossier["id"]))
    side = decree_mod.execution_side_read_fields(db, state, dossier)
    for key in (
        "appointment_tenure",
        "held_authorities",
        "authorization_ids",
        "command_power_rank",
        "distortion_weight",
    ):
        assert hit[key] == side[key]
    return hit


# ── pure helpers ──────────────────────────────────────────────────────────


def test_command_power_four_tier_strict_order_and_jianshu_not_collapsed():
    """TD-8 纯函数：真除＞兼署＞署理＞加衔；兼署不得与相邻档混同；无双逆表。"""
    ranks = {tenure: command_power_rank(tenure) for tenure in VALID_TENURES}
    assert ranks["真除"] > ranks["兼署"] > ranks["署理"] > ranks["加衔"]
    # 专门防止兼署遗漏/混同
    assert ranks["兼署"] != ranks["真除"]
    assert ranks["兼署"] != ranks["署理"]
    assert set(COMMAND_POWER_RANK) == set(VALID_TENURES)

    weights = {tenure: execution_distortion_weight(tenure) for tenure in VALID_TENURES}
    assert weights["真除"] < weights["兼署"] < weights["署理"] < weights["加衔"]
    assert weights["兼署"] != weights["真除"]
    assert weights["兼署"] != weights["署理"]
    # 走样权重由号令力逆序公式导出，不是第二份枚举表
    max_rank = max(COMMAND_POWER_RANK.values())
    for tenure in VALID_TENURES:
        assert weights[tenure] == max_rank - ranks[tenure]


def test_authority_command_relief_single_source_from_privileges():
    """特权名唯一来自 authority_privileges，不在任别模块第二份拼写。"""
    assert tuple(AUTHORITY_COMMAND_RELIEF.keys()) == AUTHORITY_PRIVILEGES
    assert set(AUTHORITY_COMMAND_RELIEF) == AUTHORITY_PRIVILEGE_SET
    assert AUTHORITY_COMMAND_RELIEF["尚方剑密授"] > AUTHORITY_COMMAND_RELIEF["便宜行事"]


def test_held_authority_privileges_reduce_distortion_weight():
    base = execution_distortion_weight("署理", [])
    for privilege in AUTHORITY_PRIVILEGES:
        eased = execution_distortion_weight(
            "署理", [{"privilege": privilege}],
        )
        assert eased < base, privilege
    assert execution_distortion_weight(
        "署理", [{"privilege": "尚方剑密授"}],
    ) < execution_distortion_weight(
        "署理", [{"privilege": "便宜行事"}],
    )


def test_project_dossiers_requires_db_and_state():
    """投影必查 DB 真态；缺 db/state 不得静默 skip。"""
    with pytest.raises(TypeError, match="missing 2 required positional arguments"):
        decree_mod.project_dossiers_for_simulator([])  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="requires db and state"):
        decree_mod.project_dossiers_for_simulator([], db=None, state=None)  # type: ignore[arg-type]


# ── live assembly chain ───────────────────────────────────────────────────


def test_td8_same_office_four_tenures_live_assembly_chain(game):
    """TD-8：同一职差覆盖四档任别；断言落 project_dossiers_for_simulator 真链。"""
    db, state, _content = game
    holder = _ministers(db, 1)[0]
    office = str(
        db.conn.execute(
            "SELECT office FROM characters WHERE name=?", (holder,),
        ).fetchone()["office"]
    )

    observed = []
    for tenure in VALID_TENURES:
        _set_tenure(db, holder, tenure, office=office)
        # 职差未变
        current_office = str(
            db.conn.execute(
                "SELECT office FROM characters WHERE name=?", (holder,),
            ).fetchone()["office"]
        )
        assert current_office == office
        consumer = _executing_policy(
            db, state, holder, target_id=f"td8-same-office-{tenure}",
        )
        hit = _live_exec_side(db, state, consumer)
        assert hit["appointment_tenure"] == tenure
        assert hit["command_power_rank"] == command_power_rank(tenure)
        assert hit["distortion_weight"] == execution_distortion_weight(tenure)
        # 承办人现职任别，不是案卷 payload 任别（payload 固定写了加衔毒丸）
        assert "payload-auth" not in hit["authorization_ids"]
        assert "payload-list" not in hit["authorization_ids"]
        observed.append(hit)

    ranks = [row["command_power_rank"] for row in observed]
    assert ranks == sorted(ranks, reverse=True)
    weights = [row["distortion_weight"] for row in observed]
    assert weights == sorted(weights)
    # 兼署夹在真除与署理之间，不得塌缩
    by_tenure = {
        row["appointment_tenure"]: row for row in observed
    }
    assert (
        by_tenure["真除"]["distortion_weight"]
        < by_tenure["兼署"]["distortion_weight"]
        < by_tenure["署理"]["distortion_weight"]
    )
    assert by_tenure["兼署"]["command_power_rank"] != by_tenure["真除"]["command_power_rank"]
    assert by_tenure["兼署"]["command_power_rank"] != by_tenure["署理"]["command_power_rank"]


def test_execution_and_sim_assembly_reuse_611_projection_not_payload(game):
    db, state, content = game
    holder = _ministers(db, 1)[0]
    _set_tenure(db, holder, "署理")
    domain_target = "边饷专差"
    grant_dossier = _eligible_dossier(
        db, state, holder, target_id=domain_target,
    )
    authority_id = _grant(
        db, state, content, holder, "专差督办",
        f"issue:{domain_target}", grant_dossier,
    )
    consumer = _executing_policy(
        db, state, holder, target_id=domain_target,
    )

    exec_row = _live_exec_side(db, state, consumer)
    assert [item["id"] for item in exec_row["held_authorities"]] == [authority_id]
    assert exec_row["authorization_ids"] == [str(authority_id)]
    assert exec_row["appointment_tenure"] == "署理"
    # 授权抬升号令力 → 走样权重低于裸署理
    assert exec_row["distortion_weight"] < execution_distortion_weight("署理")

    sim_rows = decree_mod.project_dossiers_for_simulator(
        [consumer], db=db, state=state,
    )
    assert len(sim_rows) == 1
    sim = sim_rows[0]
    assert sim["held_authorities"] == exec_row["held_authorities"]
    assert sim["authorization_ids"] == exec_row["authorization_ids"]
    assert sim["appointment_tenure"] == "署理"
    assert "payload-auth" not in sim["authorization_ids"]
    assert "payload-list" not in sim["authorization_ids"]

    # Extractor 装配链同一投影，不另造 side-channel
    extractor = build_extractor_shared_context(
        db, state, narrative="试", decree_text="",
        decree_dossiers=sim_rows,
    )
    ext = next(
        row for row in extractor["decree_dossiers"]
        if int(row["id"]) == int(consumer["id"])
    )
    assert ext["held_authorities"] == exec_row["held_authorities"]
    assert ext["authorization_ids"] == [str(authority_id)]
    assert ext["appointment_tenure"] == "署理"


def test_authority_lifecycle_grant_revoke_restore_on_real_assembly(game):
    """无授权→授予→收回；执行格与推演同向；GameDB 重开一致。与 #611 共用 fixture。"""
    db, state, content = game
    holder = _ministers(db, 1)[0]
    _set_tenure(db, holder, "兼署")
    target = "清丈田亩"
    consumer = _executing_policy(db, state, holder, target_id=target)

    bare_exec = _live_exec_side(db, state, consumer)
    bare_sim = decree_mod.project_dossiers_for_simulator(
        [consumer], db=db, state=state,
    )[0]
    assert bare_exec["held_authorities"] == []
    assert bare_sim["held_authorities"] == []
    bare_weight = bare_exec["distortion_weight"]

    grant_dossier = _eligible_dossier(db, state, holder, target_id=target)
    authority_id = _grant(
        db, state, content, holder, "尚方剑密授",
        f"issue:{target}", grant_dossier,
    )

    granted_exec = _live_exec_side(db, state, consumer)
    granted_sim = decree_mod.project_dossiers_for_simulator(
        [consumer], db=db, state=state,
    )[0]
    expected_held = [{
        "id": authority_id,
        "holder_id": holder,
        "privilege": "尚方剑密授",
        "scope": f"issue:{target}",
        "effective_turn": state.turn,
    }]
    assert granted_exec["held_authorities"] == expected_held
    assert granted_sim["held_authorities"] == expected_held
    assert granted_exec["distortion_weight"] < bare_weight

    db_path = db.path
    db.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    restored_consumer = restored.get_decree_dossier(consumer["id"])
    after_restore = _live_exec_side(restored, restored_state, restored_consumer)
    after_sim = decree_mod.project_dossiers_for_simulator(
        [restored_consumer], db=restored, state=restored_state,
    )[0]
    assert after_restore["held_authorities"] == expected_held
    assert after_sim["held_authorities"] == expected_held
    assert after_restore["appointment_tenure"] == "兼署"

    revoke_dossier = _eligible_dossier(
        restored, restored_state, holder, target_id="收权清丈",
    )
    _revoke(restored, restored_state, content, authority_id, revoke_dossier)

    restored.close()
    final = GameDB(db_path, content)
    final_state = final.load_state()
    final_consumer = final.get_decree_dossier(consumer["id"])
    gone_exec = _live_exec_side(final, final_state, final_consumer)
    gone_sim = decree_mod.project_dossiers_for_simulator(
        [final_consumer], db=final, state=final_state,
    )[0]
    assert gone_exec["held_authorities"] == []
    assert gone_sim["held_authorities"] == []
    assert gone_exec["authorization_ids"] == []
    assert gone_exec["distortion_weight"] == bare_weight


def test_court_roster_carries_appointment_tenure_four_tiers(game):
    """月末推演盘面简报 court_roster 带任别四档。"""
    db, state, _content = game
    names = _ministers(db, 4)
    for name, tenure in zip(names, VALID_TENURES):
        _set_tenure(db, name, tenure)

    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    cols = payload["court_roster"]["cols"]
    assert "appointment_tenure" in cols
    idx = cols.index("appointment_tenure")
    name_idx = cols.index("name")
    by_name = {
        row[name_idx]: row[idx] for row in payload["court_roster"]["rows"]
    }
    for name, tenure in zip(names, VALID_TENURES):
        assert by_name[name] == tenure


def test_season_simulator_prompt_covers_command_power_order():
    from ming_sim.content import GameContent

    text = GameContent.load().season_simulator_prompt
    assert "真除＞兼署＞署理＞加衔" in text or "真除>兼署>署理>加衔" in text
    assert "兼署" in text
    assert "held_authorities" in text or "在持授权" in text
    assert "appointment_tenure" in text


def _clear_character_offices(db, name):
    """人物仍在 characters，但 character_offices 无行（缺档合法态）。"""
    db.conn.execute(
        "DELETE FROM character_offices WHERE character_name=?", (name,),
    )
    db.conn.commit()
    assert db.conn.execute(
        "SELECT 1 FROM character_offices WHERE character_name=?", (name,),
    ).fetchone() is None
    assert db.conn.execute(
        "SELECT 1 FROM characters WHERE name=?", (name,),
    ).fetchone() is not None


def test_missing_offices_explicit_executor_falls_to_bare_not_other_lead(game):
    """显式 executor 缺 character_offices 行：bare 真除，不得静默继承他人主办任别。"""
    db, state, _content = game
    executor, other_lead = _ministers(db, 2)
    _clear_character_offices(db, executor)
    _set_tenure(db, other_lead, "加衔")

    consumer = _executing_policy(
        db, state, executor,
        target_id="missing-offices-explicit-executor",
        roster=[
            {"character_id": executor, "tier": "主办", "role": "承办"},
            {"character_id": other_lead, "tier": "主办", "role": "协理"},
        ],
    )
    assert consumer["executor_id"] == executor

    hit = _live_exec_side(db, state, consumer)
    bare_weight = execution_distortion_weight(DEFAULT_APPOINTMENT_TENURE)
    other_weight = execution_distortion_weight("加衔")
    assert hit["appointment_tenure"] == DEFAULT_APPOINTMENT_TENURE == "真除"
    assert hit["appointment_tenure"] != "加衔"
    assert hit["command_power_rank"] == command_power_rank("真除")
    assert hit["distortion_weight"] == bare_weight
    assert hit["distortion_weight"] != other_weight
    # 直读 resolve 同口径，禁跨候选换人
    assert decree_mod.resolve_executor_appointment_tenure(db, consumer) == "真除"

    # 与 court_roster COALESCE 缺档=真除自洽
    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    cols = payload["court_roster"]["cols"]
    name_idx = cols.index("name")
    tenure_idx = cols.index("appointment_tenure")
    by_name = {
        row[name_idx]: row[tenure_idx] for row in payload["court_roster"]["rows"]
    }
    assert by_name[executor] == "真除"
    assert by_name[other_lead] == "加衔"


def test_missing_offices_first_lead_falls_to_bare_not_next_lead(game):
    """无显式 character executor 时首位主办缺档：bare 真除，不得继承次名主办任别。"""
    db, state, _content = game
    first_lead, second_lead = _ministers(db, 2)
    _clear_character_offices(db, first_lead)
    _set_tenure(db, second_lead, "加衔")

    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="疏浚运河",
        target_kind="issue",
        target_id="missing-offices-first-lead",
        executor_kind="",
        executor_id="",
        participants=[
            {"character_id": first_lead, "tier": "主办", "role": "承办"},
            {"character_id": second_lead, "tier": "主办", "role": "协理"},
        ],
        payload={
            "authorization_id": "payload-auth",
            "authorization_ids": ["payload-list"],
            "任别": "加衔",
        },
    )
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    consumer = db.get_decree_dossier(dossier_id)
    assert consumer["status"] == "executing"
    assert not str(consumer.get("executor_id") or "").strip()

    hit = _live_exec_side(db, state, consumer)
    bare_weight = execution_distortion_weight(DEFAULT_APPOINTMENT_TENURE)
    assert hit["appointment_tenure"] == DEFAULT_APPOINTMENT_TENURE == "真除"
    assert hit["appointment_tenure"] != "加衔"
    assert hit["command_power_rank"] == command_power_rank("真除")
    assert hit["distortion_weight"] == bare_weight
    assert hit["distortion_weight"] != execution_distortion_weight("加衔")
    assert decree_mod.resolve_executor_appointment_tenure(db, consumer) == "真除"

    payload = build_simulator_payload(state, db, decree_text="", previous_narrative="")
    cols = payload["court_roster"]["cols"]
    name_idx = cols.index("name")
    tenure_idx = cols.index("appointment_tenure")
    by_name = {
        row[name_idx]: row[tenure_idx] for row in payload["court_roster"]["rows"]
    }
    assert by_name[first_lead] == "真除"
    assert by_name[second_lead] == "加衔"
