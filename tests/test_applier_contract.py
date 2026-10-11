from __future__ import annotations

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
    db.conn.execute("DROP TABLE IF EXISTS rejection_reports")
    return game


# ---------------------------------------------------------------------------
# RejectionCollector — mirror_to_jsonl
# ---------------------------------------------------------------------------

def test_mirror_to_jsonl_appends_on_multiple_calls(game, tmp_path):
    """多次「flush→commit→mirror」批次追加而不覆盖。"""
    db, state, content = game
    out = str(tmp_path / "rejections.jsonl")
    for turn in (1, 2):
        rc = RejectionCollector()
        ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
        rc.record("metric_delta", ri, turn=turn)
        rc.flush_to_db(db)
        db.conn.commit()
        rc.mirror_to_jsonl(out)

    lines = open(out, encoding="utf-8").readlines()
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# RejectionCollector — 规定调用序生命周期（cmr S0 r1 F1，3/3 共识）
# ADR 0008 决定 5：flush 在事务内（随回滚）；mirror 仅在 commit 成功后。
# ---------------------------------------------------------------------------


def test_mirror_idempotent_after_flush(clean_rejections, tmp_path):
    """commit 后同一批行 mirror 两次只写一次（已镜像的行不重复 append）。"""
    db, state, content = clean_rejections
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source=Provenance.unknown)
    rc.record("metric_delta", ri, turn=1)
    rc.flush_to_db(db)
    db.conn.commit()

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


def test_record_rejects_unknown_source_string():
    """source 传非法字符串响亮报错（fail-loud，不静默落非法值）。"""
    rc = RejectionCollector()
    ri = RejectedItem(item={}, reason="r", category="invalid_enum", source="not_a_provenance")
    with pytest.raises(ValueError):
        rc.record("metric_delta", ri, turn=1)
