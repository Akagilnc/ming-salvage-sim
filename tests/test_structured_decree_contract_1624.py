"""#1624 结构化旨意共同契约：真实入口主干（禁 helper 直调冒充入口；禁 prompt 文本锁）。"""

from __future__ import annotations

import json

import pytest

from ming_sim.cli_backend import capture_manual_directive_payload as _real_capture
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    assemble_structured_decree,
)
from tests.test_month_loop_tracer_1468 import _post_issue_stream, tracer_client  # noqa: F401

_OWNER_OPTION = {
    "label": "着户部继续核查陕西赈务，按月具报。",
    "hint": "督赈",
    "action_type": "assignment",
    "target_kind": "region",
    "target_id": "shaanxi",
    "locality_scope": "single",
    "region_id": "shaanxi",
    "assignee_name": "",
    "transaction_category": "督赈",
    "deadline_months": 2,
}


def _owner_manual_backend_json() -> str:
    return json.dumps({
        "拟旨意图": "拟旨",
        "动作类型": "assignment",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "地区ID": "shaanxi",
        "施行范围": "单省",
        "事务类别": "督赈",
        "承办人": "",
        "颁布方式": "普通",
        "参与人": [],
    }, ensure_ascii=False)


def _assert_hubu_duty_leads(db, dossier: dict) -> None:
    """外部可见：未点将督赈案卷的主办须为户部在任（职司路由结果）。"""
    roster = dossier.get("participant_roster") or []
    leads = [
        str(e.get("character_id") or "").strip()
        for e in roster
        if isinstance(e, dict) and str(e.get("tier") or "") == "主办"
    ]
    leads = [name for name in leads if name]
    assert leads, f"expected duty-route 主办, roster={roster!r} signal={dossier.get('execution_signal')!r}"
    for name in leads:
        row = db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?", (name,),
        ).fetchone()
        assert row is not None, f"主办未建档：{name!r}"
        assert str(row["office_type"] or "") == "户部", (
            f"主办 {name!r} office_type={row['office_type']!r}，期望户部"
        )
    signal = dossier.get("execution_signal") or {}
    if signal.get("chain") not in (None, ""):
        assert signal["chain"] == "户部"


def _seed_hubu_in_shaanxi(db) -> None:
    db.conn.execute(
        "UPDATE characters SET location='shaanxi' "
        "WHERE status='active' AND power_id='ming' AND office_type='户部'"
    )
    db.conn.commit()


def _month_end_ctx() -> dict:
    return {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [
            {"id": "xuanfu", "name": "宣府"},
            {"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"},
        ],
    }


def _army_single_bad_item() -> dict:
    """复验残留样本：辽东欠饷 option 层 army+single（矩阵非法）。"""
    return {
        "title": "辽东欠饷",
        "context": "九边欠饷数月，饥溃可待。",
        "options": [
            {
                "label": "补发关宁军饷",
                "hint": "边饷急",
                "action_type": "grant_allocation",
                "assignee_name": "",
                "target_kind": "army",
                "target_id": "guanning",
                "locality_scope": "single",
                "region_id": "",
                "transaction_category": "",
                "grant_kind": "army_pay",
                "amount": 300,
                "account": "国库",
                "purpose": "补饷",
            },
            {
                **_OWNER_OPTION,
                "label": "缓议加派",
                "hint": "候报",
            },
        ],
    }


def _army_none_legal_item() -> dict:
    """纠错轮合法：同军目标 + locality_scope=none。"""
    item = _army_single_bad_item()
    item["options"][0] = {
        **item["options"][0],
        "locality_scope": "none",
    }
    return item


def test_shared_validate_rejects_region_id_and_category_holes():
    """共同 assemble/validate 最低可证层：钉原洞 typed 拒绝。

    class1 原洞 = 非 region + national 夹带 region_id（旧闸只拒 scope==none）；
    class2 原洞 = 非 assignment 非空非法类别（旧闸闭集只罩 assignment）；
    class3 = 票拟七类动作 + national（NATIONAL_FANOUT 白名单外）必败；
    action_alias_conflict = action_type 与 dossier_action_type 双非空且不同。
    不经月末 is None（票拟七类无 policy；军令空承办另有降级面）。
    """
    with pytest.raises(StructuredDecreeCombinationError):
        assemble_structured_decree({
            "action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "national",
            "region_id": "shaanxi",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        assemble_structured_decree({
            "action_type": "assignment",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "national",
            "transaction_category": "督赈",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        assemble_structured_decree({
            "action_type": "military_order",
            "target_kind": "army",
            "target_id": "xuanfu",
            "locality_scope": "none",
            "assignee_name": "祖大寿",
            "transaction_category": "INVALID",
        })
    with pytest.raises(StructuredDecreeCombinationError):
        assemble_structured_decree({
            "action_type": "punishment",
            "target_kind": "character",
            "target_id": "某官",
            "locality_scope": "none",
            "transaction_category": "INVALID",
        })
    # 双非空动作身份冲突：默认 validate 入口 typed 拒绝，failed_fields 含两键
    with pytest.raises(StructuredDecreeCombinationError) as ei:
        assemble_structured_decree({
            "action_type": "assignment",
            "dossier_action_type": "policy",
            "target_kind": "policy",
            "target_id": "x",
            "locality_scope": "none",
            "transaction_category": "督赈",
        })
    assert ei.value.failed_fields == frozenset(
        {"action_type", "dossier_action_type"}
    )
    # 同值或一侧空：维持现状（不因 alias 比较误伤）
    same = assemble_structured_decree({
        "action_type": "policy",
        "dossier_action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "none",
    })
    assert same["action_type"] == "policy"
    assert same["dossier_action_type"] == "policy"
    only_action = assemble_structured_decree({
        "action_type": "policy",
        "target_kind": "policy",
        "target_id": "x",
        "locality_scope": "none",
    })
    assert only_action["action_type"] == "policy"
    assert only_action["dossier_action_type"] == "policy"


def test_month_end_entry_owner_and_matrix_reject(monkeypatch, tmp_path):
    """真实月末入口 tracer：Owner 例；army+single 有界纠错接受；耗尽整批降级。

    首抽 exact army+single（合并后复验残留）；纠错轮合法 army+none 被整批接受。
    另证纠错仍非法 → F2.5 响亮降级、零部分头版。不静默改写 scope/kind。
    改票真实入口由 test_pihong_dossier_1490 的 return_revise 路径覆盖。
    不申请 game：本 tracer 只经 generate_rescript_draft 真实入口，无 DB。
    """
    import ming_sim.rescript_draft as rescript_mod

    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    owner_item = {
        "title": "陕西告饥",
        "context": "秦地赤旱，饥民待哺，急须责成赈济。",
        "options": [
            dict(_OWNER_OPTION),
            {
                **_OWNER_OPTION,
                "label": "缓征以苏民力",
                "hint": "先赈后征",
                "transaction_category": "钱粮",
            },
        ],
    }

    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"items": [owner_item]}, ensure_ascii=False),
    )
    drafts = rescript_mod.generate_rescript_draft(
        object(), _month_end_ctx(), 1,
    )
    assert drafts is not None and len(drafts) == 1
    monthly = drafts[0]["options"][0]
    assert monthly["action_type"] == "assignment"
    assert monthly["target_kind"] == "region"
    assert monthly["target_id"] == "shaanxi"
    assert monthly["region_id"] == "shaanxi"
    assert monthly["locality_scope"] == "single"
    assert monthly["transaction_category"] == "督赈"
    assert not str(monthly.get("assignee_name") or "").strip()

    # army+single 首抽 → 一次有界重抽 army+none 合法接受
    calls: list[int] = []

    def _heal_once(_agent, prompt, tag=""):
        del prompt, tag
        calls.append(1)
        if len(calls) == 1:
            return json.dumps({"items": [_army_single_bad_item()]}, ensure_ascii=False)
        return json.dumps({"items": [_army_none_legal_item()]}, ensure_ascii=False)

    monkeypatch.setattr(rescript_mod, "run_agent_text", _heal_once)
    healed = rescript_mod.generate_rescript_draft(
        object(), _month_end_ctx(), 2,
    )
    assert len(calls) == 2  # spec：首抽 + 恰一次结构重抽
    assert healed is not None and len(healed) == 1
    grant = healed[0]["options"][0]
    assert grant["target_kind"] == "army"
    assert grant["target_id"] == "guanning"
    assert grant["locality_scope"] == "none"
    assert grant.get("grant_action") == "协饷"

    # 纠错耗尽仍 army+single → 整批降级、零部分头版（仍恰 2 次调用）
    exhaust_calls: list[int] = []

    def _never_heals(_agent, prompt, tag=""):
        del prompt, tag
        exhaust_calls.append(1)
        return json.dumps({"items": [_army_single_bad_item()]}, ensure_ascii=False)

    monkeypatch.setattr(rescript_mod, "run_agent_text", _never_heals)
    assert rescript_mod.generate_rescript_draft(
        object(), _month_end_ctx(), 3,
    ) is None
    assert len(exhaust_calls) == 2  # spec：有界 1 次重抽后降级，不多抽
    note_path = tmp_path / "error_packs" / "rescript_draft_degraded" / "turn3.json"
    assert note_path.is_file()
    note = json.loads(note_path.read_text(encoding="utf-8"))
    assert note.get("turn") == 3
    assert str(note.get("reason") or "").strip()


def test_rescript_follow_draft_routes_hubu(game):
    """真实批红 follow_draft：Owner 例未点将 → 主办为户部在任。"""
    import ming_sim.rescript_actions as ra
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state, content = game
    _seed_hubu_in_shaanxi(db)

    opt = normalize_rescript_layer_a_option(dict(_OWNER_OPTION))
    alt = normalize_rescript_layer_a_option({
        **_OWNER_OPTION, "label": "缓征", "hint": "b", "transaction_category": "钱粮",
    })
    db.save_rescript_drafts(int(state.turn), [{
        "title": "陕西告饥",
        "context": "秦地赤旱",
        "options": [opt, alt],
        "actor_name": "杨嗣昌",
        "actor_office": "兵部尚书",
        "actor_faction": "东林",
    }])
    db.conn.commit()
    urgent = next(
        r for r in db.list_rescript_desk(int(state.turn))
        if r.get("kind") == "rescript_draft" and r.get("title") == "陕西告饥"
    )
    before = len(db.list_decree_dossiers())
    batch = ra.validate_all([urgent], [{
        "decision_key": urgent["decision_key"],
        "action": "follow_draft",
        "draft_capability": opt["draft_capability"],
        "label": opt["label"],
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    after = db.list_decree_dossiers()
    assert len(after) > before
    created = after[-1]
    payload = json.loads(created.get("payload_json") or "{}")
    assert payload.get("target_kind") == "region"
    assert payload.get("target_id") == "shaanxi"
    assert payload.get("region_id") == "shaanxi"
    assert payload.get("locality_scope") == "single"
    assert payload.get("transaction_category") == "督赈"
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
    _assert_hubu_duty_leads(db, created)


def test_manual_owner_example_seal_advances(tracer_client, monkeypatch):
    """真实 Web 手工拟诏：Owner 例 → 盖玺；持久化 canonical + 户部主办。"""
    import ming_sim.cli_backend as cli_backend
    import web_app

    new = tracer_client.post("/api/menu/new_game")
    assert new.status_code == 200
    game = web_app.web_game
    assert game is not None
    _seed_hubu_in_shaanxi(game.db)

    def backend(*_a, **_k):
        return _owner_manual_backend_json(), 1

    monkeypatch.setattr(cli_backend, "capture_manual_directive_payload", _real_capture)
    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    response = tracer_client.post(
        "/api/directives",
        json={"text": "着户部继续核查陕西赈务，按月具报。", "notes": ""},
    )
    assert response.status_code == 200, response.text
    turn_before = game.state.turn
    _post_issue_stream(
        tracer_client, expected_turn=turn_before, step="#1624 owner seal",
    )
    assert game.state.turn == turn_before + 1
    dossiers = [dict(d) for d in game.db.list_decree_dossiers()]
    matched = [
        d for d in dossiers
        if str(json.loads(d.get("payload_json") or "{}").get("target_id") or "")
        == "shaanxi"
        and str(json.loads(d.get("payload_json") or "{}").get("transaction_category") or "")
        == "督赈"
    ]
    assert matched, f"expected shaanxi 督赈 dossier, got={dossiers!r}"
    payload = json.loads(matched[0]["payload_json"])
    assert payload.get("target_kind") == "region"
    assert payload.get("locality_scope") == "single"
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
    _assert_hubu_duty_leads(game.db, matched[0])


def test_layer_a_prompt_contract_is_typed_single_source_for_draft_and_revise(monkeypatch):
    """层 A required/present/action-conditional 为 typed 单源；初拟/改票共用。

    键集与七类条件断言落 layer_a_option_shape()；工厂注入断言同一 renderer
    返回值身份（非 prompt 措辞锁）。normalize 消费同一 shape 拒绝缺条件字段。
    """
    import ming_sim.agents as agents_mod
    from ming_sim.agents import (
        _rescript_option_instructions,
        bind_content,
        create_rescript_draft_agent,
        create_rescript_revise_agent,
    )
    from ming_sim.content import GameContent
    from ming_sim.decree_vocabulary import RESCRIPT_ROUTABLE_ACTION_TYPES
    from ming_sim.models import LLMConfig
    from ming_sim.rescript_draft import (
        _LAYER_A_PRESENT_KEYS,
        _LAYER_A_REQUIRED_KEYS,
        layer_a_option_shape,
        normalize_rescript_layer_a_option,
        rescript_layer_a_prompt_contract,
    )
    from ming_sim.structured_decree import structured_decree_prompt_contract

    shape = layer_a_option_shape()
    # shape 与模块级元组同一对象（validator/renderer 共用真源）
    assert shape["required_keys"] is _LAYER_A_REQUIRED_KEYS
    assert shape["present_keys"] is _LAYER_A_PRESENT_KEYS
    assert shape["required_keys"] == (
        "label", "hint", "action_type", "target_kind", "target_id", "locality_scope",
    )
    assert shape["present_keys"] == (
        "assignee_name", "region_id", "transaction_category",
    )
    assert shape["grant_kind_army_pay"] == "army_pay"
    assert "draft_capability" in shape["server_only_keys"]  # type: ignore[operator]

    conditional = shape["action_conditional"]
    assert isinstance(conditional, dict)
    assert frozenset(conditional) == RESCRIPT_ROUTABLE_ACTION_TYPES
    appt = conditional["appointment"]
    assert "appoint_action" in appt["required_nonempty"]  # type: ignore[index]
    assert "任命" in appt["enum_in"]["appoint_action"]  # type: ignore[index]
    assert appt["target_kind_in"] == ("character",)
    mil = conditional["military_order"]
    assert "assignee_name" in mil["required_nonempty"]  # type: ignore[index]
    assert mil["target_kind_in"] == ("army",)
    mil_any = mil.get("require_any_nonempty") or ()
    assert any(
        set(group) >= {"station", "due_turn", "deadline_months"}
        for group in mil_any  # type: ignore[union-attr]
    ), f"military dual gate missing in shape: {mil_any!r}"
    punish = conditional["punishment"]
    assert "punish_action" in punish["required_nonempty"]  # type: ignore[index]
    assert "罚俸" in punish["enum_in"]["punish_action"]  # type: ignore[index]

    # normalize 消费同一条件契约：缺 appoint_action 须失败（复判探针反例）
    with pytest.raises(ValueError, match="appoint_action"):
        normalize_rescript_layer_a_option({
            "label": "授官", "hint": "h", "action_type": "appointment",
            "target_kind": "character", "target_id": "某官",
            "locality_scope": "none", "region_id": "",
            "assignee_name": "", "transaction_category": "",
            "office": "兵部尚书",
        })
    with pytest.raises(ValueError, match="assignee_name"):
        normalize_rescript_layer_a_option({
            "label": "调驻", "hint": "h", "action_type": "military_order",
            "target_kind": "army", "target_id": "xuanfu",
            "locality_scope": "none", "region_id": "",
            "assignee_name": "", "transaction_category": "",
            "station": "京师",
        })
    # 军令 dual：驻地|正期限须具其一；双缺与 0/"0" 不得过层 A
    mil_base = {
        "label": "出战", "hint": "h", "action_type": "military_order",
        "target_kind": "army", "target_id": "xuanfu",
        "locality_scope": "none", "region_id": "",
        "assignee_name": "祖大寿", "transaction_category": "",
    }
    with pytest.raises(ValueError, match="station|due_turn|deadline_months"):
        normalize_rescript_layer_a_option(dict(mil_base))
    with pytest.raises(ValueError, match="station|due_turn|deadline_months"):
        normalize_rescript_layer_a_option({
            **mil_base, "station": "", "due_turn": 0, "deadline_months": "0",
        })
    only_station = normalize_rescript_layer_a_option({**mil_base, "station": "京师"})
    assert only_station.get("station") == "京师"
    only_deadline = normalize_rescript_layer_a_option({
        **mil_base, "deadline_months": 3,
    })
    assert int(only_deadline.get("deadline_months") or 0) == 3

    # authorization require_any 保持通用非空串语义（禁被军令正值判定误伤）
    auth_zero = normalize_rescript_layer_a_option({
        "label": "授权", "hint": "h", "action_type": "authorization",
        "target_kind": "character", "target_id": "某官",
        "locality_scope": "none", "region_id": "",
        "assignee_name": "", "transaction_category": "",
        "name": "0",
    })
    assert auth_zero.get("name") == "0"
    auth_assignee_zero = normalize_rescript_layer_a_option({
        "label": "授权", "hint": "h", "action_type": "authorization",
        "target_kind": "character", "target_id": "某官",
        "locality_scope": "none", "region_id": "",
        "assignee_name": "0", "transaction_category": "",
        "name": "",
    })
    assert auth_assignee_zero.get("assignee_name") == "0"

    contract = rescript_layer_a_prompt_contract()
    # renderer 必须消费 action_conditional（组合断言；禁措辞锁）。
    # 抽掉 shape→conditional 渲染后本断言须红——防再退回「按需填写」空壳。
    from ming_sim.rescript_draft import _render_action_conditional_contract

    conditional_seg = _render_action_conditional_contract(conditional)
    assert conditional_seg  # 七类条件段非空
    assert conditional_seg in contract

    # 共享 instructions 块 = 层 A + structured_decree 子契约（禁 agents 手抄）
    # target×locality 可接受面行为由月末入口 tracer + 8×3 矩阵层覆盖，不在此锁内部接线。
    shared = _rescript_option_instructions()
    assert shared == [contract, structured_decree_prompt_contract()]

    # 初拟/改票工厂真实组装 instructions：注入同一 renderer 返回值
    bind_content(GameContent.load())
    captured: dict[str, list] = {}

    class _FakeAgent:
        def __init__(self, **kwargs):
            captured[str(kwargs.get("id") or "")] = list(
                kwargs.get("instructions") or []
            )
            for key, val in kwargs.items():
                setattr(self, key, val)

    monkeypatch.setattr(agents_mod, "Agent", _FakeAgent)
    monkeypatch.setattr(agents_mod, "create_chat_model", lambda *_a, **_k: object())
    cfg = LLMConfig(api_key="test", base_url="http://localhost/v1", model="test")
    create_rescript_draft_agent(cfg, None)  # type: ignore[arg-type]
    create_rescript_revise_agent(cfg, None)  # type: ignore[arg-type]
    assert contract in captured.get("rescript-drafter", [])
    assert contract in captured.get("rescript-reviser", [])


def test_combo_correction_preserves_first_draw_roster(game, monkeypatch):
    """组合纠错：失败字段（含 target_kind 身份束）采纳；未失败动作/名册/类别/旨文冻结。

    样本：office/户部+single → region/shaanxi+single（#1624 owner 归正）；
    纠错轮同时漂移动作/人物/类别/正文。真实 wrapper，仅 mock backend。
    """
    import ming_sim.cli_backend as cb

    db, _state, content = game
    first = "毕自严"
    assert first in content.characters
    second = next(
        name for name, ch in content.characters.items()
        if name != first
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )

    def _first_payload() -> dict:
        return {
            "拟旨意图": "拟旨",
            "动作类型": "assignment",
            "目标类型": "office",
            "目标ID": "户部",
            "地区ID": "",
            "施行范围": "单省",
            "事务类别": "督赈",
            "承办人": "",
            "颁布方式": "普通",
            "正文": f"着户部继续核查陕西赈务，{first}会同。",
            "参与人": [{
                "character_id": first, "tier": "主办", "role": "督赈",
            }],
        }

    def _drift_payload() -> dict:
        # 纠错给出正确身份束，同时漂移动作/人物/类别/正文
        return {
            "拟旨意图": "拟旨",
            "动作类型": "punishment",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "地区ID": "shaanxi",
            "施行范围": "单省",
            "事务类别": "",
            "承办人": "",
            "颁布方式": "普通",
            "正文": f"着惩处{second}。",
            "参与人": [{
                "character_id": second, "tier": "主办", "role": "惩",
            }],
        }

    n = {"c": 0}

    def backend(prompt, *_a, tag="", **_k):
        n["c"] += 1
        if n["c"] == 1:
            return (json.dumps(_first_payload(), ensure_ascii=False), 1)
        return (json.dumps(_drift_payload(), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_roster_heal(
        "着户部继续核查陕西赈务，按月具报。", "臣遵拟。",
        db=db, content=content,
    )
    ids = [
        str(i.get("character_id") or "")
        for i in (result.get("participant_roster") or [])
    ]
    assert ids == [first], f"roster drifted to {ids!r}, expected {[first]!r}"
    assert result.get("locality_scope") == "single"
    assert result.get("dossier_action_type") == "assignment"
    assert result.get("target_kind") == "region"
    assert result.get("target_id") == "shaanxi"
    assert result.get("region_id") == "shaanxi"
    assert result.get("transaction_category") == "督赈"
    # 单条路径 draft_text=大臣回话；纠错轮正文漂移不得改写会话正文真源
    assert result.get("draft_text") == "臣遵拟。"
    assert n["c"] == 2
    # DB-backed 共同闸：身份束归正后可解析（禁 region+户部 漏网）
    assemble_structured_decree(
        {
            "action_type": result.get("dossier_action_type"),
            "target_kind": result.get("target_kind"),
            "target_id": result.get("target_id"),
            "region_id": result.get("region_id"),
            "locality_scope": result.get("locality_scope"),
            "transaction_category": result.get("transaction_category"),
        },
        conn=db.conn,
        regions_content=content.regions,
    )


@pytest.mark.parametrize("mode", ["freeze_roster", "heal_first_only_reject"])
def test_batch_combo_correction_real_wrapper(game, monkeypatch, mode):
    """批抽真实 wrapper 单条 tracer：窄合并保首抽；只修第一条不得放行第二条。

    freeze_roster：draft0 locality 非法→纠错修好但漂移动作/人物；须保留首抽结构与名册。
    heal_first_only_reject：两条均非法、纠错只修 draft0 → 须仍抛且 draft_failures 含 1。
    """
    import ming_sim.cli_backend as cb
    from ming_sim.structured_decree import StructuredDecreeCombinationError

    db, _state, content = game
    first = "毕自严"
    second = next(
        name for name, ch in content.characters.items()
        if name != first
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )

    def _assignment_draft(
        *,
        target_id: str,
        scope: str,
        body: str,
        lead: str = first,
        category: str = "督赈",
    ) -> dict:
        return {
            "正文": body,
            "动作类型": "assignment",
            "目标类型": "region",
            "目标ID": target_id,
            "地区ID": target_id,
            "施行范围": scope,
            "事务类别": category,
            "颁布方式": "普通",
            "参与人": [{"character_id": lead, "tier": "主办", "role": "督"}],
        }

    def _first_draw() -> dict:
        if mode == "freeze_roster":
            return {
                "成品旨稿": [
                    _assignment_draft(
                        target_id="shaanxi", scope="无",
                        body=f"着{first}核查陕西赈务。",
                    ),
                    {
                        "正文": "着边军整饬器械。",
                        "动作类型": "military_order",
                        "目标类型": "army",
                        "目标ID": "guanning",
                        "施行范围": "无",
                        "颁布方式": "普通",
                        "参与人": [],
                    },
                ]
            }
        # heal_first_only_reject：两条 region 交办均 locality=none
        return {
            "成品旨稿": [
                _assignment_draft(
                    target_id="shaanxi", scope="无",
                    body=f"着{first}核查陕西赈务。",
                ),
                _assignment_draft(
                    target_id="shanxi", scope="无",
                    body=f"着{first}核查山西赈务。",
                ),
            ]
        }

    def _correction() -> dict:
        if mode == "freeze_roster":
            # 好 locality + 漂移动作/目标/人物；military 行也改 target
            return {
                "成品旨稿": [
                    {
                        "正文": f"着惩处{second}。",
                        "动作类型": "punishment",
                        "目标类型": "character",
                        "目标ID": second,
                        "地区ID": "",
                        "施行范围": "单省",
                        "事务类别": "",
                        "颁布方式": "普通",
                        "参与人": [{
                            "character_id": second, "tier": "主办", "role": "惩",
                        }],
                    },
                    {
                        "正文": "着边军整饬器械。",
                        "动作类型": "military_order",
                        "目标类型": "army",
                        "目标ID": "xuanfu",
                        "施行范围": "无",
                        "颁布方式": "普通",
                        "参与人": [],
                    },
                ]
            }
        # 只修 draft0 locality；draft1 仍 none
        return {
            "成品旨稿": [
                _assignment_draft(
                    target_id="shaanxi", scope="单省",
                    body=f"着{first}核查陕西赈务。",
                ),
                _assignment_draft(
                    target_id="shanxi", scope="无",
                    body=f"着{first}核查山西赈务。",
                ),
            ]
        }

    n = {"c": 0}

    def backend(prompt, *_a, tag="", **_k):
        n["c"] += 1
        payload = _first_draw() if n["c"] == 1 else _correction()
        return (json.dumps(payload, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    if mode == "freeze_roster":
        result = cb.extract_draft_intent_with_roster_heal(
            f"两道旨着{first}核查并整饬", "臣遵拟。",
            db=db, content=content, draft_count=2,
        )
        drafts = result.get("drafts") or []
        assert len(drafts) == 2
        ids = [
            str(i.get("character_id") or "")
            for i in (drafts[0].get("participant_roster") or [])
        ]
        assert ids == [first]
        assert drafts[0].get("locality_scope") == "single"
        assert drafts[0].get("dossier_action_type") == "assignment"
        assert drafts[0].get("target_kind") == "region"
        assert drafts[0].get("target_id") == "shaanxi"
        assert drafts[0].get("transaction_category") == "督赈"
        assert first in str(drafts[0].get("draft_text") or "")
        assert drafts[1].get("target_id") == "guanning"
        assert n["c"] == 2
        return

    with pytest.raises(StructuredDecreeCombinationError) as ei:
        cb.extract_draft_intent_with_roster_heal(
            f"两道旨着{first}核查陕晋", "臣遵拟。",
            db=db, content=content, draft_count=2,
            heal_retries=1,
        )
    failures = dict(getattr(ei.value, "draft_failures", None) or {})
    # 失败图必须含 draft1；禁 OR partial 条数的放松断言
    assert 1 in failures, f"expected draft1 in draft_failures, got {failures!r}"
    assert n["c"] >= 2
