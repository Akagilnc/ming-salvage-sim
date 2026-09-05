"""Shared setup seam for rejection-section integration tests."""

from __future__ import annotations

# game：conftest 已改为方案 (c) session 模板 + 每案文件拷贝（#1233）。
# 本模块不再维护平行 module-cache 池；re-export 供既有
# ``from tests.section_rejection_helpers import game`` 消费方零改 import。
from tests.conftest import game as game  # noqa: F401


def _default_settlement_attendant_runner(*, year, period, rejections):
    """#1745：driver 不再默认零宽桩；测试注入真实非空文本，不锁措辞。"""
    del year, period
    return "递话" if rejections else ""


def prepare_then_settle(db, state, content, raw_delta, **kwargs):
    """Test glue: explicit driver prepare → settle (not a production one-shot rail)."""
    from driver import run_prepare, run_settle

    prep_kw = {}
    if "registry" in kwargs:
        prep_kw["registry"] = kwargs["registry"]
    if "source" in kwargs:
        prep_kw["source"] = kwargs["source"]
    run_prepare(db, state, content, **prep_kw)
    from tests.conftest import with_monthly_reports
    settle_kw = dict(kwargs)
    # 玩家来源拒收须经 runner；未显式注入时给结构化边界桩（非生产零宽）。
    settle_kw.setdefault(
        "settlement_attendant_runner", _default_settlement_attendant_runner,
    )
    return run_settle(
        db, state, content, with_monthly_reports(db, raw_delta), **settle_kw,
    )


def rejection_rows(db, turn, section=None, *, columns="section, reason, category, source"):
    query = (
        f"SELECT {columns} FROM rejection_reports"
        " WHERE turn=?"
    )
    params = [turn]
    if section is not None:
        query += " AND section=?"
        params.append(section)
    return db.conn.execute(query + " ORDER BY id", params).fetchall()
