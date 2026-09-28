"""#529 / #471 S14 特旨/署理：对既有 pending 人事候选的路径应答。

Seams:
- ACTION_CLUSTERS appointment 行字段（任别 / mode / target_candidate）
- pending_actions(kind=office) 原地 payload 改写（0064 任别 / 0055·0056 中旨）
- 0035 故事账开放标签（关联候选 id）
- 0038 undo_chat_turn 前像回退
- 与 #528 委任授权分界（不入授权档）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import ming_sim.action_materialize  # noqa: F401 -- installs catalog
import ming_sim.audience_night as an
import ming_sim.cli_backend as cb
import pytest
from ming_sim.action_clusters import (
    candidates_from_classifier_payload,
    cluster_by_kind,
)




def _minister(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _other_minister(db, exclude: str) -> str:
    row = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type!='后宫' AND name!=? ORDER BY name LIMIT 1",
        (exclude,),
    ).fetchone()
    assert row is not None
    return str(row["name"])




def _office_pendings(db, turn):
    return [
        p for p in db.list_pending_actions(int(turn))
        if p.get("kind") == "office" and p.get("status") == "pending"
    ]


def _payload(db, pending_id):
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (int(pending_id),),
    ).fetchone()
    return json.loads(row["payload_json"])


def _ledger_tags(db, night_id):
    rows = db.conn.execute(
        "SELECT tags, body FROM story_ledger_entries WHERE night_id=? ORDER BY id",
        (int(night_id),),
    ).fetchall()
    out = []
    for r in rows:
        try:
            tags = json.loads(r["tags"] or "[]")
        except (TypeError, ValueError):
            tags = []
        out.append((tags if isinstance(tags, list) else [], str(r["body"] or "")))
    return out


# ── catalog 字段 ──────────────────────────────────────────────────────


def test_appointment_cluster_exposes_tenure_and_target_candidate():
    cluster = cluster_by_kind("appointment")
    assert cluster is not None
    names = {f.name for f in cluster.fields}
    assert "appointment_tenure" in names
    assert "target_candidate" in names
    assert "mode" in names


# ── beat 12→13 特旨原地改中旨 ─────────────────────────────────────────










# ── 多候选消歧 ────────────────────────────────────────────────────────












# ── no-op 去重与 fallback ─────────────────────────────────────────────












# ── 撤回前像 + restore ────────────────────────────────────────────────
