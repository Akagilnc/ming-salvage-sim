"""Shared setup seam for rejection-section integration tests."""

from __future__ import annotations

# game：conftest 已改为方案 (c) session 模板 + 每案文件拷贝（#1233）。
# 本模块不再维护平行 module-cache 池；re-export 供既有
# ``from tests.section_rejection_helpers import game`` 消费方零改 import。
from tests.conftest import game as game  # noqa: F401


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
