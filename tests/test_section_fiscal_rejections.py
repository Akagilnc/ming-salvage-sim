"""财政声明逐项拒收：坏项经 canonical RejectedItem 落 rejection_reports，
独立好项照落。init_value 缺省 0 合法，在场脏值拒收；delta 显式 0 不记拒收。
由现役原子声明入口验证。
"""

from __future__ import annotations

import pytest

from tests.section_rejection_helpers import run_declaration as _run_settle
from tests.section_rejection_helpers import game, rejection_rows as _rejection_rows


def run_settle(db, state, content, extracted, **kwargs):
    """Legacy rejection fixtures now satisfy the durable-effect origin contract."""
    for section in ("fiscal_removes", "fiscal_changes"):
        for item in extracted.get(section) or []:
            item.setdefault("origin_ref", "盘面自发")
    return _run_settle(db, state, content, extracted, **kwargs)


def _a_fiscal_key(db):
    """取一个开局在册的 fiscal base key,供「好项照落」对照。"""
    cfg = db.get_fiscal_config()
    for k in cfg:
        if k.endswith("_base"):
            return k
    raise AssertionError("找不到 fiscal base key")


# ---- fiscal_removes：裁撤不存在的 key ----

@pytest.mark.parametrize("section,bad_fields,category", [
    ("fiscal_removes", {"key": "查无此税项"}, "missing_ref"),
    ("fiscal_changes", {"key": "查无此税项"}, "missing_ref"),
    *[("fiscal_changes", {"delta": value}, "invalid_enum") for value in ("增三成", 3.7, True)],
    ("fiscal_creates", {"key": None}, None),
    *[("fiscal_creates", {"account": value}, "invalid_enum") for value in ("私库", "民心", "")],
    *[("fiscal_creates", {"init_value": value}, "invalid_enum") for value in ("三百", 3.7, True)],
])
def test_fiscal_rejection_keeps_valid_sibling(game, section, bad_fields, category):
    db, state, content = game
    from ming_sim.decree import pre_settle
    pre_settle(state, db, content=content)
    existing = _a_fiscal_key(db)
    before = db.get_fiscal_config()[existing]
    good = {
        "fiscal_removes": {"key": existing},
        "fiscal_changes": {"key": existing, "delta": 3},
        "fiscal_creates": {"key": "clean_sibling", "account": "国库", "direction": "income", "init_value": 20},
    }[section]
    bad = {**good, **bad_fields}
    if section == "fiscal_creates":
        bad["key"] = existing[:-5] if bad_fields.get("key", "dirty_sibling") is None else "dirty_sibling"
    for item in (bad, good):
        item["origin_ref"] = "盘面自发"
    run_settle(db, state, content, {section: [bad, good]})
    rows = _rejection_rows(db, state.turn, section)
    assert len(rows) == 1
    assert rows[0]["reason"]
    # Duplicate creation used to assert only refusal cardinality; preserve that contract.
    if category is not None:
        assert rows[0]["category"] == category
    applied_key = good["key"] + "_base" if section == "fiscal_creates" else existing
    row = db.conn.execute("SELECT value FROM fiscal_config WHERE key=?", (applied_key,)).fetchone()
    expected = {"fiscal_removes": None, "fiscal_changes": (max(0, before + 3),), "fiscal_creates": (20,)}[section]
    assert (tuple(row) if row is not None else None) == expected
    if section == "fiscal_creates" and category is not None:
        assert db.conn.execute("SELECT 1 FROM fiscal_config WHERE key='dirty_sibling_base'").fetchone() is None




@pytest.mark.parametrize("input_key,key", [
    ("central_taicang_sink_loss_rate", "central_taicang_sink_loss_rate"),
    ("central_taicang_human_loss_rate", "central_taicang_human_loss_rate"),
    ("central_taicang_human_loss", "central_taicang_human_loss_rate"),
])
def test_remove_central_loss_rate_rejected(game, input_key, key):
    db, state, content = game
    before = db.get_fiscal_config()[key]
    run_settle(db, state, content, {"fiscal_removes": [{"key": input_key}]})
    rows = _rejection_rows(db, state.turn, "fiscal_removes")
    assert len(rows) == 1
    assert rows[0]["category"] == "invalid_enum"
    assert db.get_fiscal_config()[key] == before


def test_direct_remove_central_human_loss_rate_stem_refuses_loss_pair(read_game):
    """db.remove_fiscal_item 自身也要拒绝 stem 形态的中央损耗率配置。"""
    db, _, _ = read_game
    key = "central_taicang_human_loss_rate"
    before = db.get_fiscal_config()[key]

    removed = db.remove_fiscal_item("central_taicang_human_loss")

    assert removed is None
    assert db.get_fiscal_config()[key] == before


# ---- fiscal_creates：重复 key / 非法枚举 / 脏 init_value ----


def test_create_absent_init_value_defaults_zero(game):
    """init_value 缺省 = 合法,走默认 0 照建(「缺省走默认」不被「在场即须合法」误伤,pin)。"""
    db, state, content = game

    run_settle(db, state, content, {
        "fiscal_creates": [
            {"origin_ref": "盘面自发", "key": "defaultinit_s3", "account": "内库", "direction": "income",
             "display": "默认初值项", "reason": "缺省"}],
    }, narrative="x", decree_text="y")

    row = db.conn.execute(
        "SELECT value FROM fiscal_config WHERE key='defaultinit_s3_base'").fetchone()
    assert row is not None and row[0] == 0


# ---- fiscal_changes：未知 key / 脏 delta ----


def test_change_zero_delta_no_op_not_rejected(game):
    """fiscal_changes delta 显式给 0 = 无操作,不记拒(免得每月刷无意义拒收行;pin)。"""
    db, state, content = game
    turn = state.turn
    good = _a_fiscal_key(db)

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": good, "delta": 0, "reason": "无操作"}],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "fiscal_changes") == []


def test_change_empty_key_rejected(game):
    """fiscal_changes 空 key = 脏项,记拒留痕(invalid_enum)——空 key 与「delta=0 无操作」
    不同,前者无定位目标(ADR 决定 1 / S3)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": "", "delta": 5, "reason": "缺 key"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "fiscal_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]




def test_change_structural_sink_loss_rate_below_floor_rejected(game):
    """中央自然损耗率可调但不可清零；低于结构地板的 change 逐项拒收。"""
    db, state, content = game
    turn = state.turn
    key = "central_jingyun_sink_loss_rate"
    before = db.get_fiscal_config()[key]

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": key, "delta": -before, "reason": "试图清零自然运损"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "fiscal_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert db.get_fiscal_config()[key] == before


def test_change_central_loss_rate_pair_above_100_rejected(game):
    """中央人为+自然损耗率合计不得超过 100%，写入阶段即拒收。"""
    db, state, content = game
    turn = state.turn
    key = "central_taicang_human_loss_rate"
    before_human = db.get_fiscal_config()[key]
    before_sink = db.get_fiscal_config()["central_taicang_sink_loss_rate"]

    run_settle(db, state, content, {
        "fiscal_changes": [{
            "key": key,
            "delta": 101 - before_human,
            "reason": "试图把中央亏空率推过 100%",
        }],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "fiscal_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    cfg = db.get_fiscal_config()
    assert cfg[key] == before_human
    assert cfg["central_taicang_sink_loss_rate"] == before_sink


def test_change_central_loss_rate_rebalance_uses_batch_final_total(game):
    """中央损耗率同批重分配只看批次终态，合法 rebalance 不受行顺序影响。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE fiscal_config SET value = 80 WHERE key = 'central_taicang_human_loss_rate'"
    )
    db.conn.execute(
        "UPDATE fiscal_config SET value = 20 WHERE key = 'central_taicang_sink_loss_rate'"
    )
    db.conn.commit()
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_changes": [
            {
                "key": "central_taicang_human_loss_rate",
                "delta": 5,
                "reason": "先记人为损耗调整",
            },
            {
                "key": "central_taicang_sink_loss_rate",
                "delta": -5,
                "reason": "再压自然损耗抵扣",
            },
        ],
    }, narrative="x", decree_text="y")

    assert _rejection_rows(db, turn, "fiscal_changes") == []
    cfg = db.get_fiscal_config()
    assert cfg["central_taicang_human_loss_rate"] == 85
    assert cfg["central_taicang_sink_loss_rate"] == 15


@pytest.mark.parametrize("bad", [False, 0.0])
def test_falsy_dirty_delta_still_rejected(game, bad):
    """False==0 / 0.0==0 为真——无操作短路跑在脏值判定之前,把脏 bool/float 静默
    吞掉(cmr S3 r1 claude:与 S1 的「bool 先判」顺序对称才成立)。"""
    db, state, content = game
    turn = state.turn
    key = next(iter(db.get_fiscal_config()))

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": key, "delta": bad}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_changes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"


def test_create_rate_only_sibling_collision_rejected_not_abort(game):
    """田赋默认只有 田赋_rate 无 _base——create_fiscal_item 只查 base 键,新立
    田赋_base 时第二条 INSERT 撞 rate 键 PK = IntegrityError 崩整月,绕过拒收
    (cmr S3 r2 codex high)。存在性检查须覆盖 base+rate 双键。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "田赋_base", "account": "国库",
                            "direction": "income", "init_value": 1}],
    }, narrative="x", decree_text="y")  # 不抛 = 没崩

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_creates"]
    assert len(rows) == 1


@pytest.mark.parametrize("noop_delta", [0, None])
def test_empty_key_rejected_even_with_noop_delta(game, noop_delta):
    """空 key + delta 0/null:无操作短路不得吞掉「空 key=脏项」的留痕
    (与 falsy 短路同类序错,cmr S3 r2 claude)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": "", "delta": noop_delta}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_changes"]
    assert len(rows) == 1


def test_remove_missing_key_rejected(game):
    """fiscal_removes 缺 key → 记拒(新分支补测试,cmr S3 r2 claude)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_removes": [{"reason": "缺 key"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_removes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"


def test_create_with_rate_suffix_key_rejected(game):
    """create 的 stem 归一须与 remove 同用 _stem_of(剥 _base 和 _rate 双后缀)
    ——只剥 _base 时 key='田赋_rate' 查成 田赋_rate_base 漏撞,建出冒牌科目
    (cmr S3 r3 codex)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "田赋_rate", "account": "国库",
                            "direction": "income", "init_value": 1}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_creates"]
    assert len(rows) == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key LIKE '田赋_rate_%'"
    ).fetchone()[0] == 0  # 没建冒牌行


def test_negative_init_value_rejected_not_clamped(game):
    """负 init_value 静默 clamp 0 = 又一面「凭空建零值项」——负月度定额无意义,
    按脏值拒留痕(cmr S3 r3 claude;cleaner 同步取消 max(0,·) 有损钳制)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "负值测试_base", "account": "国库",
                            "direction": "income", "init_value": -5}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_creates"]
    assert len(rows) == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key='负值测试_base'").fetchone()[0] == 0


@pytest.mark.parametrize("bad_key", ["田赋_rate_base", "辽饷_base_base"])
def test_double_suffix_key_rejected_no_phantom(game, bad_key):
    """双后缀 key(田赋_rate_base)单层剥离后仍漏撞既有行,建出幻影预算科目并被
    iter_budget_items 当真月度流水重复计税(cmr S3 r4 claude medium)。
    _stem_of 对多重后缀返空标记非法（不循环剥归一——循环归一在 remove 路不可逆危险,见 r5）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": bad_key, "account": "国库",
                            "direction": "income", "init_value": 100}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_creates"]
    assert len(rows) == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key LIKE ?", (bad_key + "%",)
    ).fetchone()[0] == 0  # 零幻影行


def test_double_suffix_remove_rejected_not_destructive(game):
    """remove 路对多重后缀垃圾 key(辽饷_base_base)必须拒收——循环剥后缀会把它
    归一成 辽饷 命中真行,垃圾 key 触发不可逆删科目+清零各省辽饷
    (cmr S3 r5 claude medium:与 create 路同形输入须同判)。"""
    db, state, content = game
    turn = state.turn
    before = db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key LIKE '辽饷%'").fetchone()[0]
    assert before > 0  # 前提:辽饷在册

    run_settle(db, state, content, {
        "fiscal_removes": [{"key": "辽饷_base_base", "reason": "垃圾key"}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_removes"]
    assert len(rows) == 1
    after = db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key LIKE '辽饷%'").fetchone()[0]
    assert after == before  # 真科目毫发无损


def test_chinese_direction_alias_accepted_at_applier(game):
    """direction='收' 直接落账同判——同义词归一须在 applier，
    不能仅在可选 cleaner 层（DELTA_SCHEMA 明言吃中文别名）。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "别名测试_base", "account": "国库",
                            "direction": "收", "init_value": 5}],
    }, narrative="x", decree_text="y")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM fiscal_config WHERE key='别名测试_base'").fetchone()[0] == 1
    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_creates"]
    assert rows == []


def test_whitespace_only_key_rejected_at_applier(game):
    """空白 key('  ')在 applier 守门处统一 strip 并拒收。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": "  ", "delta": 5}],
    }, narrative="x", decree_text="y")

    rows = [r for r in _rejection_rows(db, turn) if r[0] == "fiscal_changes"]
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"  # 按空 key 拒,而非未知 key missing_ref


# ──────── cmr S3 r10:终局集中化——cleaner 零值逻辑,applier 唯一语义点 ────────

def test_lossless_int_string_same_verdict_both_paths(game):
    """无损整数串("5"/"300")在 applier 归一接受，不能只依赖可选 cleaner。"""
    db, state, content = game
    turn = state.turn
    key = next(iter(db.get_fiscal_config()))
    before = db.get_fiscal_config()[key]

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": key, "delta": "5"}],
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "整串测试_base", "account": "国库",
                            "direction": "income", "init_value": "300"}],
    }, narrative="x", decree_text="y")

    assert [r for r in _rejection_rows(db, turn)] == []  # 两项都不拒
    assert db.get_fiscal_config()[key] == before + 5
    assert db.conn.execute(
        "SELECT value FROM fiscal_config WHERE key='整串测试_base'").fetchone()[0] == 300


def test_direct_fiscal_create_display_defaults_from_key(game):
    """display 缺省=key 去 _base 后缀；直接落账不能依赖 cleaner 补默认值。"""
    db, state, content = game

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "显名测试_base", "account": "国库",
                            "direction": "income", "init_value": 1}],
    }, narrative="x", decree_text="y")

    row = db.conn.execute(
        "SELECT display FROM fiscal_config WHERE key='显名测试_base'").fetchone()
    assert row is not None and row[0] == "显名测试"


def test_garbage_key_category_consistent_across_sections(game):
    """同形双后缀垃圾 key 在 create/remove 两段同口径:invalid_enum「key 非法」,
    而非 remove 侧误标 missing_ref「不存在」(cmr S3 r10 claude low)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [{"origin_ref": "盘面自发", "key": "辽饷_base_base", "account": "国库",
                            "direction": "income", "init_value": 1}],
        "fiscal_removes": [{"key": "盐税_rate_rate", "reason": "垃圾"}],
        "fiscal_changes": [{"key": "商税_base_base", "delta": 3}],
    }, narrative="x", decree_text="y")

    cats = {r[0]: r[2] for r in _rejection_rows(db, turn)}
    assert cats.get("fiscal_creates") == "invalid_enum"
    assert cats.get("fiscal_removes") == "invalid_enum"  # 非法 key ≠ 不存在
    assert cats.get("fiscal_changes") == "invalid_enum"  # 三段同口径(ship-pre r5)


def test_fiscal_change_reopens_with_value_origin_history_and_scaled_rows(game):
    """A standalone fiscal change persists its live value, provenance, history and scaling together."""
    from ming_sim.db import GameDB

    db, state, content = game
    key = "商税_base"
    before = db.get_fiscal_config()[key]
    fiscal_before = {
        row["id"]: __import__("json").loads(row["fiscal"] or "{}").get("commerce_tax", 0)
        for row in db.conn.execute("SELECT id,fiscal FROM regions")
    }
    run_settle(db, state, content, {
        "fiscal_changes": [{"key": key, "delta": before, "reason": "重开核验"}],
    }, narrative="x", decree_text="y")

    reopened = GameDB(db.path, content)
    try:
        row = reopened.conn.execute(
            "SELECT value, origin_ref FROM fiscal_config WHERE key=?", (key,)
        ).fetchone()
        history = reopened.conn.execute(
            "SELECT old_value,new_value,origin_ref FROM fiscal_config_changes WHERE key=? ORDER BY id DESC LIMIT 1",
            (key,),
        ).fetchone()
        assert (row["value"], row["origin_ref"]) == (before * 2, "盘面自发")
        assert (history["old_value"], history["new_value"], history["origin_ref"]) == (
            before, before * 2, "盘面自发",
        )
        fiscal_after = {
            row["id"]: __import__("json").loads(row["fiscal"] or "{}").get("commerce_tax", 0)
            for row in reopened.conn.execute("SELECT id,fiscal FROM regions")
        }
        assert any(fiscal_after[rid] != value for rid, value in fiscal_before.items() if value > 0)
    finally:
        reopened.close()
