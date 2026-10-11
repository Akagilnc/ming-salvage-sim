"""#63 class 4 / ADR 0008 决定 1：apply_issue_tracker_output 的 close_issues 段迁逐项拒收契约。

原先：坏 issue_id 静默 continue、坏 reason print[WARN]+continue、close_issue 抛异常 print[WARN]+
continue、未找到（None）静默 continue——LLM 脏数据/陈旧引用无声蒸发，代码/DB 异常被 WARN 吞。
改为：脏数据（坏 id/reason/陈旧引用）逐项拒收留痕（经 canonical RejectedItem 落 rejection_reports），
db.close_issue 的代码/DB 异常上抛（ADR 0005 fail-loud）。
"""

from ming_sim.entities.issue.tracker import apply_issue_tracker_output
from ming_sim.applier import Provenance

import pytest


def test_close_already_inactive_rejected_missing_ref(game):
    db, state, _ = game
    iid = db.insert_issue(state, kind="situation", title="测试·先结再结",
                          effect_on_resolve={"metrics": {"民心": 1}})
    # 先合法结案一次（resolved），issue → status!=active。
    apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": iid, "reason": "resolved"}]}, source=Provenance.system_simulation)
    # 再结一次：已非 active → missing_ref（不是「未找到」，但归陈旧引用类）。
    out = apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": iid, "reason": "resolved"}]}, source=Provenance.system_simulation)
    rej = out.rejected
    assert len(rej) == 1
    assert rej[0].category == "missing_ref"



def test_close_failed_on_uncollapsible_rejected_invalid_enum(game):
    db, state, _ = game
    # 不可崩坏局势：active 但无 effect_on_fail。reason=failed → close_issue 回 None（保持 active）。
    # 这是「找到且 active 却被拒」的第三种 None——应归 invalid_enum（语义误判），非 missing_ref。
    iid = db.insert_issue(state, kind="situation", title="测试·不可崩坏天灾",
                          effect_on_resolve={"metrics": {"民心": 1}}, effect_on_fail={})
    out = apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": iid, "reason": "failed"}]}, source=Provenance.system_simulation)
    rej = out.rejected
    assert len(rej) == 1
    assert rej[0].category == "invalid_enum"
    # 行为：issue 仍 active。
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (iid,)).fetchone()["status"] == "active"



def test_close_issue_code_exception_propagates(read_game, monkeypatch):
    db, state, _ = read_game
    def _boom(*a, **k):
        raise RuntimeError("模拟 close_issue 落库代码异常")
    monkeypatch.setattr(type(db), "close_issue", _boom)
    # 代码/DB 异常不再被 WARN 吞 → 上抛（上层 applier.atomic 据此 SettlementAbort）。
    with pytest.raises(RuntimeError):
        apply_issue_tracker_output(
            db, state, {"close_issues": [{"issue_id": 1, "reason": "resolved"}]}
        , source=Provenance.system_simulation)



def test_close_valid_issue_still_succeeds(game):
    db, state, _ = game
    iid = db.insert_issue(state, kind="situation", title="真实结案", effect_on_resolve={"metrics": {"民心": 1}})
    out = apply_issue_tracker_output(
        db, state, {"close_issues": [{"issue_id": iid, "reason": "resolved", "narrative": "测试结案"}]}
    , source=Provenance.system_simulation)
    assert iid in {row["issue_id"] for row in out.closes}
