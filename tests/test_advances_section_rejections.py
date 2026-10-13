"""#63 / ADR 0008 决定 1：apply_issue_tracker_output 的 advances 段迁逐项拒收 + fail-loud。

原先：坏 issue_id 裸 continue 无留痕、非 dict 项 adv.get 抛 AttributeError 崩整月、delta_bar/
inertia_delta 裸 int() 在 try 外脏值（int("高")/int(1e309)）逃逸成 SettlementAbort、advance_issue
回 None（issue 不存在/已非 active）裸 continue 无留痕。改为：脏数据逐项拒收留痕（同 close/
new_issues 段，经 canonical RejectedItem 落 rejection_reports），advance_issue 代码/DB 异常上抛。
"""

from ming_sim.entities.issue.tracker import apply_issue_tracker_output
from ming_sim.applier import Provenance

import pytest


def _adv(result):
    return result.advances



def _rejected(result):
    return result.rejected



def _make_active_issue(db, state):
    """建一个 active situation issue，返回 id（供正常 advance / 脏字段测试用真实存在的 active id）。"""
    return db.insert_issue(
        state, kind="situation", title="测试·推进局势",
        origin_kind="event_pool", origin_ref="test_adv_seed", bar_value=50,
    )



@pytest.mark.parametrize("section,item,category", [
    *[(section, item, "invalid_enum")
      for section in ("advances", "close_issues", "new_issues")
      for item in (None, 42, "字符串", ["列表"])],
    *[(section, {"issue_id": bad_id, **fields}, "invalid_enum")
      for section, fields in (("advances", {"delta_bar": 5}), ("close_issues", {"reason": "resolved"}))
      for bad_id in ("abc", None, True, 1.5, -10 ** 100, 10 ** 100)],
    ("close_issues", {"issue_id": 123, "reason": "bogus"}, "invalid_enum"),
    ("close_issues", {"issue_id": 999999, "reason": "resolved"}, "missing_ref"),
    ("advances", {"issue_id": 999999, "delta_bar": 5}, "missing_ref"),
    *[("new_issues", {"origin_kind": "decree", "kind": "situation", "title": "脏字段", field: bad}, "invalid_enum")
      for field, bad in (
          ("bar_value", "abc"), ("severity", "高"), ("tags", 5), ("inertia", "abc"),
          ("bar_value", 1e309), ("expected_months", 1e309), ("severity", []),
          ("bar_value", 3.7), ("severity", True), ("severity", 2.5), ("inertia", True),
          ("expected_months", 1.5), ("tags", "募营"), ("tags", "单串标量"), ("tags", [5, "正常"]),
      )],
    *[("new_issues", {"origin_kind": "decree", "kind": kind, "title": "脏kind"}, "invalid_enum")
      for kind in ("reform", "policy", "局势", False, 0, [])],
])
def test_tracker_item_refusal(read_game, section, item, category):
    db, state, _ = read_game
    out = apply_issue_tracker_output(db, state, {section: [item]}, source=Provenance.system_simulation)
    assert len(out.rejected) == 1
    assert out.rejected[0].category == category



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
    out = apply_issue_tracker_output(db, state, {"advances": [{"issue_id": iid, field: bad}]}, source=Provenance.system_simulation)
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0].category == "invalid_enum"



def test_advance_non_active_issue_rejected(game):
    db, state, _ = game
    # 已结案 issue（非 active）→ advance_issue 回 None → missing_ref 留痕（陈旧引用）。
    iid = _make_active_issue(db, state)
    db.close_issue(state, iid, reason="resolved", narrative="先结案")
    out = apply_issue_tracker_output(db, state, {"advances": [{"issue_id": iid, "delta_bar": 5}]}, source=Provenance.system_simulation)
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0].category == "missing_ref"



def test_advance_valid_still_advances(game):
    db, state, _ = game
    # 正常 advance（存在 active issue + 合法字段）仍正常推进、不被误拒。
    iid = _make_active_issue(db, state)
    out = apply_issue_tracker_output(
        db, state, {"advances": [{"issue_id": iid, "delta_bar": 10, "narrative": "推进局势"}]}
    , source=Provenance.system_simulation)
    done = [a for a in _adv(out) if a.get("issue_id") == iid]
    assert len(done) == 1, out



def test_advance_code_exception_propagates(game, monkeypatch):
    db, state, _ = game
    iid = _make_active_issue(db, state)
    # advance_issue 的代码/DB 真异常上抛（上层 applier.atomic 据此 SettlementAbort），不 WARN 吞。
    def _boom(*a, **k):
        raise RuntimeError("模拟 advance_issue 落库代码异常")
    monkeypatch.setattr(type(db), "advance_issue", _boom)
    with pytest.raises(RuntimeError):
        apply_issue_tracker_output(db, state, {"advances": [{"issue_id": iid, "delta_bar": 5}]}, source=Provenance.system_simulation)



# --- reject 路径不得泄漏 metric 副作用（cmr advances r1 codex high + claude concur）---
# advances 段曾在 advance_issue 的 None 检查之前就 _apply_metric_dict（就地 mutate state.metrics）：
# 引用 stale/已非 active issue 但带 metric_delta 时，metric 已落 state、项却标 missing_ref「未落地」
# ——矛盾且结算 commit 无 rollback。fix：pre-check active，确认后才应用 metric。
