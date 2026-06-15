"""#63 / ADR 0008 决定 1：apply_issue_tracker_output 的 advances 段迁逐项拒收 + fail-loud。

原先：坏 issue_id 裸 continue 无留痕、非 dict 项 adv.get 抛 AttributeError 崩整月、delta_bar/
inertia_delta 裸 int() 在 try 外脏值（int("高")/int(1e309)）逃逸成 SettlementAbort、advance_issue
回 None（issue 不存在/已非 active）裸 continue 无留痕。改为：脏数据逐项拒收留痕（同 close/
new_issues 段，进 advances 列表、桥接收进 rejection_reports），advance_issue 代码/DB 异常上抛。
"""

import pytest

import ming_sim.issues as I


def _adv(result):
    return result.get("advances") or []


def _rejected(result):
    return [a for a in _adv(result) if a.get("rejected")]


def _make_active_issue(db, state):
    """建一个 active situation issue，返回 id（供正常 advance / 脏字段测试用真实存在的 active id）。"""
    return db.insert_issue(
        state, kind="situation", title="测试·推进局势",
        origin_kind="event_pool", origin_ref="test_adv_seed", bar_value=50,
    )


@pytest.mark.parametrize("bad_item", [None, 42, "字符串", ["列表"]])
def test_advance_non_dict_item_rejected_not_crash(game, bad_item):
    db, state, _ = game
    # 非 dict adv 项（advances:[null]/标量）：adv.get 会抛 AttributeError 崩整月——逐项拒收守门。
    out = I.apply_issue_tracker_output(db, state, {"advances": [bad_item]})
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "非对象" in rej[0]["reason"]


@pytest.mark.parametrize("bad_id", ["abc", None, True, 1.5, -10 ** 100])
def test_advance_bad_issue_id_rejected(game, bad_id):
    db, state, _ = game
    # _parse_sqlite_id 拒非整数/bool/float/超 64-bit → 逐项拒收留痕，不裸 continue 静默丢、不逃逸。
    out = I.apply_issue_tracker_output(db, state, {"advances": [{"issue_id": bad_id, "delta_bar": 5}]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "issue_id" in rej[0]["reason"]


@pytest.mark.parametrize("field,bad", [
    ("delta_bar", True),       # bool
    ("delta_bar", 1.5),        # float
    ("delta_bar", "高"),        # 非数字串
    ("delta_bar", 1e309),      # inf
    ("inertia_delta", True),
    ("inertia_delta", 2.5),
])
def test_advance_dirty_int_field_rejected(game, field, bad):
    db, state, _ = game
    iid = _make_active_issue(db, state)
    # delta_bar/inertia_delta 用 _strict_int（拒 bool/float/inf/非数）→ 脏值逐项拒收留痕，
    # 不再裸 int() 在 try 外逃逸 abort、也不静默截断（int(True)=1 / int(1.5)=1）。
    out = I.apply_issue_tracker_output(db, state, {"advances": [{"issue_id": iid, field: bad}]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"


def test_advance_missing_issue_rejected(game):
    db, state, _ = game
    # advance_issue 回 None（issue 不存在）→ missing_ref 逐项拒收留痕，不裸 continue 静默丢。
    out = I.apply_issue_tracker_output(db, state, {"advances": [{"issue_id": 999999, "delta_bar": 5}]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "missing_ref"


def test_advance_non_active_issue_rejected(game):
    db, state, _ = game
    # 已结案 issue（非 active）→ advance_issue 回 None → missing_ref 留痕（陈旧引用）。
    iid = _make_active_issue(db, state)
    db.close_issue(state, iid, reason="resolved", narrative="先结案")
    out = I.apply_issue_tracker_output(db, state, {"advances": [{"issue_id": iid, "delta_bar": 5}]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "missing_ref"


def test_advance_valid_still_advances(game):
    db, state, _ = game
    # 正常 advance（存在 active issue + 合法字段）仍正常推进、不被误拒。
    iid = _make_active_issue(db, state)
    out = I.apply_issue_tracker_output(
        db, state, {"advances": [{"issue_id": iid, "delta_bar": 10, "narrative": "推进局势"}]}
    )
    done = [a for a in _adv(out) if not a.get("rejected") and a.get("issue_id") == iid]
    assert len(done) == 1, out


def test_advance_code_exception_propagates(game, monkeypatch):
    db, state, _ = game
    iid = _make_active_issue(db, state)
    # advance_issue 的代码/DB 真异常上抛（上层 applier.atomic 据此 SettlementAbort），不 WARN 吞。
    def _boom(*a, **k):
        raise RuntimeError("模拟 advance_issue 落库代码异常")
    monkeypatch.setattr(type(db), "advance_issue", _boom)
    with pytest.raises(RuntimeError, match="模拟 advance_issue"):
        I.apply_issue_tracker_output(db, state, {"advances": [{"issue_id": iid, "delta_bar": 5}]})


# --- reject 路径不得泄漏 metric 副作用（cmr advances r1 codex high + claude concur）---
# advances 段曾在 advance_issue 的 None 检查之前就 _apply_metric_dict（就地 mutate state.metrics）：
# 引用 stale/已非 active issue 但带 metric_delta 时，metric 已落 state、项却标 missing_ref「未落地」
# ——矛盾且结算 commit 无 rollback。fix：pre-check active，确认后才应用 metric。


def test_advance_missing_issue_no_metric_leak(game):
    db, state, _ = game
    before = dict(state.metrics)
    out = I.apply_issue_tracker_output(db, state, {
        "advances": [{"issue_id": 999999, "delta_bar": 5, "metric_delta": {"民心": -10}}],
    })
    rej = _rejected(out)
    assert len(rej) == 1 and rej[0]["category"] == "missing_ref", out
    assert dict(state.metrics) == before, f"missing_ref advance 不得泄漏 metric：{before} → {dict(state.metrics)}"


def test_advance_non_active_issue_no_metric_leak(game):
    db, state, _ = game
    iid = _make_active_issue(db, state)
    db.close_issue(state, iid, reason="resolved", narrative="先结案")
    before = dict(state.metrics)
    out = I.apply_issue_tracker_output(db, state, {
        "advances": [{"issue_id": iid, "delta_bar": 5, "metric_delta": {"皇威": -8}}],
    })
    rej = _rejected(out)
    assert len(rej) == 1 and rej[0]["category"] == "missing_ref", out
    assert dict(state.metrics) == before, "已非 active advance 不得泄漏 metric"


@pytest.mark.parametrize("bad_metric", [["列表"], "字符串", 5])
def test_advance_non_dict_metric_delta_tolerated(game, bad_metric):
    db, state, _ = game
    # metric_delta 非 dict（list/str/数值）→ _apply_metric_dict 的 isinstance 守卫 sanitize 为 {}
    # （flows 同款 #117 守门）：不 raise、正常推进、metrics 不变（sourcery advances r2 testing）。
    iid = _make_active_issue(db, state)
    before = dict(state.metrics)
    out = I.apply_issue_tracker_output(db, state, {
        "advances": [{"issue_id": iid, "delta_bar": 5, "metric_delta": bad_metric}],
    })
    done = [a for a in _adv(out) if not a.get("rejected") and a.get("issue_id") == iid]
    assert len(done) == 1, out
    assert dict(state.metrics) == before, "非 dict metric_delta 须 sanitize 为 {}、metrics 不变"
