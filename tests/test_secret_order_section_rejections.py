from __future__ import annotations
from functools import partial
import json
import pytest
from tests.section_rejection_helpers import run_declaration as run_settle
from tests.section_rejection_helpers import rejection_rows
from tests.dossier_test_helpers import create_test_secret_order
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import view
"""secret_order 段拒收补精确 category（ADR 0008 决定 1 逐项拒收契约统一，#14 C2）。

updates 数据校验类拒收带精确 category（未知 order_id → missing_ref，坏值/非 active → invalid_enum）。

只覆盖 LLM 数据校验类拒收；落库真异常（except）的拒收不在此（属 #63.4 设计待定，不动）。
经现役原子声明入口查 rejection_reports。
"""






_rejection_rows = partial(rejection_rows, columns="section, reason, category")






@pytest.mark.parametrize("field,bad_note", [
    ("sim_note", {"bad": "x"}), ("result", ["a", 1]),
    ("sim_note", False), ("sim_note", 0),
])
def test_update_active_order_rejects_bad_prose_and_applies_valid_peer(game, field, bad_note):
    """Bad prose keeps its original value in rejection evidence; valid peers land."""
    db, state, content = game
    turn = state.turn
    oid = create_test_secret_order(db,
        state,
        "测试密令官",
        "合法更新正向守门",
        "先建 active 密令，再验证推演更新真实落库。",
        [],
        deadline_months=1,
    )

    bad_item = {"order_id": oid, field: bad_note}
    note = "推演副作用XYZ"
    result = run_settle(db, state, content, {
        "secret_order_updates": [bad_item, {"order_id": oid, "sim_note": note}],
    }, narrative="x", decree_text="y")

    assert [item["order_id"] for item in view(result.effects.applied[0], "secret_order_updates")] == [oid]
    rows = rejection_rows(db, turn, "secret_order_updates", columns="category, item_json")
    assert [row["category"] for row in rows] == ["invalid_shape"]
    assert json.loads(rows[0]["item_json"]) == bad_item
    dossier = db.dossiers.get_for_secret_order(oid)
    notes = db.conn.execute("SELECT * FROM dossier_actual_progress WHERE dossier_id=? ORDER BY turn, id", (int(dossier["id"]),)).fetchall()
    assert [(int(row["turn"]), row["note"]) for row in notes] == [(int(state.turn), note)]



@pytest.mark.parametrize("order_id,category", [("乙", "invalid_enum"), (999999, "missing_ref"), (10 ** 100, "invalid_enum")])
def test_invalid_secret_order_reference_rejected(game, order_id, category):
    db, state, content = game
    run_settle(db, state, content, {"secret_order_updates": [{"order_id": order_id, "sim_note": "坏引用"}]})
    rows = _rejection_rows(db, state.turn, "secret_order_updates")
    assert len(rows) == 1
    assert rows[0]["category"] == category


def test_settle_delta_secret_order_update_respects_outer_transaction_rollback(game):
    """post-merge CMR R8：secret_order_updates 不得绕过外层事务硬提交。"""
    db, state, content = game
    oid = create_test_secret_order(db, state, "测试密令官R8", "测试密令", "测试内容", [], deadline_months=1)
    db.conn.commit()

    db.conn.execute("BEGIN")
    out = settle_delta(state, db, {'secret_order_updates': [{'order_id': oid, 'sim_note': '测试密令副作用R8'}]}, SettlementContext(content=content))
    assert view(out, "secret_order_updates")[0]["order_id"] == oid
    dossier = db.dossiers.get_for_secret_order(oid)
    in_tx = db.conn.execute("SELECT * FROM dossier_actual_progress WHERE dossier_id=? ORDER BY turn, id", (int(dossier["id"]),)).fetchall()
    assert [item["note"] for item in in_tx] == ["测试密令副作用R8"]
    db.conn.rollback()

    row = db.character_knowledge.get_secret_order(oid)
    assert row is not None
    assert db.conn.execute("SELECT * FROM dossier_actual_progress WHERE dossier_id=? ORDER BY turn, id", (int(dossier["id"]),)).fetchall() == []
