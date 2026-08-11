from pathlib import Path

import pytest

import ming_sim.decree as decree_mod
from ming_sim.decree import (
    stub_promulgation_verdicts,
    validate_promulgation_verdicts,
)
from ming_sim.exceptions import LLMContractError, SettlementAbort


def test_default_promulgation_stub_passes_every_dossier_without_collaborators():
    state = object()
    dossiers = [{"id": 7}, {"id": 11}]

    assert stub_promulgation_verdicts(dossiers, state) == [
        {"dossier_id": 7, "decision": "promulgated"},
        {"dossier_id": 11, "decision": "promulgated"},
    ]


def test_injected_promulgation_batch_cannot_silently_omit_a_dossier(read_game):
    db, state, _content = read_game
    dossiers = [{"id": 7}, {"id": 11}]

    with pytest.raises(LLMContractError, match="逐案覆盖"):
        validate_promulgation_verdicts(
            [{"dossier_id": 7, "decision": "promulgated"}], dossiers, db,
        )


def _stage_policy_dossier(db, state):
    return db.create_decree_dossier(
        state, action_type="policy", decree_text="清核河工",
        target_kind="issue", target_id=f"river-{state.turn}",
    )


def test_public_resolve_seam_reuses_durable_batch_after_pre_simulation_crash(
    game, monkeypatch,
):
    db, state, content = game
    dossier_id = _stage_policy_dossier(db, state)
    calls = []

    def provider(dossiers, _state):
        calls.append([row["id"] for row in dossiers])
        return [{"dossier_id": dossier_id, "decision": "promulgated"}]

    def stop_after_persistence(_turn):
        raise RuntimeError("stop after durable verdict")

    original = db.list_decree_dossiers_for_simulation
    monkeypatch.setattr(db, "list_decree_dossiers_for_simulation", stop_after_persistence)
    with pytest.raises(RuntimeError, match="durable verdict"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工",
            content=content, promulgation_verdict_provider=provider,
        )
    assert db.get_pending_promulgation_verdicts(state.turn) == [
        {"dossier_id": dossier_id, "decision": "promulgated"},
    ]

    # Recovery must consume the same turn-scoped batch, not call the provider.
    monkeypatch.setattr(db, "list_decree_dossiers_for_simulation", original)
    monkeypatch.setattr(
        decree_mod, "create_season_simulator_agent",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stop after recovery")),
    )
    with pytest.raises(RuntimeError, match="stop after recovery"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工",
            content=content, promulgation_verdict_provider=provider,
        )
    assert calls == [[dossier_id]]


@pytest.mark.parametrize("stored_json", ["{", "[]"])
def test_public_resolve_seam_wraps_corrupt_durable_verdict_on_real_recovery(
    game, monkeypatch, stored_json,
):
    db, state, content = game
    dossier_id = _stage_policy_dossier(db, state)
    provider_calls = []

    def provider(dossiers, _state):
        provider_calls.append([row["id"] for row in dossiers])
        return [{"dossier_id": dossier_id, "decision": "promulgated"}]

    original = db.list_decree_dossiers_for_simulation
    monkeypatch.setattr(
        db, "list_decree_dossiers_for_simulation",
        lambda _turn: (_ for _ in ()).throw(RuntimeError("durable tracer")),
    )
    with pytest.raises(RuntimeError, match="durable tracer"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工",
            content=content, promulgation_verdict_provider=provider,
        )

    baseline_state = tuple(db.conn.execute(
        "SELECT turn, turn_phase FROM game_state WHERE id=1"
    ).fetchone())
    baseline_metrics = list(db.conn.execute(
        "SELECT key, value FROM metrics ORDER BY key"
    ).fetchall())
    baseline_dossier = db.get_decree_dossier(dossier_id)
    assert baseline_dossier["status"] == "proposed"
    assert db.list_decree_dossier_decisions(dossier_id) == []

    db.conn.execute(
        "UPDATE pending_promulgation_verdicts SET verdict_json=? "
        "WHERE turn=? AND dossier_id=?",
        (stored_json, state.turn, dossier_id),
    )
    db.conn.commit()
    monkeypatch.setattr(db, "list_decree_dossiers_for_simulation", original)
    monkeypatch.setattr(
        decree_mod, "create_season_simulator_agent",
        lambda *a, **k: pytest.fail("坏持久判决不得进入 simulator"),
    )

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工",
            content=content,
            promulgation_verdict_provider=lambda *_: pytest.fail(
                "恢复必须读取原批次，不得重跑 provider"
            ),
        )

    abort = exc_info.value
    assert abort.stage == "promulgation"
    assert abort.error_pack_path and Path(abort.error_pack_path).is_dir()
    assert isinstance(abort.__cause__, LLMContractError)
    assert isinstance(abort.__cause__.__cause__, ValueError)
    assert provider_calls == [[dossier_id]]
    report = db.conn.execute(
        "SELECT item_json FROM rejection_reports "
        "WHERE turn=? ORDER BY id DESC LIMIT 1", (state.turn,),
    ).fetchone()
    assert __import__("json").loads(report["item_json"]) == {"raw_value": stored_json}
    assert tuple(db.conn.execute(
        "SELECT turn, turn_phase FROM game_state WHERE id=1"
    ).fetchone()) == baseline_state
    assert list(db.conn.execute(
        "SELECT key, value FROM metrics ORDER BY key"
    ).fetchall()) == baseline_metrics
    assert db.get_decree_dossier(dossier_id) == baseline_dossier
    assert db.list_decree_dossier_decisions(dossier_id) == []
    assert db.conn.execute(
        "SELECT verdict_json FROM pending_promulgation_verdicts "
        "WHERE turn=? AND dossier_id=?", (state.turn, dossier_id),
    ).fetchone()["verdict_json"] == stored_json


def test_public_resolve_seam_rejects_bad_shape_without_persisting(game):
    db, state, content = game
    _stage_policy_dossier(db, state)

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
            promulgation_verdict_provider=lambda *_: {"decision": "promulgated"},
        )
    assert exc_info.value.stage == "promulgation"
    assert exc_info.value.error_pack_path
    assert db.get_pending_promulgation_verdicts(state.turn) == []
    report = db.conn.execute(
        "SELECT item_json FROM rejection_reports "
        "WHERE turn=? ORDER BY id DESC LIMIT 1", (state.turn,),
    ).fetchone()
    assert __import__("json").loads(report["item_json"]) == {
        "decision": "promulgated",
    }


def test_public_resolve_seam_wraps_scalar_verdict_item_for_audit(game):
    db, state, content = game
    _stage_policy_dossier(db, state)

    with pytest.raises(SettlementAbort):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
            promulgation_verdict_provider=lambda *_: [None],
        )

    report = db.conn.execute(
        "SELECT item_json FROM rejection_reports "
        "WHERE turn=? ORDER BY id DESC LIMIT 1", (state.turn,),
    ).fetchone()
    assert __import__("json").loads(report["item_json"]) == {"raw_value": None}


def test_public_resolve_seam_rejects_rejected_verdict_without_affected_parties(game):
    db, state, content = game
    dossier_id = _stage_policy_dossier(db, state)

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
            promulgation_verdict_provider=lambda *_: [{
                "dossier_id": dossier_id,
                "decision": "rejected",
                "blocked_layer": "six_offices",
                "primary_opponents": ["东林"],
                "gatekeeper_id": None,
                "reason": "科臣封驳。",
                "criteria_snapshot": {
                    "imperial_authority_band": "偏弱",
                    "involved_office_types": ["言官"],
                    "authorization_ids": [],
                    "endorsement_entry_ids": [],
                },
            }],
        )

    assert exc_info.value.stage == "promulgation"
    assert db.get_pending_promulgation_verdicts(state.turn) == []
    assert db.list_decree_dossier_decisions(dossier_id) == []


@pytest.mark.parametrize("contamination", [
    {"resistance_score": 99.5},
    {"resistance_score": "99.5"},
    {"resistance_detail": {"score": 99.5}},
    {"resistance_detail": {"score": "99.5"}},
])
def test_public_resolve_seam_audits_numeric_verdict_rejection(game, contamination):
    db, state, content = game
    dossier_id = _stage_policy_dossier(db, state)
    raw = {
        "dossier_id": dossier_id,
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": None,
        "reason": "科臣封驳。",
        "affected_parties": [
            {"kind": "faction", "key": "东林", "severity": "不满"},
        ],
        "criteria_snapshot": {
            "imperial_authority_band": "偏弱",
            "involved_office_types": ["言官"],
            "authorization_ids": [],
            "endorsement_entry_ids": [],
        },
        **contamination,
    }

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
            promulgation_verdict_provider=lambda *_: [raw],
        )

    assert exc_info.value.stage == "promulgation"
    assert db.get_pending_promulgation_verdicts(state.turn) == []
    assert db.list_decree_dossier_decisions(dossier_id) == []
    report = db.conn.execute(
        "SELECT section,item_json,category,source FROM rejection_reports "
        "WHERE turn=? ORDER BY id DESC LIMIT 1", (state.turn,),
    ).fetchone()
    assert report["section"] == "promulgation_verdicts"
    assert __import__("json").loads(report["item_json"]) == raw
    assert report["category"] == "invalid_shape"
    assert report["source"] == "player_decree"


def test_public_resolve_seam_audits_only_invalid_provider_item_not_valid_or_exempt(game):
    db, state, content = game
    valid_id = _stage_policy_dossier(db, state)
    invalid_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="整饬漕运",
        target_kind="issue", target_id="canal",
    )
    exempt_id = db.create_decree_dossier(
        state, action_type="secret_authorization", decree_text="密授查仓之权",
        target_kind="issue", target_id="granary",
    )
    valid = {"dossier_id": valid_id, "decision": "promulgated"}
    invalid = {"dossier_id": invalid_id, "decision": "unknown"}

    with pytest.raises(SettlementAbort):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
            promulgation_verdict_provider=lambda dossiers, _state: (
                [valid, invalid] if {row["id"] for row in dossiers} == {valid_id, invalid_id}
                else pytest.fail("provider 只能收到实际外廷审查案卷")
            ),
        )

    reports = db.conn.execute(
        "SELECT item_json FROM rejection_reports WHERE turn=? ORDER BY id",
        (state.turn,),
    ).fetchall()
    assert [__import__("json").loads(row["item_json"]) for row in reports] == [invalid]
    assert db.get_pending_promulgation_verdicts(state.turn) == []
    assert db.list_decree_dossier_decisions(valid_id) == []
    assert db.list_decree_dossier_decisions(invalid_id) == []
    assert db.list_decree_dossier_decisions(exempt_id) == []


def test_public_resolve_seam_rejects_incomplete_persisted_batch(game):
    db, state, content = game
    first_id = _stage_policy_dossier(db, state)
    second_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="整饬漕运",
        target_kind="issue", target_id="canal",
    )
    db.save_pending_promulgation_verdicts(
        state.turn, [{"dossier_id": first_id, "decision": "promulgated"}],
    )

    with pytest.raises(SettlementAbort) as exc_info:
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工并整饬漕运",
            content=content,
            promulgation_verdict_provider=lambda *_: pytest.fail(
                "残缺持久批次必须 fail-loud，不得重跑 provider"
            ),
        )
    assert exc_info.value.stage == "promulgation"
    assert {first_id, second_id} == {
        row["id"] for row in db.list_decree_dossiers(status="proposed")
    }


def test_public_resolve_seam_rolls_back_partial_batch_persistence(
    game, monkeypatch,
):
    db, state, content = game
    dossier_id = _stage_policy_dossier(db, state)
    original_save = db.save_pending_promulgation_verdicts

    def fail_during_atomic_replace(turn, verdicts):
        valid = list(verdicts)[0]
        return original_save(turn, [
            valid, {"dossier_id": "not-an-int", "decision": "rejected"},
        ])

    monkeypatch.setattr(
        db, "save_pending_promulgation_verdicts", fail_during_atomic_replace,
    )
    with pytest.raises((TypeError, ValueError)):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
            promulgation_verdict_provider=lambda *_: [
                {"dossier_id": dossier_id, "decision": "promulgated"},
            ],
        )
    assert db.get_pending_promulgation_verdicts(state.turn) == []
    assert db.get_decree_dossier(dossier_id)["status"] == "proposed"


def test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row(game):
    db, state, _content = game
    dossier_id = _stage_policy_dossier(db, state)
    original = [{"dossier_id": dossier_id, "decision": "promulgated"}]
    db.save_pending_promulgation_verdicts(state.turn, original)

    with pytest.raises((TypeError, ValueError)):
        db.save_pending_promulgation_verdicts(state.turn, [
            original[0], {"dossier_id": "not-an-int", "decision": "rejected"},
        ])

    assert db.get_pending_promulgation_verdicts(state.turn) == original


def test_public_resolve_seam_ignores_previous_turn_batch(game, monkeypatch):
    db, state, content = game
    dossier_id = _stage_policy_dossier(db, state)
    db.save_pending_promulgation_verdicts(
        state.turn - 1, [{"dossier_id": dossier_id, "decision": "rejected"}],
    )
    called = []

    def provider(dossiers, _state):
        called.append(True)
        return [{"dossier_id": dossiers[0]["id"], "decision": "promulgated"}]

    monkeypatch.setattr(
        db, "list_decree_dossiers_for_simulation",
        lambda _turn: (_ for _ in ()).throw(RuntimeError("stop after current batch")),
    )
    with pytest.raises(RuntimeError, match="current batch"):
        decree_mod.resolve_directives(
            state, db, None, None, [object()], "清核河工", content=content,
            promulgation_verdict_provider=provider,
        )
    assert called == [True]
    assert db.get_pending_promulgation_verdicts(state.turn) == [
        {"dossier_id": dossier_id, "decision": "promulgated"},
    ]
