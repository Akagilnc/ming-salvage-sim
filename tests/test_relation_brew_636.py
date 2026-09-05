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
import httpx
import json
import sqlite3
import threading

import pytest
from openai import APIConnectionError, APITimeoutError

import ming_sim.decree as decree_module
from ming_sim.faction_brew import STANCE_KEY, VIEW_FACTION_STANCE
from ming_sim.db import GameDB
from ming_sim.decree import SettlementAbort, settle_with_delta
from ming_sim.exceptions import LLMUnavailable
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    RECENT_KEY,
    MonthEndRelationBrewLeg,
    build_brew_input,
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
    """确定性假酿制手：记录每次收到的 payload，按条目身份分队列脚本化输出。

    #637 同批双契约：关系工作项按序弹 outputs（原语义不变）；派系工作项按序弹
    stances、未备则用默认合法态势产出——批内派系腿静默成功，不劫持关系脚本、
    也不留派系 pending 噪声污染后续月份的选中判据。"""

    def _brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        calls.append(payload)
        if payload.get("view") == VIEW_FACTION_STANCE:
            stances = getattr(_brew, "stances", None)
            script = (
                dict(stances.pop(0)) if stances else {STANCE_KEY: "派系态势重酿。"}
            )
        else:
            outputs = getattr(_brew, "outputs", None)
            script = outputs.pop(0) if outputs else {
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
    # 同批新事实：杨嗣昌党籍投影皇党（factions 表现存）→ 关系对＋皇党两个工作项。
    assert report["selected"] == 2 and len(report["brewed"]) == 2

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
    # 同批新事实：钱谦益党籍投影东林 → 关系对＋东林。
    assert len(run_month_end_month["brewed"]) == 2

    # 语义翻转月：新辜负事件入账后重酿，酿制输入必含该新事件。
    flip_id = _add_edge(db, state, source=EMPEROR_NODE, target="钱谦益", kind="辜负",
                        context="钱谦益哭谏被拒，圣眷转衰。", origin="audience:turn-2")
    calls.clear()
    brew_fn.outputs = [_script(recent="钱谦益因哭谏被拒而离心。")]
    run_month_end_relation_brew(db, state, brew_fn)

    # 同批含东林派系工作项：翻转判据只辖关系腿的调用缝。
    relation_calls = [c for c in calls if "view" not in c]
    assert len(relation_calls) == 1
    payload = relation_calls[0]
    assert payload["new_events"] and payload["new_events"][0]["context"] == "钱谦益哭谏被拒，圣眷转衰。"
    assert payload["new_events"][0]["event_kind"] == "辜负"
    assert payload["recent_segment"] == "钱谦益蒙知遇。"
    summary = db.get_relation_summary(EMPEROR_NODE, "钱谦益")
    assert summary["last_event_id"] >= flip_id


# --------------------------------- TD-5／庭裁 r1 F1 失败月 pending-backlog

def test_failed_month_degrades_to_pending_and_rebrews_next_month(game):
    db, state, _ = game
    failed_context = "温体仁当殿讦周延儒。"
    failed_id = _add_edge(
        db, state, source="温体仁", target="周延儒", kind="结怨",
        context=failed_context, origin="audience:turn-1",
    )

    # 真 LLM 单条失败（声明类型 LLMUnavailable）→ 降级留痕；程序错类不走此路。
    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")

    report = run_month_end_relation_brew(db, state, failing_brew)
    # 同批新事实：温/周均皇党 → 关系对＋皇党，双双降级。
    assert report["selected"] == 2 and report["degraded"]

    # 保旧摘要（本就无摘要）、事件不丢、pending 持久在册。
    assert db.get_relation_summary("温体仁", "周延儒") is None
    assert db.get_relation_edge_events(source="温体仁", target="周延儒")
    pending = db.get_relation_brew_pending()
    assert [(row["source"], row["target"]) for row in pending] == [("温体仁", "周延儒")]

    # 次月无新事件，仍因 pending 被选中；成功后 pending 清除、摘要落定。
    # #642：失败月事件在次月 payload 双桶并集中恰一次，且落 new 不落 prior。
    state.turn += 1
    state.period += 1
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="温周结怨，朝堂侧目。")]
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 2 and len(report["brewed"]) == 2
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls and relation_calls[0]["has_pending_failure"] is True
    payload = relation_calls[0]
    new_hits = [e for e in payload["new_events"] if e["context"] == failed_context]
    prior_hits = [e for e in payload["prior_events"] if e["context"] == failed_context]
    assert len(new_hits) + len(prior_hits) == 1
    assert len(new_hits) == 1 and prior_hits == []
    assert db.get_relation_brew_pending() == []
    summary = db.get_relation_summary("温体仁", "周延儒")
    assert summary["recent_segment"] == "温周结怨，朝堂侧目。"
    assert summary["dimension"] == "大臣"
    assert int(summary["last_event_id"]) >= int(failed_id)


# ---------------- #642 r3 R2：commit→join→persist 前窗口（非 SIGKILL 可控接缝）

def test_r2_commit_join_before_persist_fault_keeps_pending_and_rebrrews_once(
    game, monkeypatch,
):
    """#642 R2：settle atomic 已提交、brew join 已完成、真实 persist 尚未写入时可控中止。

    注入＝既有生产接缝 MonthEndRelationBrewLeg.persist 入口抛错（非 SIGKILL、
    无 test-only 生产钩子）。重开后续跑恰一次补酿、旧摘要字节不变、边 id 不双增。
    """
    db, state, content = game
    source, target = "洪承畴", EMPEROR_NODE
    _add_edge(db, state, source=source, target=target, kind="兑现所托",
              context="洪承畴剿抚办结。", origin="audience:turn-1")
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="洪承畴初结天恩。")]
    run_month_end_relation_brew(db, state, brew_fn)
    old_recent = db.get_relation_summary(source, target)["recent_segment"]
    assert old_recent == "洪承畴初结天恩。"

    # 次月新边事件：进入 settle 生产序后被选中并 durable claim。
    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=source, target=target, kind="辜负",
              context="洪承畴所请饷银被驳。", origin="audience:turn-2")
    edge_ids_before = {
        int(row["id"])
        for row in db.get_relation_edge_events(source=source, target=target)
    }

    persist_hits = {"n": 0}
    real_persist = MonthEndRelationBrewLeg.persist

    def boom_then_real(self):
        persist_hits["n"] += 1
        if persist_hits["n"] == 1:
            # join 之后、真实写入之前：直接中止，不调用真实 persist。
            raise RuntimeError("persist 前可控中止（#642 R2）")
        return real_persist(self)

    monkeypatch.setattr(MonthEndRelationBrewLeg, "persist", boom_then_real)

    def runner(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        brew = _brew_fn_factory(calls)
        brew.outputs = [_script(recent="洪承畴请饷被驳，心怨。")]
        return MonthEndRelationBrewLeg(
            settle_db, settle_state, brew,
            settled_turn=settled_turn,
            settled_year=settled_year,
            settled_period=settled_period,
        )

    before_turn = state.turn
    with pytest.raises(RuntimeError, match="persist 前可控中止"):
        settle_with_delta(
            state, db, {}, before_turn=before_turn, content=content,
            relation_brew_runner=runner,
        )

    # settle atomic 已提交（turn 推进）；摘要未半写；认领先行 pending 在册。
    assert state.turn == before_turn + 1
    assert persist_hits["n"] == 1
    path = db.path
    db.close()
    db = GameDB(path)
    pending_pairs = [(row["source"], row["target"]) for row in db.get_relation_brew_pending()]
    assert (source, target) in pending_pairs
    assert db.get_relation_summary(source, target)["recent_segment"] == old_recent
    edge_ids_mid = {
        int(row["id"])
        for row in db.get_relation_edge_events(source=source, target=target)
    }
    assert edge_ids_mid == edge_ids_before

    # 再次结算：补酿恰一次、pending 清除、摘要落定；边 id 不双增。
    calls.clear()

    def runner2(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        brew = _brew_fn_factory(calls)
        brew.outputs = [_script(recent="洪承畴请饷被驳，心怨。")]
        return MonthEndRelationBrewLeg(
            settle_db, settle_state, brew,
            settled_turn=settled_turn,
            settled_year=settled_year,
            settled_period=settled_period,
        )

    # 重载 state 与打开的 db 对齐（真实恢复路径）。
    row = db.conn.execute(
        "SELECT turn, year, period FROM game_state WHERE id = 1"
    ).fetchone()
    state.turn = int(row["turn"])
    state.year = int(row["year"])
    state.period = int(row["period"])
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content,
        relation_brew_runner=runner2,
    )
    relation_calls = [c for c in calls if "view" not in c]
    assert len(relation_calls) == 1
    assert (source, target) not in [
        (row["source"], row["target"]) for row in db.get_relation_brew_pending()
    ]
    assert db.get_relation_summary(source, target)["recent_segment"] == (
        "洪承畴请饷被驳，心怨。"
    )
    edge_ids_after = {
        int(row["id"])
        for row in db.get_relation_edge_events(source=source, target=target)
    }
    assert edge_ids_after == edge_ids_before


# ---------------- #642 锚④：build_brew_input 只投影 prior 字段（全序/筛选归 read 缝）

def test_build_brew_input_projects_prior_event_fields():
    """brew 侧只锁 prior_events 字段投影与空列表；全量有序/和解归 read 缝主干。"""
    prior = [{
        "id": 9, "event_kind": "知遇", "context": "越次一召原句。",
        "origin": "seed:founding", "year": 1628, "period": 11,
    }]
    payload = build_brew_input(
        source=EMPEROR_NODE, target="杨嗣昌", dimension="君臣",
        year=1635, period=6, summary=None, new_events=[],
        has_pending=False, prior_events=prior,
    )
    assert payload["prior_events"] == [{
        "event_kind": "知遇", "context": "越次一召原句。",
        "origin": "seed:founding", "year": 1628, "period": 11,
    }]
    assert "id" not in payload["prior_events"][0]
    assert build_brew_input(
        source="甲", target="乙", dimension="大臣",
        year=1635, period=6, summary=None, new_events=[],
        has_pending=True, prior_events=[],
    )["prior_events"] == []


def test_prepare_attaches_prior_events_only_via_history_seam(game, monkeypatch):
    """生产装配：prepare→build_brew_input 经历史读缝取 prior；与 new 互斥。

    先成功酿出水位，再加次月新事件——已消化旧事只在 prior，本批新事只在 new。
    """
    db, state, _ = game
    source, target = EMPEROR_NODE, "杨嗣昌"
    prior_context = "越次一召原句。"
    # 严格早于开局年月（1627/10）的奠基原句，水位推进后才能进 prior_events。
    db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context=prior_context, origin="seed:founding:yueci",
        turn=0, year=1626, period=6,
    )
    _add_edge(db, state, source=source, target=target, kind="知遇",
              context="首月知遇。", origin="audience:month-1")
    brew_fn = _brew_fn_factory([])
    brew_fn.outputs = [_script(recent="首月近况。")]
    run_month_end_relation_brew(db, state, brew_fn)
    assert db.get_relation_summary(source, target) is not None

    # 次月新事件：prior 经历史读缝、与 new 互斥、已消化旧事只在 prior。
    state.turn += 1
    state.period += 1
    new_context = "次月新知遇。"
    _add_edge(db, state, source=source, target=target, kind="知遇",
              context=new_context, origin="audience:month-2")

    import ming_sim.relation_brew as brew_mod
    import ming_sim.relation_read as read_mod
    seen = []
    real = read_mod.load_relation_history_before

    def spy(db_, *, source, target, before_year, before_period):
        seen.append((source, target, before_year, before_period))
        return real(
            db_, source=source, target=target,
            before_year=before_year, before_period=before_period,
        )

    monkeypatch.setattr(brew_mod, "load_relation_history_before", spy)
    calls: list = []
    brew_fn = _brew_fn_factory(calls)
    brew_fn.outputs = [_script(recent="次月近况。")]
    run_month_end_relation_brew(db, state, brew_fn)
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls
    payload = relation_calls[0]
    new_contexts = [e["context"] for e in payload["new_events"]]
    prior_contexts = [e["context"] for e in payload["prior_events"]]
    assert new_context in new_contexts
    assert prior_context not in new_contexts
    assert prior_context in prior_contexts
    assert new_context not in prior_contexts
    assert set(new_contexts).isdisjoint(prior_contexts)
    assert (source, target, int(state.year), int(state.period)) in seen


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

    barrier = threading.Barrier(len(pairs))
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


# -------------------------------- 结算接缝：事务内定型即启酿、与 chapter/ending 重叠（判词类②）

def test_settle_brew_overlaps_chapter_and_joins_before_persist(game):
    """ID-10/P5：本月边事件集在结算事务内定型后即启酿——酿制 LLM 等待与无依赖的
    章节记忆重叠；摘要持久化前 join；串行实现（等整个 atomic 完成才同步调）在此破裂。"""
    db, state, content = game
    _add_edge(db, state, source="徐光启", target=EMPEROR_NODE, kind="协作",
              context="徐光启与皇上当场协作。", origin="audience:turn-1")

    started = threading.Barrier(3)  # 两个酿制 worker ＋ chapter
    release = threading.Event()
    brew_turns: list = []

    def brew_fn(payload_json: str) -> str:
        payload = json.loads(payload_json)
        brew_turns.append(int(state.turn))  # 事务内启酿：state 尚未被 next_period 推进
        started.wait()
        release.wait()  # 串行实现则永久等；CI job 终线承接
        if payload.get("view") == VIEW_FACTION_STANCE:
            return json.dumps({STANCE_KEY: "西学态势在案。"}, ensure_ascii=False)
        return json.dumps(_script(recent="协作在案。"), ensure_ascii=False)

    def runner(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        return MonthEndRelationBrewLeg(
            settle_db, settle_state, brew_fn,
            settled_turn=settled_turn,
            settled_year=settled_year,
            settled_period=settled_period,
        )

    def chapter(db_, s, decree_text, narrative, applied):
        started.wait()  # 两个工作项均已在 next_period 前读取 state.turn
        release.set()

    before_turn = state.turn
    settled_year, settled_period = int(state.year), int(state.period)
    settle_with_delta(
        state, db, {}, before_turn=before_turn, content=content,
        chapter_recorder=chapter, relation_brew_runner=runner,
    )

    assert state.turn == before_turn + 1
    # 重叠证明：brew 在事务内（next_period 前）启酿、且与 chapter 互等通过。
    # 同批新事实：徐光启党籍投影西学 → 关系对＋西学两条工作项同批同缝启酿。
    assert set(brew_turns) == {before_turn}
    summary = db.get_relation_summary("徐光启", EMPEROR_NODE)
    assert summary["recent_segment"] == "协作在案。"
    assert (summary["last_brewed_year"], summary["last_brewed_period"]) == (
        settled_year, settled_period,
    )


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
        return MonthEndRelationBrewLeg(
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
    # 同批新事实：徐光启投影西学 → 关系对＋西学；两腿落款都须是结算月快照。
    assert len(calls) == 2
    for payload in calls:
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
    # 补酿不重复记账只在严格字节全等时成立：整段原样重报（含多行句）逐字全等→跳过。
    merged = merge_founding_segment("", ["甲句。", "乙句。\n乙二句。"])
    assert merged == "甲句。\n乙句。\n乙二句。"
    assert merge_founding_segment(merged, [merged]) == merged


def test_merge_founding_segment_exact_old_entry_re_report_appended_verbatim():
    """r5：跨轮去重收窄——只有「候选与整个旧段全等」与「同批候选间全等」跳过；
    旧段内某个精确历史条目被再次报出→如实逐字追加（有界重复噪声，酿制读面
    自行消化）；禁止恢复任何条目级拆解去重。"""
    merged = merge_founding_segment("", ["甲句。", "乙句。\n乙二句。"])
    assert merge_founding_segment(merged, ["甲句。", "乙句。\n乙二句。"]) == (
        merged + "\n甲句。\n乙句。\n乙二句。"
    )
    # 同批候选间全等仍去重；候选与整个旧段全等仍跳过（补酿整段重报不重复记账）。
    assert merge_founding_segment(merged, [merged]) == merged


def test_merge_founding_segment_never_infers_by_lines():
    """判词类①机械反例（冻结）：按行拆分＋集合推断会把整段候选误删。

    旧段 '甲\\n中\\n乙' 配候选 '甲\\n乙'：候选的每一行各自都在旧段内，旧的行集合
    推断据此把整条候选吞掉——零删改宪法下候选必须完整逐字追加。"""
    assert merge_founding_segment("甲\n中\n乙", ["甲\n乙"]) == "甲\n中\n乙\n甲\n乙"
    # 多行候选即使每一行都已在段内，也整条逐字追加（不拆行不推断）。
    assert merge_founding_segment("甲句。", ["甲句。\n甲句二。"]) == "甲句。\n甲句。\n甲句二。"


# ------- 判词类③ fail-loud 异常边界：DB/schema/程序错误响亮，仅 LLM 单条降级

def test_prepare_claim_db_error_propagates_loudly(game):
    """认领 DB 失败不得伪装成 LLM 降级：无 durable claim 就开酿会让失败月失去恢复
    凭据（庭裁 r3 F1②缝），必须响亮上抛（ADR 0005/0008）。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("认领库不可写")

    db.claim_relation_brew_targets = boom
    with pytest.raises(sqlite3.OperationalError, match="认领库不可写"):
        run_month_end_relation_brew(db, state, _brew_fn_factory([]))


def test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure(game):
    """apply 落定的 DB/schema 错误是落库侧错（ADR 0005）：响亮上抛，不走单条降级、
    不再重复 mark 补降级。"""
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("落定库不可写")

    db.apply_relation_brew_result = boom
    marked: list = []
    original_mark = db.mark_relation_brew_pending

    def spy_mark(**kwargs):
        marked.append(kwargs)
        return original_mark(**kwargs)

    db.mark_relation_brew_pending = spy_mark
    with pytest.raises(sqlite3.OperationalError, match="落定库不可写"):
        run_month_end_relation_brew(db, state, _brew_fn_factory([]))
    assert marked == []  # 宽吞与重复补降级已删


def test_mark_failure_after_llm_failure_propagates_loudly(game):
    """LLM 单条失败（声明类型 LLMUnavailable）本身合法降级，但降级留痕的 pending
    写若遇 DB 错误同样响亮上抛。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("pending 库不可写")

    db.mark_relation_brew_pending = boom
    with pytest.raises(sqlite3.OperationalError, match="pending 库不可写"):
        run_month_end_relation_brew(db, state, failing_brew)


def test_brew_program_error_propagates_loudly_not_degraded(game):
    """判词残留项②：_brew_one 宽吞拆类——brew_fn 内的程序错（KeyError 等非 LLM
    失败声明类型）不得被吞成单条降级留痕，必须响亮上抛（ADR 0005）；durable
    claim 已在册，恢复凭据不丢。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def buggy_brew(payload_json: str) -> str:
        raise KeyError("酿制手程序错误")

    with pytest.raises(KeyError, match="酿制手程序错误"):
        run_month_end_relation_brew(db, state, buggy_brew)
    # 响亮上扑而非降级：无 degraded 留痕；认领先行的 pending 凭据已持久在册。
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        ("温体仁", "周延儒")
    ]


def test_brew_fn_value_error_is_program_error_propagates_loudly(game):
    """判词机械反例（确认庭 r5 残余）：_brew_fn 自身抛出的裸 ValueError 是程序错
    ——降级面按结构位置分界而非异常类型，LLM 调用缝只收声明类型 LLMUnavailable，
    调用段的 ValueError/KeyError 等一律响亮上抛（ADR 0005），不得吞成单条降级；
    durable claim 已在册，恢复凭据不丢。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def buggy_brew(payload_json: str) -> str:
        raise ValueError("酿制手程序错误")

    with pytest.raises(ValueError, match="酿制手程序错误"):
        run_month_end_relation_brew(db, state, buggy_brew)
    # 响亮上抛而非降级：无 degraded 留痕；认领先行的 pending 凭据已持久在册。
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        ("温体仁", "周延儒")
    ]


def test_parse_seam_value_error_degrades_single_item(game):
    """解析/shape 校验缝的 ValueError（输出结构化契约违约，parse_brew_output 声明
    类型）属真 LLM 单条失败：单条降级留痕（保旧摘要＋pending 在册），不响亮上抛。
    与上一测试合起来钉死分界：同是 ValueError，缝内降级、缝外上抛。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def malformed_brew(payload_json: str) -> str:
        # 合法 JSON 但 shape 违约：recent_segment 缺失 → parse_brew_output 抛 ValueError。
        return json.dumps({FOUNDINGS_KEY: []}, ensure_ascii=False)

    report = run_month_end_relation_brew(db, state, malformed_brew)
    # 同批新事实：温/周均皇党 → 关系对＋皇党，双双单条降级。
    assert report["selected"] == 2 and report["degraded"]
    assert report["brewed"] == []
    # 保旧摘要（本就无摘要）、事件不丢、pending 持久在册。
    assert db.get_relation_summary("温体仁", "周延儒") is None
    assert db.get_relation_edge_events(source="温体仁", target="周延儒")
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        ("温体仁", "周延儒")
    ]


def test_settle_aborts_loudly_when_brew_prepare_db_fails(game):
    """生产路径：prepare 的 claim DB 错误发生在结算 atomic 内→随整体回滚走错误包
    SettlementAbort，绝不静默继续（ADR 0008 决定 6）。"""
    db, state, content = game
    _add_edge(db, state, source="徐光启", target=EMPEROR_NODE, kind="协作",
              context="徐光启与皇上当场协作。", origin="audience:turn-1")

    class _BoomLeg:
        def prepare(self):
            raise sqlite3.OperationalError("认领库不可写")

        def brew(self):
            raise AssertionError("prepare 已响，不可达")

        def persist(self):
            raise AssertionError("prepare 已响，不可达")

    def runner(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        return _BoomLeg()

    before_turn = state.turn
    with pytest.raises(SettlementAbort):
        settle_with_delta(
            state, db, {}, before_turn=before_turn, content=content,
            relation_brew_runner=runner,
        )
    # 结算整体回滚：turn 不推进、无摘要落定。
    assert state.turn == before_turn
    assert db.get_relation_summary("徐光启", EMPEROR_NODE) is None


def test_settle_brew_program_error_propagates_loudly_after_commit(game):
    """brew 相的程序错误不是 LLM 单条失败：join 时响亮上抛（ADR 0005）；结算本体
    已提交不受影响；join/shutdown 保证不悬空 worker。"""
    db, state, content = game

    class _BoomLeg:
        def prepare(self):
            return True

        def brew(self):
            raise RuntimeError("酿制编排程序错误必须响亮")

        def persist(self):
            raise AssertionError("join 已响，不可达")

    def runner(settle_state, settle_db, *, settled_turn, settled_year, settled_period):
        return _BoomLeg()

    before_turn = state.turn
    with pytest.raises(RuntimeError, match="酿制编排程序错误必须响亮"):
        settle_with_delta(
            state, db, {}, before_turn=before_turn, content=content,
            relation_brew_runner=runner,
        )
    assert state.turn == before_turn + 1  # 结算本体已提交


def test_relation_dimension_marks_emperor_edges():
    assert relation_dimension(EMPEROR_NODE, "杨嗣昌") == "君臣"
    assert relation_dimension("杨嗣昌", EMPEROR_NODE) == "君臣"
    assert relation_dimension("毕自严", "王绍徽") == "大臣"


# -------------------------------- 庭裁 Z1：畸形酿制产出严格拒收（不修补不改写）


def test_duplicate_json_objects_rejected_not_first_object_picked(game):
    """庭裁 Z1 机械反例①：模型重复拼接两个完整 JSON object 时，共享解析器
    parse_agent_json 的「截首个平衡对象」修补会把改写后的首对象当模型产出落库。
    酿制专用边界必须整包契约错拒收：单条降级、旧摘要字节不变、pending 在册。"""
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召，擢杨嗣昌于五品郎中。", origin="audience:turn-1")
    brew_fn = _brew_fn_factory([])
    brew_fn.outputs = [_script(foundings=["越次一召，擢杨嗣昌于五品郎中。"], recent="原文一")]
    run_month_end_relation_brew(db, state, brew_fn)
    first = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    assert first["recent_segment"] == "原文一"

    state.turn += 1
    state.period += 1
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="辜负",
              context="所请被驳。", origin="audience:turn-2")

    def duplicated_brew(payload_json: str) -> str:
        return (
            json.dumps(_script(recent="原文一"), ensure_ascii=False)
            + json.dumps(_script(recent="原文二"), ensure_ascii=False)
        )

    report = run_month_end_relation_brew(db, state, duplicated_brew)
    assert report["selected"] == 2 and report["degraded"] and report["brewed"] == []
    second = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")
    # 拒收而非择取：旧摘要（含奠基段与近况段）字节不变。
    assert second["founding_segment"] == first["founding_segment"]
    assert second["recent_segment"] == first["recent_segment"]
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        (EMPEROR_NODE, "杨嗣昌")
    ]


def test_unescaped_control_byte_rejected_not_stripped(game):
    """庭裁 Z1 机械反例②：recent_segment 内含未转义 U+0001 控制字节的输出，
    共享解析器的 control-char 正则清洗会静默删字节后接受为「甲乙」——必须契约
    错拒收（零删改），单条降级留痕。"""
    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召，擢杨嗣昌于五品郎中。", origin="audience:turn-1")

    def control_byte_brew(payload_json: str) -> str:
        # 手拼 raw：内嵌未转义控制字节（json.dumps 会转义成 \u0001，不能用它）。
        return '{"' + FOUNDINGS_KEY + '": [], "' + RECENT_KEY + '": "甲\x01乙"}'

    report = run_month_end_relation_brew(db, state, control_byte_brew)
    assert report["selected"] == 2 and report["degraded"] and report["brewed"] == []
    assert db.get_relation_summary(EMPEROR_NODE, "杨嗣昌") is None
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        (EMPEROR_NODE, "杨嗣昌")
    ]


# -------------------------------- 庭裁 Z2：删固定 max_workers=4，按批定容


def test_batch_of_five_relations_all_enter_call_seam_concurrently(game):
    """庭裁 Z2：worker 数按本批实际 jobs 数定容，不设固定 4 上限——5 条独立
    关系同批时第 5 条必须能与前四条同时进入调用缝（串行或固定上限实现会在
    Barrier 处超时破裂）。不新增速率限制/信号量/配额等任何护栏。"""
    db, state, _ = game
    pairs = [("甲", "乙"), ("丙", "丁"), ("戊", "己"), ("庚", "辛"), ("壬", "癸")]
    for source, target in pairs:
        _add_edge(db, state, source=source, target=target, kind="协作",
                  context=f"{source}与{target}当场协作。", origin=f"audience:{source}{target}")

    barrier = threading.Barrier(len(pairs))
    threads: list = []

    def parallel_brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        threads.append(threading.current_thread().name)
        barrier.wait()  # 第 5 条排不到缝即在此超时破裂
        return json.dumps(
            _script(recent=f"{payload['source']}与{payload['target']}协作在案。"),
            ensure_ascii=False,
        )

    report = run_month_end_relation_brew(db, state, parallel_brew, parallel=True)
    assert len(report["brewed"]) == 5
    assert len(set(threads)) == 5
    for source, target in pairs:
        assert db.get_relation_summary(source, target)["recent_segment"] == (
            f"{source}与{target}协作在案。"
        )


# ------------------- 庭裁 Z3：生产 provider 已知故障译 typed 单条降级


def _brew_runner_leg(game, monkeypatch, provider_error):
    """经生产注入工厂 _make_relation_brew_runner 构造真实闭包，把 provider 调用
    替换为抛指定已知异常；返回已 prepare 的 Leg。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    monkeypatch.setattr(decree_module, "create_relation_brew_agent", lambda cfg, adb: object())
    monkeypatch.setattr(decree_module, "create_faction_brew_agent", lambda cfg, adb: object())

    def failing_run(agent, prompt, tag):
        raise provider_error

    monkeypatch.setattr(decree_module, "run_agent_text", failing_run)
    runner = decree_module._make_relation_brew_runner(None, None)
    leg = runner(
        state, db,
        settled_turn=int(state.turn),
        settled_year=int(state.year),
        settled_period=int(state.period),
    )
    assert leg.prepare()
    return db, leg


@pytest.mark.parametrize("error_factory", [
    lambda: APITimeoutError(request=httpx.Request("POST", "https://llm.invalid/v1")),
    lambda: APIConnectionError(request=httpx.Request("POST", "https://llm.invalid/v1")),
], ids=["timeout", "connection"])
def test_provider_known_fault_translates_to_typed_single_degradation(game, monkeypatch, error_factory):
    """庭裁 Z3：生产 provider 直抛的超时/连接异常在调用适配缝译成声明类型
    LLMUnavailable（保留 cause），_brew_one 依法单条降级：旧摘要不变、pending
    保留、结算不因该条报程序错。KeyError/ValueError 程序错不在捕获列，照旧
    响亮（既有测试钉死）。"""
    provider_error = error_factory()
    db, leg = _brew_runner_leg(game, monkeypatch, provider_error)
    leg.brew()
    # 译型保留 cause：outcomes 里是 LLMUnavailable，原异常挂在 __cause__。
    job, parsed, exc = leg.outcomes[0]
    assert exc is not None and parsed is None
    assert isinstance(exc, LLMUnavailable)
    assert isinstance(exc.__cause__, type(provider_error))

    report = leg.persist()
    source, target = job["source"], job["target"]
    # 同批新事实：关系条目在前、派系条目（温/周均皇党）在后，双双 typed 单条降级。
    assert report["degraded"][0] == {"source": source, "target": target, "reason": str(exc)}
    assert report["degraded"][1]["faction"] == "皇党"
    assert report["brewed"] == []
    assert db.get_relation_summary(source, target) is None
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        (source, target)
    ]
