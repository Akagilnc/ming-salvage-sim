"""Shared setup seam for rejection-section integration tests."""

from __future__ import annotations

import json

# game：conftest 已改为方案 (c) session 模板 + 每案文件拷贝（#1233）。
# 本模块不再维护平行 module-cache 池；re-export 供既有
# ``from tests.section_rejection_helpers import game`` 消费方零改 import。
from tests.conftest import game as game  # noqa: F401


def default_settlement_attendant_runner(*, year, period, rejections):
    """#1745：settle 注入边界；真实非空文本，不锁措辞、非生产零宽。"""
    del year, period
    return "递话" if rejections else ""


# 旧名兼容
_default_settlement_attendant_runner = default_settlement_attendant_runner


def install_settlement_attendant_agent_stub(
    monkeypatch, decree_mod, *, text="递话", capture=None,
):
    """#1745：替身下移到真实 runner 的 agent 边界（不整换 run_settlement_attendant_message）。

    capture 若给出，追加生产事实包 rejections 列表（section/category/reason）。
    """
    class _Out:
        content = text

    class _Agent:
        def run(self, prompt):
            if capture is not None:
                payload = json.loads(prompt)
                capture.append(list(payload.get("rejections") or []))
            return _Out()

    monkeypatch.setattr(
        decree_mod,
        "create_settlement_attendant_agent",
        lambda *_a, **_k: _Agent(),
    )


def prepare_then_settle(db, state, content, raw_delta, **kwargs):
    """Test glue: explicit driver prepare → settle (not a production one-shot rail)."""
    from driver import run_prepare, run_settle as _drv_settle

    prep_kw = {}
    if "registry" in kwargs:
        prep_kw["registry"] = kwargs["registry"]
    if "source" in kwargs:
        prep_kw["source"] = kwargs["source"]
    run_prepare(db, state, content, **prep_kw)
    from tests.conftest import with_monthly_reports
    settle_kw = dict(kwargs)
    settle_kw.setdefault(
        "settlement_attendant_runner", default_settlement_attendant_runner,
    )
    return _drv_settle(
        db, state, content, with_monthly_reports(db, raw_delta), **settle_kw,
    )


def run_settle(db, state, content, raw_delta, **kwargs):
    """已 prepare 后的 driver settle；默认注入 attendant runner（#1745 测试入口）。"""
    from driver import run_settle as _drv_settle

    settle_kw = dict(kwargs)
    settle_kw.setdefault(
        "settlement_attendant_runner", default_settlement_attendant_runner,
    )
    return _drv_settle(db, state, content, raw_delta, **settle_kw)


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
