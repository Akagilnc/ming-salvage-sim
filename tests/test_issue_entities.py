"""国策结案实体后果 + 全局严格(不静默)。

覆盖 issues._apply_issue_entities 与底层 apply：
- 建军 / 补兵 / 人物状态(死/流放/下狱) 真落库
- 非法 delta 抛错中断，绝不静默跳过（用户拍板的全局严格·选项1）
"""

from __future__ import annotations

import pytest

import ming_sim.issues as I
from tests.conftest import active_ming_character


def _army_count(db) -> int:
    return db.conn.execute("SELECT COUNT(*) FROM armies").fetchone()[0]


def test_resolve_creates_army(game):
    db, state, _ = game
    before = _army_count(db)
    effect = {"new_armies": [{
        "id": "tianxiongjun_test", "name": "天雄军测试", "owner_power": "ming",
        "manpower": 18000, "maintenance_per_turn": 3, "commander": "卢象升",
        "station": "大名", "troop_type": "步",
    }]}
    I._apply_issue_entities(db, state, effect, "局势#测试结案")
    assert _army_count(db) == before + 1
    row = db.conn.execute("SELECT manpower, commander FROM armies WHERE id='tianxiongjun_test'").fetchone()
    assert row["manpower"] == 18000
    assert row["commander"] == "卢象升"


def test_resolve_changes_character_status(game):
    db, state, content = game
    name = active_ming_character(db, content)
    I._apply_issue_entities(db, state, {
        "character_status_changes": [{"name": name, "status": "exiled", "reason": "国策清算"}],
    }, "局势#测试结案")
    assert db.get_character_status(name)[0] == "exiled"


def test_malformed_army_raises_not_silent(game):
    """缺 manpower 的建军必须抛错，不许静默跳过（全局严格）。"""
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "broken", "name": "残军", "owner_power": "ming"}],
        }, "局势#测试")


def test_army_bad_owner_power_raises(game):
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "new_armies": [{"id": "x", "name": "野军", "owner_power": "不存在的势力",
                            "manpower": 1000, "maintenance_per_turn": 1}],
        }, "局势#测试")


def test_unknown_character_raises(game):
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": [{"name": "查无此人张三", "status": "dead"}],
        }, "局势#测试")


def test_bad_status_raises(game):
    db, state, content = game
    name = active_ming_character(db, content)
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "character_status_changes": [{"name": name, "status": "升仙"}],
        }, "局势#测试")


def test_empty_effect_noop(game):
    """无实体段的 effect 不应报错、不改军队数。"""
    db, state, _ = game
    before = _army_count(db)
    I._apply_issue_entities(db, state, {"metrics": {"民心": 5}}, "局势#测试")
    assert _army_count(db) == before


def test_apply_score_extraction_validates_before_half_apply(game):
    """#57:apply_score_extraction 在任何 DB 改动前校验 delta 容器/二级类型——畸形二级 dict
    不让前面的 metric/economy 先落库再在 region apply 崩(half-落库,违反 P1 落库铁律)。
    真实流此前只有 driver 侧 _validate_delta_shape;现在落库核自身也守。"""
    db, state, _ = game
    treasury_before = state.metrics.get("国库")
    bad = {
        "metric_delta": {"国库": 50},                 # 合法,排在 region 之前处理
        "region_delta": {"shanxi": "not-a-dict"},     # 二级非 dict → 落库前应抛 ValueError
    }
    with pytest.raises(ValueError):
        I.apply_score_extraction(db, state, bad)
    # 校验在 apply 之前 → metric 不该已落库
    assert state.metrics.get("国库") == treasury_before


def test_apply_score_extraction_accepts_flat_faction_scalar(game):
    """CMR(Claude+codex concur,HIGH):faction_delta 支持旧扁平 int 格式 {"阉党": -10}
    (extractor prompt 明确允许、_apply_faction_dict 主动消费)。validate 不得把它当二级非 dict
    误拒,否则合法 extractor 输出会让真实流 settle 整个崩。class 非 dict 同样应被放行(apply 静默跳)。"""
    db, state, _ = game
    # 不抛 = 通过;扁平 int faction + 非 dict class 都该被 validate 放行(apply 各自容忍)。
    I.apply_score_extraction(db, state, {
        "faction_delta": {"阉党": -10},
        "class_delta": {"农民": 0},   # 非 dict 二级:_apply_class_dict 静默跳,validate 不该拒
    })


def test_apply_score_extraction_tolerates_null_field(game):
    """Gemini R1:LLM 输出某字段为 null 时,validate 不得比 apply 更严——None 当缺省 no-op,
    不抛 ValueError(apply 本就 `.get(key) or {}` 容忍)。"""
    db, state, _ = game
    # region_delta=None(null)+ army_delta=None,均应被当空 no-op 放行,不抛。
    I.apply_score_extraction(db, state, {"region_delta": None, "army_delta": None})


def test_apply_score_extraction_rejects_unknown_top_level_key(game):
    """#57:落库核拒未知顶层 key(拼写错=静默无效落库)。用 canonicalize 之后仍不在 schema 的
    真·未知 key(非中文别名——别名会被 _canonicalize_extraction 映射成合法 key,Red Team RT-C)。"""
    db, state, _ = game
    with pytest.raises(ValueError):
        I.apply_score_extraction(db, state, {"region_delta_typo": {"shanxi": {"unrest": 5}}})


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


def test_army_delta_unknown_army_raises(game):
    """army_delta 引用未入库军队 → 抛错中断（全局严格，绝不静默）。"""
    db, state, _ = game
    with pytest.raises(ValueError):
        I._apply_issue_entities(db, state, {
            "army_delta": {"查无此军": {"manpower": 100}},
        }, "局势#测试")


def test_non_dict_character_status_item_raises(game):
    """character_status_changes 含非 dict 项 → 抛错，不静默丢（docstring 称全局严格，CMR F7）。"""
    db, state, _ = game
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
            "origin_kind": "decree", "title": "效果字段畸形国策", "kind": "initiative",
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
        "new_issues": [{"origin_kind": "decree", "title": "空回报国策", "kind": "initiative"}],
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
        "new_issues": [{"origin_kind": "decree", "title": "runtime空回报国策", "kind": "initiative"}],
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
        "new_issues": [{"origin_kind": "decree", "title": "api空回报国策", "kind": "initiative"}],
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
            "manpower": 5000, "maintenance_per_turn": 1}]},
    )
    apply_issue_inertia_and_ongoing(db, state)   # inertia +1 把 bar 99→100 → resolved
    cnt = db.conn.execute(
        "SELECT COUNT(*) FROM armies WHERE id='inertia_army_test'").fetchone()[0]
    assert cnt == 1                               # 自然结案也建了奖励军


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
