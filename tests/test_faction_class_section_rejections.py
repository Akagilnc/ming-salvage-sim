"""faction_delta / class_delta 两段逐项拒收契约及不同输入形状（ADR 0008 决定 1，#14/#63）。

原先 `db.adjust_factions`/`adjust_classes` 对查无此派系/阶级名 `if not row: continue`
零痕迹静默丢（#63 死法 3、#14 模式 C），`_apply_*_dict` 对非整数值也 `continue` 静默跳
（#14 模式 A）。改为：未知名 → missing_ref 逐项拒收、坏值（含 bool/float）→ invalid_enum
逐项拒收，好项照落、坏一项不带走整批；faction 合法扁平 int / 0 增量不误拒，
class 则只收嵌套字段 dict、扁平 int 逐项拒收。

拒收项落独立 *_rejections 段（不复用 faction_delta/class_delta，后者仍载 web 面板的
已落 delta dict——cmr r1 claude：复用同 key 会令面板误渲染拒收项）。

经 driver.run_settle 端到端驱动（公共接口，与 test_power_section_rejections.py 同风格）。
"""

from __future__ import annotations

from driver import run_settle
from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows

FACTION_REJ_SECTION = "faction_delta_rejections"
CLASS_REJ_SECTION = "class_delta_rejections"


def _valid_faction(db):
    row = db.conn.execute("SELECT name FROM factions LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一个派系"
    return row[0]


def _valid_class_key(db):
    """取一个合法阶级 key（name 或 name@region_id），供「好项照落」对照。"""
    row = db.conn.execute(
        "SELECT name, region_id FROM classes LIMIT 1").fetchone()
    assert row is not None, "probe.db 需至少一个阶级"
    name, region_id = row[0], row[1]
    return f"{name}@{region_id}" if region_id else name


def test_unknown_faction_rejected_good_item_lands(game):
    """faction_delta 引用未入库派系 → 该项 missing_ref 逐项拒收留痕（不再静默 continue），
    同信封里合法派系的改动照常落库——坏一项不带走整批（ADR 决定 1）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)
    before = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "faction_delta": {"查无此派系": {"satisfaction": 5}, good: {"satisfaction": 7}},
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, FACTION_REJ_SECTION)
    assert len(rows) == 1, rows
    assert rows[0][2] == "missing_ref"
    assert rows[0][1]  # 人读原因非空
    after = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]
    assert after != before, "好项（合法派系）应照常落库"


def _class_satisfaction(db, key):
    name, region_id = (key.split("@", 1) + [""])[:2] if "@" in key else (key, "")
    return db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name=? AND region_id=?",
        (name.strip(), region_id.strip())).fetchone()[0]


def test_unknown_class_rejected_good_item_lands(game):
    """class_delta 引用未入库阶级 → missing_ref 逐项拒收留痕，合法阶级照落（好项不被坏项带走）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_class_key(db)
    before = _class_satisfaction(db, good)

    run_settle(db, state, content, {
        "class_delta": {
            "查无此阶级": {"satisfaction": 5},
            good: {"satisfaction": 6},
        },
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, CLASS_REJ_SECTION)
    assert len(rows) == 1, rows
    assert rows[0][2] == "missing_ref"
    assert rows[0][1]
    # 好项（合法阶级）应精确落库，不被坏项带走（cmr r4 codex）
    assert _class_satisfaction(db, good) == max(0, min(100, before + 6))


def test_illegal_faction_value_rejected(game):
    """faction_delta 合法派系但 satisfaction 值非整数 → invalid_enum 逐项拒收留痕。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)

    run_settle(db, state, content, {
        "faction_delta": {good: {"satisfaction": "abc"}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, FACTION_REJ_SECTION)
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows
    assert rows[0][1]


def test_illegal_class_value_rejected(game):
    """class_delta 合法阶级但值非整数 → invalid_enum 逐项拒收，阶级行不变（对称 faction）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_class_key(db)
    before = _class_satisfaction(db, good)

    run_settle(db, state, content, {
        "class_delta": {good: {"satisfaction": "boom"}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, CLASS_REJ_SECTION)
            if r[2] == "invalid_enum"]
    assert len(rows) == 1, rows
    assert rows[0][1]
    assert _class_satisfaction(db, good) == before


def test_float_and_bool_class_values_rejected(game):
    """class_delta satisfaction/leverage 为 float/bool → 两条 invalid_enum 拒收，不落库
    （对称 faction，cmr 线上 r1 sourcery）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_class_key(db)
    before = _class_satisfaction(db, good)

    run_settle(db, state, content, {
        "class_delta": {good: {"satisfaction": 3.7, "leverage": True}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, CLASS_REJ_SECTION)
            if r[2] == "invalid_enum"]
    assert len(rows) == 2, rows
    assert _class_satisfaction(db, good) == before


def test_float_and_bool_faction_values_rejected(game):
    """float(3.7→3 静默截断)与 bool(True→1)叶子值绕过 int() 异常路 → 一律 invalid_enum
    拒收（prompt 要求整数 delta；与 power/fiscal section 同约，cmr r1 codex）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)
    before = db.conn.execute(
        "SELECT satisfaction, leverage FROM factions WHERE name=?", (good,)).fetchone()

    run_settle(db, state, content, {
        "faction_delta": {good: {"satisfaction": 3.7, "leverage": True}},
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn, FACTION_REJ_SECTION)
            if r[2] == "invalid_enum"]
    assert len(rows) == 2, rows
    # 坏值不静默落库（不被 int 截断成 3 / 1）
    after = db.conn.execute(
        "SELECT satisfaction, leverage FROM factions WHERE name=?", (good,)).fetchone()
    assert (after[0], after[1]) == (before[0], before[1])


def test_web_panel_faction_delta_stays_applied_dict(game):
    """回归（cmr r1 claude）：玩家可见 extractor_output 的 faction_delta 段仍载已落 delta
    dict（web「派系变化」面板形状不变），且拒收项不进玩家可见（P4）——否则面板会把拒收
    列表当 dict 误渲染、并泄露 rejected/reason 内部字段给皇帝。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)

    run_settle(db, state, content, {
        "faction_delta": {good: {"satisfaction": 4}, "查无此派系": {"satisfaction": 9}},
    }, narrative="x", decree_text="y")

    visible = db.get_turn_extraction(turn)["extractor_output"]
    fd = visible.get("faction_delta")
    assert isinstance(fd, dict), f"faction_delta 段应为 web 面板 dict，实为 {type(fd)}"
    assert good in fd
    assert not any(isinstance(v, dict) and v.get("rejected") for v in fd.values())
    # 未落库的未知派系不得出现在面板 dict（cmr r3 codex：值可解析的未知名曾混进 cleaned
    # 被当「已落」误显 = DB↔呈现漂移）。
    assert "查无此派系" not in fd
    # 拒收项不进玩家可见呈现（P4）
    assert "faction_delta_rejections" not in visible


def test_valid_flat_int_faction_not_rejected(game):
    """合法扁平 int 格式 {派系: -5} 不误拒（extractor prompt 允许），且照常落库。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)
    before = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]

    run_settle(db, state, content, {
        "faction_delta": {good: -5},
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, FACTION_REJ_SECTION) == []
    after = db.conn.execute(
        "SELECT satisfaction FROM factions WHERE name=?", (good,)).fetchone()[0]
    assert after == max(0, before - 5)


def test_flat_class_delta_is_rejected_instead_of_silently_dropped(game):
    db, state, content = game
    turn = state.turn
    run_settle(db, state, content, {
        "class_delta": {_valid_class_key(db): -4},
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, CLASS_REJ_SECTION)
    assert len(rows) == 1
    assert rows[0]["category"] == "invalid_enum"


def test_zero_delta_faction_not_rejected(game):
    """0 增量是合法 no-op，不当拒收（不误报）。"""
    db, state, content = game
    turn = state.turn
    good = _valid_faction(db)

    run_settle(db, state, content, {
        "faction_delta": {good: 0},
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, FACTION_REJ_SECTION) == []


def test_issue_effect_faction_rejection_reaches_reports(game):
    """局势 effect_on_resolve 里的 factions 引用未知派系 → 拒收经 entity_rejections 落
    rejection_reports，不蒸发（与 test_issue_path_tolerated_rejections_reach_reports 同契约，
    cmr r2 codex：issue 路派系拒收原被 bare 调用丢弃，#14/#63）。"""
    db, state, content = game
    turn = state.turn
    issue_id = db.insert_issue(
        state, kind="initiative", title="测试派系拒收留痕", origin_kind="decree",
        origin_ref="", bar_value=50, bar_good_meaning="成", bar_bad_meaning="败",
        inertia=0, stage_text="", severity=50, region_hint="", faction_hint="",
        tags=[], ongoing_effects={},
        effect_on_resolve={"factions": {"查无此派系": {"satisfaction": 9}}},
        effect_on_fail={}, resolve_condition="", fail_condition="",
        cancellable="decree", cancel_cost={},
    )
    db.conn.commit()

    run_settle(db, state, content, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved", "narrative": "测试结案"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "issue_summary.entity_rejections")
    rows = [r for r in rows if r[2] == "missing_ref"]
    assert len(rows) == 1, rows
    assert "查无此派系" in rows[0][1]
