"""#629: the due-review projection preserves the supplied criterion verbatim."""

from ming_sim.due_review import project_due_review_scene
from ming_sim.issues import apply_score_extraction
from ming_sim.staged_commitment import ENTRY_KIND_STAGED, write_due_staged_commitment_todos


def test_due_review_preserves_diegetic_fenjie_phrase(game):
    """An ordinary criterion is passed through intact, not stripped as a system token."""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()

    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' "
        "AND office IS NOT NULL AND office != '' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text="北疆定策",
        target_kind="issue",
        target_id="fenjie-629",
        executor_kind="character",
        executor_id=holder,
        participants=[{"character_id": holder, "tier": "主办"}],
        payload={"mode": "ordinary"},
    )
    db.record_dossier_decision(did, "promulgated")
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,))
    db.conn.commit()

    diegetic = "与喀尔喀分界而治"
    stages = [{
        "stage_idx": 0,
        "due_turn": state.turn,
        "criterion_text": diegetic,
        "origin_context": f"北疆定策：{diegetic}",
    }]
    out = apply_score_extraction(
        db, state,
        {
            "new_issues": [{
                "origin_kind": "decree",
                "origin_ref": f"dossier:{did}",
                "kind": "initiative",
                "title": "分界而治之诺",
                "stage_text": diegetic,
                "commitment_kind": "until_stop",
                "ongoing_effects": {},
                "stages": stages,
            }]
        },
        content=content,
    )
    created = out["issue_summary"]["new_issues"][0]
    assert created.get("rejected") is False, created
    issue_id = int(created["issue_id"])
    write_due_staged_commitment_todos(db, state)
    staged_todo = [
        t for t in db.list_next_audience_todos(commitment_ref=issue_id)
        if str(t.get("entry_kind") or "") == ENTRY_KIND_STAGED
    ][0]
    scene = project_due_review_scene(db, staged_todo)
    assert scene["criterion_text"] == diegetic
    assert scene["origin_context"] == f"北疆定策：{diegetic}"
