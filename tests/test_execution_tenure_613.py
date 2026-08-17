"""#613 执行侧任别读端：执行格/月末推演号令力 + #611 授权投影共用。"""

import pytest

from ming_sim import issues as issue_engine
from ming_sim.appointment_tenure import (
    BASE_DISTORTION_WEIGHT,
    COMMAND_POWER_RANK,
    command_power_rank,
    execution_distortion_weight,
)
from ming_sim.db import GameDB
import ming_sim.decree as decree_mod
from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload


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


def _eligible_auth_dossier(db, state, holder, *, target_id):
    dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="授以便宜行事之权",
        target_kind="issue",
        target_id=target_id,
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办", "role": "承办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    assert db.dossier_authorizes_effects(dossier_id)
    return db.get_decree_dossier(dossier_id)


def _grant(db, state, content, holder, privilege, scope, dossier):
    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": privilege,
            "scope": scope,
            "dossier_id": dossier["id"],
        }],
    }, content=content)["authority_changes"][0]
    assert result.get("rejected") is not True
    return int(result["authority_id"])


def _revoke(db, state, content, authority_id, dossier):
    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "收回",
            "authority_id": authority_id,
            "dossier_id": dossier["id"],
        }],
    }, content=content)["authority_changes"][0]
    assert result.get("rejected") is not True
    return result


# ── pure helpers ──────────────────────────────────────────────────────────


def test_command_power_four_tier_strict_order_and_jianshu_not_collapsed():
    """TD-8：真除＞兼署＞署理＞加衔；兼署不得与相邻档混同。"""
    ranks = {tenure: command_power_rank(tenure) for tenure in VALID_TENURES}
    assert ranks["真除"] > ranks["兼署"] > ranks["署理"] > ranks["加衔"]
    # 专门防止兼署遗漏/混同
    assert ranks["兼署"] != ranks["真除"]
    assert ranks["兼署"] != ranks["署理"]
    assert set(COMMAND_POWER_RANK) == set(VALID_TENURES)
    assert set(BASE_DISTORTION_WEIGHT) == set(VALID_TENURES)

    weights = {tenure: execution_distortion_weight(tenure) for tenure in VALID_TENURES}
    assert weights["真除"] < weights["兼署"] < weights["署理"] < weights["加衔"]
    assert weights["兼署"] != weights["真除"]
    assert weights["兼署"] != weights["署理"]


def test_held_authority_privileges_reduce_distortion_weight():
    base = execution_distortion_weight("署理", [])
    for privilege in ("尚方剑密授", "便宜行事", "专差督办", "新机构专办"):
        eased = execution_distortion_weight(
            "署理", [{"privilege": privilege}],
        )
        assert eased < base, privilege
    assert execution_distortion_weight(
        "署理", [{"privilege": "尚方剑密授"}],
    ) < execution_distortion_weight(
        "署理", [{"privilege": "便宜行事"}],
    )


# ── execution judge input surface ──────────────────────────────────────────


def test_execution_judge_context_covers_four_tenures_same_office(game):
    """同一职差覆盖四档任别；执行格输入面带号令力与走样权重。"""
    db, state, _content = game
    names = _ministers(db, 4)
    dossiers = []
    for name, tenure in zip(names, VALID_TENURES):
        _set_tenure(db, name, tenure)
        dossiers.append(
            _executing_policy(db, state, name, target_id=f"tenure-{tenure}"),
        )

    context = decree_mod.build_execution_judge_context(db, state, dossiers)
    assert context["command_power_order"] == ["真除", "兼署", "署理", "加衔"]
    by_tenure = {
        row["appointment_tenure"]: row for row in context["dossiers"]
    }
    assert set(by_tenure) == set(VALID_TENURES)
    # 承办人现职任别，不是案卷 payload 任别（payload 固定写了加衔毒丸）
    for tenure in VALID_TENURES:
        row = by_tenure[tenure]
        assert row["appointment_tenure"] == tenure
        assert row["command_power_rank"] == command_power_rank(tenure)
        assert row["distortion_weight"] == execution_distortion_weight(tenure)
        assert "payload-auth" not in row["authorization_ids"]
        assert "payload-list" not in row["authorization_ids"]

    ranks = [by_tenure[t]["command_power_rank"] for t in VALID_TENURES]
    assert ranks == sorted(ranks, reverse=True)
    weights = [by_tenure[t]["distortion_weight"] for t in VALID_TENURES]
    assert weights == sorted(weights)
    # 兼署夹在真除与署理之间，不得塌缩
    assert (
        by_tenure["真除"]["distortion_weight"]
        < by_tenure["兼署"]["distortion_weight"]
        < by_tenure["署理"]["distortion_weight"]
    )


def test_execution_and_sim_assembly_reuse_611_projection_not_payload(game):
    db, state, content = game
    holder = _ministers(db, 1)[0]
    _set_tenure(db, holder, "署理")
    domain_target = "边饷专差"
    grant_dossier = _eligible_auth_dossier(
        db, state, holder, target_id=domain_target,
    )
    authority_id = _grant(
        db, state, content, holder, "专差督办",
        f"issue:{domain_target}", grant_dossier,
    )
    consumer = _executing_policy(
        db, state, holder, target_id=domain_target,
    )

    exec_ctx = decree_mod.build_execution_judge_context(db, state, [consumer])
    exec_row = exec_ctx["dossiers"][0]
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
    """无授权→授予→收回；执行格与推演同向；GameDB 重开一致。与 #611 共用样本形态。"""
    db, state, content = game
    holder = _ministers(db, 1)[0]
    _set_tenure(db, holder, "兼署")
    target = "清丈田亩"
    consumer = _executing_policy(db, state, holder, target_id=target)

    bare_exec = decree_mod.build_execution_judge_context(db, state, [consumer])
    bare_sim = decree_mod.project_dossiers_for_simulator(
        [consumer], db=db, state=state,
    )[0]
    assert bare_exec["dossiers"][0]["held_authorities"] == []
    assert bare_sim["held_authorities"] == []
    bare_weight = bare_exec["dossiers"][0]["distortion_weight"]

    grant_dossier = _eligible_auth_dossier(db, state, holder, target_id=target)
    authority_id = _grant(
        db, state, content, holder, "尚方剑密授",
        f"issue:{target}", grant_dossier,
    )

    granted_exec = decree_mod.build_execution_judge_context(db, state, [consumer])
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
    assert granted_exec["dossiers"][0]["held_authorities"] == expected_held
    assert granted_sim["held_authorities"] == expected_held
    assert granted_exec["dossiers"][0]["distortion_weight"] < bare_weight

    db_path = db.path
    db.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    restored_consumer = restored.get_decree_dossier(consumer["id"])
    after_restore = decree_mod.build_execution_judge_context(
        restored, restored_state, [restored_consumer],
    )
    after_sim = decree_mod.project_dossiers_for_simulator(
        [restored_consumer], db=restored, state=restored_state,
    )[0]
    assert after_restore["dossiers"][0]["held_authorities"] == expected_held
    assert after_sim["held_authorities"] == expected_held
    assert after_restore["dossiers"][0]["appointment_tenure"] == "兼署"

    revoke_dossier = _eligible_auth_dossier(
        restored, restored_state, holder, target_id="收权清丈",
    )
    _revoke(restored, restored_state, content, authority_id, revoke_dossier)

    restored.close()
    final = GameDB(db_path, content)
    final_state = final.load_state()
    final_consumer = final.get_decree_dossier(consumer["id"])
    gone_exec = decree_mod.build_execution_judge_context(
        final, final_state, [final_consumer],
    )
    gone_sim = decree_mod.project_dossiers_for_simulator(
        [final_consumer], db=final, state=final_state,
    )[0]
    assert gone_exec["dossiers"][0]["held_authorities"] == []
    assert gone_sim["held_authorities"] == []
    assert gone_exec["dossiers"][0]["authorization_ids"] == []
    assert gone_exec["dossiers"][0]["distortion_weight"] == bare_weight


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
