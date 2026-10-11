import pytest
import json



def test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate(game):
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector

    db, state, _ = game
    collector = RejectionCollector()
    collector.record(
        "new_issues",
        RejectedItem({"title": "中文\ud800"}, "坏", "invalid_enum", Provenance.player_decree),
        state.turn,
    )
    collector.flush_to_db(db)
    row = db.conn.execute("SELECT item_json FROM rejection_reports").fetchone()
    assert json.loads(row["item_json"]) == {"title": "中文\ud800"}







def test_sqlite_text_encoding_fault_aborts_dispatch_without_refusal(game):
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, _ = game
    dispatch_declaration(db, state, {"effects": []}, source=Provenance.system_simulation)
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text="新立局势", target_kind="issue",
        target_id="encoding-fault",
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    before_metrics = dict(state.metrics)
    before_issues = db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    with pytest.raises(UnicodeEncodeError):
        dispatch_declaration(db, state, {"effects": [{
            "metric_delta": {"民心": 2},
            "new_issues": [{"kind": "situation", "title": "中文\ud800",
                            "origin_kind": "decree", "origin_ref": f"dossier:{dossier_id}"}],
        }]}, source=Provenance.system_simulation)
    assert state.metrics == before_metrics
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before_issues
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 0
