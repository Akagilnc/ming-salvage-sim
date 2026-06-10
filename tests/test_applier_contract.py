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


def test_rejected_item_constructs_with_fields():
    """四字段按名构造可读（非 frozen，可变性不在契约内）。"""
    ri = RejectedItem(
        item={}, reason="test", category="invalid_enum", source=Provenance.unknown
    )
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

@pytest.fixture
def clean_rejections(game):
    """game 基底是活存档 probe.db 副本——真实游玩可能已写入 rejection_reports。

    收集器测试用绝对计数断言，必须从已知空表起步（cmr S0 r2 C-R2）。
    """
    db, state, content = game
    db.conn.execute("DROP TABLE IF EXISTS rejection_reports")
    return game


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

def test_rejection_collector_flush_before_record_leaves_db_empty(clean_rejections):
    """flush 前 DB 中无 rejection_reports 行。"""
    db, state, content = clean_rejections
    rc = RejectionCollector()
    rc.flush_to_db(db)
    count = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    assert count == 0


def test_rejection_collector_flush_writes_rows(clean_rejections):
    """record 两项后 flush_to_db，DB 落 2 行，字段内容正确。"""
    db, state, content = clean_rejections
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


def test_rejection_collector_flush_clears_buffer(clean_rejections):
    """flush 后缓冲清空，再次 flush 不写新行。"""
    db, state, content = clean_rejections
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=state.turn)
    rc.flush_to_db(db)
    rc.flush_to_db(db)  # 第二次 flush 缓冲已空
    count = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    assert count == 1  # 只有第一次 flush 的 1 行


def test_rejection_collector_flush_stores_item_as_json(clean_rejections):
    """原 item dict 以 JSON 字符串存入 DB，可反序列化。"""
    db, state, content = clean_rejections
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

def test_mirror_to_jsonl_writes_lines(game, tmp_path):
    """flush 后 mirror_to_jsonl 把已落库行 append 为 jsonl 行。"""
    db, state, content = game
    rc = RejectionCollector()
    ri = RejectedItem(
        item={"id": "ghost"}, reason="不存在", category="hallucinated_id", source=Provenance.unknown
    )
    rc.record("army_delta", ri, turn=5)
    rc.flush_to_db(db)

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)

    lines = open(out, encoding="utf-8").readlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["section"] == "army_delta"
    assert row["turn"] == 5
    assert row["category"] == "hallucinated_id"
    assert json.loads(row["item_json"]) == {"id": "ghost"}


def test_mirror_to_jsonl_appends_on_multiple_calls(game, tmp_path):
    """多次「flush→mirror」批次追加而不覆盖。"""
    db, state, content = game
    out = str(tmp_path / "rejections.jsonl")
    for turn in (1, 2):
        rc = RejectionCollector()
        ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
        rc.record("metric_delta", ri, turn=turn)
        rc.flush_to_db(db)
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


# ---------------------------------------------------------------------------
# RejectionCollector — 规定调用序生命周期（cmr S0 r1 F1，3/3 共识）
# ADR 0008 决定 5：flush 在事务内（随回滚）；mirror 仅在 commit 成功后。
# ---------------------------------------------------------------------------

def test_flush_then_mirror_writes_jsonl(clean_rejections, tmp_path):
    """规定调用序 record → flush(事务内) → commit → mirror：jsonl 必须有行。

    回归 cmr S0 r1 F1：flush 清缓冲导致 commit 后 mirror 静默写零行。
    """
    db, state, content = clean_rejections
    rc = RejectionCollector()
    ri = RejectedItem(
        item={"id": "ghost"}, reason="不存在", category="hallucinated_id",
        source=Provenance.system_simulation,
    )
    rc.record("army_delta", ri, turn=7)
    rc.flush_to_db(db)
    db.conn.commit()

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)

    lines = open(out, encoding="utf-8").readlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["section"] == "army_delta"
    assert row["turn"] == 7


def test_mirror_idempotent_after_flush(clean_rejections, tmp_path):
    """同一批行 mirror 两次只写一次（已镜像的行不重复 append）。"""
    db, state, content = clean_rejections
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)
    rc.mirror_to_jsonl(out)

    lines = open(out, encoding="utf-8").readlines()
    assert len(lines) == 1


def test_unflushed_rows_never_mirrored(tmp_path):
    """未 flush（未进 DB）的行不进 jsonl——回滚时这些行会消失，镜像它们=孤立行。"""
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)

    import os
    assert not os.path.exists(out)


def test_reset_discards_pending_and_flushed(clean_rejections, tmp_path):
    """reset()（回滚路径）丢弃缓冲与已 flush 快照，之后 flush/mirror 均无输出。"""
    db, state, content = clean_rejections
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)
    rc.record("army_delta", ri, turn=1)

    rc.reset()

    rc.flush_to_db(db)  # 缓冲已空，不再写行
    count = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    assert count == 1  # 只有 reset 前那次 flush 的 1 行（DB 回滚由事务层负责，非 reset 职责）

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)
    import os
    assert not os.path.exists(out)


def test_record_accepts_plain_string_source(clean_rejections):
    """source 传普通字符串不崩（运行时不查注解），落库归一为枚举值字符串。

    回归 cmr S0 r1 F3：rejected_item.source.value 对 str 抛 AttributeError。
    """
    db, state, content = clean_rejections
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source="player_decree")
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)
    src = db.conn.execute("SELECT source FROM rejection_reports").fetchone()[0]
    assert src == "player_decree"


def test_record_rejects_unknown_source_string():
    """source 传非法字符串响亮报错（fail-loud，不静默落非法值）。"""
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source="not_a_provenance")
    with pytest.raises(ValueError):
        rc.record("metric_delta", ri, turn=1)


# ---------------------------------------------------------------------------
# 环境不变式 pin（cmr S0 r2）
# ---------------------------------------------------------------------------

def test_collector_counts_deterministic_on_polluted_save(game):
    """活存档已带 rejection_reports 行时，clean 起步后计数仍确定（cmr S0 r2 C-R2）。

    模拟「真实游玩写入拒收行后的 probe.db」：先污染再清场，断言计数从 0 起。
    """
    db, state, content = game
    rc0 = RejectionCollector()
    ri = RejectedItem(item={}, reason="既有行", category="invalid_enum", source=Provenance.unknown)
    rc0.record("army_delta", ri, turn=3)
    rc0.flush_to_db(db)
    db.conn.commit()  # 污染已提交，等价于游玩过的存档

    db.conn.execute("DROP TABLE IF EXISTS rejection_reports")  # clean_rejections 同款清场

    rc = RejectionCollector()
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)
    count = db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0]
    assert count == 1


def test_ddl_in_open_transaction_rolls_back(game):
    """CREATE TABLE 在打开的事务内不隐式 commit，且随 rollback 撤销。

    S1 事务包裹依赖此行为（flush_to_db 的建表在事务中段执行）。
    实证基线 python3.14.5/sqlite3.53.1；环境回归此处先咬。
    """
    db, state, content = game
    db.conn.execute("DROP TABLE IF EXISTS rejection_reports")
    db.conn.commit()

    db.conn.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES ('ddl_pin_probe', '1')")
    assert db.conn.in_transaction
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)  # 事务中段建表+写行
    assert db.conn.in_transaction  # DDL 没有隐式 commit

    db.conn.rollback()
    tbl = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE name='rejection_reports'"
    ).fetchone()
    assert tbl is None  # 建表本身随事务回滚
