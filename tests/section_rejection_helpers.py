"""拒收段集成测的薄夹具。

#1843：只经现役声明分发入口及拒收账查询。
"""

from __future__ import annotations


# game：conftest 已改为方案 (c) session 模板 + 每案文件拷贝（#1233）。
# 本模块不再维护平行 module-cache 池；re-export 供既有
# ``from tests.section_rejection_helpers import game`` 消费方零改 import。
from tests.conftest import game as game  # noqa: F401

def default_settlement_attendant_runner(*, year, period, rejections):
    del year, period
    return "递话" if rejections else ""


def install_settlement_attendant_agent_stub(
    monkeypatch, decree_mod, *, text="递话", capture=None,
):
    """#1871：代码触发递话 agent 已删；旧调用点保留 no-op，runner 形参仍由 #1843 承接。"""
    del monkeypatch, decree_mod, text, capture


def run_declaration(db, state, content, raw_delta, *, narrative="", decree_text=""):
    """Enter the current fiscal bracket and atomically dispatch a month declaration."""
    del narrative, decree_text
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import dispatch_declaration
    from ming_sim.decree import pre_settle
    from tests.conftest import with_monthly_reports

    pre_settle(state, db, content=content)
    return dispatch_declaration(
        db, state, {"effects": with_monthly_reports(db, raw_delta)},
        source=Provenance.player_decree,
    )


def rejection_rows(db, turn, section=None, *, columns="section, reason, category, source"):
    query = f"SELECT {columns} FROM rejection_reports WHERE turn=?"
    params: list = [turn]
    if section is not None:
        query += " AND section=?"
        params.append(section)
    return db.conn.execute(query + " ORDER BY id", params).fetchall()
