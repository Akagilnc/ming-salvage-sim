"""#63 class 4 / ADR 0008 决定 1：apply_issue_tracker_output 的 new_issues 段 insert 路迁逐项拒收。

原先：db.insert_issue 连同内联 int()/dict()/list() 强转一起裹在 `try: ... except Exception:
print[WARN]; skip`——脏字段（int("abc")/dict("脏")/list(5)）与 insert 代码/DB 异常混在一起
被 WARN 吞、整项静默丢。改为：字段强转脏数据逐项拒收留痕（拒整项，new_issue 即「项」），
insert 的代码/DB 异常上抛（ADR 0005 fail-loud）。用 kind=situation 避开 initiative 配额门。
"""

import json

import pytest

import ming_sim.issues as I
from ming_sim.models import Event
from tests.section_rejection_helpers import game


def _decree_origin(db, state) -> str:
    dossier_id = db.create_decree_dossier(state, action_type="policy", decree_text="测试新立局势来源", target_kind="issue", target_id="validation")
    db.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"


class _TempEvents:
    def __init__(self, content, *events):
        self.content = content
        self.events = events
        self.previous = {}
        self.previous_positions = {}

    def __enter__(self):
        for ev in self.events:
            for idx, existing in enumerate(self.content.events):
                if getattr(existing, "id", None) == ev.id:
                    self.previous_positions[ev.id] = idx
                    self.content.events[idx] = ev
                    break
            else:
                self.previous_positions[ev.id] = None
                self.content.events.append(ev)
            self.previous[ev.id] = self.content.event_by_id.get(ev.id)
            self.content.event_by_id[ev.id] = ev
        return self.events

    def __exit__(self, exc_type, exc, tb):
        for ev in self.events:
            old = self.previous.get(ev.id)
            pos = self.previous_positions.get(ev.id)
            if pos is not None and pos < len(self.content.events) and self.content.events[pos] is ev:
                if old is None:
                    self.content.events.pop(pos)
                else:
                    self.content.events[pos] = old
            elif ev in self.content.events:
                self.content.events.remove(ev)
            if old is None:
                self.content.event_by_id.pop(ev.id, None)
            else:
                self.content.event_by_id[ev.id] = old


def _new(result):
    return result.get("new_issues") or []


def _rejected(result):
    return [n for n in _new(result) if n.get("rejected")]


def _pick_event_pool_id(db):
    """取一个 situation 类、非 auto_trigger、当前库未触发过的预设 event id（不硬编死名，
    随内容包变化自适应，同 conftest.active_ming_character 风格）。供 event_pool 路径用例。"""
    for eid, ev in I._ctx().event_by_id.items():
        if getattr(ev, "event_type", "") != "situation":
            continue
        if getattr(ev, "auto_trigger", False):
            continue
        if db.find_any_issue_by_origin("event_pool", ev.id) is not None:
            continue
        return eid
    pytest.skip("内容包无可用 situation/非auto/未触发 预设 event，跳过 event_pool 用例")


def _open_event_window(state, ev):
    if getattr(ev, "trigger_year", 0) > 0:
        state.year = ev.trigger_year
        state.period = ev.trigger_month or 1


def _ensure_event_candidate(db, state, eid):
    if not any(c.id == eid for c in I.gather_candidate_events(state, db)):
        pytest.skip(f"{eid} 当前盘面不在 event_pool 候选集，无法覆盖 insert 异常传播路径")


def _hist_event(eid, gate=None):
    return Event(
        id=eid,
        title=f"测试事件 {eid}",
        kind="测试",
        summary="x",
        urgency=50,
        severity=50,
        credibility=50,
        interests=[],
        audiences=[],
        trigger_year=1,
        trigger_month=1,
        open_window=True,
        trigger_gate=gate or {},
    )


def test_temp_events_replaces_same_id_and_restores_original(content):
    eid = "__temp_events_replace_existing__"
    original = _hist_event(eid)
    replacement = _hist_event(eid)
    replacement.title = "替换事件"
    content.events.append(original)
    content.event_by_id[eid] = original
    try:
        with _TempEvents(content, replacement):
            same_id_events = [ev for ev in content.events if ev.id == eid]
            assert same_id_events == [replacement]
            assert content.event_by_id[eid] is replacement

        same_id_events = [ev for ev in content.events if ev.id == eid]
        assert same_id_events == [original]
        assert content.event_by_id[eid] is original
    finally:
        if original in content.events:
            content.events.remove(original)
        if content.event_by_id.get(eid) is original:
            content.event_by_id.pop(eid, None)


@pytest.mark.parametrize("bad_item", [None, 42, "字符串"])
def test_new_issue_non_dict_item_rejected_not_crash(read_game, bad_item):
    db, state, _ = read_game
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [bad_item]})
    rej = _rejected(out)
    assert len(rej) == 1
    assert rej[0]["category"] == "invalid_enum"
    assert "非对象" in rej[0]["reason"]


@pytest.mark.parametrize("field,bad", [
    ("bar_value", "abc"),     # int() 抛
    ("severity", "高"),        # int() 抛
    ("tags", 5),               # list(int) 抛
    # 注：cancel_cost 不在此（拒整项）——它与 ongoing/effect 同属 dict 字段，走 _eff_dict 容忍
    # 归 {}（次要字段脏不丢整个 issue=符 P1），见 test_new_issue_non_dict_cancel_cost_tolerated。
])
def test_new_issue_dirty_coercion_field_rejected(read_game, field, bad):
    db, state, _ = read_game
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·脏字段", field: bad}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "强转失败" in rej[0]["reason"]


@pytest.mark.parametrize("bad_kind", ["reform", "policy", "局势"])
def test_new_issue_bad_kind_rejected(read_game, bad_kind):
    db, state, _ = read_game
    # 脏 kind（DELTA_SCHEMA 记 reform 等是已知坏值）→ insert_issue 会抛 ValueError；移除 broad
    # except 后须预检拒整项，不能逃逸成 SettlementAbort（cmr ni r1 concur）。
    ni = {"origin_kind": "decree", "kind": bad_kind, "title": "测试·脏kind"}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "kind" in rej[0]["reason"]


def test_new_issue_dirty_inertia_rejected(read_game):
    db, state, _ = read_game
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
        "new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "kind": "situation",
                        "title": "测试·超大severity", "severity": 10 ** 100}],
    })
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out  # 不 abort、照常落库
    iid = int(created[0]["issue_id"])
    sev = db.conn.execute("SELECT severity FROM issues WHERE id=?", (iid,)).fetchone()["severity"]
    assert sev == 100  # clamp 到域上界


def test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition(game):
    db, state, _ = game
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "origin_ref": _decree_origin(db, state),
            "kind": "situation",
            "title": "测试·stop_condition fallback",
            "bar_value": 90,
            "resolve_condition": "   ",
            "stop_condition": "region.shaanxi.unrest <= 30",
        }],
    })

    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out
    iid = int(created[0]["issue_id"])
    row = db.conn.execute(
        "SELECT resolve_condition, stop_condition FROM issues WHERE id=?", (iid,)).fetchone()
    assert row["resolve_condition"] == "region.shaanxi.unrest <= 30"
    assert row["stop_condition"] == "region.shaanxi.unrest <= 30"

    advanced = db.advance_issue(
        state, iid, trigger_kind="decree", delta_bar=20,
        narrative="legacy fallback 普通推进到满值。")
    assert advanced["bar_value"] == 100
    assert advanced["status"] == "resolved"


def test_new_issue_infinity_field_rejected_not_abort(read_game):
    db, state, _ = read_game
    # JSON 里 1e309 解析成 float('inf')，int(inf) 抛 OverflowError（非 TypeError/ValueError）——
    # 预校验须连 OverflowError 一起拒整项，不能逃逸 abort（cmr ni r3 codex）。
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·inf", "bar_value": 1e309}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "强转失败" in rej[0]["reason"]


def test_new_issue_infinity_expected_months_rejected_not_abort(read_game):
    db, state, _ = read_game
    # expected_months=inf 经严格化的 _compute_inertia（_strict_int 拒 float/inf，cmr ni r6）→
    # 拒整项（与 bar_value=inf 一致），不逃逸 abort。
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·inf月数", "expected_months": 1e309}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"


def test_new_issue_severity_zero_preserved(game):
    db, state, _ = game
    # 合法 severity=0 须保留，不能被 `or 50` 静默改成 50（数据保真，cmr ni r4 codex）。
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "kind": "situation", "title": "测试·severity0",
                        "severity": 0, "effect_on_resolve": {"metrics": {"民心": 1}}}],
    })
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out
    iid = int(created[0]["issue_id"])
    assert db.conn.execute("SELECT severity FROM issues WHERE id=?", (iid,)).fetchone()["severity"] == 0


def test_new_issue_garbage_severity_rejected(read_game):
    db, state, _ = read_game
    # severity=[] 是脏值（非缺省/null）——应走拒整项（int([]) TypeError），不静默默认 50。
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{"origin_kind": "decree", "kind": "situation", "title": "测试·脏severity", "severity": []}],
    })
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"


@pytest.mark.parametrize("field,bad", [
    ("bar_value", 3.7),    # float 截断非合法整数 delta
    ("severity", True),    # bool
    ("severity", 2.5),     # float
    ("inertia", True),     # bool（legacy inertia 经 _compute_inertia 严格转换）
    ("expected_months", 1.5),  # float（expected_months 经 _compute_inertia）
])
def test_new_issue_bool_float_int_field_rejected(read_game, field, bad):
    db, state, _ = read_game
    # 整数字段用 _strict_int：bool/float 拒整项（与 region/army/faction 段一致，cmr ni r6 codex），
    # 不再 int(3.7)=3 / int(True)=1 静默强转落库。
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·bool/float", field: bad}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"


@pytest.mark.parametrize("bad_kind", [False, 0, []])
def test_new_issue_falsy_nonstring_kind_rejected(read_game, bad_kind):
    db, state, _ = read_game
    # present 的 falsy 非串 kind（false/0/[]）不再被 `or "initiative"` 静默默认、绕过白名单——
    # None-sentinel 只对 缺省/null/空串 默认，其余走白名单拒收（cmr ni r6 codex）。
    ni = {"origin_kind": "decree", "kind": bad_kind, "title": "测试·falsy kind"}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "kind" in rej[0]["reason"]


def test_new_issue_insert_code_exception_propagates(game, monkeypatch):
    db, state, _ = game
    def _boom(*a, **k):
        raise RuntimeError("模拟 insert_issue 落库代码异常")
    monkeypatch.setattr(type(db), "insert_issue", _boom)
    # insert 代码/DB 异常不再 WARN 吞 → 上抛（上层 applier.atomic 据此 SettlementAbort）。
    with pytest.raises(RuntimeError, match="模拟 insert_issue"):
        I.apply_issue_tracker_output(db, state, {
            "new_issues": [{"origin_kind": "decree", "origin_ref": _decree_origin(db, state),
                            "kind": "situation", "title": "测试·正常字段"}],
        })


def test_new_issue_valid_decree_still_creates(game):
    db, state, _ = game
    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree", "kind": "situation", "title": "测试·新立局势",
            "origin_ref": _decree_origin(db, state),
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


# --- event_pool 路径 fail-loud（cmr ni r7 codex high）---
# new_issues 段第二条 insert 路 = event_pool（预设事件触发，走 event_to_issue）。decree 路径
# R1-R6 已 fail-loud（insert 代码/DB 真异常上抛），但 event_to_issue 旧把 db.insert_issue 裹在
# `except Exception: WARN; return None`，把真异常吞成 None、调用方记普通 rejected——同段契约的
# 遗漏分支。移除该 broad except 后真异常上抛（与 decree 路径一致），幂等去重 early-return None
# （在 try 外）不受影响。


def test_event_to_issue_insert_exception_propagates(read_game, monkeypatch):
    db, state, _ = read_game
    # 直接覆盖 fix 点：event_to_issue 内 insert 真异常上抛，不再 WARN 吞成 None。
    eid = _pick_event_pool_id(db)
    ev = I._ctx().event_by_id[eid]

    def _boom(*a, **k):
        raise RuntimeError("模拟 event_to_issue insert 落库代码异常")

    monkeypatch.setattr(type(db), "insert_issue", _boom)
    with pytest.raises(RuntimeError, match="模拟 event_to_issue"):
        I.event_to_issue(db, state, ev)


def test_new_issue_event_pool_insert_exception_propagates(game, monkeypatch):
    db, state, content = game
    # codex 强调的 call-site seam：通过 apply_issue_tracker_output 的 event_pool 分支驱动，
    # insert 真异常一路上抛（上层 applier.atomic 据此 SettlementAbort），不被吞成静默 rejected。
    eid = "__event_pool_insert_exception__"
    ev = _hist_event(eid)
    I.bind_content(content)
    _open_event_window(state, ev)

    def _boom(*a, **k):
        raise RuntimeError("模拟 event_pool insert 落库代码异常")

    with _TempEvents(content, ev):
        _ensure_event_candidate(db, state, eid)
        monkeypatch.setattr(type(db), "insert_issue", _boom)
        with pytest.raises(RuntimeError, match="模拟 event_pool"):
            I.apply_issue_tracker_output(db, state, {
                "new_issues": [{"origin_kind": "event_pool", "id": eid}],
            })


def test_event_to_issue_duplicate_returns_none_not_raise(game):
    db, state, _ = game
    # 幂等回归保护：移除 broad except 不得波及两种 None 的区分——同源事件第二次触发仍由
    # try 外的去重 early-return None（正常跳过），绝不抛、不重立（否则 fix 错把幂等当真异常）。
    eid = _pick_event_pool_id(db)
    ev = I._ctx().event_by_id[eid]
    first = I.event_to_issue(db, state, ev)
    assert first is not None, "首次触发应立项"
    again = I.event_to_issue(db, state, ev)
    assert again is None, "同源事件重复触发应幂等返回 None，不抛不重立"


def test_new_issue_event_pool_rejects_expired_event(game):
    db, state, _ = game
    eid = _pick_event_pool_id(db)
    db.mark_event_expired(state, eid)

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{"origin_kind": "event_pool", "id": eid}],
    })

    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["id"] == eid
    assert "过期" in rej[0]["reason"] or "终态" in rej[0]["reason"]
    assert db.find_any_issue_by_origin("event_pool", eid) is None


def test_authoritative_event_pool_rejects_same_batch_obsolete_event(game):
    db, state, content = game
    I.bind_content(content)
    state.year = 1
    state.period = 1
    upstream = _hist_event("__authoritative_upstream_triggers__")
    downstream = _hist_event(
        "__authoritative_downstream_obsolete__",
        {"event.__authoritative_upstream_triggers__.triggered": "<1"},
    )
    with _TempEvents(content, upstream, downstream):
        snapshot = {candidate.id for candidate in I.gather_candidate_events(state, db)}
        assert {upstream.id, downstream.id} <= snapshot

        out = I.apply_issue_tracker_output(
            db,
            state,
            {
                "new_issues": [
                    {"origin_kind": "event_pool", "id": upstream.id},
                    {"origin_kind": "event_pool", "id": downstream.id},
                ],
            },
            candidate_event_ids_at_input=snapshot,
            candidate_event_ids_authoritative=True,
        )

    created = [item for item in _new(out) if item.get("issue_id")]
    rejected = [item for item in _rejected(out) if item.get("id") == downstream.id]
    assert [item["id"] for item in created] == [upstream.id], out
    assert len(rejected) == 1, out
    assert "终态" in rejected[0]["reason"] or "作废" in rejected[0]["reason"]
    assert db.find_any_issue_by_origin("event_pool", downstream.id) is None


# --- tags 字段严格化（cmr ni r8 codex medium）---
# tags = list(ni.get("tags") or []) 对标量串静默拆字（list("募营")=['募','营']）、对非串元素
# 不拒（list([5])=[5]）。后果：_initiative_resolve_pairing_warnings 用子串匹配整词「募营」判
# new_armies 配对，拆字后「募 营」失配 → bypass #45/#46 守门；且拆字本身污染 DB tags。与 R6
# int 字段 _strict_int 同一字段校验 class——缺省/null/空串→[]，present 须 list/tuple 且元素全 str。


@pytest.mark.parametrize("bad_tags", ["募营", "单串标量"])
def test_new_issue_scalar_string_tags_rejected(read_game, bad_tags):
    db, state, _ = read_game
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·标量tags", "tags": bad_tags}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "tags" in rej[0]["reason"]


def test_new_issue_non_string_tag_element_rejected(read_game):
    db, state, _ = read_game
    ni = {"origin_kind": "decree", "kind": "situation", "title": "测试·脏tag元素", "tags": [5, "正常"]}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    rej = _rejected(out)
    assert len(rej) == 1, out
    assert rej[0]["category"] == "invalid_enum"
    assert "tags" in rej[0]["reason"]


def test_new_issue_valid_list_tags_preserved(game):
    db, state, _ = game
    # 正常 list[str] tags 整词保全（不拆字），pairing 短语完整 → 正常立项落库。
    ni = {"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "kind": "situation", "title": "测试·正常tags", "tags": ["募营", "边事"]}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out
    iid = int(created[0]["issue_id"])
    row = db.conn.execute("SELECT tags FROM issues WHERE id=?", (iid,)).fetchone()
    assert json.loads(row["tags"]) == ["募营", "边事"], "整词须保全、不得拆字"


# --- cancel_cost 与 effect 字段同走 _eff_dict 容忍（cmr ni r9 codex medium）---
# cancel_cost 旧用 dict(raw)：标量串 raise 拒整项（违 P1：次要字段脏不该丢整个 issue），list-of-pairs
# 静默 garble（dict([["民心",-5]])={'民心':-5}、dict(["ab"])={'a':'b'}）。改与 ongoing/effect 三个
# dict 字段统一 _eff_dict（非 dict → {} 容忍）：issue 仍正常立、cancel_cost 落空 {} 不 garble。


@pytest.mark.parametrize("bad_cancel", ["白银万两", [["民心", -5]], ["ab"], [], 5])
def test_new_issue_non_dict_cancel_cost_tolerated(game, bad_cancel):
    db, state, _ = game
    ni = {"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "kind": "situation", "title": "测试·脏cancel", "cancel_cost": bad_cancel}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out  # issue 仍立（不因次要字段脏拒整项）
    iid = int(created[0]["issue_id"])
    row = db.conn.execute("SELECT cancel_cost FROM issues WHERE id=?", (iid,)).fetchone()
    assert json.loads(row["cancel_cost"]) == {}, "非 dict cancel_cost 须容忍归空 {}，不得 garble"


def test_new_issue_valid_cancel_cost_preserved(game):
    db, state, _ = game
    # 正常 dict cancel_cost 原样保全（_eff_dict 对 dict 直通）。
    ni = {"origin_kind": "decree", "origin_ref": _decree_origin(db, state), "kind": "situation", "title": "测试·正常cancel",
          "cancellable": "decree", "cancel_cost": {"民心": -5, "皇威": -2}}
    out = I.apply_issue_tracker_output(db, state, {"new_issues": [ni]})
    created = [n for n in _new(out) if not n.get("rejected") and n.get("issue_id")]
    assert len(created) == 1, out
    iid = int(created[0]["issue_id"])
    row = db.conn.execute("SELECT cancel_cost FROM issues WHERE id=?", (iid,)).fetchone()
    assert json.loads(row["cancel_cost"]) == {"民心": -5, "皇威": -2}
