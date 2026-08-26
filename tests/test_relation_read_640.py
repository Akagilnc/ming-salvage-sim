"""#640 S9 读端交付形态＋判官读面＋P4 哨兵（冻结票面＋庭裁 r1-r3）。

验收锚：
- 「按视角取边」接口形态：参与者可见自己的边、非参与者默认不可见
  （ID-11 参与即知；裁切语义归 #472 线）。
- 返回形态＝可见边摘要＋最近原始事件/回指（ID-1/ID-11 口径，机器可断言）。
- 庭裁 r1 F2 单一接缝：角色视角与全知读面=同一 DTO、同一查询/投影核心，
  仅授权参数不同；全知结果为角色视角权限超集。
- 判官机面全知（ID-12）：fixture 断言判官能读到普通角色视角不可见的边；
  接入归 #634 线，本票不造判官。
- TD-7 双断言 oracle（庭裁 r2/r3）：①DTO 字段集合恰等五字段冻结白名单
  source/target/summary/recent_context/updated_at_period；②局部 marker 负断言
  （结构键/事件类目数据不 ride-along 进玩家可感投影输出）。
"""

from __future__ import annotations

import json

import pytest

from ming_sim.db import GameDB
from ming_sim.models import GameState
from ming_sim.relation_read import project_relation_ledger
from ming_sim.relations import EMPEROR_NODE

# 冻结票面 r3 白名单本体——独立真源（票面原文照抄），不从生产代码重推导。
FROZEN_DTO_WHITELIST = {"source", "target", "summary", "recent_context", "updated_at_period"}

# TD-7 局部 marker：测试局部唯一串（非全局词表），只进本 fixture 的结构字段。
MARKER = "TD7哨兵-640-唯一标记QINGYUAN"


def _add_edge(db, state, *, source, target, kind, context, origin):
    return db.record_relation_edge_event(
        source=source, target=target, event_kind=kind, context=context,
        origin=origin, turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )


@pytest.fixture
def ledger(game):
    """三对关系 fixture：甲→乙、皇帝→杨嗣昌（已酿制）、丙→丁。

    甲的可见面＝{甲→乙}；丙丁边对甲不可见；皇帝→杨嗣昌带两段式酿制产物。
    """
    db: GameDB
    state: GameState
    db, state, _ = game
    _add_edge(db, state, source="王绍徽", target="崔呈秀", kind="结怨",
              context="王绍徽背影里的戾气，毕自严再挡他路时还在。",
              origin=f"audience:turn-1|{MARKER}")
    db.apply_relation_brew_result(
        source=EMPEROR_NODE, target="杨嗣昌", dimension="君臣",
        founding_segment="越次一召，擢杨嗣昌于五品郎中。",
        recent_segment="杨嗣昌蒙知遇之恩，复命时记得皇爷上月简拔。",
        last_event_id=99, turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召，擢杨嗣昌于五品郎中。", origin="audience:turn-1")
    _add_edge(db, state, source="钱谦益", target="温体仁", kind="把柄",
              context="温体仁握有钱谦益科场案的把柄。",
              origin=f"dossier:9:credit:cover|round:2|{MARKER}")
    return db, state


# ---------------------------------------------------------------- 视角裁切形态


def test_participant_sees_own_edge_non_participant_default_invisible(ledger):
    """参与者即知自己的边；非参与者默认不可见（ID-11）。"""
    db, _ = ledger
    jia_view = project_relation_ledger(db, viewer="王绍徽")
    assert [(d["source"], d["target"]) for d in jia_view] == [("王绍徽", "崔呈秀")]
    # 非参与者（丙）看不见甲乙的边。
    qian_view = project_relation_ledger(db, viewer="钱谦益")
    assert [(d["source"], d["target"]) for d in qian_view] == [("钱谦益", "温体仁")]


def test_role_view_cuts_by_either_end_participation(ledger):
    """边的任一端参与即知：乙端视角同样读到该边。"""
    db, _ = ledger
    cui_view = project_relation_ledger(db, viewer="崔呈秀")
    assert [(d["source"], d["target"]) for d in cui_view] == [("王绍徽", "崔呈秀")]


def test_blank_viewer_fails_closed_not_omniscient(ledger):
    """空白 viewer fail-closed（判卷修复）：空串/纯空白是 malformed 授权参数，

    绝不静默当全知（与 None 同态）也不当任意角色；直接拒绝。
    """
    db, _ = ledger
    with pytest.raises(ValueError):
        project_relation_ledger(db, viewer="")
    with pytest.raises(ValueError):
        project_relation_ledger(db, viewer="   ")
    # 全知面仍只认显式 None，且未被空白态污染：仍读到全部三对边。
    judge_pairs = {(d["source"], d["target"]) for d in project_relation_ledger(db, viewer=None)}
    assert len(judge_pairs) == 3
    # 有效人名（含首尾空白的规范化输入）始终执行参与边过滤，不受影响。
    jia_view = project_relation_ledger(db, viewer="  王绍徽  ")
    assert [(d["source"], d["target"]) for d in jia_view] == [("王绍徽", "崔呈秀")]


def test_empty_ledger_projects_empty(ledger):
    """无账行为可辨：零边零摘要时空投影；有账后非空且含酿制产物。"""
    db, _ = ledger
    assert project_relation_ledger(db, viewer=None) != []
    fresh: GameDB = ledger[0]
    # 同核空库判别：直接另起内存库不可行（GameDB 依赖 content），改用
    # 无任何关系数据的视角人物——其可见面为空。
    assert project_relation_ledger(fresh, viewer="孙承宗") == []


# ---------------------------------------------------------------- 返回形态


def test_dto_shape_summary_plus_recent_context_with_backref(ledger):
    """返回形态＝摘要＋最近原始事件语境/回指（ID-1/ID-11，机器可断言）。"""
    db, _state = ledger
    judge_face = project_relation_ledger(db, viewer=None)
    wei_yang = next(
        d for d in judge_face
        if (d["source"], d["target"]) == (EMPEROR_NODE, "杨嗣昌")
    )
    # summary＝两段式摘要原文（奠基段＋近况段，零改写拼接）。
    assert "越次一召，擢杨嗣昌于五品郎中。" in wei_yang["summary"]
    assert "杨嗣昌蒙知遇之恩" in wei_yang["summary"]
    # recent_context＝最近原始事件语境原文＋纪年回指（括注时点）。
    assert wei_yang["recent_context"].startswith("越次一召，擢杨嗣昌于五品郎中。")
    assert wei_yang["recent_context"].endswith("（天启七年十月）")


def test_updated_at_period_is_era_label_not_bare_turn(r3_guard):
    """updated_at_period＝更新纪年语义标识（天启七年十月式），非裸 turn 数。"""
    db, state = r3_guard
    wei_yang = next(
        d for d in project_relation_ledger(db, viewer=None)
        if (d["source"], d["target"]) == (EMPEROR_NODE, "杨嗣昌")
    )
    assert wei_yang["updated_at_period"] == "天启七年十月"
    assert wei_yang["updated_at_period"] != str(state.turn)


@pytest.fixture
def r3_guard(game):
    db, state, _ = game
    db.apply_relation_brew_result(
        source=EMPEROR_NODE, target="杨嗣昌", dimension="君臣",
        founding_segment="奠.", recent_segment="近.",
        last_event_id=1, turn=5, year=1627, period=10,
    )
    return db, state


# ---------------------------------------------------------------- 判官全知机面


def test_judge_face_reads_edges_invisible_to_role_view(ledger):
    """判官机面全知（ID-12）：读到普通角色视角不可见的边；两面不混用。"""
    db, _ = ledger
    judge_face = project_relation_ledger(db, viewer=None)
    judge_pairs = {(d["source"], d["target"]) for d in judge_face}
    assert ("钱谦益", "温体仁") in judge_pairs  # 王绍徽视角不可见
    jia_pairs = {(d["source"], d["target"]) for d in project_relation_ledger(db, viewer="王绍徽")}
    assert ("钱谦益", "温体仁") not in jia_pairs
    # 有账与无账行为可辨：判官读面含酿制产物原文。
    wei_yang = next(d for d in judge_face if (d["source"], d["target"]) == (EMPEROR_NODE, "杨嗣昌"))
    assert "杨嗣昌蒙知遇之恩" in wei_yang["summary"]


def test_omniscient_is_superset_same_core(ledger):
    """庭裁 r1 F2：同一 DTO 同一投影核心，仅授权参数不同；全知＝权限超集。"""
    db, _ = ledger
    judge_face = project_relation_ledger(db, viewer=None)
    for viewer in ("王绍徽", "钱谦益", "崔呈秀"):
        role_face = project_relation_ledger(db, viewer=viewer)
        role_map = {(d["source"], d["target"]): d for d in role_face}
        judge_map = {(d["source"], d["target"]): d for d in judge_face}
        assert set(role_map) <= set(judge_map)
        for pair, dto in role_map.items():
            # 共享对逐字段全等：同一核心、同一 DTO，未走第二套序列化。
            assert dto == judge_map[pair]


# ---------------------------------------------------------------- TD-7 双断言 oracle


def test_td7_dto_field_set_equals_frozen_whitelist(ledger):
    """TD-7①：DTO 字段集合==票面冻结五字段白名单（机械集合相等，两面都咬）。"""
    db, _ = ledger
    for dto in project_relation_ledger(db, viewer=None):
        assert set(dto.keys()) == FROZEN_DTO_WHITELIST
    for dto in project_relation_ledger(db, viewer="王绍徽"):
        assert set(dto.keys()) == FROZEN_DTO_WHITELIST


def test_td7_local_marker_negative_assertion(ledger):
    """TD-7②：局部 marker 负断言——结构键/事件类目数据不进玩家可感投影输出。

    marker 只埋在本 fixture 的结构字段（origin 尾段）与绕过写口直插的
    event_kind 列；玩家可感投影（角色视角 DTO 序列化）中必须零出现。
    """
    db, state = ledger
    # 绕过 fail-closed 写口直插一条含 marker 的 event_kind 行：证明即便存储层
    # 存在该类目数据，投影也绝不 surfacing（确定性装配面，ADR 0143）。
    db.conn.execute(
        "INSERT INTO relation_edge_events "
        "(source, target, event_kind, context, origin, origin_round, turn, year, period)"
        " VALUES ('王绍徽', '崔呈秀', ?, '结构哨兵语境。', 'probe:td7', 1, 1, 1627, 10)",
        (MARKER,),
    )
    db.conn.commit()
    projection = project_relation_ledger(db, viewer="王绍徽")
    rendered = json.dumps(projection, ensure_ascii=False)
    assert MARKER not in rendered
    # 事件类目词本身也不作字段值出现（白名单恒等已保证，这里按票面再咬一口）。
    for dto in projection:
        assert "event_kind" not in dto
        assert set(dto.keys()) == FROZEN_DTO_WHITELIST


def test_missing_viewer_rejected(ledger):
    """漏传 viewer（keyword-only 必填）不被接受，绝不静默落全知机面。"""
    db, _ = ledger
    with pytest.raises(TypeError):
        project_relation_ledger(db)


# ---------------------------------------------------------------- #642 锚④：coda 历史读缝


def test_load_relation_history_before_returns_full_stable_prior_stream(game):
    """r4：已选中有向对的严格早于 settled 年月的完整历史——多旧事全量、含和解、无裁剪。"""
    from ming_sim.relation_read import load_relation_history_before

    db, state, _ = game
    source, target = "杨嗣昌", "倪元璐"
    # 旧事 1（奠基）
    db.record_relation_edge_event(
        source=source, target=target, event_kind="结怨",
        context="杨嗣昌与倪元璐初有细缝。", origin="seed:founding:yang-ni",
        turn=0, year=1627, period=10,
    )
    # 旧事 2（后续加深）
    db.record_relation_edge_event(
        source=source, target=target, event_kind="使绊",
        context="清丈议上，杨嗣昌挡了倪元璐的硬路。", origin="audience:turn-2",
        turn=2, year=1628, period=11,
    )
    # 旧事 3（和解——同流后续，不删旧怨）
    db.record_relation_edge_event(
        source=source, target=target, event_kind="协作",
        context="二人当面言和，暂释前隙。", origin="audience:turn-3",
        turn=3, year=1629, period=3,
    )
    # 本 settled 月新事——不得进入 prior
    db.record_relation_edge_event(
        source=source, target=target, event_kind="站台",
        context="本月新站台，不应进历史包。", origin="audience:turn-4",
        turn=4, year=1630, period=5,
    )

    prior = load_relation_history_before(
        db, source=source, target=target, before_year=1630, before_period=5,
    )
    assert [row["context"] for row in prior] == [
        "杨嗣昌与倪元璐初有细缝。",
        "清丈议上，杨嗣昌挡了倪元璐的硬路。",
        "二人当面言和，暂释前隙。",
    ]
    # 稳定序＝纪年 (year, period) ＋事件 id；语境字节不改。
    assert [(int(r["year"]), int(r["period"])) for r in prior] == [
        (1627, 10), (1628, 11), (1629, 3),
    ]
    ids = [int(r["id"]) for r in prior]
    assert ids == sorted(ids)
    assert prior[2]["context"] == "二人当面言和，暂释前隙。"


def test_load_relation_history_before_empty_when_no_older_events(game):
    """r4 验收第三例：无严格更早流水 → 空列表。"""
    from ming_sim.relation_read import load_relation_history_before

    db, state, _ = game
    db.record_relation_edge_event(
        source="徐光启", target="杨嗣昌", event_kind="协作",
        context="本月当场协作。", origin="audience:now",
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    prior = load_relation_history_before(
        db, source="徐光启", target="杨嗣昌",
        before_year=int(state.year), before_period=int(state.period),
    )
    assert prior == []
