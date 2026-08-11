import json


def _make_midzhi_dossier(db, state, *, target_id="river-works"):
    return db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="特旨清核河工",
        target_kind="issue",
        target_id=target_id,
        payload={"mode": "midzhi"},
    )


def test_predeclared_midzhi_is_exposed_to_promulgation_provider_seam(game):
    db, state, _content = game
    midzhi_id = _make_midzhi_dossier(db, state)
    ordinary_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="清核仓场",
        target_kind="issue",
        target_id="granary",
    )

    by_id = {row["id"]: row for row in db.list_decree_dossiers(status="proposed")}

    assert by_id[midzhi_id]["mode"] == "midzhi"
    assert by_id[ordinary_id]["mode"] == "ordinary"


def test_predeclared_midzhi_records_append_only_stigma_when_promulgated(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)

    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier_id, "decision": "promulgated"}]
    )
    dossier = db.get_decree_dossier(dossier_id)

    assert dossier["stigma"] == [{
        "kind": "midzhi",
        "reason": "predeclared",
        "turn": state.turn,
        "source_action": "promulgated",
    }]
    assert json.loads(dossier["stigma_json"]) == dossier["stigma"]


def test_rejected_midzhi_and_force_promulgation_each_record_one_stigma(game):
    db, state, _content = game
    dossier_id = _make_midzhi_dossier(db, state)

    db.apply_dossier_promulgation(
        state, dossier_id, "rejected", blocked_layer="six_offices", reason="科臣封驳"
    )
    db.apply_dossier_promulgation(state, dossier_id, "force_promulgated")
    # Recovery/replay cannot append the same marker twice.
    db.append_dossier_stigma(
        dossier_id, kind="midzhi", reason="predeclared",
        turn=state.turn, source_action="rejected",
    )

    dossier = db.get_decree_dossier(dossier_id)
    assert dossier["stigma"] == [
        {
            "kind": "midzhi",
            "reason": "predeclared",
            "turn": state.turn,
            "source_action": "rejected",
        },
        {
            "kind": "midzhi",
            "reason": "rescript",
            "turn": state.turn,
            "source_action": "force_promulgated",
        },
    ]
