"""#1853 J8-R2：成功构造后必备 GameDB 能力不得靠 AttributeError 软兼容。

判定：缺 conn / 缺 resolve_revoke_decree_target_ids 时必须响亮失败，
不得洗成 None / False / {}。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ming_sim.knowledge import _household_ledger, knowledge_row_visible_to
from ming_sim.materials import revoke_target_facts


class _DbMissingConn:
    """有知识辅助方法、却缺必备 conn——模拟「持有 db 但能力缺失」。"""

    def knowledge_exclusions_for_source(self, _source_id):
        return []

    def knowledge_exclusion_targets_for_source(self, _source_id):
        return {}


def test_knowledge_row_visible_to_raises_when_conn_capability_missing():
    db = _DbMissingConn()
    row = {"source_id": "s1", "kind": "public", "excluded_names": "[]", "excluded_targets": "{}"}
    with pytest.raises(AttributeError):
        knowledge_row_visible_to(db, row, "孙承宗")


def test_household_ledger_raises_when_conn_capability_missing():
    db = _DbMissingConn()
    state = SimpleNamespace(metrics={"国库": 0})
    with pytest.raises(AttributeError):
        _household_ledger(db, state, "孙承宗")


def test_revoke_target_facts_raises_when_resolve_method_missing():
    db = SimpleNamespace()  # 无 resolve_revoke_decree_target_ids
    with pytest.raises(AttributeError):
        revoke_target_facts(db, {"revoke_target_dossier_id": 1})
