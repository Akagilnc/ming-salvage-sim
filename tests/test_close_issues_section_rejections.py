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


@pytest.mark.parametrize("bad_item", [None, 42, "字符串", ["列表"]])
def test_close_non_dict_item_rejected_not_crash(game, bad_item):
    db, state, _ = game
    # 非 dict close 项（close_issues:[null]/标量，_sanitize 不清列表项可达）：必须逐项拒收，
    # 不能 cl.get 抛 AttributeError 崩整月（codex r4）。
    out = I.apply_issue_tracker_output(db, state, {"close_issues": [bad_item]})
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "非对象" in rej[0]["reason"]


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


def test_close_overflow_issue_id_rejected(game):
    db, state, _ = game
    # 10**100：int() 过得了但绑定 SQLite 会抛 OverflowError——必须在解析期拒收（invalid_enum），
    # 不能让 OverflowError 上抛崩整月（codex r1，复用 _parse_sqlite_id 64-bit 守门）。
    out = I.apply_issue_tracker_output(
        db, state, {"close_issues": [{"issue_id": 10 ** 100, "reason": "resolved"}]}
    )
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"


def test_close_already_inactive_rejected_missing_ref(game):
    db, state, _ = game
    iid = db.insert_issue(state, kind="situation", title="测试·先结再结",
                          effect_on_resolve={"metrics": {"民心": 1}})
    # 先合法结案一次（resolved），issue → status!=active。
    I.apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": iid, "reason": "resolved"}]})
    # 再结一次：已非 active → missing_ref（不是「未找到」，但归陈旧引用类）。
    out = I.apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": iid, "reason": "resolved"}]})
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "missing_ref"
    assert "active" in rej[0]["reason"]


def test_close_failed_on_uncollapsible_rejected_invalid_enum(game):
    db, state, _ = game
    # 不可崩坏局势：active 但无 effect_on_fail。reason=failed → close_issue 回 None（保持 active）。
    # 这是「找到且 active 却被拒」的第三种 None——应归 invalid_enum（语义误判），非 missing_ref。
    iid = db.insert_issue(state, kind="situation", title="测试·不可崩坏天灾",
                          effect_on_resolve={"metrics": {"民心": 1}}, effect_on_fail={})
    out = I.apply_issue_tracker_output(db, state, {"close_issues": [{"issue_id": iid, "reason": "failed"}]})
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "不可崩坏" in rej[0]["reason"]
    # 行为：issue 仍 active（拒结案，不被误标 missing_ref 也未被结案）。
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (iid,)).fetchone()["status"] == "active"


def test_close_rejection_reaches_rejection_reports(game):
    """端到端 plumbing：close 段拒收经 _collect_inline_rejections 真落 rejection_reports 表
    （桥接下探 issue_summary.closes，cmr Claude r1）。"""
    db, state, _ = game
    from ming_sim.applier import Provenance, RejectionCollector
    from ming_sim.decree import _collect_inline_rejections

    applied = {"issue_summary": {"closes": [{
        "rejected": True, "category": "missing_ref",
        "reason": "close 测试拒收", "item": {"issue_id": 999999, "reason": "resolved"},
    }]}}
    collector = RejectionCollector()
    _collect_inline_rejections(collector, applied, 7, Provenance.unknown)
    collector.flush_to_db(db)

    row = db.conn.execute(
        "SELECT section, category, reason FROM rejection_reports "
        "WHERE turn=7 AND section LIKE '%closes%'"
    ).fetchone()
    assert row is not None, "close 段拒收未落 rejection_reports"
    assert row["category"] == "missing_ref"


def test_effect_brief_ignores_rejected_closes():
    """效果摘要消费 issue_summary.closes 时必须跳过拒收项——否则无 title 的拒收 wrapper
    被当成功结案喊进「了结局势」污染章节摘要（cmr close-issues r2 codex）。"""
    from ming_sim.memories import effect_brief
    only_rejected = {"issue_summary": {"closes": [
        {"rejected": True, "category": "missing_ref", "reason": "查无此 issue", "item": {}},
    ]}}
    assert "了结局势" not in effect_brief(only_rejected)
    mixed = {"issue_summary": {"closes": [
        {"rejected": True, "category": "missing_ref", "reason": "查无此 issue", "item": {}},
        {"issue_id": 5, "title": "真·平叛结案", "rejected": False},
    ]}}
    brief = effect_brief(mixed)
    assert "真·平叛结案" in brief and "了结局势" in brief


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
