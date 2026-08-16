"""#611 authority ledger: production slot, projection, restore, revoke impression."""

import pytest

from ming_sim.db import GameDB
from ming_sim import issues as issue_engine
import ming_sim.decree as decree_mod
from ming_sim.relations import EMPEROR_NODE
from ming_sim.simulation import TOP_LEVEL_ALIASES, canonicalize_extraction


def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _eligible_dossier(db, state, holder, *, target_kind="issue", target_id="清丈田亩"):
    """Real effect-eligible dossier used as authority_changes source."""
    dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="授以便宜行事之权",
        target_kind=target_kind,
        target_id=target_id,
        executor_kind="character",
        executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办", "role": "承办"},
        ],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    assert db.dossier_authorizes_effects(dossier_id)
    return db.get_decree_dossier(dossier_id)


def _grant(db, state, content, holder, privilege, scope, dossier, **turns):
    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予", "holder_id": holder, "privilege": privilege,
            "scope": scope, "dossier_id": dossier["id"], **turns,
        }],
    }, content=content)["authority_changes"][0]
    assert result.get("rejected") is not True
    return int(result["authority_id"])


def _revoke(db, state, content, authority_id, dossier):
    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "收回", "authority_id": authority_id,
            "dossier_id": dossier["id"],
        }],
    }, content=content)["authority_changes"][0]
    assert result.get("rejected") is not True
    return result


def test_authority_changes_alias_canonicalizes_chinese_and_english_op_locally():
    assert TOP_LEVEL_ALIASES["授权变更"] == "authority_changes"
    canonical = canonicalize_extraction({
        "authority_changes": [{
            "op": "revoke", "authority_id": 2, "dossier_id": 3,
        }],
    })
    assert canonical["authority_changes"] == [{
        "op": "revoke", "authority_id": 2, "dossier_id": 3,
    }]

    chinese = canonicalize_extraction({
        "授权变更": [{
            "动作": "授予", "授予对象": "甲", "权项": "便宜行事",
            "事域": "issue:x", "案卷编号": 1,
        }],
    })
    assert chinese["authority_changes"] == [{
        "op": "授予", "holder_id": "甲", "privilege": "便宜行事",
        "scope": "issue:x", "dossier_id": 1,
    }]


def test_authority_op_alias_does_not_rewrite_other_sections_action_field():
    canonical = canonicalize_extraction({
        "人物变更": [{"动作": "任命", "name": "甲"}],
        "建筑": [{"动作": "create", "名称": "火器局"}],
        "authority_changes": [{"动作": "grant", "dossier_id": 7}],
    })

    assert canonical["人物变更"][0]["action"] == "任命"
    assert canonical["建筑"][0]["action"] == "create"
    assert canonical["authority_changes"][0]["op"] == "grant"


def test_production_path_grant_restore_revoke_impression_tracer(game):
    """Real production-slot lifecycle: grant → judge → restore → revoke → restore."""
    db, state, content = game
    holder = _minister(db)
    domain = "issue:清丈田亩"
    grant_dossier = _eligible_dossier(
        db, state, holder, target_id="清丈田亩",
    )
    consumer = _eligible_dossier(
        db, state, holder, target_id="清丈田亩",
    )
    metrics_before = dict(state.metrics)
    factions_before = [
        dict(row) for row in db.conn.execute(
            "SELECT name,satisfaction,leverage FROM factions ORDER BY name"
        )
    ]

    grant_result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": domain,
            "dossier_id": grant_dossier["id"],
        }],
    }, content=content)
    assert grant_result["authority_changes"][0].get("rejected") is not True
    authority_id = int(grant_result["authority_changes"][0]["authority_id"])
    assert authority_id > 0

    # Same holder/domain; projection must surface the granted row.
    before = decree_mod.build_promulgation_judge_context(db, state, [consumer])
    expected_held = [{
        "id": authority_id,
        "holder_id": holder,
        "privilege": "便宜行事",
        "scope": domain,
        "effective_turn": state.turn,
    }]
    assert before["dossiers"][0]["held_authorities"] == expected_held
    assert before["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == [
        str(authority_id),
    ]

    db_path = db.path
    db.close()
    restored = GameDB(db_path, content)
    restored_state = restored.load_state()
    after_restore = decree_mod.build_promulgation_judge_context(
        restored, restored_state, [restored.get_decree_dossier(consumer["id"])],
    )
    assert after_restore["dossiers"][0]["held_authorities"] == expected_held
    assert after_restore["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == [
        str(authority_id),
    ]

    revoke_dossier = _eligible_dossier(
        restored, restored_state, holder, target_id="收权清丈",
    )
    revoke_result = issue_engine.apply_score_extraction(restored, restored_state, {
        "authority_changes": [{
            "动作": "收回",
            "authority_id": authority_id,
            "dossier_id": revoke_dossier["id"],
        }],
    }, content=content)
    assert revoke_result["authority_changes"][0].get("rejected") is not True
    assert revoke_result["authority_changes"][0]["authority_id"] == authority_id

    restored.close()
    final = GameDB(db_path, content)
    final_state = final.load_state()
    record = final.get_authority(authority_id)
    assert record["revoked"] is True
    assert record["revoked_turn"] == final_state.turn

    edges = final.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )
    assert len(edges) == 1
    assert edges[0]["context"] == f"收权·罢差·便宜行事·{domain}"
    assert edges[0]["origin"].startswith(f"authority_revoke:{authority_id}")
    assert not edges[0]["evidence"]

    # Zero 0056 / 皇威 / faction cost on revoke.
    assert final_state.metrics == metrics_before
    assert [
        dict(row) for row in final.conn.execute(
            "SELECT name,satisfaction,leverage FROM factions ORDER BY name"
        )
    ] == factions_before

    gone = decree_mod.build_promulgation_judge_context(
        final, final_state, [final.get_decree_dossier(consumer["id"])],
    )
    assert gone["dossiers"][0]["held_authorities"] == []
    assert gone["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == []

    # Idempotent already_revoked: no second edge, no revoked_turn rewrite.
    first_revoked_turn = record["revoked_turn"]
    again = issue_engine.apply_score_extraction(final, final_state, {
        "authority_changes": [{
            "动作": "收回",
            "authority_id": authority_id,
            "dossier_id": revoke_dossier["id"],
        }],
    }, content=content)
    assert again["authority_changes"][0]["reason"] == "already_revoked"
    assert again["authority_changes"][0].get("rejected") is not True
    assert final.get_authority(authority_id)["revoked_turn"] == first_revoked_turn
    assert len(final.get_relation_edge_events(
        source=holder, target=EMPEROR_NODE, event_kind="结怨",
    )) == 1


def test_authority_changes_rejects_ineligible_keeps_legal_peer(game):
    db, state, content = game
    holder = _minister(db)
    good = _eligible_dossier(db, state, holder, target_id="合法授予")
    rejected_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="打回之旨",
        target_kind="issue", target_id="打回",
        executor_kind="character", executor_id=holder,
    )
    db.record_dossier_decision(rejected_id, "rejected", reason="封驳")
    assert not db.dossier_authorizes_effects(rejected_id)

    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [
            {
                "动作": "授予",
                "holder_id": holder,
                "privilege": "尚方剑密授",
                "scope": "issue:打回",
                "dossier_id": rejected_id,
            },
            {
                # Missing dossier_id entirely.
                "动作": "授予",
                "holder_id": holder,
                "privilege": "专差督办",
                "scope": "issue:无来源",
            },
            {
                "动作": "授予",
                "holder_id": holder,
                "privilege": "新机构专办",
                "scope": "issue:合法授予",
                "dossier_id": good["id"],
            },
        ],
    }, content=content)

    rows = result["authority_changes"]
    assert rows[0]["rejected"] is True
    assert rows[0]["reason"] == "dossier_not_effect_eligible"
    assert rows[1]["rejected"] is True
    assert rows[1]["reason"] == "missing_dossier_source"
    assert rows[2].get("rejected") is not True
    authority_id = int(rows[2]["authority_id"])
    assert db.get_authority(authority_id)["privilege"] == "新机构专办"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 1


def test_projection_typed_domain_only_and_ignores_payload_authorization(game):
    db, state, content = game
    holder = _minister(db)
    other = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND name<>? ORDER BY name LIMIT 1",
        (holder,),
    ).fetchone()["name"]
    domain = "issue:边饷"
    typed = _grant(
        db, state, content, holder, "专差督办", domain,
        _eligible_dossier(db, state, holder, target_id="typed-projection"),
        effective_turn=state.turn,
    )
    # Legacy bare-domain rows (pre-gate) must still never match typed projection.
    db.conn.execute(
        "INSERT INTO authority_records "
        "(holder_id,privilege,scope,effective_turn,expires_turn,dossier_id) "
        "VALUES (?,?,?,?,NULL,NULL)",
        (holder, "便宜行事", "边饷", state.turn),
    )
    bare = int(db.conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    # Informed-only roster member must not count as actor.
    informed_only = _grant(
        db, state, content, other, "尚方剑密授", domain,
        _eligible_dossier(db, state, other, target_id="informed-projection"),
        effective_turn=state.turn,
    )

    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="边饷专差",
        target_kind="issue", target_id="边饷",
        executor_kind="character", executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办"},
            {"character_id": other, "tier": "知情"},
        ],
        payload={
            "authorization_id": "payload-auth",
            "authorization_ids": ["payload-list"],
            "assignee_id": other,
            "character_id": other,
        },
    )
    dossier = db.get_decree_dossier(dossier_id)
    projected = db.project_applicable_authorities(state.turn, dossier)
    assert [row["id"] for row in projected] == [typed]
    assert bare not in {row["id"] for row in projected}
    assert informed_only not in {row["id"] for row in projected}

    context = decree_mod.build_promulgation_judge_context(db, state, [dossier])
    assert context["dossiers"][0]["held_authorities"] == projected
    assert context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"] == [
        str(typed),
    ]
    assert "payload-auth" not in (
        context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"]
    )
    assert "payload-list" not in (
        context["dossiers"][0]["criteria_snapshot_source"]["authorization_ids"]
    )


def test_same_dossier_grant_replay_is_idempotent(game):
    """同源案卷重放按 dossier origin 幂等，不插第二行。"""
    db, state, content = game
    holder = _minister(db)
    dossier = _eligible_dossier(db, state, holder, target_id="replay")
    payload = {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": "issue:replay",
            "dossier_id": dossier["id"],
        }],
    }
    first = issue_engine.apply_score_extraction(db, state, payload, content=content)
    assert first["authority_changes"][0].get("rejected") is not True
    authority_id = int(first["authority_changes"][0]["authority_id"])

    second = issue_engine.apply_score_extraction(db, state, payload, content=content)
    assert second["authority_changes"][0].get("rejected") is not True
    assert int(second["authority_changes"][0]["authority_id"]) == authority_id
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 1


@pytest.mark.parametrize("terminal_state", ["revoked", "expired"])
def test_same_dossier_grant_replay_returns_terminal_origin_without_regrant(
    game, terminal_state,
):
    db, state, content = game
    holder = _minister(db)
    target = f"{terminal_state}-replay"
    dossier = _eligible_dossier(db, state, holder, target_id=target)
    item = {
        "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
        "scope": f"issue:{target}", "dossier_id": dossier["id"],
    }
    if terminal_state == "expired":
        item["expires_turn"] = state.turn
    payload = {"authority_changes": [item]}
    first = issue_engine.apply_score_extraction(db, state, payload, content=content)
    authority_id = int(first["authority_changes"][0]["authority_id"])
    if terminal_state == "revoked":
        revoke_dossier = _eligible_dossier(db, state, holder, target_id="replay-revoke")
        _revoke(db, state, content, authority_id, revoke_dossier)
    else:
        state.turn += 1

    replay = issue_engine.apply_score_extraction(db, state, payload, content=content)

    assert replay["authority_changes"][0]["authority_id"] == authority_id
    assert replay["authority_changes"][0]["reason"] == "same_dossier_replay"
    record = db.get_authority(authority_id)
    if terminal_state == "revoked":
        assert record["revoked"] is True
    else:
        assert record["expires_turn"] == state.turn - 1
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 1

def test_duplicate_active_authority_is_rejected_across_dossiers(game):
    """不同案卷对同一在持三元组重复授予 → duplicate_active_authority。"""
    db, state, content = game
    holder = _minister(db)
    first_dossier = _eligible_dossier(db, state, holder, target_id="dup-a")
    second_dossier = _eligible_dossier(db, state, holder, target_id="dup-b")
    first = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": "issue:dup",
            "dossier_id": first_dossier["id"],
        }],
    }, content=content)
    assert first["authority_changes"][0].get("rejected") is not True

    second = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": "issue:dup",
            "dossier_id": second_dossier["id"],
        }],
    }, content=content)
    assert second["authority_changes"][0]["rejected"] is True
    assert second["authority_changes"][0]["reason"] == "duplicate_active_authority"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 1


def test_duplicate_check_uses_current_turn_not_future_effective_turn(game):
    db, state, content = game
    holder = _minister(db)
    first_dossier = _eligible_dossier(db, state, holder, target_id="current-active")
    second_dossier = _eligible_dossier(db, state, holder, target_id="future-request")
    _grant(
        db, state, content, holder, "便宜行事", "issue:turn-boundary",
        first_dossier, effective_turn=state.turn, expires_turn=state.turn,
    )

    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
            "scope": "issue:turn-boundary", "effective_turn": state.turn + 1,
            "dossier_id": second_dossier["id"],
        }],
    }, content=content)

    assert result["authority_changes"][0]["reason"] == "duplicate_active_authority"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 1


def test_duplicate_check_ignores_authority_only_active_in_future(game):
    db, state, content = game
    holder = _minister(db)
    future_dossier = _eligible_dossier(db, state, holder, target_id="future-existing")
    current_dossier = _eligible_dossier(db, state, holder, target_id="current-grant")
    _grant(
        db, state, content, holder, "便宜行事", "issue:turn-boundary-future",
        future_dossier, effective_turn=state.turn + 1,
    )

    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予", "holder_id": holder, "privilege": "便宜行事",
            "scope": "issue:turn-boundary-future", "effective_turn": state.turn,
            "expires_turn": state.turn,
            "dossier_id": current_dossier["id"],
        }],
    }, content=content)

    assert result["authority_changes"][0].get("rejected") is not True
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 2


def test_production_rejects_bare_domain_scope(game):
    db, state, content = game
    holder = _minister(db)
    dossier = _eligible_dossier(db, state, holder, target_id="bare")
    result = issue_engine.apply_score_extraction(db, state, {
        "authority_changes": [{
            "动作": "授予",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": "边饷",
            "dossier_id": dossier["id"],
        }],
    }, content=content)
    assert result["authority_changes"][0]["rejected"] is True
    assert result["authority_changes"][0]["reason"] == "invalid_authority_scope"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM authority_records"
    ).fetchone()["n"] == 0


def test_promulgation_payload_does_not_write_authority_records(game):
    """授权案卷不得平行直写 authority_records；#528 仅经 authority_changes 授予。

    完整 privilege/scope/holder 的公开委任顺颁后落一条授权档（单一入口）；
    skill_grants 仍为零（禁技能镜像）。
    """
    db, state, _content = game
    holder = _minister(db)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="authorization",
        decree_text="授以便宜",
        target_kind="issue",
        target_id="payload旁路",
        executor_kind="character",
        executor_id=holder,
        payload={
            "character_id": holder,
            "skill_id": "便宜行事",
            "holder_id": holder,
            "privilege": "便宜行事",
            "scope": "issue:payload旁路",
            "mode": "ordinary",
        },
    )
    skills_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM skill_grants WHERE character_name=?",
        (holder,),
    ).fetchone()["n"]
    db.apply_dossier_promulgation(state, dossier_id, "promulgated")
    rows = db.conn.execute(
        "SELECT * FROM authority_records WHERE dossier_id=?",
        (int(dossier_id),),
    ).fetchall()
    assert len(rows) == 1
    assert str(rows[0]["holder_id"]) == holder
    assert str(rows[0]["privilege"]) == "便宜行事"
    assert str(rows[0]["scope"]) == "issue:payload旁路"
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM skill_grants WHERE character_name=?",
        (holder,),
    ).fetchone()["n"] == skills_before


def test_promulgation_judge_instructions_cover_held_authority_modifiers(monkeypatch):
    import ming_sim.agents as agents_mod
    from ming_sim.models import LLMConfig

    monkeypatch.setattr(
        agents_mod, "create_chat_model", lambda _cfg, **kwargs: object(),
    )
    monkeypatch.setattr(agents_mod, "Agent", lambda **kwargs: kwargs)
    agent = agents_mod.create_promulgation_judge_agent(
        LLMConfig(api_key="test", base_url="http://unused", model="test"),
        object(),
    )
    text = "\n".join(str(item) for item in agent["instructions"])
    assert "held_authorities" in text
    assert "尚方剑密授" in text and "阻力" in text
    assert "便宜行事" in text and "程序" in text
    assert "专差督办" in text and "节制" in text
