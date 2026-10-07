"""#1831 事务记录与指向：收夜同生、新指旧、当前情况可恢复、代码不判了结。"""

from __future__ import annotations


import pytest

import ming_sim.audience_night as audience_night
import ming_sim.simulation as simulation
from ming_sim.db import GameDB
from ming_sim import issues as issues_mod
from ming_sim.issues import apply_score_extraction, apply_issue_tracker_output
from ming_sim.public_sayings import list_public_sayings, record_public_saying
from tests.test_declaration_dispatch_1835 import _minister



NINGYUAN = "宁远护送"
ORIGIN = "拨银、调将、派兵去宁远"
PROGRESS = "护送银两已出京，尚未抵宁远"


def _declaration(*, attach="new", birth_key="", affair_id=None, identity=""):
    body = {"attach": attach}
    if attach == "new":
        body["name"] = NINGYUAN
        body["origin"] = ORIGIN
        if birth_key:
            body["birth_key"] = birth_key
        if identity:
            body["identity"] = identity
    else:
        body["affair_id"] = int(affair_id)
    return body






def test_conflicting_affair_declaration_on_existing_dossier_fails_loud(game):
    db, state, _ = game
    minister = _minister(db)
    pending_id = 91002
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    other = db.affairs.open(
        name="另事", origin="另一件交办",
        year=state.year, period=state.period, turn=state.turn,
    )
    db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="调洪承畴赴宁远",
        target_kind="issue",
        target_id="ningyuan-general",
        executor_kind="character",
        executor_id=minister,
        pending_action_id=pending_id,
        payload={
            "assignee_id": minister,
            "affair_declaration": _declaration(attach="existing", affair_id=first.id),
        },
    )
    before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    with pytest.raises(ValueError):
        db.create_decree_dossiers(
            state,
            action_type="assignment",
            decree_text="调洪承畴赴宁远",
            target_kind="issue",
            target_id="ningyuan-general",
            executor_kind="character",
            executor_id=minister,
            pending_action_id=pending_id,
            payload={
                "assignee_id": minister,
                "affair_declaration": _declaration(
                    attach="existing", affair_id=other.id,
                ),
            },
        )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before




def test_same_name_affairs_are_not_merged_and_illegal_attach_is_rejected(game):
    """Same display name does not merge; illegal attach enum/ref fails loud and does not write.

    Keeps generic create_decree_dossiers negative only — no exclusive retired-close proof (F44).
    """
    db, state, _ = game
    minister = _minister(db)
    first = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    second = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    assert first.id != second.id
    before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    with pytest.raises(ValueError):
        db.create_decree_dossiers(
            state,
            action_type="assignment",
            decree_text="调洪承畴赴宁远",
            target_kind="issue",
            target_id="ningyuan-general",
            executor_kind="character",
            executor_id=minister,
            payload={
                "assignee_id": minister,
                "affair_declaration": _declaration(attach="close", affair_id=first.id),
            },
        )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == before
    assert db.affairs.get(first.id).status == "open"






def test_typed_affair_new_issues_share_provenance(game):
    db, state, content = game
    existing = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    result = apply_score_extraction(
        db, state,
        {
            "new_issues": [
                {
                    "origin_kind": "decree", "kind": "situation",
                    "title": "护送仍在途中",
                    "affair_declaration": _declaration(
                        attach="existing", affair_id=existing.id,
                    ),
                },
                {
                    "origin_kind": "decree", "kind": "situation",
                    "title": "推演另起风波",
                    "affair_declaration": _declaration(identity="new-storm"),
                },
            ],
        },
        content=content, open_affair_ids_at_input={existing.id},
    )
    created = result["issue_summary"]["new_issues"]
    assert [item["rejected"] for item in created] == [False, False]
    assert db.affairs.affair_id_for_issue(created[0]["issue_id"]) == existing.id
    assert db.affairs.affair_id_for_issue(created[1]["issue_id"]) != existing.id
    assert db.affairs.get(existing.id).status == "open"




def test_strategic_event_unauthorized_person_origin_reaches_final_projection(game):
    """战略人物越权来源逐项拒收；已声明的合法同批战果仍落账。"""
    db, state, content = game
    issues_mod.bind_content(content)
    state.year = 1638
    state.period = 9
    authorized = db.affairs.open(
        name=NINGYUAN, origin=ORIGIN,
        year=state.year, period=state.period, turn=state.turn,
    )
    db.conn.execute(
        "UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"),
    )
    db.conn.execute(
        "UPDATE characters SET status = ? WHERE name = ?", ("active", "卢象升"),
    )
    from ming_sim.month_translate import dispatch_month_segment

    def translate(_request, _config):
        # Appears after the translation input's visible references are frozen.
        unauthorized = db.affairs.open(
            name="另事", origin="另一件交办",
            year=state.year, period=state.period, turn=state.turn,
        )
        return {"effects": [{
            "event_id": "wuyin_lubian",
            "new_issues": [{"origin_kind": "event_pool", "id": "wuyin_lubian"}],
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发",
                    "military_pressure": 15,
                    "reason": "戊寅虏变软判畿南受压",
                },
            },
            "人物变更": [{
                "name": "卢象升",
                "动作": "处置",
                "status": "dead",
                "origin_ref": db.affairs.origin_ref(unauthorized.id),
                "reason": "戊寅虏变软判主帅功过",
            }],
        }]}

    dispatch_month_segment(db, state, segment="戊寅虏变战果", translate_fn=translate)
    assert db.has_event_triggered("wuyin_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",),
    ).fetchone()["military_pressure"] == 35
    assert db.conn.execute(
        "SELECT status FROM characters WHERE name = ?", ("卢象升",),
    ).fetchone()["status"] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM rejection_reports WHERE section='applied_person_changes' "
        "AND category='unauthorized_affair_origin'"
    ).fetchone()[0] == 1


def test_new_issue_affair_attach_failure_leaves_no_partial_product(game, monkeypatch):
    db, state, _ = game
    issues_before = db.conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"]
    affairs_before = db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"]
    pointers_before = db.conn.execute(
        "SELECT COUNT(*) AS n FROM issues WHERE affair_id > 0",
    ).fetchone()["n"]

    def boom(*_a, **_k):
        raise RuntimeError("attach boom")

    monkeypatch.setattr(db.affairs, "attach_from_declaration", boom)
    with pytest.raises(RuntimeError):
        apply_issue_tracker_output(
            db, state,
            {"new_issues": [{
                "origin_kind": "decree",
                "kind": "situation",
                "title": "原子落库",
                "affair_declaration": _declaration(identity="atomic-issue"),
            }]},
        )
    assert db.conn.execute("SELECT COUNT(*) AS n FROM issues").fetchone()["n"] == issues_before
    assert db.conn.execute("SELECT COUNT(*) AS n FROM affairs").fetchone()["n"] == affairs_before
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM issues WHERE affair_id > 0",
    ).fetchone()["n"] == pointers_before
