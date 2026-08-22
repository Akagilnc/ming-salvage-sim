"""国策结案实体后果 + 全局严格(不静默)。

覆盖 issues._apply_issue_entities 与底层 apply：
- 建军 / 补兵 / 人物状态(死/流放/下狱) 真落库
- 非法 delta 抛错中断，绝不静默跳过（用户拍板的全局严格·选项1）
"""

from __future__ import annotations

import pytest

import ming_sim.issues as I
from ming_sim.memories import effect_brief
from tests.conftest import active_ming_character



def _decree_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(state, action_type="policy", decree_text="测试国策来源", target_kind="issue", target_id="test")
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"

def _army_count(db) -> int:
    return db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]


def _pay_source() -> dict[str, object]:
    return {
        "pay_source_region": "shaanxi",
        "province_pay_share": 1.0,
        "central_pay_share": 0.0,
    }


def test_resolve_creates_army(game):
    db, state, _ = game
    before = _army_count(db)
    effect = {"new_armies": [{
        "id": "tianxiongjun_test", "name": "天雄军测试", "owner_power": "ming",
        "manpower": 18000, "maintenance_per_turn": 3, "commander": "卢象升",
        "station": "大名", "troop_type": "步", **_pay_source(),
    }]}
    I._apply_issue_entities(db, state, effect, "局势#测试结案")
    assert _army_count(db) == before + 1
    row = db.conn.execute("SELECT manpower, commander FROM armies WHERE id='tianxiongjun_test'").fetchone()
    assert row["manpower"] == 18000
    assert row["commander"] == "卢象升"


def test_resolve_changes_character_status(game):
    db, state, content = game
    name = active_ming_character(db, content)
    before_logs = db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0]
    I._apply_issue_entities(db, state, {
        "character_status_changes": [{"name": name, "status": "exiled", "reason": "国策清算"}],
    }, "局势#测试结案")
    assert db.get_character_status(name)[0] == "exiled"
    assert db.conn.execute("SELECT COUNT(*) FROM person_logs").fetchone()[0] == before_logs + 1
    log = db.conn.execute(
        "SELECT person_name, action, payload_summary, derived_from, source "
        "FROM person_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert dict(log) == {
        "person_name": name,
        "action": "处置",
        "payload_summary": "国策清算",
        "derived_from": "局势#测试结案",
        "source": "system_simulation",
    }


def test_legacy_issue_status_change_uses_person_transition_matrix(game):
    db, state, content = game
    name = active_ming_character(db, content)
    db.set_character_status(state, name, "dead", "前置死亡")
    content.characters[name].status = "dead"

    with pytest.raises(ValueError, match="dead 无 status 出边"):
        I._apply_issue_entities(
            db,
            state,
            {
                "character_status_changes": [
                    {"name": name, "status": "dismissed", "reason": "旧键误写罢黜"}
                ]
            },
            "局势#测试结案",
            content=content,
        )

    assert db.get_character_status(name)[0] == "dead"
    assert content.characters[name].status == "dead"


def test_legacy_issue_status_change_does_not_use_month_end_active_gate(game):
    db, state, content = game
    name = active_ming_character(db, content)
    ch = content.characters[name]
    old_status = ch.status
    old_office = ch.office
    old_transit_to = ch.transit_to

    try:
        db.set_character_status(state, name, "imprisoned", "前置下狱")
        ch.status = "imprisoned"
        ch.office = ""
        ch.transit_to = ""

        I._apply_issue_entities(
            db,
            state,
            {
                "character_status_changes": [
                    {"name": name, "status": "dead", "reason": "结案赐死"}
                ]
            },
            "局势#测试结案",
            content=content,
        )

        assert db.get_character_status(name)[0] == "dead"
        assert ch.status == "dead"
    finally:
        ch.status = old_status
        ch.office = old_office
        ch.transit_to = old_transit_to


def test_resolve_character_status_syncs_content_travel_state(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_transit_to = content.characters[name].transit_to

    try:
        I.apply_score_extraction(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
            content=content,
        )

        I._apply_issue_entities(
            db,
            state,
            {
                "character_status_changes": [
                    {"name": name, "status": "dismissed", "reason": "局势失败问责"}
                ]
            },
            "局势#测试结案",
            content=content,
        )

        row = db.conn.execute(
            "SELECT status, office, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "dismissed"
        assert row["office"] == ""
        assert row["transit_to"] == ""
        assert content.characters[name].status == "dismissed"
        assert content.characters[name].office == ""
        assert content.characters[name].transit_to == ""
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].transit_to = old_transit_to


def test_resolve_applies_unified_person_change_effect(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_location = content.characters[name].location
    old_transit_to = content.characters[name].transit_to

    try:
        tolerated = I._apply_issue_entities(
            db,
            state,
            {"人物变更": [{"name": name, "动作": "行止", "transit_to": "liaodong"}]},
            "局势#测试结案",
            content=content,
        )

        row = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert tolerated == []
        assert row["location"] == old_location
        assert row["transit_to"] == "liaodong"
        assert content.characters[name].transit_to == "liaodong"
    finally:
        content.characters[name].location = old_location
        content.characters[name].transit_to = old_transit_to


def test_issue_unified_person_change_shadows_legacy_person_effects(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    old_office_type = content.characters[name].office_type
    applied_person_changes = []

    try:
        I._apply_issue_entities(
            db,
            state,
            {
                "character_status_changes": [
                    {
                        "name": name,
                        "status": "imprisoned",
                        "reason_code": "陷虏",
                        "reason": "旧键应被新键遮蔽",
                    }
                ],
                "人物变更": [
                    {
                        "name": name,
                        "动作": "任命",
                        "office": "陕西总督",
                        "reason": "新键任官",
                    }
                ],
            },
            "局势#测试结案",
            content=content,
            applied_person_changes=applied_person_changes,
        )

        row = db.conn.execute(
            "SELECT status, office, reason_code FROM characters WHERE name=?", (name,)
        ).fetchone()
        assert row["status"] == "active"
        assert row["office"] == "陕西总督"
        assert row["reason_code"] == ""
        assert all(item.get("status") != "imprisoned" for item in applied_person_changes)
        assert any(item.get("new_office") == "陕西总督" for item in applied_person_changes)
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office
        content.characters[name].office_type = old_office_type


def test_resolve_rejects_bad_unified_person_change_effect(read_game):
    db, state, content = read_game

    with pytest.raises(ValueError, match="人物变更 非法"):
        I._apply_issue_entities(
            db,
            state,
            {"人物变更": [{"name": "不存在的人", "动作": "行止", "transit_to": "liaodong"}]},
            "局势#测试结案",
            content=content,
        )


@pytest.mark.parametrize("bad_effect", [{"人物变更": "bad"}, {"人物变更": ["bad"]}])
def test_issue_person_change_effect_rejects_malformed_shape(read_game, bad_effect):
    db, state, content = read_game

    with pytest.raises(ValueError, match="人物变更"):
        I._apply_issue_entities(db, state, bad_effect, "局势#测试结案", content=content)


def test_malformed_army_raises_not_silent(read_game):
    """缺 manpower 的建军必须抛错，不许静默跳过（全局严格）。"""
    db, state, _ = read_game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "broken", "name": "残军", "owner_power": "ming"}],
        }, "局势#测试")


def test_army_bad_owner_power_raises(read_game):
    db, state, _ = read_game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "x", "name": "野军", "owner_power": "不存在的势力",
                            "manpower": 1000, "maintenance_per_turn": 1}],
        }, "局势#测试")


def test_unknown_character_raises(read_game):
    db, state, _ = read_game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": [{"name": "查无此人张三", "status": "dead"}],
        }, "局势#测试")


def test_bad_status_raises(read_game):
    db, state, content = read_game
    name = active_ming_character(db, content)
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": [{"name": name, "status": "升仙"}],
        }, "局势#测试")


def test_empty_effect_noop(read_game):
    """无实体段的 effect 不应报错、不改军队数。"""
    db, state, _ = read_game
    before = _army_count(db)
    I._apply_issue_entities(db, state, {"metrics": {"民心": 5}}, "局势#测试")
    assert _army_count(db) == before


def test_apply_score_extraction_splits_bad_nested_entity(game):
    """ADR0015：嵌套实体坏值逐实体拒收，不带走同批好字段。"""
    db, state, _ = game
    bad = {
        "region_delta": {"shanxi": "not-a-dict", "henan": {"unrest": 1}},
    }
    applied = I.apply_score_extraction(db, state, bad)
    assert applied["validate_shape_rejections"][0]["item"] == {"entity_id": "shanxi", "raw_value": "not-a-dict"}


def test_apply_score_extraction_accepts_flat_faction_scalar(game):
    """faction_delta 支持旧扁平 int 格式 {"阉党": -10}（extractor prompt 明确允许、
    _apply_faction_dict 主动消费）。validate 不得把它当二级非 dict 误拒；class 扁平 item
    则由段适配器按 #564 契约逐项 invalid_enum 拒收，不升级成整批 shape 中止。"""
    db, state, _ = game
    # 不抛 = validate 未错杀合法 faction；非法 class item 由 adapter 逐项拒收。
    I.apply_score_extraction(db, state, {
        "faction_delta": {"阉党": -10},
        "class_delta": {"农民": 0},   # 非法扁平 class item：adapter 逐项 invalid_enum 拒收
    })


def test_apply_score_extraction_rejects_nondict_power_second_level_per_entity(game):
    """ADR0015：power_updates 二级非 dict 逐 power 拒收。"""
    db, state, _ = game
    applied = I.apply_score_extraction(db, state, {"power_updates": {"houjin": {"leverage": 1}, "mongol": "bad"}})
    assert applied["validate_shape_rejections"][0]["item"] == {"entity_id": "mongol", "raw_value": "bad"}


def test_apply_score_extraction_rejects_nondict_list_item_per_item(read_game):
    """ADR0015：list 字段含非 dict 项 → 逐项拒收。"""
    db, state, _ = read_game
    applied = I.apply_score_extraction(db, state, {"fiscal_creates": [{"key": "x"}, "bad-scalar"]})
    assert applied["validate_shape_rejections"][0]["item"] == {"raw_value": "bad-scalar"}


def test_apply_score_extraction_tolerates_null_field(read_game):
    """Gemini R1:LLM 输出某字段为 null 时,validate 不得比 apply 更严——None 当缺省 no-op,
    不抛 ValueError(apply 本就 `.get(key) or {}` 容忍)。"""
    db, state, _ = read_game
    # region_delta=None(null)+ army_delta=None,均应被当空 no-op 放行,不抛。
    I.apply_score_extraction(db, state, {"region_delta": None, "army_delta": None})


def test_apply_score_extraction_rejects_unknown_top_level_key(game):
    """#57 起源、#649 r4 分层终态改钉：未知顶层 key（拼写错，canonicalize 后仍不在 schema）
    ＝可拆 section → 按段拒收留痕、其余 section 照落，不整份 ValueError（ADR 0015）。"""
    db, state, _ = game
    applied = I.apply_score_extraction(
        db, state, {"region_delta_typo": {"shanxi": {"unrest": 5}}, "metric_delta": {"民心": 1}},
    )
    shape = [r for r in applied["validate_shape_rejections"]
             if "region_delta_typo" in str(r.get("reason"))]
    assert shape and shape[0]["rejected"] is True
    assert shape[0]["item"] == {"raw_value": {"shanxi": {"unrest": 5}}}
    assert applied["metric_delta"].get("民心") == 1  # 其余 section 不受累


def test_resolve_army_delta_reinforces_existing(game):
    """国策给既有军扩编：army_delta 累加到该军兵额（不新建）。"""
    db, state, _ = game
    before = _army_count(db)
    old = db.conn.execute("SELECT manpower FROM armies WHERE id='jingying'").fetchone()["manpower"]
    I._apply_issue_entities(db, state, {
        "army_delta": {"jingying": {"manpower": 500, "reason": "国策募兵补京营"}},
    }, "局势#测试结案")
    new = db.conn.execute("SELECT manpower FROM armies WHERE id='jingying'").fetchone()["manpower"]
    assert new == old + 500
    assert _army_count(db) == before          # 扩编不新建军队


def test_army_delta_unknown_army_raises(read_game):
    """army_delta 引用未入库军队 → 抛错中断（全局严格，绝不静默）。"""
    db, state, _ = read_game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "army_delta": {"查无此军": {"manpower": 100}},
        }, "局势#测试")


def test_non_dict_character_status_item_raises(read_game):
    """character_status_changes 含非 dict 项 → 抛错，不静默丢（docstring 称全局严格，CMR F7）。"""
    db, state, _ = read_game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": ["这不是dict"],
        }, "局势#测试")


def test_new_issue_nondict_effect_fields_do_not_crash(game, monkeypatch):
    """LLM 把 effect 字段给成非 dict(字符串/数组) → isinstance 守门归 {}，不让 dict() 抛错
    越过单条拒绝、崩整月落库（codexB-P1）。"""
    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)   # 不触发 enrich
    before = db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "效果字段畸形国策", "kind": "initiative",
            "effect_on_resolve": "这是字符串不是dict",   # 恶意非 dict（旧码 dict() 会抛 ValueError）
            "ongoing_effects": ["也不是dict"],
            "effect_on_fail": None,
        }],
    })
    # 不抛错、整月不崩；该国策被正常处理(创建)
    new = [e for e in out["new_issues"] if e.get("title") == "效果字段畸形国策"]
    assert new and not new[0].get("rejected")
    assert db.conn.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == before + 1


def test_initiative_floor_applies_when_enrich_empty(game, monkeypatch):
    """CLI 后端国策 enrich 没补出 resolve（或抛错）时，floor 兜最小回报，绝不入空壳（codexB）。"""
    import ming_sim.cli_backend as _cb
    db, state, _ = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    I.apply_issue_tracker_output(db, state, {
        "new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "空回报国策", "kind": "initiative"}],
    })
    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='空回报国策'").fetchone()
    assert row is not None                         # 国策入库了
    import json as _j
    assert _j.loads(row["effect_on_resolve"]) == {"metrics": {"民心": 1}}   # floor 生效，非空壳


def test_runtime_cli_initiative_floor_applies_without_backend_env(game, monkeypatch):
    """runtime CLI 通道无 env 时，月末国策空回报也要走 CLI floor，不能落空壳。"""
    import json as _j
    from ming_sim.models import LLMConfig
    import ming_sim.cli_backend as _cb

    db, state, _ = game
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: {"effect_on_resolve": {}, "ongoing_effects": {}, "effect_on_fail": {}})
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    I.apply_score_extraction(db, state, {
        "new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "runtime空回报国策", "kind": "initiative"}],
    }, llm_config=cfg)

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='runtime空回报国策'").fetchone()
    assert row is not None
    assert _j.loads(row["effect_on_resolve"]) == {"metrics": {"民心": 1}}


def test_api_channel_initiative_does_not_use_backend_env_floor(game, monkeypatch):
    """显式 API 通道下，即便 env 残留 CLI backend，也不能触发 CLI-only 国策补全/floor。"""
    import json as _j
    from ming_sim.models import LLMConfig
    import ming_sim.cli_backend as _cb

    db, state, _ = game
    called = []
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(_cb, "enrich_initiative_effects",
                        lambda *a, **k: called.append((a, k)) or {
                            "effect_on_resolve": {},
                            "ongoing_effects": {},
                            "effect_on_fail": {},
                        })
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-api",
        channel="api",
    )

    I.apply_score_extraction(db, state, {
        "new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "title": "api空回报国策", "kind": "initiative"}],
    }, llm_config=cfg)

    row = db.conn.execute(
        "SELECT effect_on_resolve FROM issues WHERE title='api空回报国策'").fetchone()
    assert row is not None
    assert called == []
    assert _j.loads(row["effect_on_resolve"]) == {}


def test_inertia_natural_resolve_applies_entities(game):
    """issue 靠 inertia 自然推到 100 结案 → effect_on_resolve 的实体后果(建军)也要落，
    不能只落 metrics/economy；须与 tracker advance/close 路径一致（codexB-P1）。"""
    from ming_sim.issues import apply_issue_inertia_and_ongoing
    db, state, _ = game
    db.insert_issue(
        state, kind="situation", title="自然结案建军测试",
        bar_value=99, inertia=1,
        effect_on_resolve={"new_armies": [{
            "id": "inertia_army_test", "name": "惯性军", "owner_power": "ming",
            "manpower": 5000, "maintenance_per_turn": 1, **_pay_source()}]},
    )
    apply_issue_inertia_and_ongoing(db, state)   # inertia +1 把 bar 99→100 → resolved
    cnt = db.conn.execute(
        "SELECT COUNT(*) FROM armies WHERE id='inertia_army_test'").fetchone()[0]
    assert cnt == 1                               # 自然结案也建了奖励军


def test_inertia_natural_resolve_applies_unified_person_change_with_bound_content(game):
    """自然结案的人物变更与 tracker close 同口径,不能因缺 content 误拒合法在册人物。"""
    from ming_sim.issues import apply_issue_inertia_and_ongoing
    db, state, content = game
    name = active_ming_character(db, content)
    old_office = content.characters[name].office

    try:
        db.insert_issue(
            state, kind="situation", title="自然结案人事测试",
            bar_value=99, inertia=1,
            effect_on_resolve={
                "人物变更": [
                    {
                        "name": name,
                        "动作": "调任",
                        "office": "陕西总督",
                        "office_type": "督抚",
                        "reason": "自然结案调任",
                    }
                ]
            },
        )

        apply_issue_inertia_and_ongoing(db, state)

        row = db.conn.execute("SELECT office FROM characters WHERE name=?", (name,)).fetchone()
        assert row["office"] == "陕西总督"
        assert content.characters[name].office == "陕西总督"
    finally:
        content.characters[name].office = old_office


def test_issue_resolve_person_effect_is_visible_to_effect_brief(game):
    db, state, content = game
    name = active_ming_character(db, content)
    old_status = content.characters[name].status
    old_office = content.characters[name].office
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title="结案人事摘要测试",
        bar_value=50,
        effect_on_resolve={
            "人物变更": [
                {"name": name, "动作": "处置", "status": "dismissed", "reason": "结案问责"}
            ]
        },
    )

    try:
        applied = I.apply_score_extraction(
            db,
            state,
            {
                "close_issues": [
                    {"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}
                ]
            },
            content=content,
        )

        assert applied["issue_summary"]["applied_person_changes"] == [
            {"name": name, "动作": "处置", "status": "dismissed", "reason": "结案问责"}
        ]
        assert f"处分：{name}" in effect_brief({"issue_summary": applied["issue_summary"]})
    finally:
        content.characters[name].status = old_status
        content.characters[name].office = old_office


def test_inertia_natural_fail_applies_entities(game):
    """issue 靠 inertia 自然跌到 0 失败 → effect_on_fail 的实体后果(人物状态)也要落。"""
    from ming_sim.issues import apply_issue_inertia_and_ongoing
    from tests.conftest import active_ming_character
    db, state, content = game
    name = active_ming_character(db, content)
    db.insert_issue(
        state, kind="situation", title="自然失败人物测试",
        bar_value=1, inertia=-1,
        effect_on_fail={"character_status_changes": [{"name": name, "status": "dismissed", "reason": "局势失控问责"}]},
    )
    apply_issue_inertia_and_ongoing(db, state)   # inertia -1 把 bar 1→0 → failed
    assert db.get_character_status(name)[0] == "dismissed"
