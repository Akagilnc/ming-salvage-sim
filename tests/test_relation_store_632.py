from __future__ import annotations

import sqlite3

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
            "event_kind": "兑现所托",
            "context": "奉诏清丈，按期复命。",
            "origin": "credit:fixture:兑现所托",
            "turn": 4,
        },
        {
            "person": "毕自严",
            "event_kind": "辜负",
            "context": "帝面却毕自严泣血之谏。",
            "origin": "credit:fixture:辜负",
            "turn": 5,
        },
        {
            "person": "王承恩",
            "event_kind": "撑腰",
            "context": "皇帝当面为王承恩挡下责难。",
            "origin": "credit:fixture:撑腰",
            "turn": 6,
        },
        {
            "person": "洪承畴",
            "event_kind": "弃卒保车",
            "context": "皇帝为保全大局弃置洪承畴。",
            "origin": "credit:fixture:弃卒保车",
            "turn": 7,
        },
        {
            "person": "徐光启",
            "event_kind": "知遇",
            "context": "越次简拔，命其入阁。",
            "origin": "credit:fixture:知遇",
            "turn": 8,
        },
    ]

    edges = credit_events_as_edges(fixture)

    assert [(edge["source"], edge["target"]) for edge in edges] == [
        ("杨嗣昌", EMPEROR_NODE),
        (EMPEROR_NODE, "毕自严"),
        (EMPEROR_NODE, "王承恩"),
        (EMPEROR_NODE, "洪承畴"),
        (EMPEROR_NODE, "徐光启"),
    ]
    assert [edge["event_kind"] for edge in edges] == [
        "兑现所托",
        "辜负",
        "撑腰",
        "弃卒保车",
        "知遇",
    ]


def test_relation_edges_survive_restore(game, tmp_path):
    """R1：边事件 + 关系摘要双表面经关闭重开逐字段一致（#642 扩摘要面）。"""
    db, state, content = game
    db.record_relation_edge_event(
        source="杨嗣昌",
        target="徐光启",
        event_kind="协作",
        context="二人当面相发明。",
        origin="audience:turn-1:round-7",
        turn=state.turn,
    )
    edge = db.get_relation_edge_events(source="杨嗣昌", target="徐光启")[0]
    db.apply_relation_brew_result(
        source="杨嗣昌", target="徐光启", dimension="大臣",
        founding_segment="徐杨相发明奠基。",
        recent_segment="协作在案。",
        last_event_id=int(edge["id"]),
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    summary = db.get_relation_summary("杨嗣昌", "徐光启")
    path = db.path
    db.close()

    restored = GameDB(path, content)
    try:
        rows = restored.get_relation_edge_events(source="杨嗣昌", target="徐光启")
        assert len(rows) == 1
        assert rows[0]["context"] == "二人当面相发明。"
        assert rows[0]["origin_round"] == 7
        for key in (
            "source", "target", "event_kind", "context", "origin",
            "year", "period", "turn",
        ):
            assert rows[0][key] == edge[key]
        summary2 = restored.get_relation_summary("杨嗣昌", "徐光启")
        for key in (
            "founding_segment", "recent_segment", "last_event_id",
            "last_brewed_year", "last_brewed_period", "dimension",
        ):
            assert summary2[key] == summary[key]
    finally:
        restored.close()


def test_distinct_pipe_origins_are_never_merged(game):
    """通用写口身份=精确 origin 全串（含 |round 后缀）+端点+类目+context。
    合法不同 origin（同端点/kind，首个 `|` 后非 round）各落一行，append-only
    真源不得静默吞并事件（#635 r2：荐人专属稳定 origin 判重归其 helper，
    不得扩权到全局写口）。"""
    db, state, _ = game
    first_id = db.record_relation_edge_event(
        source="毕自严", target="王绍徽", event_kind="站台",
        context="同一对端点的第一个独立事件。",
        origin="foo|a", turn=state.turn,
    )
    second_id = db.record_relation_edge_event(
        source="毕自严", target="王绍徽", event_kind="站台",
        context="同一对端点的第二个独立事件。",
        origin="foo|b", turn=state.turn,
    )
    assert first_id != second_id
    rows = db.get_relation_edge_events(source="毕自严", target="王绍徽")
    assert len(rows) == 2
    assert {row["origin"] for row in rows} == {"foo|a|round:%d" % int(state.turn),
                                                "foo|b|round:%d" % int(state.turn)}


def test_record_relation_edge_event_respects_caller_owned_transaction(game):
    """PR #804 P2:调用方已开事务时,record_relation_edge_event 不得提前 commit。

    原 bug:入口先调 load_state(),其末尾 self.conn.commit() 把调用方半成品落盘;
    入口自身尾部的 commit 守卫又漏判 conn.in_transaction。修复后两处都与
    owns_transaction() 一致——调用方回滚则入口写入一并消失,无半成品落盘。
    """
    db, state, _ = game
    db.conn.execute("DELETE FROM kv_store WHERE key='s1_rel_open'")
    db.conn.commit()
    # 调用方开事务(裸 DML → in_transaction True,非 atomic 暂停期)
    db.conn.execute("INSERT INTO kv_store(key,value) VALUES('s1_rel_open','half')")
    assert db.conn.in_transaction

    # 走新入口:原 bug 在 load_state() 处提前 commit,把 kv 半成品落盘
    db.record_relation_edge_event(
        source="甲",
        target="乙",
        event_kind="结怨",
        context="调用方持有事务时的边事件。",
        origin="audience:tx-probe",
    )
    assert db.conn.in_transaction  # 入口没提前 commit,事务仍由调用方持有

    # 抛错回滚:入口的 INSERT 与 kv 半成品一并消失
    db.conn.rollback()
    assert not db.conn.in_transaction
    assert db.kv_get("s1_rel_open") is None
    assert db.conn.execute(
        "SELECT id FROM relation_edge_events WHERE source='甲' AND target='乙'"
    ).fetchone() is None
    # 另开连接验真:磁盘上无半成品落盘
    other = sqlite3.connect(db.path)
    try:
        assert other.execute(
            "SELECT id FROM relation_edge_events WHERE source='甲' AND target='乙'"
        ).fetchone() is None
    finally:
        other.close()
