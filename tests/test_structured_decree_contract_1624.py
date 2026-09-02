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
        "army_targets": [{"id": "xuanfu", "name": "宣府"}],
    }


def test_shared_validate_rejects_region_id_and_category_holes():
    """共同 assemble/validate 最低可证层：钉原洞 typed 拒绝。

    class1 原洞 = 非 region + national 夹带 region_id（旧闸只拒 scope==none）；
    class2 原洞 = 非 assignment 非空非法类别（旧闸闭集只罩 assignment）。
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


def test_month_end_entry_owner_and_matrix_reject(monkeypatch, game):
    """真实月末生成入口：Owner 例落 canonical；office+single 矩阵坏形整批降级。

    改票真实入口由 test_pihong_dossier_1490 的 return_revise 路径覆盖。
    region_id/category 原洞见 test_shared_validate_rejects_region_id_and_category_holes。
    """
    import ming_sim.rescript_draft as rescript_mod

    del game
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

    # office+single：矩阵矛盾（非 region_id/category 原洞）→ 整批降级
    bad = {
        "title": "坏形",
        "context": "x",
        "options": [{
            **_OWNER_OPTION,
            "target_kind": "office",
            "target_id": "户部",
            "locality_scope": "single",
            "region_id": "",
        }, dict(_OWNER_OPTION)],
    }
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *_a, **_k: json.dumps({"items": [bad]}, ensure_ascii=False),
    )
    assert rescript_mod.generate_rescript_draft(
        object(), _month_end_ctx(), 1,
    ) is None


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
    """层 A required/present/action-conditional 为 typed 单源；初拟/改票共用 renderer。

    禁 agents 手抄键表；禁 prompt 文本锁——只断言 instructions 含 shape 渲染结果
    且与 validator 同源键集。
    """
    import ming_sim.agents as agents_mod
    from ming_sim.agents import (
        _rescript_option_instructions,
        bind_content,
        create_rescript_draft_agent,
        create_rescript_revise_agent,
    )
    from ming_sim.content import GameContent
    from ming_sim.models import LLMConfig
    from ming_sim.rescript_draft import (
        layer_a_option_shape,
        normalize_rescript_layer_a_option,
        rescript_layer_a_prompt_contract,
    )
    from ming_sim.structured_decree import structured_decree_prompt_contract

    shape = layer_a_option_shape()
    required = tuple(shape["required_keys"])  # type: ignore[arg-type]
    present = tuple(shape["present_keys"])  # type: ignore[arg-type]
    assert required == (
        "label", "hint", "action_type", "target_kind", "target_id", "locality_scope",
    )
    assert present == ("assignee_name", "region_id", "transaction_category")
    assert "grant_allocation" in shape["action_conditional_keys"]  # type: ignore[operator]
    assert shape["grant_kind_army_pay"] == "army_pay"

    contract = rescript_layer_a_prompt_contract()
    # renderer 由 shape 派生：改 shape 键即改 contract（同源，非手抄）
    for key in required + present:
        assert key in contract
    assert "army_pay" in contract
    assert "assignment" in contract

    # 共享 instructions 块 = 层 A + structured_decree 子契约（禁 agents 手抄）
    shared = _rescript_option_instructions()
    assert shared == [contract, structured_decree_prompt_contract()]

    # validator 仍咬完整层 A（缺 required → 失败）；不放松
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({
            "target_kind": "region", "target_id": "shaanxi",
            "locality_scope": "single", "region_id": "shaanxi",
            "assignee_name": "", "transaction_category": "督赈",
        })

    # 初拟/改票工厂真实组装 instructions（spy Agent/model，不打网）
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
    draft_text = "\n".join(str(p) for p in captured.get("rescript-drafter", []))
    revise_text = "\n".join(str(p) for p in captured.get("rescript-reviser", []))
    assert contract in draft_text
    assert contract in revise_text


def test_combo_correction_preserves_first_draw_roster(game, monkeypatch):
    """组合纠错：首抽合法甲 + 坏 locality → 次轮合法乙 + 好 locality；返回甲+好 scope。

    真实 wrapper，仅 mock 外部 backend（Codex-3）。
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

    def _payload(person: str, *, scope: str) -> dict:
        return {
            "拟旨意图": "拟旨",
            "动作类型": "assignment",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "地区ID": "shaanxi",
            "施行范围": scope,
            "事务类别": "督赈",
            "承办人": "",
            "颁布方式": "普通",
            "正文": f"着{person}核查陕西赈务。",
            "参与人": [{
                "character_id": person, "tier": "主办", "role": "督赈",
            }],
        }

    n = {"c": 0}

    def backend(prompt, *_a, tag="", **_k):
        n["c"] += 1
        if n["c"] == 1:
            # 甲 + region/none → 组合失败
            return (json.dumps(_payload(first, scope="无"), ensure_ascii=False), 1)
        # 乙 + region/single → 组合过，但名册已漂
        return (json.dumps(_payload(second, scope="单省"), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_roster_heal(
        f"着{first}核查陕西赈务", "臣遵拟。",
        db=db, content=content,
    )
    ids = [
        str(i.get("character_id") or "")
        for i in (result.get("participant_roster") or [])
    ]
    assert ids == [first], f"roster drifted to {ids!r}, expected {[first]!r}"
    assert result.get("locality_scope") == "single"
    assert result.get("target_kind") == "region"
    assert result.get("target_id") == "shaanxi"
    assert result.get("region_id") == "shaanxi"
    assert n["c"] == 2


def test_combo_correction_preserves_batch_first_draw_roster(game, monkeypatch):
    """批抽组合纠错：逐 draft 保留首抽 participant_roster。"""
    import ming_sim.cli_backend as cb

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

    def _batch(person: str, *, scope: str) -> dict:
        return {
            "成品旨稿": [
                {
                    "正文": f"着{person}核查陕西赈务。",
                    "动作类型": "assignment",
                    "目标类型": "region",
                    "目标ID": "shaanxi",
                    "地区ID": "shaanxi",
                    "施行范围": scope,
                    "事务类别": "督赈",
                    "颁布方式": "普通",
                    "参与人": [{
                        "character_id": person, "tier": "主办", "role": "督",
                    }],
                },
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

    n = {"c": 0}

    def backend(prompt, *_a, tag="", **_k):
        n["c"] += 1
        if n["c"] == 1:
            return (json.dumps(_batch(first, scope="无"), ensure_ascii=False), 1)
        return (json.dumps(_batch(second, scope="单省"), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
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
    assert drafts[1].get("target_id") == "guanning"
    assert n["c"] == 2
