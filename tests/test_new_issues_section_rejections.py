"""#63 class 4 / ADR 0008 决定 1：apply_issue_tracker_output 的 new_issues 段 insert 路迁逐项拒收。

原先：db.insert_issue 连同内联 int()/dict()/list() 强转一起裹在 `try: ... except Exception:
print[WARN]; skip`——脏字段（int("abc")/dict("脏")/list(5)）与 insert 代码/DB 异常混在一起
被 WARN 吞、整项静默丢。改为：字段强转脏数据逐项拒收留痕（拒整项，new_issue 即「项」），
insert 的代码/DB 异常上抛（ADR 0005 fail-loud）。用 kind=situation 避开 initiative 配额门。
"""

import pytest

import ming_sim.issues as I


def _new(result):
    return result.get("new_issues") or []


def _rejected(result):
    return [n for n in _new(result) if n.get("rejected")]


@pytest.mark.parametrize("bad_item", [None, 42, "字符串"])
def test_new_issue_non_dict_item_rejected_not_crash(game, bad_item):
    db, state, _ = game
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [bad_item]})
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "非对象" in rej[0]["reason"]


@pytest.mark.parametrize("field,bad", [
    ("bar_value", "abc"),     # int() 抛
    ("severity", "高"),        # int() 抛
    ("cancel_cost", "白银万两"),  # dict(str) 抛
    ("tags", 5),               # list(int) 抛
])
def test_new_issue_dirty_coercion_field_rejected(game, field, bad):
    db, state, _ = game
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·脏字段", field: bad}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "强转失败" in rej[0]["reason"]


@pytest.mark.parametrize("bad_kind", ["reform", "policy", "局势"])
def test_new_issue_bad_kind_rejected(game, bad_kind):
    db, state, _ = game
    # 脏 kind（DELTA_SCHEMA 记 reform 等是已知坏值）→ insert_issue 会抛 ValueError；移除 broad
    # except 后须预检拒整项，不能逃逸成 SettlementAbort（cmr ni r1 concur）。
    ni = {"origin_kind": "decree", "kind": bad_kind, "title": "测试·脏kind"}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "kind" in rej[0]["reason"]


def test_new_issue_dirty_inertia_rejected(game):
    db, state, _ = game
    # _compute_inertia 的 legacy int(inertia) 回退在其 try 外，脏 inertia 会抛——须在预校验 try
    # 内拒整项，不能逃逸 abort（cmr ni r2 codex）。
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·脏inertia", "inertia": "abc"}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "强转失败" in rej[0]["reason"]


def test_new_issue_oversized_severity_clamped_not_abort(game):
    db, state, _ = game
    # severity=10**100：int() 过得了但绑定 SQLite 抛 OverflowError——insert_issue 移除 broad
    # except 后会逃逸 abort。severity 与 bar_value 同 0-100 分值，应 clamp 到 100、照常落库
    # （非拒整项；与 bar_value 静默 clamp 一致，cmr ni r2 codex）。
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{"origin_kind": "decree", "kind": "situation",
                        "title": "测试·超大severity", "severity": 10 ** 100}],
    })
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out  # 不 abort、照常落库
    iid = int(created[0]["issue_id"])
    sev = db.conn.execute("SELECT severity FROM issues WHERE id=?", (iid,)).fetchone()["severity"]
    assert sev == 100  # clamp 到域上界


def test_new_issue_insert_code_exception_propagates(game, monkeypatch):
    db, state, _ = game
    def _boom(*a, **k):
        raise RuntimeError("模拟 insert_issue 落库代码异常")
    monkeypatch.setattr(type(db), "insert_issue", _boom)
    # insert 代码/DB 异常不再 WARN 吞 → 上抛（上层 applier.atomic 据此 SettlementAbort）。
    with pytest.raises(RuntimeError, match="模拟 insert_issue"):
        I.apply_issue_tracker_output(db, state, {
            "new_issues": [{"origin_kind": "decree", "kind": "situation", "title": "测试·正常字段"}],
        })


def test_new_issue_valid_decree_still_creates(game):
    db, state, _ = game
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree", "kind": "situation", "title": "测试·新立局势",
            "bar_value": 30, "severity": 60, "tags": ["测试"],
            "effect_on_resolve": {"metrics": {"民心": 1}},
        }],
    })
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out
    iid = int(created[0]["issue_id"])
    row = db.conn.execute("SELECT title, status FROM issues WHERE id=?", (iid,)).fetchone()
    assert row["title"] == "测试·新立局势"
    assert row["status"] == "active"
