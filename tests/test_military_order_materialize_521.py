"""#521 军令·调遣：候选→收夜案卷→0055 判后 station/office/due_turn。

Seams:
- commit_pending_actions（收夜落案卷，不成 station/office 效果）
- apply_dossier_verdicts（0055 顺颁才落 army 写核 / 人物变更核 / due_turn）
- reload_state_from_db（只读 DB 无损接续）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    cluster_by_kind,
)
from ming_sim.decree import reload_state_from_db
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict




def _active_ming(db, content, *, exclude=""):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )


def _army_row(db, army_id):
    return db.conn.execute(
        "SELECT * FROM armies WHERE id=?", (army_id,),
    ).fetchone()


def _army_count(db):
    return int(db.conn.execute("SELECT COUNT(*) AS n FROM armies").fetchone()["n"])




def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


# ── catalog 挂点 ──────────────────────────────────────────────────────




# ── 三锚例顺颁 ────────────────────────────────────────────────────────








# ── 各自负例 ──────────────────────────────────────────────────────────






def test_deadline_sortie_without_future_due_fails_at_admission(game):
    """负例3：限期出战缺未来 due_turn → 成案失败，零效果。"""
    db, state, content = game
    army_id = "guanning"
    old_station = str(_army_row(db, army_id)["station"])
    actor = _active_ming(db, content)
    # 直接 stage 缺期限的军令候选（绕过 classifier 默认 deadline）
    pending_id = db.stage_directive_candidate(state.turn, actor.name, {
        "text": "着即日出战。",
        "actor": actor.name,
        "dossier_action_type": "military_order",
        "target_kind": "army",
        "target_id": army_id,
        "assignee": actor.name,
        # 无 due_turn / deadline_months
    })
    db.commit_pending_actions(
        state, content=content, action_ids=[pending_id], directive_status="draft",
    )
    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        d["pending_action_id"] == pending_id for d in db.list_decree_dossiers()
    )
    assert str(_army_row(db, army_id)["station"]) == old_station


# ── #521 r1：无期限调驻/移镇成案 + 同站 noop ───────────────────────────








# ── 打回零效果 ────────────────────────────────────────────────────────




# ── 正常/无诏结算 + restore ──────────────────────────────────────────






# ── #521 r2：成案前军队存在 / 同军独立候选 / 分类契约 / 复杂度 ──────────


def _military_pending_payloads(db, turn, *, target_id):
    rows = []
    for row in db.list_pending_actions(int(turn)):
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "military_order":
            continue
        if str(payload.get("target_id") or "").strip() != target_id:
            continue
        rows.append((int(row["id"]), payload))
    return rows


def _military_field_zh(field_name: str) -> str:
    cluster = cluster_by_kind("military_order")
    assert cluster is not None
    for field in cluster.fields:
        if field.name == field_name:
            return field.zh
    raise AssertionError(f"military_order FieldSpec 缺少 {field_name}")


def test_fake_army_deadline_sortie_rejected_at_admission(game):
    """虚假 army id 催战：admission 成案前拒绝，不得进 proposed/executing。"""
    db, state, content = game
    fake_army = "no_such_army_521"
    assert _army_row(db, fake_army) is None
    actor = _active_ming(db, content)
    armies_before = _army_count(db)

    pending_id = db.stage_directive_candidate(state.turn, actor.name, {
        "text": f"着{actor.name}督{fake_army}三月内出战。",
        "actor": actor.name,
        "dossier_action_type": "military_order",
        "target_kind": "army",
        "target_id": fake_army,
        "assignee": actor.name,
        "due_turn": state.turn + 3,
    })
    db.commit_pending_actions(
        state, content=content, action_ids=[pending_id], directive_status="draft",
    )
    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert pending["status"] == "failed"
    assert not any(
        d["pending_action_id"] == pending_id for d in db.list_decree_dossiers()
    )
    assert _army_count(db) == armies_before








def test_multi_draft_schema_example_uses_army_target_kind_for_military_order():
    """多旨稿 schema 示例：military_order 的目标类型须为 army（与票面一致）。"""
    import inspect

    import ming_sim.cli_backend as cli_backend

    source = inspect.getsource(cli_backend.extract_draft_intent)
    assert '"动作类型":"military_order","目标类型":"army"' in source.replace(" ", ""), (
        "多旨稿 schema 示例须写目标类型=army，不得 region"
    )
    assert '"动作类型":"military_order","目标类型":"region"' not in source.replace(" ", "")


def test_apply_military_order_verdict_effect_within_line_limit():
    """_apply_military_order_verdict_effect 本体 ≤100 行（职责拆到辅助单元）。"""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("ming_sim/db.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if (
                isinstance(item, ast.FunctionDef)
                and item.name == "_apply_military_order_verdict_effect"
            ):
                n = item.end_lineno - item.lineno + 1
                assert n <= 100, f"_apply_military_order_verdict_effect 仍超上限：{n} 行"
                return
    raise AssertionError("未找到 _apply_military_order_verdict_effect")
