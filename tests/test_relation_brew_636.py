"""#636 关系摘要层 S5：两段式存储＋月末增量重酿腿。

验收锚（冻结票面＋庭裁 r1-r4）：
- TD-2 奠基段永存：连续多轮重酿奠基段字节不丢不改。
- TD-3／庭裁 r3③ 无事不变：既无新事件又无 pending 的月份字节不变、零重酿调用。
- TD-4 翻转可回溯：重酿输入必含新边事件。
- TD-5／庭裁 r1 F1 失败月进持久 pending-backlog，下月补酿。
- 庭裁 r3 F1 三条故障注入机械验收（①②③）。
- 庭裁 r3/r4 F2 超长 fixture（B×436＝32,700 字节，sha256 冻结）经真实酿制
  持久化链路写入→读回字节原样。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading

import pytest

from ming_sim.db import GameDB
from ming_sim.decree import settle_with_delta
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    RECENT_KEY,
    merge_founding_segment,
    relation_dimension,
    run_month_end_relation_brew,
)
from ming_sim.relations import EMPEROR_NODE


def _add_edge(db, state, *, source, target, kind, context, origin):
    return db.record_relation_edge_event(
        source=source, target=target, event_kind=kind, context=context,
        origin=origin, turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )


def _brew_fn_factory(calls):
    """确定性假酿制手：记录每次收到的 payload，按序返回脚本化输出。"""

    def _brew(payload_json: str) -> str:
        calls.append(json.loads(payload_json))
        script = _brew.outputs.pop(0) if getattr(_brew, "outputs", None) else {
            FOUNDINGS_KEY: [], RECENT_KEY: "无事近况。",
        }
        return json.dumps(script, ensure_ascii=False)

    return _brew


def _script(foundings=None, recent="近况重酿。"):
    return {FOUNDINGS_KEY: list(foundings or []), RECENT_KEY: recent}


# ---------------------------------------------------------------- TD-2 奠基段永存

def test_founding_segment_survives_consecutive_brews_byte_identical(game):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召，擢杨嗣昌于五品郎中。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(foundings=["越次一召，擢杨嗣昌于五品郎中。"],
                               recent="杨嗣昌蒙知遇之恩。")]

    report = run_month_end_relation_brew(db, state, brew_fn)
    assert report["selected"] == 1 and len(report["brewed"]) == 1

    first = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert first["dimension"] == "君臣"
    assert first["founding_segment"] == "越次一召，擢杨嗣昌于五品郎中。"

    # 次月：新边事件入账（先落事件、后在本月末酿——与生产同序），酿制手不再报
    # 奠基句——奠基段字节不丢不改。次月无新事件的关系不因历史旧事件被选中。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="兑现所托",
              context="杨嗣昌复命，所托之事办结。", origin="audience:turn-2")
    brew_fn.outputs = [_script(foundings=[], recent="杨嗣昌所托办结，恩遇正浓。")]
    run_month_end_relation_brew(db, state, brew_fn)

    second = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert second["founding_segment"] == first["founding_segment"]
    assert second["recent_segment"] == "杨嗣昌所托办结，恩遇正浓。"

    # 第三月：酿制手重复报同一奠基句也不重复入段（补酿不重复记账）。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="辜负",
              context="杨嗣昌所请被驳。", origin="audience:turn-3")
    brew_fn.outputs = [_script(foundings=["越次一召，擢杨嗣昌于五品郎中。"],
                               recent="杨嗣昌所请被驳，渐生离心。")]
    run_month_end_relation_brew(db, state, brew_fn)
    third = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert third["founding_segment"] == first["founding_segment"]


# ------------------------------------------------- TD-3／庭裁 r3③ 无事不变

def test_no_new_events_and_no_pending_month_bytes_unchanged_zero_brews(game):
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="毕王有站台之谊。")]
    run_month_end_relation_brew(db, state, brew_fn)
    before = db.get_relation_summary("毕自严", "王绍徽")

    # 成功月重跑结算（跨月推进、无新事件、无 pending）：字节不变、零重酿调用。
    calls.clear()
    state.turn += 1
    state.period += 1
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 0
    assert calls == []
    after = db.get_relation_summary("毕自严", "王绍徽")
    assert after["recent_segment"] == before["recent_segment"]
    assert after["founding_segment"] == before["founding_segment"]


# ------------------------------------------------------- TD-4 翻转可回溯

def test_flip_brew_input_must_contain_new_edge_events(game):
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="知遇",
              context="钱谦益蒙召对，简拔入朝。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="钱谦益蒙知遇。")]
    run_month_end_month = run_month_end_relation_brew(db, state, brew_fn)
    assert len(run_month_end_month["brewed"]) == 1

    # 语义翻转月：新辜负事件入账后重酿，酿制输入必含该新事件。
    flip_id = _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="辜负",
                        context="钱谦益哭谏被拒，圣眷转衰。", origin="audience:turn-2")
    calls.clear()
    brew_fn.outputs = [_script(recent="钱谦益因哭谏被拒而离心。")]
    run_month_end_relation_brew(db, state, brew_fn)

    assert len(calls) == 1
    payload = calls[0]
    assert payload["new_events"] and payload["new_events"][0]["context"] == "钱谦益哭谏被拒，圣眷转衰。"
    assert payload["new_events"][0]["event_kind"] == "辜负"
    assert payload["recent_segment"] == "钱谦益蒙知遇。"
    summary = db.get_relation_summary(EMPEROR_NODE, "钱谦益")
    assert summary["last_event_id"] >= flip_id


# --------------------------------- TD-5／庭裁 r1 F1 失败月 pending-backlog

def test_failed_month_degrades_to_pending_and_rebrews_next_month(game):
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def failing_brew(payload_json: str) -> str:
        raise RuntimeError("酿制裁判失手")

    report = run_month_end_relation_brew(db, state, failing_brew)
    assert report["selected"] == 1 and report["degraded"]

    # 保旧摘要（本就无摘要）、事件不丢、pending 持久在册。
    assert db.get_relation_summary("温体仁", "周延儒") is None
    assert db.get_relation_edge_events(source="温体仁", target="周延儒")
    pending = db.get_relation_brew_pending()
    assert [(row["source"], row["target"]) for row in pending] == [("温体仁", "周延儒")]

    # 次月无新事件，仍因 pending 被选中；成功后 pending 清除、摘要落定。
    state.turn += 1
    state.period += 1
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="温周结怨，朝堂侧目。")]
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 1 and len(report["brewed"]) == 1
    assert calls and calls[0]["has_pending_failure"] is True
    assert db.get_relation_brew_pending() == []
    summary = db.get_relation_summary("温体仁", "周延儒")
    assert summary["recent_segment"] == "温周结怨，朝堂侧目。"
    assert summary["dimension"] == "大臣"


# ------------------------------------ 庭裁 r3 F1① 故障注入 A：事务未提交即崩

def test_fault_a_uncommitted_summary_crash_keeps_pending_and_old_summary(game):
    db, state, content = game
    _add_edge(db, state, source="洪承畴", target=EMPEROR_NODE, kind="兑现所托",
              context="洪承畴剿抚办结。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="洪承畴初结天恩。")]
    run_month_end_relation_brew(db, state, brew_fn)
    old_summary = db.get_relation_summary("洪承畴", EMPEROR_NODE)

    # 次月：先推进、再落新边事件（事件落在次月），随后注入「摘要已写、事务未提交
    # 即崩」：第 1 次 commit＝认领（须成功、先于崩溃点持久），第 2 次起全部失败——
    # 真实崩溃点之后任何写（含 catch 后补记）都无法落盘，重启后 pending 在册即
    # 证明它来自崩溃前的认领，而非 catch 补记。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source="洪承畴", target=EMPEROR_NODE, kind="辜负",
              context="洪承畴所请饷银被驳。", origin="audience:turn-2")
    original_commit = db.conn.commit
    commits = {"n": 0}

    def crashing_commit():
        commits["n"] += 1
        if commits["n"] >= 2:
            raise sqlite3.OperationalError("injected: crash before commit")
        original_commit()

    db.conn.commit = crashing_commit
    try:
        brew_fn.outputs = [_script(recent="洪承畴请饷被驳，心怨。")]
        run_month_end_relation_brew(db, state, brew_fn)
    finally:
        db.conn.commit = original_commit
    assert commits["n"] >= 2  # 崩溃点确实被注入在认领提交之后的 apply 提交处

    # 重启（关闭重开 DB）：pending 仍在——且只能是崩前已持久的认领；
    # 摘要读回＝崩前旧值（不得已见新摘要）。
    path = db.path
    db.close()
    db = GameDB(path, content)
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        ("洪承畴", EMPEROR_NODE)
    ]
    assert db.get_relation_summary("洪承畴", EMPEROR_NODE)["recent_segment"] == (
        old_summary["recent_segment"]
    )

    # 补酿恰一次：再跑结算，成功落定、pending 清除。
    calls.clear()
    brew_fn.outputs = [_script(recent="洪承畴请饷被驳，心怨。")]
    report = run_month_end_relation_brew(db, state, brew_fn)
    assert len(report["brewed"]) == 1
    assert len(calls) == 1
    assert db.get_relation_brew_pending() == []
    assert db.get_relation_summary("洪承畴", EMPEROR_NODE)["recent_segment"] == "洪承畴请饷被驳，心怨。"


# ------------------------------------ 庭裁 r3 F1② 故障注入 B：pending 未持久即崩

def test_fault_b_pending_mark_lost_still_selected_and_brewed_once(game):
    db, state, content = game
    _add_edge(db, state, source="孙传庭", target=EMPEROR_NODE, kind="辜负",
              context="孙传庭困守乏饷。", origin="audience:turn-1")

    # 注入 fresh claim→durable pending 缝：第 1 次 commit（认领）即崩，且窗口内
    # 后续 commit 全部失败——pending 确实未曾持久。
    original_commit = db.conn.commit
    injected = {"active": True}

    def crashing_commit():
        if injected["active"]:
            raise sqlite3.OperationalError("injected: crash before pending durable")
        original_commit()

    def failing_brew(payload_json: str) -> str:
        raise RuntimeError("酿制裁判失手")

    db.conn.commit = crashing_commit
    try:
        run_month_end_relation_brew(db, state, failing_brew)
    finally:
        injected["active"] = False
        db.conn.commit = original_commit

    # 重启（关闭重开 DB）：pending 未持久、边事件已在册。
    path = db.path
    db.close()
    db = GameDB(path, content)
    assert db.get_relation_brew_pending() == []
    assert db.get_relation_edge_events(source="孙传庭", target=EMPEROR_NODE)

    # 该月仍被选中（本月新事件判据）、酿制恰一次：认领→成功→pending 同事务清除。
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="孙传庭困守乏饷，怨望渐深。")]
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 1
    assert len(calls) == 1
    assert len(report["brewed"]) == 1
    assert db.get_relation_summary("孙传庭", EMPEROR_NODE)["recent_segment"] == (
        "孙传庭困守乏饷，怨望渐深。"
    )
    assert db.get_relation_brew_pending() == []


# --------------------------- 庭裁 r3/r4 F2 超长 fixture：32,700 字节零删改

def test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical(game):
    # r4 冻结公式：B（UTF-8 75 字节）× 436 ＝ 32,700 字节，sha256 冻结。
    block = "崇祯边事关系账超长验收样文-Chongzhen-relation-brew-0123456789-".encode("utf-8")
    assert len(block) == 75
    fixture = block * 436
    assert len(fixture) == 32700
    assert hashlib.sha256(fixture).hexdigest() == (
        "8241a513648a4a99d6690f0a2cc942ee9523702301e6db12a9333c458c032240"
    )
    fixture_text = fixture.decode("utf-8")

    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召。", origin="audience:turn-1")

    def fixture_brew(payload_json: str) -> str:
        return json.dumps(
            {FOUNDINGS_KEY: [], RECENT_KEY: fixture_text}, ensure_ascii=False
        )

    # 经真实酿制持久化链路（run_month_end_relation_brew → apply_relation_brew_result）
    # 写入→读回：字节原样，全链无截断无删改。
    report = run_month_end_relation_brew(db, state, fixture_brew)
    assert len(report["brewed"]) == 1

    stored = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")["recent_segment"]
    stored_bytes = stored.encode("utf-8")
    assert len(stored_bytes) == 32700
    assert hashlib.sha256(stored_bytes).hexdigest() == (
        "8241a513648a4a99d6690f0a2cc942ee9523702301e6db12a9333c458c032240"
    )


# --------------------------------------------- P5：批内条目并行不串行

def test_brew_batch_runs_items_in_parallel_not_serialized(game):
    db, state, _ = game
    pairs = [("甲", "乙"), ("丙", "丁")]
    for source, target in pairs:
        _add_edge(db, state, source=source, target=target, kind="协作",
                  context=f"{source}与{target}当场协作。", origin=f"audience:{source}{target}")

    barrier = threading.Barrier(len(pairs), timeout=10)
    threads: list = []

    def parallel_brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        threads.append(threading.current_thread().name)
        barrier.wait()  # 串行实现会在第二个条目处超时破裂
        return json.dumps(
            _script(recent=f"{payload['source']}与{payload['target']}协作在案。"),
            ensure_ascii=False,
        )

    report = run_month_end_relation_brew(db, state, parallel_brew, parallel=True)
    assert len(report["brewed"]) == 2
    assert len(set(threads)) == 2
    for source, target in pairs:
        assert db.get_relation_summary(source, target)["recent_segment"] == (
            f"{source}与{target}协作在案。"
        )


# ------------------------------------------------- 「本月新增」总判据（历史水位不选旧事）

def test_historical_events_alone_do_not_select_in_later_month(game):
    """历史月份的未酿旧事件（无 pending、无本月新事件）不得在后续月被选中。"""
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="结怨",
              context="毕自严当殿与王绍徽结怨。", origin="audience:turn-1")

    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    state.turn += 1
    state.period += 1
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 0
    assert calls == []
    assert db.get_relation_summary("毕自严", "王绍徽") is None


# ------------------------------------------------- 结算接缝：腿在事务提交后启酿、失败不阻塞

def test_settle_invokes_brew_leg_after_commit_and_survives_leg_failure(game):
    db, state, content = game
    observed: list = []

    def runner(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        # 输入依赖边界：runner 收到调用时结算事务已提交（state 已推进），但 settled
        # 年月快照必须是 next_period 之前的本结算月（不得把下一个月写进输入/落款）。
        observed.append((
            "called", settle_state.turn, settle_db is db,
            settled_turn, int(settled_year), int(settled_period),
        ))
        raise RuntimeError("腿整体故障")

    before_turn = state.turn
    settled_year, settled_period = int(state.year), int(state.period)
    settle_with_delta(
        state, db, {}, before_turn=before_turn, content=content,
        relation_brew_runner=runner,
    )

    assert state.turn == before_turn + 1
    assert observed == [(
        "called", before_turn + 1, True,
        before_turn, settled_year, settled_period,
    )]  # 结算未被腿故障拖垮；快照＝next_period 前的本结算月


def test_settle_brew_leg_records_settled_month_not_advanced_month(game):
    """next_period 已把 state 推进到下一个月后，酿制输入/摘要落款仍须是本结算月
    快照（decree 传递），不得把下一个月写进输入/last_brewed（错月修复）。"""
    db, state, content = game
    _add_edge(db, state, source="徐光启", target=EMPEROR_NODE, kind="协作",
              context="徐光启与皇上当场协作。", origin="audience:turn-1")
    calls: list = []

    def runner(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        brew_fn = _brew_fn_factory(calls)
        brew_fn.outputs = [_script(recent="协作在案。")]
        return run_month_end_relation_brew(
            settle_db, settle_state, brew_fn,
            settled_turn=settled_turn,
            settled_year=settled_year,
            settled_period=settled_period,
        )

    before_turn = state.turn
    settled_year, settled_period = int(state.year), int(state.period)
    settle_with_delta(
        state, db, {}, before_turn=before_turn, content=content,
        relation_brew_runner=runner,
    )

    assert state.turn == before_turn + 1  # state 已被推进，但落款不得跟着走
    assert len(calls) == 1
    payload = calls[0]
    assert (payload["year"], payload["period"]) == (settled_year, settled_period)
    summary = db.get_relation_summary("徐光启", EMPEROR_NODE)
    assert (summary["last_brewed_year"], summary["last_brewed_period"]) == (
        settled_year, settled_period,
    )
    assert summary["recent_segment"] == "协作在案。"


# ------------------------------------------------------- 奠基段拼装机械语义

def test_merge_founding_segment_append_only_and_dedup():
    assert merge_founding_segment("", ["甲句。", "乙句。"]) == "甲句。\n乙句。"
    assert merge_founding_segment("甲句。", ["甲句。", "丙句。"]) == "甲句。\n丙句。"
    assert merge_founding_segment("甲句。", []) == "甲句。"
    # 空字符串条目是结构空操作；空白条目是合法字符串，逐字保留不去除。
    assert merge_founding_segment("甲句。", [""]) == "甲句。"
    assert merge_founding_segment("甲句。", ["  "]) == "甲句。\n  "


def test_merge_founding_segment_preserves_bytes_exactly():
    # P6/ADR 0142 零删改：旧段空行与末尾换行逐字保留，新句只做结构追加。
    old = "甲句。\n\n乙句。\n"
    assert merge_founding_segment(old, ["丙句。"]) == old + "\n丙句。"
    assert merge_founding_segment(old, []) == old
    # 新字符串逐字保留：首尾空白不剥。
    assert merge_founding_segment("", ["  句前空格。  "]) == "  句前空格。  "
    assert merge_founding_segment("甲句。", [" 甲句。 "]) == "甲句。\n 甲句。 "
    # 严格字节相等去重：仅逐字全等才跳过；近似串（多空格/带后缀）不吞。
    assert merge_founding_segment("甲句。", ["甲句。", "甲句。", "甲句 "]) == "甲句。\n甲句 "
    # 补酿不重复记账：整段重复报同一句（含多行句）不重复追加。
    merged = merge_founding_segment("", ["甲句。", "乙句。\n乙二句。"])
    assert merged == "甲句。\n乙句。\n乙二句。"
    assert merge_founding_segment(merged, ["乙句。\n乙二句。", "甲句。"]) == merged


def test_relation_dimension_marks_emperor_edges():
    assert relation_dimension(EMPEROR_NODE, "杨嗣昌") == "君臣"
    assert relation_dimension("杨嗣昌", EMPEROR_NODE) == "君臣"
    assert relation_dimension("毕自严", "王绍徽") == "大臣"
