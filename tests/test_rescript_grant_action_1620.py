"""#1620：票拟生成契约产 canonical grant_action；禁同义动作 alias。"""

from __future__ import annotations

import pytest

from ming_sim.action_materialize import GRANT_ACTIONS
from ming_sim.rescript_draft import (
    build_rescript_draft_payload,
    normalize_rescript_layer_a_option,
)


def _base_grant_option(**extra):
    opt = {
        "label": "补饷关宁",
        "hint": "边饷急",
        "action_type": "grant_allocation",
        "assignee_name": "",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "grant_action": "协饷",
        "amount": 300,
        "account": "国库",
        "purpose": "补饷",
    }
    opt.update(extra)
    return opt


def test_rescript_payload_exposes_canonical_grant_actions(game):
    """生成契约 payload 注入 GRANT_ACTIONS 闭集（与 Layer-A 同源）。"""
    db, state, _content = game
    payload = build_rescript_draft_payload(
        state,
        narrative="本月邸报：关宁欠饷。",
        simulator_payload={"active_issues": [], "regions": None, "armies": None},
        triage_actor={"name": "韩爌", "office": "首辅", "faction": ""},
    )
    actions = payload.get("grant_actions")
    assert isinstance(actions, list)
    expected = sorted(GRANT_ACTIONS - {"无"})
    assert actions == expected
    assert "协饷" in actions
    assert "补发军饷" not in actions


def test_layer_a_accepts_canonical_xiexang_rejects_synonym():
    """typed canonical 协饷过层 A；冻结同义「补发军饷」仍拒（无 alias/parser）。"""
    ok = normalize_rescript_layer_a_option(_base_grant_option())
    assert ok["grant_action"] == "协饷"
    assert int(ok["amount"]) == 300
    assert str(ok.get("account") or "") == "国库"

    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option(_base_grant_option(grant_action="补发军饷"))
