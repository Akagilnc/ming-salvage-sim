"""#1729 召对拟旨入口将受控 target 形态写回 canonical id。"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cli_backend
from ming_sim.matching import canonical_army_id_exact, canonical_region_id_exact
from ming_sim.session import GameSession


def _run_audience_draft(db, state, content, monkeypatch, *, message: str, canned: dict):
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "power_id", "ming") == "ming"
        and getattr(ch, "office_type", "") != "后宫"
        and db.get_character_status(ch.name)[0] == "active"
    )
    monkeypatch.setattr(
        cli_backend, "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(canned, ensure_ascii=False), 1),
    )
    session = types.SimpleNamespace(
        db=db, state=state, content=content,
        llm_config=types.SimpleNamespace(channel="cli"), registry=None,
    )
    return GameSession.apply_cli_conversation_actions(
        session, minister, player_message=message, answer="臣谨拟旨，请陛下裁可。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )


def _persisted_payload(db, pending_id: int) -> dict:
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert row is not None
    return json.loads(row["payload_json"])


@pytest.mark.parametrize(
    ("canonicalize", "raw"),
    [
        (canonical_region_id_exact, "京师赈务"),
        (canonical_region_id_exact, "请接济北直隶"),
        (canonical_army_id_exact, "请拨给关宁军"),
        (canonical_army_id_exact, "宁锦防线欠饷"),
    ],
)
def test_exact_target_canonicalizers_reject_prose(content, canonicalize, raw):
    """受控别名/命名空间不放宽 exact seam 为子串或散文匹配。"""
    entities = content.regions if canonicalize is canonical_region_id_exact else content.armies
    assert canonicalize(raw, entities) is None


@pytest.mark.parametrize(
    ("target_id", "region_id"),
    [
        ("京师", "京师"),
        ("北直隶", "北直隶"),
        ("北直隶 / 京师", "北直隶 / 京师"),
        ("京师", "@beizhili"),
    ],
)
def test_audience_region_draft_persists_canonical_target(
    game, monkeypatch, target_id, region_id,
):
    """真实召对拟旨→结构化暂存：region 两字段统一写 canonical id。"""
    db, state, content = game
    out = _run_audience_draft(
        db, state, content, monkeypatch,
        message="着南京户部尚书毕自严从内库拨银二十万两接济京师刚性支出。",
        canned={
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "目标类型": "region",
            "目标ID": target_id,
            "地区ID": region_id,
            "施行范围": "单省",
            "拨款动作": "发内帑",
            "金额": 20,
            "账户": "内库",
            "参与人": [],
        },
    )
    pending_id = int(out["pending_action_id"])
    payload = _persisted_payload(db, pending_id)
    assert payload["target_id"] == "beizhili"
    assert payload["region_id"] == "beizhili"


@pytest.mark.parametrize(
    "target_id", ["army.guanning", "guanning", "关宁军", "宁锦防线"],
)
def test_audience_army_pay_draft_persists_canonical_target(
    game, monkeypatch, target_id,
):
    """真实召对拟旨→结构化暂存：协饷 target 写 canonical army id。"""
    db, state, content = game
    out = _run_audience_draft(
        db, state, content, monkeypatch,
        message="从国库拨银十五万两协饷关宁军。",
        canned={
            "拟旨意图": "拟旨",
            "动作类型": "grant_allocation",
            "目标类型": "army",
            "目标ID": target_id,
            "施行范围": "无",
            "grant_action": "协饷",
            "amount": 15,
            "account": "国库",
            "purpose": "补饷",
            "参与人": [],
        },
    )
    pending_id = int(out["pending_action_id"])
    payload = _persisted_payload(db, pending_id)
    assert payload["target_id"] == "guanning"
