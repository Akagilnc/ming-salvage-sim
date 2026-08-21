"""#633 [479·S2] 结算口：extractor 边事件模块——契约·捕获·落库。

验收对表（冻结票面 + 庭裁 r1/r2）：
- 邸报大臣互动经 extractor delta → apply_score_extraction → relation_edge_events 落库，
  origin 回指本回合（TD-1 结算侧）。
- relations 模块并入既有 ThreadPoolExecutor 并发装配，无第二套编排。
- 捕获为空零事件零副作用；shape 垃圾按既有 extractor 契约拒收。
- F1：context 存储零删改——strip 只作非空谓词，全链字节相等。
- F2（r2）：基数=每条互动、每「施动者→受动者」有序对恰一行；N 方联名=牵头→各联署
  N-1 行；负向=无反向行/联署互连行；断言 source/target/kind 三元组而非「有一行」。
"""

from __future__ import annotations

import json

from ming_sim.issues import apply_score_extraction
from ming_sim.relations import (
    MINISTER_EDGE_KINDS,
    settlement_edge_origin,
)
from ming_sim.simulation import (
    EMPTY_EXTRACTION,
    EXTRACTION_MODULES,
    MODULE_FIELDS,
    _FIELD_OWNER_MODULE,
)


def _edge_rows(db, **kw):
    return db.get_relation_edge_events(**kw)


def _triplets(rows):
    return {(r["source"], r["target"], r["event_kind"]) for r in rows}


# ── 路由归属：受控 section 归 relations 独占槽 ────────────────────────


def test_relation_edge_events_slot_owned_by_relations_module():
    assert "relations" in EXTRACTION_MODULES
    assert MODULE_FIELDS["relations"] == {"relation_edge_events"}
    assert "relation_edge_events" in EMPTY_EXTRACTION
    assert EMPTY_EXTRACTION["relation_edge_events"] == []
    assert _FIELD_OWNER_MODULE["relation_edge_events"] == "relations"


# ── TD-1 结算侧：当场落库、origin 回指本回合、方向三元组 ─────────────


def test_settlement_interaction_lands_directed_edge_with_origin_round(game):
    db, state, content = game
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [{
                "施动者": "毕自严", "受动者": "王绍徽", "类目": "使绊",
                "语境": "毕自严在户部用度上挡了王绍徽的路。",
                "来源引用": "盘面自发",
            }],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    assert not any(r.get("rejected") for r in res), res
    rows = _edge_rows(db, source="毕自严", target="王绍徽")
    assert len(rows) == 1
    row = rows[0]
    # F2：断言 source/target/kind 三元组，非「有一行」
    assert (row["source"], row["target"], row["event_kind"]) == (
        "毕自严", "王绍徽", "使绊",
    )
    # TD-1：origin 回指本回合
    assert row["turn"] == state.turn
    assert row["origin_round"] == state.turn
    assert f"|round:{state.turn}" in row["origin"]
    assert row["origin"] == settlement_edge_origin("盘面自发", "使绊") + f"|round:{state.turn}"
    # 反向无边（写端不做对称翻倍）
    assert _edge_rows(db, source="王绍徽", target="毕自严") == []


# ── r2 F2 基数：三人联名=牵头→各联署恰两行；负向禁例 ─────────────────


def test_three_way_joint_memorial_expands_lead_to_each_cosigner_only(game):
    db, state, content = game
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [{
                "施动者": "温体仁",
                "受动者": ["钱龙锡", "闵洪学"],
                "类目": "联名",
                "语境": "温体仁牵头联合钱龙锡、闵洪学上疏。",
                "来源引用": "盘面自发",
            }],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    assert not any(r.get("rejected") for r in res), res
    rows = [r for r in _edge_rows(db) if r["event_kind"] == "联名"]
    # 正例：唯一应有集合 {甲→乙, 甲→丙}，同 origin
    assert _triplets(rows) == {
        ("温体仁", "钱龙锡", "联名"),
        ("温体仁", "闵洪学", "联名"),
    }
    assert len(rows) == 2
    assert len({r["origin"] for r in rows}) == 1
    # 负向：不得出现乙→丙、丙→乙、乙→甲、丙→甲或任何反向/重复行
    pairs = [(r["source"], r["target"]) for r in rows]
    assert pairs.count(("温体仁", "钱龙锡")) == 1
    assert pairs.count(("温体仁", "闵洪学")) == 1
    banned = {("钱龙锡", "闵洪学"), ("闵洪学", "钱龙锡"),
              ("钱龙锡", "温体仁"), ("闵洪学", "温体仁")}
    assert not banned & set(pairs)


def test_replayed_delta_does_not_double_write(game):
    """结算重放（恢复/重试）幂等：UNIQUE(source,target,kind,context,origin) 吸收重复。"""
    db, state, content = game
    delta = {
        "relation_edge_events": [{
            "施动者": "杨嗣昌", "受动者": ["徐光启"], "类目": "协作",
            "语境": "杨嗣昌与徐光启当面相发明历法。",
            "来源引用": "盘面自发",
        }],
    }
    apply_score_extraction(db, state, json.loads(json.dumps(delta)), content=content)
    apply_score_extraction(db, state, json.loads(json.dumps(delta)), content=content)
    rows = [r for r in _edge_rows(db) if r["event_kind"] == "协作"]
    assert len(rows) == 1


# ── 空捕获：零事件零副作用 ───────────────────────────────────────────


def test_empty_capture_writes_nothing(game):
    db, state, content = game
    before = db.conn.execute(
        "SELECT COUNT(*) AS c FROM relation_edge_events"
    ).fetchone()["c"]
    out = apply_score_extraction(
        db, state, {"relation_edge_events": []}, content=content,
    )
    assert out["relation_edge_event_resolutions"] == []
    after = db.conn.execute(
        "SELECT COUNT(*) AS c FROM relation_edge_events"
    ).fetchone()["c"]
    assert after == before == 0


# ── shape 垃圾按既有契约拒收 ─────────────────────────────────────────


def test_shape_garbage_rejected_per_existing_extractor_contract(game):
    db, state, content = game
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [
                "不是对象",  # 非 dict item → sanitize 层逐项拒收
                {"施动者": "甲", "受动者": "乙", "类目": "擅自发明", "语境": "x"},  # 未知类目
                {"施动者": "甲", "受动者": "乙", "类目": "结怨", "语境": "   "},  # 空语境
                {"受动者": "乙", "类目": "结怨", "语境": "缺施动者"},  # 缺施动者
                {"施动者": "甲", "受动者": "皇帝", "类目": "兑现所托", "语境": "君臣类目不归本口"},
            ],
        },
        content=content,
    )
    # 非 dict item 由既有 sanitize_delta_shape 列表逐项拒收（ADR 0015 形，raw_value 载荷）
    validate_rejections = out["validate_shape_rejections"]
    assert any(
        isinstance(r.get("item"), dict) and r["item"].get("raw_value") == "不是对象"
        for r in validate_rejections
    )
    # 内容级坏项由适配器逐条拒收留痕，不阻塞其它项
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 4
    assert all(r["category"] == "invalid_relation_event" for r in rejected)
    assert any("未知边事件类目" in r["reason"] for r in rejected)
    assert any("语境不能为空" in r["reason"] for r in rejected)
    assert any("施动者不能为空" in r["reason"] for r in rejected)
    assert any("只收大臣侧类目" in r["reason"] for r in rejected)
    # 全部拒收：库里零写入
    assert _edge_rows(db) == []


def test_module_misroute_of_relation_field_is_stripped_not_applied(monkeypatch):
    """大臣互动错放进其它模块：白名单剔除 + misroute 留痕，不落库。"""
    from ming_sim.simulation import _sanitize_module_output

    msgs: list[str] = []
    import ming_sim.simulation as sim
    monkeypatch.setattr(sim, "tlog", lambda m: msgs.append(m))
    out = _sanitize_module_output(
        "issues",
        {"new_issues": [], "relation_edge_events": [{"施动者": "甲"}]},
    )
    assert out.get("relation_edge_events") in ([], None)
    hit = next(
        r for r in (out.get("_module_rejections") or [])
        if (r.get("item") or {}).get("field") == "relation_edge_events"
    )
    assert hit["category"] == "misrouted_field"
    assert "relations" in hit["reason"]


# ── F1：context 存储零删改，全链字节相等 ────────────────────────────


def test_context_stored_byte_identical_through_full_chain(game):
    """含首尾空白+换行的 context 经 extractor JSON → apply → DB 字节相等。"""
    db, state, content = game
    raw_context = "  毕自严当面替王绍徽担名。\n\t"
    payload = {
        "relation_edge_events": [{
            "施动者": "毕自严", "受动者": ["王绍徽"], "类目": "站台",
            "语境": raw_context, "来源引用": "盘面自发",
        }],
    }
    extracted = json.loads(json.dumps(payload, ensure_ascii=False))
    apply_score_extraction(db, state, extracted, content=content)
    row = _edge_rows(db, source="毕自严", target="王绍徽")[0]
    assert row["context"] == raw_context  # 字节相等，无 strip/裁剪/归一


def test_writer_stores_whitespace_context_byte_identical(game):
    """S1 写缝直接验收：record_relation_edge_event 对空白语境存储原样。"""
    db, state, _ = game
    raw = "\n  带首尾空白的把柄语境。\t\n"
    db.record_relation_edge_event(
        source="甲", target="乙", event_kind="把柄",
        context=raw, origin="settle:f1-probe", turn=state.turn,
    )
    row = _edge_rows(db, source="甲", target="乙")[0]
    assert row["context"] == raw
    # 空白语境仍拒收（strip 只作非空谓词）
    import pytest
    with pytest.raises(ValueError, match="语境不能为空"):
        db.record_relation_edge_event(
            source="甲", target="乙", event_kind="把柄",
            context="   \n\t ", origin="settle:f1-blank", turn=state.turn,
        )


# ── P5 并行装配：新模块并入同一 executor，不串行 ────────────────────


_CANNED = {
    "internal": '{"economy_moves": [], "fiscal_changes": [], "fiscal_creates": [], "fiscal_removes": []}',
    "military_external": '{"army_delta": {}, "new_armies": [], "power_updates": {}, "world_advance": {}}',
    "issues": '{"issue_advances": [], "new_issues": [], "事件结局": {}, "cancels": [], "close_issues": []}',
    "personnel_secret": '{"人物变更": [], "secret_order_updates": [], "emperor_fate": null}',
    "relations": '{"大臣互动": [{"施动者": "温体仁", "受动者": ["钱龙锡"], "类目": "联名", "语境": "联名上疏。"}]}',
}


def _module_of(tag: str) -> str:
    return tag.split("/", 1)[1]


def test_relations_module_joins_parallel_extraction(read_game, monkeypatch):
    """五模块同一 ThreadPoolExecutor 并发装配；merged/localized 含大臣互动段。"""
    import ming_sim.simulation as sim

    tags: list[str] = []

    def _fake_run(agent, prompt, tag):
        tags.append(tag)
        if tag.startswith("extractor/"):
            return _CANNED[_module_of(tag)]
        return prompt

    db, state, content = read_game
    monkeypatch.setattr(sim, "run_agent_text", _fake_run)
    agents = {m: object() for m in EXTRACTION_MODULES}
    merged, localized, _inputs = sim.extract_scores_by_modules_with_agno(
        agents, db, state, "邸报", parallel=True,
    )
    assert sorted(tags.count(f"extractor/{m}") for m in EXTRACTION_MODULES) == [1] * len(EXTRACTION_MODULES)
    items = merged["relation_edge_events"]
    assert [it["施动者"] for it in items] == ["温体仁"]
    assert "大臣互动" in localized
