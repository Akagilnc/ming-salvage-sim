"""#656 / ADR 0093 前半：急务分拣＋票拟生成（DECISION 通道＋邸报头版）。

覆盖票面修正案 r1-r3 的 F2（pending_decisions kind 扩列、事务序列、崩溃恢复不重跑、
跨月留存）与 F3（分拣人唯一规则、actor 身份随行落库、原样落库零扫描）。
并发 oracle（五路 barrier）见 test_rescript_fanout_656.py。
"""
from __future__ import annotations

import json

import pytest

from ming_sim.db import GameDB

_CANNED = '{"economy_moves": [], "new_armies": [], "new_issues": [], "secret_order_updates": []}'

# #1778 决定 3：生成批次的票拟必带参与名单（ADR 0053 三档，至少一名主办）。
_ROSTER = [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}]

def _army_pay_grant_option(**extra) -> dict:
    opt = {
        "label": "补发关宁军饷",
        "hint": "边饷急",
        "action_type": "grant_allocation",
        "assignee_name": "",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "grant_kind": "army_pay",
        "amount": 300,
        "account": "国库",
        "purpose": "补饷",
        "participant_roster": [dict(item) for item in _ROSTER],
    }
    opt.update(extra)
    return opt



def test_r3_strict_parse_control_char_raises_contract_error():
    """r3-2 strict 解析：含非法控制字符的 raw 不做清洗，直解失败抛 LLMContractError。"""
    from ming_sim.rescript_draft import _parse_rescript_json_strict
    from ming_sim.exceptions import LLMContractError
    # 控制字符 \x01 在 JSON 字符串内非法，必须触发 JSONDecodeError→LLMContractError
    raw = '{"items": [{"title": "a\x01b", "context": "c", "options": [{"label": "l1", "hint": "h1"}, {"label": "l2", "hint": "h2"}]}]}'
    with pytest.raises(LLMContractError):
        _parse_rescript_json_strict(raw)

def test_r3_strict_parse_concatenated_objects_raises_contract_error():
    """r3-2 strict 解析：拼接对象不截首块，直解失败抛 LLMContractError。"""
    from ming_sim.rescript_draft import _parse_rescript_json_strict
    from ming_sim.exceptions import LLMContractError
    raw = '{"items": [{"title": "甲", "context": "c", "options": [{"label": "a", "hint": "h1"}, {"label": "b", "hint": "h2"}]}]}{"items": []}'
    with pytest.raises(LLMContractError):
        _parse_rescript_json_strict(raw)

def test_657_s1_rescript_emitted_set_subset_of_dossier():
    """A12 前置（#1778 后）：只剩 emitted 闭集 ⊂ DOSSIER；七类 routable 已整体取消。"""
    from ming_sim.decree_vocabulary import (
        DOSSIER_ACTION_TYPES,
        RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
    )
    assert RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES <= DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES

def test_657_s1_derive_draft_capability_stable_and_sensitive():
    """capability：同字段稳定；闭集任一有效差改变键。"""
    from ming_sim.decree_vocabulary import derive_draft_capability

    base = {
        "action_type": "assignment",
        "label": "发帑赈济",
        "hint": "所安者饥民",
        "assignee_name": "杨嗣昌",
        "target_kind": "region",
        "target_id": "shaanxi",
        "transaction_category": "督赈",
        "locality_scope": "single",
        "region_id": "shaanxi",
    }
    a = derive_draft_capability(base)
    b = derive_draft_capability(dict(base))
    assert isinstance(a, str) and a == b and len(a) >= 16
    # 扰动 label
    changed = dict(base)
    changed["label"] = "缓征"
    assert derive_draft_capability(changed) != a
    # 扰动 assignee
    changed2 = dict(base)
    changed2["assignee_name"] = "洪承畴"
    assert derive_draft_capability(changed2) != a
    # 缺键按默认参与派生，不因插入空串而变
    with_default = dict(base)
    with_default["summon_target"] = ""
    assert derive_draft_capability(with_default) == a

def test_657_s1_option_shape_stamps_draft_capability():
    """层 A option 必填键校验；服务端写 draft_capability。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    raw = {
        "label": "发帑赈济",
        "hint": "所安者饥民",
        "action_type": "assignment",
        "assignee_name": "杨嗣昌",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "transaction_category": "督赈",
    }
    opt = normalize_rescript_layer_a_option(raw)
    assert opt["draft_capability"]
    assert opt["label"] == "发帑赈济"
    assert opt["action_type"] == "assignment"
    # 缺必填键 → 拒
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({"label": "x", "hint": "y"})
    # #1778：库级全集内的类型（policy 等）照常受理，无七类闭集
    policy_opt = normalize_rescript_layer_a_option({
        **raw,
        "action_type": "policy",
        "target_kind": "policy",
        "target_id": "清丈全国田亩",
        "locality_scope": "national",
        "region_id": "",
    })
    assert policy_opt["action_type"] == "policy"
    assert policy_opt["draft_capability"]
    # 库级全集之外仍 fail-loud（ADR 0040 形状检查）
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**raw, "action_type": "修仙"})

def test_1620_layer_a_reward_with_army_target_stays_reward():
    """赏赉+army 不因 target_kind 升格协饷。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    opt = normalize_rescript_layer_a_option({
        "label": "赏关宁将士",
        "hint": "恩赏",
        "action_type": "grant_allocation",
        "assignee_name": "",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "grant_action": "赏赉",
        "amount": 50,
        "account": "国库",
    })
    assert opt["grant_action"] == "赏赉"

@pytest.mark.parametrize("extra,drop", [
    pytest.param({"grant_action": "赏赉"}, (), id="conflict-reward"),
    pytest.param({"grant_kind": "other"}, (), id="unknown-kind"),
    pytest.param({"grant_action": "补发军饷"}, ("grant_kind",), id="zh-synonym"),
    # 非 grant 携 grant_kind：不得因 allowed 白名单静默丢键
    pytest.param(
        {"action_type": "assignment", "assignee_name": "杨嗣昌"}, (),
        id="non-grant-kind",
    ),
    # #1503 五字段 admission：缺 purpose/account、非法 target_kind
    pytest.param({"purpose": ""}, (), id="empty-purpose"),
    pytest.param({}, ("purpose",), id="drop-purpose"),
    pytest.param({"account": ""}, (), id="empty-account"),
    pytest.param({}, ("account",), id="drop-account"),
    pytest.param(
        {"target_kind": "region", "target_id": "shaanxi"}, (),
        id="region-target",
    ),
])
def test_1620_layer_a_army_pay_rejects_bad_typed_shape(extra, drop):
    """层 A：五字段缺漏、矛盾 kind、未知 kind、中文同义、非 grant 携 kind 均 fail-loud。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    raw = _army_pay_grant_option(**extra)
    for key in drop:
        raw.pop(key, None)
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option(raw)

def test_1620_internal_canonical_xiexang_renormalizes_without_kind():
    """内部 canonical（无 kind、grant_action=协饷）二次归一仍通；生成旁路另闸。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    raw = _army_pay_grant_option(grant_action="协饷")
    raw.pop("grant_kind", None)
    opt = normalize_rescript_layer_a_option(raw)
    assert opt["grant_action"] == "协饷"
    assert opt["purpose"] == "补饷"
    assert opt["account"] == "国库"

