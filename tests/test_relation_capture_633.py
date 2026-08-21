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
                "受动者": ["周延儒", "黄立极"],
                "类目": "联名",
                "语境": "温体仁牵头联合周延儒、黄立极上疏。",
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
        ("温体仁", "周延儒", "联名"),
        ("温体仁", "黄立极", "联名"),
    }
    assert len(rows) == 2
    assert len({r["origin"] for r in rows}) == 1
    # 负向：不得出现乙→丙、丙→乙、乙→甲、丙→甲或任何反向/重复行
    pairs = [(r["source"], r["target"]) for r in rows]
    assert pairs.count(("温体仁", "周延儒")) == 1
    assert pairs.count(("温体仁", "黄立极")) == 1
    banned = {("周延儒", "黄立极"), ("黄立极", "周延儒"),
              ("周延儒", "温体仁"), ("黄立极", "温体仁")}
    assert not banned & set(pairs)


def test_replayed_delta_does_not_double_write(game):
    """结算重放（恢复/重试）幂等：UNIQUE(source,target,kind,context,origin) 吸收重复。"""
    db, state, content = game
    delta = {
        "relation_edge_events": [{
            "施动者": "杨嗣昌", "受动者": ["孙元化"], "类目": "协作",
            "语境": "杨嗣昌与孙元化当面相发炮术历法。",
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
    # 内容级坏项由适配器逐条拒收留痕，不阻塞其它项；未入名册端点也是拒收理由之一
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


def test_non_string_actor_target_context_shapes_rejected(game):
    """施动者/受动者/语境非字符串形状逐项拒收留痕，零写入（不 str() 搭救）。"""
    db, state, content = game
    base = {"受动者": "乙", "类目": "结怨", "语境": "x", "来源引用": "盘面自发"}
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [
                {"施动者": 123, **base},  # 数字型施动者
                {"施动者": {"名": "甲"}, **base},  # 对象型施动者
                {"施动者": "甲", "受动者": ("乙",), "类目": "结怨",
                 "语境": "x", "来源引用": "盘面自发"},  # tuple 受动者容器
                {"施动者": "甲", "受动者": ["乙", 3], "类目": "结怨",
                 "语境": "x", "来源引用": "盘面自发"},  # 混型受动者列表
                {"施动者": "甲", "受动者": "乙", "类目": "结怨",
                 "语境": 42, "来源引用": "盘面自发"},  # 数字型语境
                {"施动者": "甲", "受动者": "乙", "类目": "结怨",
                 "语境": {"句": "x"}, "来源引用": "盘面自发"},  # 对象型语境
            ],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 6
    assert all(r["category"] == "invalid_relation_event" for r in rejected)
    assert any("施动者必须为字符串" in r["reason"] for r in rejected)
    assert any("受动者必须为字符串或字符串列表" in r["reason"] for r in rejected)
    assert any("语境必须为字符串" in r["reason"] for r in rejected)
    assert _edge_rows(db) == []


def test_missing_or_forged_provenance_rejected_with_trace_no_edges(game):
    """缺 provenance/伪前缀/未知未授权案卷/自带 round 的伪造值：逐项拒收留痕不落边。"""
    db, state, content = game
    base = {"施动者": "甲", "受动者": "乙", "类目": "结怨", "语境": "x"}
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [
                dict(base),  # 缺 provenance 条目
                {**base, "来源引用": None},  # 空来源
                {**base, "来源引用": "   "},  # 空白来源
                {**base, "来源引用": "盘面自发|round:999"},  # 伪造当前回合回指
                {**base, "来源引用": "dossier:999999"},  # 未知案卷
                {**base, "来源引用": "fake"},  # 伪前缀自由文本
                {**base, "来源引用": " 盘面自发 "},  # 空白包裹哨兵变体
                {**base, "来源引用": "\n盘面自发\t"},  # 换行/制表包裹变体
            ],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 8
    assert all(r["category"] == "invalid_relation_event" for r in rejected)
    assert all(
        "origin_ref" in r["reason"] or "来源引用" in r["reason"]
        or "本批冻结输入" in r["reason"]
        for r in rejected
    )
    # 全部拒收：库里零边、无任何 origin 被默认成「盘面自发」落库
    assert _edge_rows(db) == []


def test_whitespace_padded_noncanonical_origins_rejected_no_strip_rescue(game):
    """r2 残余：来源只收精确 canonical 值——空白/变体一律拒收留痕，不 strip 后放行。

    庭裁 probe：守门曾先 strip 后授权，把非 canonical provenance 归一成合法
    来源（fail-open）；本负例钉死精确匹配契约。"""
    db, state, content = game
    base = {"施动者": "甲", "受动者": "乙", "类目": "结怨", "语境": "x"}
    variants = [" 盘面自发 ", "\n盘面自发\t", "盘面自发\n", "\t盘面自发", "盘面自发 "]
    out = apply_score_extraction(
        db, state,
        {"relation_edge_events": [{**base, "来源引用": v} for v in variants]},
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == len(variants), res
    assert all(r["category"] == "invalid_relation_event" for r in rejected)
    assert all("不归一首尾空白" in r["reason"] for r in rejected)
    # 零写入：无任何归一后的「盘面自发」origin 溜进库
    assert _edge_rows(db) == []


def test_settlement_edge_origin_rejects_missing_and_non_string():
    """拼装器本体不再静默默认哨兵；缺失/非字符串诚实报错。"""
    import pytest

    from ming_sim.relations import settlement_edge_origin

    with pytest.raises(ValueError, match="来源引用必须为字符串"):
        settlement_edge_origin(None, "联名")
    with pytest.raises(ValueError, match="来源引用必须为字符串"):
        settlement_edge_origin(123, "联名")
    with pytest.raises(ValueError, match="盘面自然演化须显式标为"):
        settlement_edge_origin("   ", "联名")
    # 合法条目照常拼装；拼装器不独立 strip——值原样进入 origin（空白只作非空谓词）
    assert settlement_edge_origin("盘面自发", "联名") == "盘面自发:relation:联名"


def _promulgated_dossier(db, state, holder, token):
    """建并颁布一个案卷，返回 id（effect_origin_rejection 授权路径）。"""
    did = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="结算口来源验",
        target_kind="issue",
        target_id=token,
        executor_kind="character",
        executor_id=holder,
        payload={"token": token},
    )
    db.record_dossier_decision(did, "promulgated")
    return did


def test_authorized_dossier_origin_accepted_bound_to_current_turn(game):
    """冻结闭集内且已颁授权的 dossier 引用照常落边，origin_round 由当前回合绑定。"""
    db, state, content = game
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    did = _promulgated_dossier(db, state, holder, "relation-origin-633")
    db.conn.commit()
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [{
                "施动者": "毕自严", "受动者": "王绍徽", "类目": "把柄",
                "语境": "案卷授权的互动。", "来源引用": f"dossier:{did}",
            }, {
                # 空白包裹的 dossier 引用：非 canonical，逐项拒收不搭救
                "施动者": "毕自严", "受动者": "王绍徽", "类目": "结怨",
                "语境": "空白包裹的案卷引用。", "来源引用": f" dossier:{did} ",
            }],
        },
        content=content,
        dossier_ids_at_input={did},
    )
    res = out["relation_edge_event_resolutions"]
    padded = next(
        r for r in res if (r.get("item") or {}).get("语境") == "空白包裹的案卷引用。"
    )
    assert padded.get("rejected") and padded["category"] == "invalid_relation_event"
    assert "不归一首尾空白" in padded["reason"]
    assert not any(r.get("rejected") for r in res if r is not padded), res
    # 恰一行合法边落库；无归一后的 dossier origin 变体
    rows = _edge_rows(db)
    assert len(rows) == 1
    assert rows[0]["origin"] == f"dossier:{did}:relation:把柄|round:{state.turn}"
    row = _edge_rows(db, source="毕自严", target="王绍徽")[0]
    assert row["origin"] == f"dossier:{did}:relation:把柄|round:{state.turn}"
    assert row["origin_round"] == state.turn


# ── V2：dossier 来源锁本批冻结输入闭集（fail-closed 双重合取） ────────


def test_authorized_dossier_outside_frozen_batch_rejected_zero_edges(game):
    """已颁授权但不在本批冻结输入的案卷：逐项拒收留痕，好项不受牵连。"""
    db, state, content = game
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    in_batch = _promulgated_dossier(db, state, holder, "v2-in-batch")
    stale = _promulgated_dossier(db, state, holder, "v2-stale-legal-but-not-fed")
    db.conn.commit()
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [
                {"施动者": "毕自严", "受动者": "王绍徽", "类目": "把柄",
                 "语境": "陈旧无关旧旨归因。", "来源引用": f"dossier:{stale}"},
                {"施动者": "毕自严", "受动者": "王绍徽", "类目": "协作",
                 "语境": "本批闭集内合法来源。", "来源引用": f"dossier:{in_batch}"},
            ],
        },
        content=content,
        dossier_ids_at_input={in_batch},
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 1
    assert "本批冻结输入" in rejected[0]["reason"]
    assert (rejected[0]["item"]["来源引用"] == f"dossier:{stale}")
    # 好项不牵连：闭集内且授权的照常落库
    rows = _edge_rows(db)
    assert len(rows) == 1
    assert rows[0]["origin"] == f"dossier:{in_batch}:relation:协作|round:{state.turn}"


def test_unauthorized_dossier_inside_frozen_set_still_rejected(game):
    """闭集合取另一支：在本批集合但未颁/未授权（effect_origin_rejection 不过）仍拒收。"""
    db, state, content = game
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    unissued = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text="建而不颁",
        target_kind="issue",
        target_id="v2-unissued",
        executor_kind="character",
        executor_id=holder,
        payload={"token": "v2-unissued"},
    )
    db.conn.commit()
    out = apply_score_extraction(
        db, state,
        {"relation_edge_events": [{
            "施动者": "毕自严", "受动者": "王绍徽", "类目": "结怨",
            "语境": "未颁案卷引用。", "来源引用": f"dossier:{unissued}",
        }]},
        content=content,
        dossier_ids_at_input={unissued},
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 1
    assert "origin_ref 非法" in rejected[0]["reason"]
    assert _edge_rows(db) == []


def test_missing_frozen_dossier_set_is_empty_closed_set(game):
    """None/缺集按空闭集：live DB 里已颁授权也不搭救（不从 DB 重建）。"""
    db, state, content = game
    holder = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"]
    did = _promulgated_dossier(db, state, holder, "v2-fail-closed")
    db.conn.commit()
    out = apply_score_extraction(
        db, state,
        {"relation_edge_events": [{
            "施动者": "毕自严", "受动者": "王绍徽", "类目": "结怨",
            "语境": "缺冻结集时已授权也拒。", "来源引用": f"dossier:{did}",
        }]},
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 1
    assert "本批冻结输入" in rejected[0]["reason"]
    assert _edge_rows(db) == []
    # 盘面自发不受 dossier 闭集影响：同批照常落边
    out2 = apply_score_extraction(
        db, state,
        {"relation_edge_events": [{
            "施动者": "温体仁", "受动者": "周延儒", "类目": "站台",
            "语境": "盘面自发不受案卷闭集影响。", "来源引用": "盘面自发",
        }]},
        content=content,
    )
    assert not any(r.get("rejected") for r in out2["relation_edge_event_resolutions"])
    assert len(_edge_rows(db, source="温体仁", target="周延儒")) == 1


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


# ── V1：端点须为当前在朝合格大臣（复用既有名册投影，先校验后零边写入） ──


def test_hallucinated_and_emperor_endpoints_rejected_per_item_zero_edges(game):
    """幻觉名/错字/「皇帝」入大臣边端点：逐项拒收留痕，零写入。"""
    db, state, content = game
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [
                # 幻觉 source
                {"施动者": "幻觉甲", "受动者": "王绍徽", "类目": "结怨",
                 "语境": "幻觉施动者。", "来源引用": "盘面自发"},
                # 幻觉 target
                {"施动者": "毕自严", "受动者": "幻觉乙", "类目": "结怨",
                 "语境": "幻觉受动者。", "来源引用": "盘面自发"},
                # 皇帝作 source（君臣类目归 0079，皇帝节点不归大臣边任一端）
                {"施动者": "皇帝", "受动者": "王绍徽", "类目": "把柄",
                 "语境": "皇帝施动者。", "来源引用": "盘面自发"},
                # 皇帝作 target
                {"施动者": "毕自严", "受动者": "皇帝", "类目": "把柄",
                 "语境": "皇帝受动者。", "来源引用": "盘面自发"},
                # 未登场/已退场（不在当前在朝名册）
                {"施动者": "毕自严", "受动者": "徐光启", "类目": "协作",
                 "语境": "未登场人物。", "来源引用": "盘面自发"},
            ],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 5
    assert all(r["category"] == "invalid_relation_event" for r in rejected)
    assert all("当前在朝合格大臣" in r["reason"] for r in rejected)
    assert _edge_rows(db) == []


def test_multi_target_with_one_bad_endpoint_writes_zero_edges_for_item(game):
    """同互动含任一非法端点：先整项校验后零边写入，不做部分落库；好项隔离照落。"""
    db, state, content = game
    out = apply_score_extraction(
        db, state,
        {
            "relation_edge_events": [
                {"施动者": "温体仁", "受动者": ["周延儒", "幻觉丙"],
                 "类目": "联名", "语境": "联名混入幻觉联署者。",
                 "来源引用": "盘面自发"},
                {"施动者": "毕自严", "受动者": "王绍徽", "类目": "协作",
                 "语境": "同批好项照常落。", "来源引用": "盘面自发"},
            ],
        },
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    rejected = [r for r in res if r.get("rejected")]
    assert len(rejected) == 1
    assert "幻觉丙" in rejected[0]["reason"]
    # 坏项零写入（含好端点也不部分落库）；好项不受牵连
    rows = _edge_rows(db)
    assert _triplets(rows) == {("毕自严", "王绍徽", "协作")}


def test_valid_roster_endpoints_still_land_after_endpoint_gate(game):
    """两个合格在朝大臣的合法边照常落库（端点守门不误伤）。"""
    db, state, content = game
    out = apply_score_extraction(
        db, state,
        {"relation_edge_events": [{
            "施动者": "孙传庭", "受动者": ["洪承畴"], "类目": "恩义",
            "语境": "合格名册双端点。", "来源引用": "盘面自发",
        }]},
        content=content,
    )
    res = out["relation_edge_event_resolutions"]
    assert not any(r.get("rejected") for r in res), res
    assert _triplets(_edge_rows(db)) == {("孙传庭", "洪承畴", "恩义")}
