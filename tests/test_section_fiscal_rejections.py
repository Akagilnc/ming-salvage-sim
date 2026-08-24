"""PR2-S3(ADR 0008 决定 1,#91)——apply_score_extraction 的 fiscal 三段迁拒收契约。

fiscal_removes / fiscal_creates / fiscal_changes 三段原先 LLM 脏项要么 print 静默跳、
要么静默归 0/continue。改为:裁撤不存在 key、create 重复 key/非法枚举、changes 未知 key
或脏 delta → 逐项拒收留痕(返回列表含 {rejected,reason,category,item}),好项照落、坏一项
不带走整批;桥接 _collect_inline_rejections 自动收进 rejection_reports。

「在场即须合法」vs「缺省走默认」:fiscal_creates 的 init_value 缺省 0 合法、在场脏值拒;
fiscal_changes 的 delta 显式给 0 = 无操作不记拒。

经 driver.run_settle 端到端驱动(公共接口,与 test_section4_rejections.py 同风格)。
"""

from __future__ import annotations

import pytest

from tests.section_rejection_helpers import prepare_then_settle as _run_settle
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

def test_remove_unknown_fiscal_key_rejected_good_removal_lands(game):
    """fiscal_removes 引用不存在的 key → 原 print 静默跳,改为逐项拒收留痕(missing_ref),
    同信封里真实存在的 key 照样裁撤——坏一项不带走整批(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _a_fiscal_key(db)

    run_settle(db, state, content, {
        "fiscal_removes": [
            {"key": "查无此税项", "reason": "罢废"},
            {"key": good, "reason": "裁撤"},
        ],
    }, narrative="x", decree_text="y")  # 不抛 = 没崩整月

    rows = _rejection_rows(db, turn, "fiscal_removes")
    assert len(rows) == 1
    _, reason, category, _ = rows[0]
    assert reason  # 人读原因非空
    assert category == "missing_ref"
    # 好项照落:base key 被删
    assert db.conn.execute(
        "SELECT 1 FROM fiscal_config WHERE key=?", (good,)).fetchone() is None


def test_remove_dynamic_tax_still_zeroes_region_field(game):
    """好路 pin:裁撤 dynamic 税(辽饷)→ base/rate 行删除 + 各省实收字段归零
    (db.remove_fiscal_item 的 dynamic 联动语义不被本切片破坏)。"""
    db, state, content = game
    # 先确保至少一省有辽饷实收
    db.conn.execute(
        "UPDATE regions SET fiscal=json_set(COALESCE(NULLIF(fiscal,''),'{}'),'$.liao_xiang',500)"
        " WHERE id=(SELECT id FROM regions LIMIT 1)")
    db.conn.commit()
    rid = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]

    run_settle(db, state, content, {
        "fiscal_removes": [{"key": "辽饷", "reason": "永罢辽饷"}],
    }, narrative="x", decree_text="y")

    assert db.conn.execute(
        "SELECT 1 FROM fiscal_config WHERE key='辽饷_base'").fetchone() is None
    import json as _json
    fiscal = _json.loads(db.conn.execute(
        "SELECT fiscal FROM regions WHERE id=?", (rid,)).fetchone()[0] or "{}")
    assert int(fiscal.get("liao_xiang", 0) or 0) == 0  # dynamic 联动归零


def test_remove_structural_sink_loss_rate_rejected(game):
    """中央自然损耗率是结构地板，不能被 fiscal_removes 裁撤成 0。"""
    db, state, content = game
    turn = state.turn
    key = "central_taicang_sink_loss_rate"
    before = db.get_fiscal_config()[key]

    run_settle(db, state, content, {
        "fiscal_removes": [{"key": key, "reason": "试图抹平自然损耗"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "fiscal_removes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert db.get_fiscal_config()[key] == before


def test_remove_central_human_loss_rate_rejected_as_loss_pair(game):
    """中央人为损耗率虽无最低地板，也属于成对损耗率，不可被 fiscal_removes 裁撤。"""
    db, state, content = game
    turn = state.turn
    key = "central_taicang_human_loss_rate"
    before = db.get_fiscal_config()[key]

    run_settle(db, state, content, {
        "fiscal_removes": [{"key": key, "reason": "试图裁撤人为损耗"}],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "fiscal_removes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert db.get_fiscal_config()[key] == before


def test_remove_central_human_loss_rate_stem_rejected_as_loss_pair(game):
    """stem 写法也不可绕过中央损耗率成对配置裁撤保护。"""
    db, state, content = game
    turn = state.turn
    key = "central_taicang_human_loss_rate"
    before = db.get_fiscal_config()[key]

    run_settle(db, state, content, {
        "fiscal_removes": [{
            "key": "central_taicang_human_loss",
            "reason": "试图用 stem 裁撤人为损耗",
        }],
    }, narrative="x", decree_text="y")

    rows = _rejection_rows(db, turn, "fiscal_removes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
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

def test_create_duplicate_key_rejected_good_create_lands(game):
    """fiscal_creates 命中已存在的 base key → db.create_fiscal_item 返 None,原 print
    静默跳,改为逐项拒收留痕;同信封里的合法新立照建(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    dup_stem = _a_fiscal_key(db)[:-5]  # 去掉 _base 取 stem

    run_settle(db, state, content, {
        "fiscal_creates": [
            {"origin_ref": "盘面自发", "key": dup_stem, "account": "国库", "direction": "income",
             "display": "撞名项", "init_value": 100, "reason": "重复"},
            {"origin_ref": "盘面自发", "key": "haiguan_s3", "account": "国库", "direction": "income",
             "display": "海关税", "init_value": 50, "reason": "新立"},
        ],
    }, narrative="x", decree_text="y")  # 不抛

    rows = _rejection_rows(db, turn, "fiscal_creates")
    assert len(rows) == 1
    assert rows[0][1]  # reason 非空
    # 好项照落:新 base key 建成
    assert db.conn.execute(
        "SELECT 1 FROM fiscal_config WHERE key='haiguan_s3_base'").fetchone() is not None


@pytest.mark.parametrize("bad_account", ["私库", "民心", ""])
def test_create_illegal_account_rejected_sibling_lands(game, bad_account):
    """fiscal_creates account 非法（不在 国库/内库）→ 原纯静默 continue,改记拒留痕
    (invalid_enum);同信封合法新立照建(在场即须合法 / 集中化白名单)。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [
            {"origin_ref": "盘面自发", "key": "badacct_s3", "account": bad_account, "direction": "income",
             "display": "脏账户项", "init_value": 10, "reason": "脏"},
            {"origin_ref": "盘面自发", "key": "goodacct_s3", "account": "内库", "direction": "expense",
             "display": "内库支项", "init_value": 5, "reason": "好"},
        ],
    }, narrative="x", decree_text="y")  # 不抛

    rows = _rejection_rows(db, turn, "fiscal_creates")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    assert db.conn.execute(
        "SELECT 1 FROM fiscal_config WHERE key='goodacct_s3_base'").fetchone() is not None
    assert db.conn.execute(
        "SELECT 1 FROM fiscal_config WHERE key='badacct_s3_base'").fetchone() is None


@pytest.mark.parametrize("bad_init", ["三百", 3.7, True])
def test_create_dirty_init_value_rejected_not_silent_zero(game, bad_init):
    """fiscal_creates init_value 在场但脏(字符串/float/bool)= LLM 脏数据,原静默归 0
    凭空建零值项,改显式拒(invalid_enum);bool 是 int 子类先判(对称 S1/S2)。
    同信封合法新立照建。"""
    db, state, content = game
    turn = state.turn

    run_settle(db, state, content, {
        "fiscal_creates": [
            {"origin_ref": "盘面自发", "key": "dirtyinit_s3", "account": "国库", "direction": "income",
             "display": "脏初值项", "init_value": bad_init, "reason": "脏"},
            {"origin_ref": "盘面自发", "key": "cleaninit_s3", "account": "国库", "direction": "income",
             "display": "净初值项", "init_value": 20, "reason": "好"},
        ],
    }, narrative="x", decree_text="y")  # 不抛

    rows = _rejection_rows(db, turn, "fiscal_creates")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    # 脏项没落、好项照落
    assert db.conn.execute(
        "SELECT 1 FROM fiscal_config WHERE key='dirtyinit_s3_base'").fetchone() is None
    assert db.conn.execute(
        "SELECT value FROM fiscal_config WHERE key='cleaninit_s3_base'").fetchone()[0] == 20


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

def test_change_unknown_key_rejected_good_change_lands(game):
    """fiscal_changes 引用未知 key → 原 print 静默跳,改为逐项拒收留痕(missing_ref);
    同信封里真实 key 的调率照落(ADR 决定 1)。"""
    db, state, content = game
    turn = state.turn
    good = _a_fiscal_key(db)
    before = db.get_fiscal_config()[good]

    run_settle(db, state, content, {
        "fiscal_changes": [
            {"key": "查无此配置项", "delta": 10, "reason": "未知"},
            {"key": good, "delta": 5, "reason": "调增"},
        ],
    }, narrative="x", decree_text="y")  # 不抛

    rows = _rejection_rows(db, turn, "fiscal_changes")
    assert len(rows) == 1
    _, reason, category, _ = rows[0]
    assert reason
    assert category == "missing_ref"
    # 好项照落
    assert db.get_fiscal_config()[good] == max(0, before + 5)


@pytest.mark.parametrize("bad_delta", ["增三成", 3.7, True])
def test_change_dirty_delta_rejected_sibling_lands(game, bad_delta):
    """fiscal_changes delta 脏(字符串/float/bool)→ 原裸 int() 静默 continue(吞),改显式
    拒留痕(invalid_enum);bool 是 int 子类先判(对称 S1/S2);同信封好项照落。"""
    db, state, content = game
    turn = state.turn
    good = _a_fiscal_key(db)
    before = db.get_fiscal_config()[good]

    run_settle(db, state, content, {
        "fiscal_changes": [
            {"key": good, "delta": bad_delta, "reason": "脏"},
            {"key": good, "delta": 3, "reason": "好"},
        ],
    }, narrative="x", decree_text="y")  # 不抛

    rows = _rejection_rows(db, turn, "fiscal_changes")
    assert len(rows) == 1
    assert rows[0][2] == "invalid_enum"
    assert rows[0][1]
    # 好项照落
    assert db.get_fiscal_config()[good] == max(0, before + 3)


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


def test_change_dynamic_tax_rate_scales_region_field(game):
    """好路 pin:调 dynamic 税(辽饷)系数 → fiscal_config 改 + 各省实收按比例缩放
    (db dynamic 联动缩放语义不被本切片破坏)。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE regions SET fiscal=json_set(COALESCE(NULLIF(fiscal,''),'{}'),'$.liao_xiang',400)"
        " WHERE id=(SELECT id FROM regions LIMIT 1)")
    db.conn.commit()
    rid = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()[0]
    old_rate = db.get_fiscal_config()["辽饷_rate"]

    run_settle(db, state, content, {
        "fiscal_changes": [{"key": "辽饷_rate", "delta": -50, "reason": "减辽饷"}],
    }, narrative="x", decree_text="y")

    new_rate = db.get_fiscal_config()["辽饷_rate"]
    assert new_rate == max(0, old_rate - 50)
    import json as _json
    fiscal = _json.loads(db.conn.execute(
        "SELECT fiscal FROM regions WHERE id=?", (rid,)).fetchone()[0] or "{}")
    # 按 new/old 比例缩放后实收 < 400(联动当真生效)
    assert 0 <= int(fiscal.get("liao_xiang", 0) or 0) < 400


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


# ───────── cmr S3 r1:引擎真路 cleaner 不得吞脏(验证单点化在 applier) ─────────

def test_cleaner_passes_dirty_delta_through():
    """_clean_fiscal_changes 不得 coerce(3.7→3/True→1)或静默丢脏串——原样透传,
    由 applier 拒收留痕;无损整数串("5")照转,真 int 0 照旧滤掉(cmr S3 r1,2/2:
    引擎真路被 cleaner 预消毒,拒收契约对 fiscal 失明)。"""
    from ming_sim.simulation import _clean_fiscal_changes

    out = _clean_fiscal_changes([
        {"key": "a_base", "delta": 3.7},      # lossy float → 透传
        {"key": "b_base", "delta": True},     # bool → 透传
        {"key": "c_base", "delta": "三成"},    # 脏串 → 透传
        {"key": "d_base", "delta": "5"},      # 无损整数串 → 转 5
        {"key": "e_base", "delta": 0},        # 真 0 → 滤
        {"key": "f_base", "delta": 2},        # 好值 → 保
    ])
    by_key = {c["key"]: c["delta"] for c in out}
    assert by_key["a_base"] == 3.7
    assert by_key["b_base"] is True
    assert by_key["c_base"] == "三成"
    assert by_key["d_base"] == 5
    assert "e_base" not in by_key
    assert by_key["f_base"] == 2


def test_cleaner_passes_dirty_create_fields_through():
    """_clean_fiscal_creates 不得把脏 init_value 归 0、不得静默丢非法
    account/direction——透传由 applier 拒留痕;direction 同义词(收/支出)仍规范化,
    init_value 缺省/null 仍归 0(合法默认)(cmr S3 r1,2/2)。"""
    from ming_sim.simulation import _clean_fiscal_creates

    out = _clean_fiscal_creates([
        {"key": "t1", "account": "国库", "direction": "收", "init_value": 10},   # 同义词规范化
        {"key": "t2", "account": "国库", "direction": "income", "init_value": "三百"},  # 脏值透传
        {"key": "t3", "account": "省库", "direction": "income", "init_value": 1},  # 非法 account 透传
        {"key": "t4", "account": "国库", "direction": "斜着走", "init_value": 1},  # 非法 direction 透传
        {"key": "t5", "account": "国库", "direction": "income"},                  # 缺省 → 0
    ])
    by_key = {c["key"]: c for c in out}
    assert by_key["t1"]["direction"] == "income"
    assert by_key["t2"]["init_value"] == "三百"
    assert by_key["t3"]["account"] == "省库"
    assert by_key["t4"]["direction"] == "斜着走"
    assert by_key["t5"]["init_value"] == 0
    assert by_key["t5"]["display"] == ""  # cleaner 不预填 display,默认归 applier(r12)


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


def test_sanitizer_passes_empty_key_items_through():
    """引擎 sanitizer 路的空 key 项不得被 cleaner 静默滤——透传给 applier 记拒
    (cmr S3 r7 codex:driver 路有痕、引擎路无痕=同输入两判,推翻原 disposition)。"""
    from ming_sim.simulation import (
        _clean_fiscal_changes, _clean_fiscal_creates, _clean_fiscal_removes,
    )

    assert _clean_fiscal_changes([{"key": "", "delta": 5}]) != []
    assert _clean_fiscal_changes([{"key": ""}]) != []  # 空 key+无 delta 退化角(r8)
    assert _clean_fiscal_changes([{"key": "", "delta": 0}]) != []  # 空 key+真0 退化角(r8)
    assert _clean_fiscal_creates([{"key": "", "account": "国库",
                                   "direction": "income", "init_value": 1}]) != []
    assert _clean_fiscal_removes([{"key": "", "reason": "x"}]) != []


def test_chinese_direction_alias_accepted_on_driver_path(game):
    """direction='收' 经 driver 路也要同判落库——同义词归一须在唯一守门人(applier)
    处做,放在 driver 不经过的 cleaner 层 = 同输入两判(cmr S3 r9 claude;
    DELTA_SCHEMA 明言吃中文别名)。"""
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


def test_whitespace_only_key_rejected_on_driver_path(game):
    """空白 key('  ')在 applier 不 strip 时两路两判——applier 守门处统一 strip
    (cmr S3 r9 codex)。"""
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
    """无损整数串("5"/"300")在 applier 归一接受——转换留在 cleaner 时引擎路收
    driver 路拒=同输入两判(cmr S3 r10,2/2 high;与 r9 direction 同处方)。"""
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


def test_driver_path_display_defaults_from_key(game):
    """display 缺省=key 去 _base 后缀——默认只在 cleaner 时 driver 路建出空名
    预算行(DELTA_SCHEMA 契约对象正是 driver 路)(cmr S3 r10 claude medium)。"""
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
