from __future__ import annotations

import pytest

from ming_sim.db import GameDB
from ming_sim.relations import EMPEROR_NODE, credit_events_as_edges


def test_directed_edge_events_are_stored_and_queryable(game):
    db, state, _ = game

    forward_id = db.record_relation_edge_event(
        source="毕自严",
        target="王绍徽",
        event_kind="站台",
        context="毕自严当面替王绍徽担名。",
        origin="audience:turn-1:round-2",
        turn=state.turn,
    )
    reverse_id = db.record_relation_edge_event(
        source="王绍徽",
        target="毕自严",
        event_kind="使绊",
        context="王绍徽随后反过来截断毕自严的路。",
        origin="audience:turn-1:round-3",
        turn=state.turn,
    )

    assert forward_id != reverse_id
    assert [row["source"] for row in db.get_relation_edge_events(source="毕自严", target="王绍徽")] == ["毕自严"]
    assert db.get_relation_edge_events(source="王绍徽", target="毕自严")[0]["target"] == "毕自严"
    assert db.get_relation_edge_events(source="毕自严", target="王绍徽")[0]["origin_round"] == 2
    assert db.get_relation_edge_events(source="王绍徽", target="毕自严")[0]["origin_round"] == 3


def test_edge_event_kind_and_evidence_are_fail_closed(game):
    db, state, _ = game

    with pytest.raises(ValueError, match="未知边事件类目"):
        db.record_relation_edge_event(
            source="甲",
            target="乙",
            event_kind="擅自发明的类目",
            context="不应入账",
            origin="test:unknown",
            turn=state.turn,
        )

    with pytest.raises(ValueError, match="evidence"):
        db.record_relation_edge_event(
            source="甲",
            target="乙",
            event_kind="把柄",
            context="结构化把柄",
            origin="seed:case",
            turn=state.turn,
            evidence="yes",
        )

    row_id = db.record_relation_edge_event(
        source="甲",
        target="乙",
        event_kind="把柄",
        context="结构化把柄",
        origin="seed:case",
        turn=state.turn,
        evidence=True,
    )
    row = db.get_relation_edge_events()[0]
    assert row["id"] == row_id
    assert row["evidence"] is True
    assert "round:" in row["origin"]


def test_credit_contract_fixture_reads_as_semantic_directed_edges():
    fixture = [
        {
            "person": "杨嗣昌",
            "event_kind": "知遇",
            "context": "越次简拔，命其入阁。",
            "origin": "credit:fixture:知遇",
            "turn": 4,
        },
        {
            "person": "毕自严",
            "event_kind": "辜负",
            "context": "帝面却毕自严泣血之谏。",
            "origin": "credit:fixture:辜负",
            "turn": 5,
        },
    ]

    edges = credit_events_as_edges(fixture)

    assert (edges[0]["source"], edges[0]["target"]) == (EMPEROR_NODE, "杨嗣昌")
    assert (edges[1]["source"], edges[1]["target"]) == ("毕自严", EMPEROR_NODE)
    assert all(edge["event_kind"] in {"知遇", "辜负"} for edge in edges)


def test_relation_edges_survive_restore(game, tmp_path):
    db, state, content = game
    db.record_relation_edge_event(
        source="杨嗣昌",
        target="徐光启",
        event_kind="协作",
        context="二人当面相发明。",
        origin="audience:turn-1:round-7",
        turn=state.turn,
    )
    path = db.path
    db.close()

    restored = GameDB(path, content)
    try:
        rows = restored.get_relation_edge_events(source="杨嗣昌", target="徐光启")
        assert len(rows) == 1
        assert rows[0]["context"] == "二人当面相发明。"
        assert rows[0]["origin_round"] == 7
    finally:
        restored.close()
