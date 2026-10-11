"""#1624 结构化旨意共同契约：真实入口主干（禁 helper 直调冒充入口；禁 prompt 文本锁）。"""

from __future__ import annotations

import json

import pytest

from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    assemble_structured_decree,
)
from tests.rescript_test_helpers import sql_rescript_draft


# #1778 决定 3：拟票大臣把参与名单写进票拟（主办可多人）；代码不按职司表配人。
_OWNER_ROSTER = [
    {"character_id": "毕自严", "tier": "主办", "role": "总核赈务", "delegator_id": None},
    {"character_id": "陈新甲", "tier": "协办", "role": "", "delegator_id": None},
]

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
    "participant_roster": [dict(item) for item in _OWNER_ROSTER],
}

def _owner_manual_backend_json() -> str:
    # 附件 r3 回显形态：LLM 误带执行面=immediate；assignment 不得透传落库。
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
        "执行面": "immediate",
        "参与人": [dict(item) for item in _OWNER_ROSTER],
    }, ensure_ascii=False)

def _assert_drafted_roster_nailed(db, dossier: dict) -> None:
    """#1778 决定 3/5：主办＝旨意自带名单里的主办，逐字钉进案卷（不是职司表推出的人）。"""
    roster = dossier.get("participant_roster") or []
    tiers = {
        (str(e.get("character_id") or "").strip(), str(e.get("tier") or "").strip())
        for e in roster
        if isinstance(e, dict)
    }
    expected = {
        (str(item["character_id"]), str(item["tier"])) for item in _OWNER_ROSTER
    }
    assert expected <= tiers, f"roster={roster!r}"
    leads = sorted(name for name, tier in tiers if tier == "主办" and name)
    assert leads == ["毕自严"], f"名单外不得由代码补主办：{roster!r}"
    for name, _tier in tiers:
        assert db.conn.execute(
            "SELECT 1 FROM characters WHERE name=?", (name,),
        ).fetchone() is not None, f"参与人未建档：{name!r}"


def test_shared_validate_rejects_region_id_and_category_holes():
    """共同 assemble/validate 最低可证层：钉原洞 typed 拒绝。

    class1 原洞 = 非 region + national 夹带 region_id（旧闸只拒 scope==none）；
    class2 原洞 = 非 assignment 非空非法类别（旧闸闭集只罩 assignment）；
    action_alias_conflict = action_type 与 dossier_action_type 双非空且不同。
    #1778：动作×national 白名单已取消，national 只受 8×3 矩阵约束。
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

def test_rescript_follow_draft_nails_drafted_roster(game):
    """真实批红 follow_draft：Owner 例未点将 → 主办来自票拟名单，成案钉进案卷。"""
    import ming_sim.rescript_actions as ra
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    db, state, content = game

    opt = normalize_rescript_layer_a_option(dict(_OWNER_OPTION))
    alt = normalize_rescript_layer_a_option({
        **_OWNER_OPTION, "label": "缓征", "hint": "b", "transaction_category": "钱粮",
    })
    sql_rescript_draft(
        db, int(state.turn), idx=0, event_id="draft:陕西告饥",
        title="陕西告饥", context="秦地赤旱",
        options=[opt, alt],
        actor_name="杨嗣昌", actor_office="兵部尚书", actor_faction="东林",
    )
    db.conn.commit()
    urgent = next(
        r for r in db.issues.list_rescript_desk(int(state.turn))
        if r.get("kind") == "rescript_draft" and r.get("title") == "陕西告饥"
    )
    before = len(db.dossiers.list_dossiers())
    batch = ra.validate_all([urgent], [{
        "decision_key": urgent["decision_key"],
        "action": "follow_draft",
        "draft_capability": opt["draft_capability"],
        "label": opt["label"],
    }])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(), content=content)
    after = db.dossiers.list_dossiers()
    assert len(after) > before
    created = after[-1]
    payload = json.loads(created.get("payload_json") or "{}")
    assert payload.get("target_kind") == "region"
    assert payload.get("target_id") == "shaanxi"
    assert payload.get("region_id") == "shaanxi"
    assert payload.get("locality_scope") == "single"
    assert payload.get("transaction_category") == "督赈"
    assert not str(payload.get("assignee_id") or payload.get("assignee") or "").strip()
    _assert_drafted_roster_nailed(db, created)


def _executing_counts(db, *, owner_name: str, region_id: str):
    """Observe durable executing dossiers, not the retired simulator board."""
    owner_open = db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers d, json_each(d.participant_roster) r "
        "WHERE d.status='executing' AND json_extract(r.value, '$.tier')='主办' "
        "AND json_extract(r.value, '$.character_id')=?", (owner_name,),
    ).fetchone()[0]
    province_open = db.conn.execute(
        "SELECT COUNT(*) FROM decree_dossiers "
        "WHERE status='executing' AND region_id=?", (region_id,),
    ).fetchone()[0]
    return owner_open, province_open


def test_normalize_rescript_layer_a_option_contract(game):
    """坏选项拒收；合法军令与授权经真实改票写口存入待批票拟。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    # 缺 appoint_action 须失败
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({
            "label": "授官", "hint": "h", "action_type": "appointment",
            "target_kind": "character", "target_id": "某官",
            "locality_scope": "none", "region_id": "",
            "assignee_name": "", "transaction_category": "",
            "office": "兵部尚书",
        })
    with pytest.raises(ValueError):
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
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option(dict(mil_base))
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({
            **mil_base, "station": "", "due_turn": 0, "deadline_months": "0",
        })
    import ming_sim.rescript_actions as ra
    db, state, content = game
    auth_base = {
        "label": "授权", "hint": "h", "action_type": "authorization",
        "target_kind": "character", "target_id": "某官",
        "locality_scope": "none", "region_id": "", "transaction_category": "",
    }
    options = [
        {**mil_base, "station": "京师"},
        {**mil_base, "deadline_months": 3},
        {**auth_base, "name": "0", "assignee_name": ""},
        {**auth_base, "name": "", "assignee_name": "0"},
    ]
    sql_rescript_draft(db, int(state.turn), idx=0, event_id="draft:改票",
                       title="改票", options=[dict(_OWNER_OPTION)])
    db.conn.commit()
    urgent = db.issues.list_rescript_desk(int(state.turn))[0]
    key = urgent["decision_key"]
    batch = ra.validate_all([urgent], [{"decision_key": key, "action": "return_revise", "note": "再拟"}])
    ra.apply_rescript_batch(db, state, batch, ra.PrewriteResults(revise_by_key={key: options}), content=content)
    stored = db.issues.list_rescript_drafts()[0]["options"]
    assert stored[0]["station"] == "京师"
    assert stored[1]["deadline_months"] == 3
    assert stored[2]["name"] == "0"
    assert stored[3]["assignee_name"] == "0"
    assert db.issues.list_rescript_drafts()[0]["revision_round"] == 1


def test_combo_correction_preserves_first_draw_roster(game, monkeypatch):
    """组合纠错：失败字段（含 target_kind 身份束）采纳；未失败动作/名册/类别/旨文冻结。

    样本：office/户部+single → region/shaanxi+single（#1624 owner 归正）；
    纠错轮同时漂移动作/人物/类别/正文。真实 wrapper，仅 mock backend。
    """
    import ming_sim.cli_backend as cb

    db, state, content = game
    first = "毕自严"
    assert first in content.characters
    second = next(
        name for name, ch in content.characters.items()
        if name != first
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.characters.get_character_status(name)[0] == "active"
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
    from tests.month_chain_helpers import make_light_session
    session = make_light_session(db, state, content)
    directive = session.add_directive(result["draft_text"], dossier_payload=result)
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.dossiers.get_for_directive(directive.id)
    payload = json.loads(dossier["payload_json"])
    assert [item["character_id"] for item in dossier["participant_roster"]] == [first]
    assert dossier["action_type"] == "assignment"
    assert dossier["target_kind"] == "region"
    assert dossier["target_id"] == "shaanxi"
    assert payload["region_id"] == "shaanxi"
    assert payload["locality_scope"] == "single"
    assert payload["transaction_category"] == "督赈"


@pytest.mark.parametrize("mode", ["freeze_roster", "heal_first_only_reject"])
def test_batch_combo_correction_real_wrapper(game, monkeypatch, mode):
    """批抽真实 wrapper 单条 tracer：窄合并保首抽；只修第一条不得放行第二条。

    freeze_roster：draft0 locality 非法→纠错修好但漂移动作/人物；须保留首抽结构与名册。
    heal_first_only_reject：两条均非法、纠错只修 draft0 → 须仍抛且 draft_failures 含 1。
    """
    import ming_sim.cli_backend as cb
    from ming_sim.structured_decree import StructuredDecreeCombinationError

    db, state, content = game
    first = "毕自严"
    second = next(
        name for name, ch in content.characters.items()
        if name != first
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.characters.get_character_status(name)[0] == "active"
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
                        "期限月数": 3,
                        "施行范围": "无",
                        "颁布方式": "普通",
                        "参与人": [{"character_id": first, "tier": "主办"}],
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
        from tests.month_chain_helpers import make_light_session
        session = make_light_session(db, state, content)
        staged = []
        for draft in result["drafts"]:
            directive = session.add_directive(draft["draft_text"], dossier_payload=draft)
            db.ensure_dossiers_for_draft_directives(state)
            staged.append(db.dossiers.get_for_directive(directive.id))
        assert len(staged) == 2
        assert [item["character_id"] for item in staged[0]["participant_roster"]] == [first]
        payload = json.loads(staged[0]["payload_json"])
        assert staged[0]["action_type"] == "assignment"
        assert staged[0]["target_kind"] == "region"
        assert staged[0]["target_id"] == "shaanxi"
        assert payload["locality_scope"] == "single"
        assert payload["transaction_category"] == "督赈"
        assert staged[1]["target_id"] == "guanning"
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
