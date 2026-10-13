from __future__ import annotations
import json
import pytest
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector




# ---------------------------------------------------------------------------
# RejectionCollector fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_rejections(game):
    """game 基底是活存档 probe.db 副本——真实游玩可能已写入 rejection_reports。

    收集器测试用绝对计数断言，必须从已知空表起步（cmr S0 r2 C-R2）。
    """
    db, state, content = game
    db.conn.execute("DELETE FROM rejection_reports")
    return game


# ---------------------------------------------------------------------------
# RejectionCollector — mirror_to_jsonl
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RejectionCollector — 规定调用序生命周期（cmr S0 r1 F1，3/3 共识）
# ADR 0008 决定 5：flush 在事务内（随回滚）；mirror 仅在 commit 成功后。
# ---------------------------------------------------------------------------


def test_mirror_idempotent_after_flush(clean_rejections, tmp_path):
    """commit 后同一批行 mirror 两次只写一次（已镜像的行不重复 append）。"""
    db, state, content = clean_rejections
    rc = RejectionCollector()
    rc.flush_to_db(db)
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 0
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)
    rc.flush_to_db(db)
    assert db.conn.execute("SELECT COUNT(*) FROM rejection_reports").fetchone()[0] == 1
    db.conn.commit()

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)
    rc.mirror_to_jsonl(out)

    with open(out, encoding="utf-8") as fh:
        assert [(row["turn"], row["section"]) for row in map(json.loads, fh)] == [(1, "metric_delta")]
    rc.record("metric_delta", ri, turn=2)
    rc.flush_to_db(db)
    db.conn.commit()
    rc.mirror_to_jsonl(out)
    with open(out, encoding="utf-8") as fh:
        assert [(row["turn"], row["section"]) for row in map(json.loads, fh)] == [(1, "metric_delta"), (2, "metric_delta")]
    rc.record("metric_delta", ri, turn=3)
    rc.reset()
    rc.flush_to_db(db)
    rc.mirror_to_jsonl(out)
    assert [row["turn"] for row in db.conn.execute("SELECT turn FROM rejection_reports ORDER BY id")] == [1, 2]
    with open(out, encoding="utf-8") as fh:
        assert [(row["turn"], row["section"]) for row in map(json.loads, fh)] == [(1, "metric_delta"), (2, "metric_delta")]


def test_unflushed_rows_never_mirrored(tmp_path):
    """未 flush（未进 DB）的行不进 jsonl——回滚时这些行会消失，镜像它们=孤立行。"""
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)

    out = str(tmp_path / "rejections.jsonl")
    rc.mirror_to_jsonl(out)

    import os
    assert not os.path.exists(out)


def test_record_rejects_unknown_source_string():
    """source 传非法字符串响亮报错（fail-loud，不静默落非法值）。"""
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source="not_a_provenance")
    with pytest.raises(ValueError):
        rc.record("metric_delta", ri, turn=1)
