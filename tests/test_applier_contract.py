"""S0 — ming_sim/applier.py 契约类型骨架测试。

覆盖：Provenance 枚举 / RejectedItem / SectionResult 聚合 / ApplyContext /
RejectionCollector 缓冲→flush_to_db / mirror_to_jsonl。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.applier import ApplyContext, Provenance, RejectedItem, RejectionCollector, SectionResult


def test_provenance_enum_values():
    """五个成员值与字符串标识一致（ADR 0008 决定 5）。"""
    assert Provenance.player_decree.value == "player_decree"
    assert Provenance.hitl_decision.value == "hitl_decision"
    assert Provenance.secret_order.value == "secret_order"
    assert Provenance.system_simulation.value == "system_simulation"
    assert Provenance.unknown.value == "unknown"


def test_provenance_from_string():
    """可按字符串反查成员。"""
    assert Provenance("player_decree") is Provenance.player_decree
    assert Provenance("system_simulation") is Provenance.system_simulation


# ---------------------------------------------------------------------------
# RejectedItem
# ---------------------------------------------------------------------------

def test_rejected_item_fields():
    """RejectedItem 持 item/reason/category/source 四字段。"""
    raw = {"id": "fake_army", "manpower": 5000}
    ri = RejectedItem(
        item=raw,
        reason="id 不在军队表",
        category="hallucinated_id",
        source=Provenance.system_simulation,
    )
    assert ri.item is raw
    assert ri.reason == "id 不在军队表"
    assert ri.category == "hallucinated_id"
    assert ri.source is Provenance.system_simulation


def test_rejected_item_is_immutable_by_default():
    """dataclass frozen=True 或至少字段存在——不要求 frozen，只验字段。"""
    ri = RejectedItem(
        item={}, reason="test", category="invalid_enum", source=Provenance.unknown
    )
    # 字段可读
    assert ri.category == "invalid_enum"


# ---------------------------------------------------------------------------
# SectionResult
# ---------------------------------------------------------------------------

def _make_ri(category="hallucinated_id") -> RejectedItem:
    return RejectedItem(item={}, reason="x", category=category, source=Provenance.unknown)


def test_section_result_holds_applied_and_rejected():
    """applied 为任意列表，rejected 为 RejectedItem 列表。"""
    r = SectionResult(applied=["a", "b"], rejected=[_make_ri()])
    assert len(r.applied) == 2
    assert len(r.rejected) == 1


def test_section_result_merge():
    """两个 SectionResult 聚合后 applied/rejected 各自拼接。"""
    a = SectionResult(applied=[1, 2], rejected=[_make_ri("hallucinated_id")])
    b = SectionResult(applied=[3], rejected=[_make_ri("invalid_enum"), _make_ri("missing_ref")])
    merged = a.merge(b)
    assert merged.applied == [1, 2, 3]
    assert len(merged.rejected) == 3


def test_section_result_merge_empty():
    """空 SectionResult 与非空合并，结果与非空相等。"""
    empty = SectionResult(applied=[], rejected=[])
    non_empty = SectionResult(applied=[42], rejected=[_make_ri()])
    assert empty.merge(non_empty).applied == [42]
    assert len(empty.merge(non_empty).rejected) == 1
    assert non_empty.merge(empty).applied == [42]


# ---------------------------------------------------------------------------
# ApplyContext
# ---------------------------------------------------------------------------

def test_apply_context_holds_all_fields(game):
    """ApplyContext 持 db/state/content/registry（可 None）+ source。"""
    db, state, content = game
    ctx = ApplyContext(db=db, state=state, content=content, registry=None, source=Provenance.player_decree)
    assert ctx.db is db
    assert ctx.state is state
    assert ctx.content is content
    assert ctx.registry is None
    assert ctx.source is Provenance.player_decree


# ---------------------------------------------------------------------------
# RejectionCollector — 缓冲与 flush
# ---------------------------------------------------------------------------

def test_rejection_collector_flush_before_record_leaves_db_empty(game):
    """flush 前 DB 中无 rejection_reports 行。"""
    db, state, content = game
    rc = RejectionCollector()
    rc.flush_to_db(db)
    count = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    assert count == 0


def test_rejection_collector_flush_writes_rows(game):
    """record 两项后 flush_to_db，DB 落 2 行，字段内容正确。"""
    db, state, content = game
    rc = RejectionCollector()

    ri1 = RejectedItem(
        item={"id": "ghost_army"},
        reason="军队 id 不存在",
        category="hallucinated_id",
        source=Provenance.system_simulation,
    )
    ri2 = RejectedItem(
        item={"faction": "???"},
        reason="派系枚举非法",
        category="invalid_enum",
        source=Provenance.player_decree,
    )
    rc.record("army_delta", ri1, turn=state.turn)
    rc.record("faction_delta", ri2, turn=state.turn)
    rc.flush_to_db(db)

    rows = db.conn.execute(
        "SELECT section, reason, category, source FROM rejection_reports ORDER BY rowid"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "army_delta"
    assert rows[0][1] == "军队 id 不存在"
    assert rows[0][2] == "hallucinated_id"
    assert rows[0][3] == "system_simulation"
    assert rows[1][0] == "faction_delta"
    assert rows[1][2] == "invalid_enum"


def test_rejection_collector_flush_clears_buffer(game):
    """flush 后缓冲清空，再次 flush 不写新行。"""
    db, state, content = game
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=state.turn)
    rc.flush_to_db(db)
    rc.flush_to_db(db)  # 第二次 flush 缓冲已空
    count = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    assert count == 1  # 只有第一次 flush 的 1 行


def test_rejection_collector_flush_stores_item_as_json(game):
    """原 item dict 以 JSON 字符串存入 DB，可反序列化。"""
    db, state, content = game
    rc = RejectionCollector()
    raw = {"id": "xyz", "manpower": 999}
    ri = RejectedItem(item=raw, reason="r", category="hallucinated_id", source=Provenance.unknown)
    rc.record("army_delta", ri, turn=1)
    rc.flush_to_db(db)

    item_json = db.conn.execute(
        "SELECT item_json FROM rejection_reports"
    ).fetchone()[0]
    assert json.loads(item_json) == raw


# ---------------------------------------------------------------------------
# RejectionCollector — mirror_to_jsonl
# ---------------------------------------------------------------------------

def test_mirror_to_jsonl_writes_lines(tmp_path):
    """mirror_to_jsonl 在显式调用时把缓冲 append 为 jsonl 行。"""
    rc = RejectionCollector()
    ri = RejectedItem(
        item={"id": "ghost"}, reason="不存在", category="hallucinated_id", source=Provenance.unknown
    )
    rc.record("army_delta", ri, turn=5)

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)

    lines = open(out, encoding="utf-8").readlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["section"] == "army_delta"
    assert row["turn"] == 5
    assert row["category"] == "hallucinated_id"
    assert json.loads(row["item_json"]) == {"id": "ghost"}


def test_mirror_to_jsonl_appends_on_multiple_calls(tmp_path):
    """多次调用 mirror_to_jsonl 追加而不覆盖（每次调用前 record 新项）。"""
    out = str(tmp_path / "rejections.jsonl")
    for turn in (1, 2):
        rc = RejectionCollector()
        ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
        rc.record("metric_delta", ri, turn=turn)
        rc.mirror_to_jsonl(out)

    lines = open(out, encoding="utf-8").readlines()
    assert len(lines) == 2


def test_mirror_to_jsonl_empty_buffer_writes_nothing(tmp_path):
    """缓冲为空时 mirror_to_jsonl 不创建文件（或文件存在则不追加行）。"""
    rc = RejectionCollector()
    out = str(tmp_path / "empty.jsonl")
    rc.mirror_to_jsonl(out)
    import os
    assert not os.path.exists(out)
