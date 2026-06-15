"""#63 class 4 / ADR 0008 决定 1：apply_issue_tracker_output 的 close_issues 段迁逐项拒收契约。

原先：坏 issue_id 静默 continue、坏 reason print[WARN]+continue、close_issue 抛异常 print[WARN]+
continue、未找到（None）静默 continue——LLM 脏数据/陈旧引用无声蒸发，代码/DB 异常被 WARN 吞。
改为：脏数据（坏 id/reason/陈旧引用）逐项拒收留痕（进 closes 列表、S0 桥接收进 rejection_reports），
db.close_issue 的代码/DB 异常上抛（ADR 0005 fail-loud）。
"""

import pytest

import ming_sim.issues as I


def _closes(result):
    return result.get("closes") or []


def _rejected(result):
    return [c for c in _closes(result) if c.get("rejected")]


def test_close_bad_issue_id_rejected(game):
    db, state, _ = game
    out = I.apply_issue_tracker_output(
        db, state, {"close_issues": [{"issue_id": "abc", "reason": "resolved"}]}
    )
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "issue_id" in rej[0]["reason"]


def test_close_bad_reason_rejected(game):
    db, state, _ = game
    # reason 在调用 close_issue 前先验，故任意 id 都会先因坏 reason 被拒。
    out = I.apply_issue_tracker_output(
        db, state, {"close_issues": [{"issue_id": 123, "reason": "bogus"}]}
    )
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "reason" in rej[0]["reason"]


def test_close_unknown_issue_rejected_missing_ref(game):
    db, state, _ = game
    # 合法 reason + 不存在的 issue_id → close_issue 回 None → missing_ref 拒收（不再静默 continue）。
    out = I.apply_issue_tracker_output(
        db, state, {"close_issues": [{"issue_id": 999999, "reason": "resolved"}]}
    )
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "missing_ref"


def test_close_issue_code_exception_propagates(game, monkeypatch):
    db, state, _ = game
    def _boom(*a, **k):
        raise RuntimeError("模拟 close_issue 落库代码异常")
    monkeypatch.setattr(type(db), "close_issue", _boom)
    # 代码/DB 异常不再被 WARN 吞 → 上抛（上层 applier.atomic 据此 SettlementAbort）。
    with pytest.raises(RuntimeError, match="模拟 close_issue"):
        I.apply_issue_tracker_output(
            db, state, {"close_issues": [{"issue_id": 1, "reason": "resolved"}]}
        )


def test_close_valid_issue_still_succeeds(game):
    db, state, _ = game
    active = db.list_active_issues()
    if not active:
        pytest.skip("seed 无 active issue，跳过 happy-path 控制")
    iid = int(active[0]["id"])
    out = I.apply_issue_tracker_output(
        db, state, {"close_issues": [{"issue_id": iid, "reason": "resolved", "narrative": "测试结案"}]}
    )
    closed = [c for c in _closes(out) if not c.get("rejected")]
    assert any(int(c.get("issue_id", -1)) == iid for c in closed), out
    assert iid in (out.get("touched_ids") or [])
