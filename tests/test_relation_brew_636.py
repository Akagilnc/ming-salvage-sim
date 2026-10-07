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

import json
import threading

import pytest

from ming_sim.faction_brew import STANCE_KEY, VIEW_FACTION_STANCE
from ming_sim.exceptions import LLMUnavailable
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    MonthEndRelationBrewLeg,
    RECENT_KEY,
    build_brew_input,
    merge_founding_segment,
    relation_dimension,
    MonthEndRelationBrewLeg,
)
from ming_sim.relations import EMPEROR_NODE


def run_month_end_relation_brew(db, state, brew_fn, *, parallel=True, settled_turn=None, settled_year=None, settled_period=None):
    """Test helper: drive the live Leg three-phase entry (no retired convenience wrapper)."""
    leg = MonthEndRelationBrewLeg(
        db, state, brew_fn,
        settled_turn=settled_turn,
        settled_year=settled_year,
        settled_period=settled_period,
        parallel=parallel,
    )
    if not leg.prepare():
        return leg.report
    leg.brew()
    return leg.persist()


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


# ------------------------------------------------- TD-3／庭裁 r3③ 无事不变


# ------------------------------------------------------- TD-4 翻转可回溯


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

    leg = MonthEndRelationBrewLeg(db, state, failing_brew, parallel=False)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()
    assert all(isinstance(error, LLMUnavailable) for _, _, error in leg.outcomes)
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
    leg = MonthEndRelationBrewLeg(db, state, brew_fn, parallel=False)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()

    assert report["selected"] == 2 and len(report["brewed"]) == 2
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls and relation_calls[0]["has_pending_failure"] is True
    payload = relation_calls[0]
    new_hits = [e for e in payload["new_events"] if e["origin"] == "audience:turn-1"]
    prior_hits = [e for e in payload["prior_events"] if e["origin"] == "audience:turn-1"]
    assert len(new_hits) + len(prior_hits) == 1
    assert len(new_hits) == 1 and prior_hits == []
    assert db.get_relation_brew_pending() == []
    summary = db.get_relation_summary("温体仁", "周延儒")
    assert summary["recent_segment"] == "温周结怨，朝堂侧目。"
    assert summary["dimension"] == "大臣"
    assert int(summary["last_event_id"]) >= int(failed_id)


def test_prepare_attaches_prior_events_only_via_history_seam(game, monkeypatch):
    """生产装配：prepare→build_brew_input 经历史读缝取 prior；与 new 互斥。

    先成功酿出水位，再加次月新事件——已消化旧事只在 prior，本批新事只在 new。
    """
    db, state, _ = game
    source, target = EMPEROR_NODE, "杨嗣昌"
    prior_context = "越次一召原句。"
    # 严格早于开局年月（1627/10）的奠基原句，水位推进后才能进 prior_events。
    prior_id = db.record_relation_edge_event(
        source=source, target=target, event_kind="知遇",
        context=prior_context, origin="seed:founding:yueci",
        turn=0, year=1626, period=6,
    )
    prior_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (prior_id,),
    ).fetchone()["origin"]
    _add_edge(db, state, source=source, target=target, kind="知遇",
              context="首月知遇。", origin="audience:month-1")
    brew_fn = _brew_fn_factory([])
    brew_fn.outputs = [_script(recent="首月近况。")]
    leg = MonthEndRelationBrewLeg(db, state, brew_fn, parallel=False)
    assert leg.prepare()
    leg.brew()
    leg.persist()
    assert db.get_relation_summary(source, target) is not None

    # 次月新事件：prior 经历史读缝、与 new 互斥、已消化旧事只在 prior。
    state.turn += 1
    state.period += 1
    new_context = "次月新知遇。"
    new_id = _add_edge(db, state, source=source, target=target, kind="知遇",
                       context=new_context, origin="audience:month-2")
    new_origin = db.conn.execute(
        "SELECT origin FROM relation_edge_events WHERE id=?", (new_id,),
    ).fetchone()["origin"]

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
    leg = MonthEndRelationBrewLeg(db, state, brew_fn, parallel=False)
    assert leg.prepare()
    leg.brew()
    leg.persist()
    relation_calls = [c for c in calls if "view" not in c]
    assert relation_calls
    payload = relation_calls[0]
    new_origins = {e["origin"] for e in payload["new_events"]}
    prior_origins = {e["origin"] for e in payload["prior_events"]}
    assert new_origin in new_origins
    assert prior_origin not in new_origins
    assert prior_origin in prior_origins
    assert new_origin not in prior_origins
    assert new_origins.isdisjoint(prior_origins)
    assert (source, target, int(state.year), int(state.period)) in seen


# --------------------------- 庭裁 r3/r4 F2 超长 fixture：32,700 字节零删改

def test_brew_persistence_chain_preserves_32700_byte_fixture_byte_identical(game):
    # Keep the long injected input; compare its before-image directly, not a
    # parallel checksum/length oracle for the same preservation contract.
    block = "崇祯边事关系账超长验收样文-Chongzhen-relation-brew-0123456789-".encode("utf-8")
    fixture = block * 436
    fixture_text = fixture.decode("utf-8")

    db, state, _ = game
    _add_edge(db, state, source=EMPEROR_NODE, target="杨嗣昌", kind="知遇",
              context="越次一召。", origin="audience:turn-1")

    def fixture_brew(payload_json: str) -> str:
        return json.dumps(
            {FOUNDINGS_KEY: [], RECENT_KEY: fixture_text}, ensure_ascii=False
        )

    # 经真实酿制持久化链路（MonthEndRelationBrewLeg.prepare/brew/persist
    # → apply_relation_brew_result）写入→读回：字节原样，全链无截断无删改。
    # 已删 run_month_end_relation_brew 不恢复；确定性 parallel=False。
    leg = MonthEndRelationBrewLeg(db, state, fixture_brew, parallel=False)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()
    assert len(report["brewed"]) == 1

    stored = db.get_relation_summary(EMPEROR_NODE, "杨嗣昌")["recent_segment"]
    assert stored.encode("utf-8") == fixture


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
        # 标准库 Barrier 超时：串行故障秒级 BrokenBarrierError，不无限挂起。
        barrier.wait(timeout=2.0)
        return json.dumps(
            _script(recent=f"{payload['source']}与{payload['target']}协作在案。"),
            ensure_ascii=False,
        )

    # 现役 prepare／brew／persist 接缝；默认 parallel=True，不复活退休包装。
    leg = MonthEndRelationBrewLeg(db, state, parallel_brew)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()
    assert len(report["brewed"]) == 2
    assert len(set(threads)) == 2
    for source, target in pairs:
        assert db.get_relation_summary(source, target)["recent_segment"] == (
            f"{source}与{target}协作在案。"
        )


# ------------------------------------------------- 「本月新增」总判据（历史水位不选旧事）


# ------- 判词类③ fail-loud 异常边界：DB/schema/程序错误响亮，仅 LLM 单条降级

def test_prepare_claim_db_error_propagates_loudly(game):
    """认领 DB 失败不得伪装成 LLM 降级：无 durable claim 就开酿会让失败月失去恢复
    凭据（庭裁 r3 F1②缝），必须响亮上抛（ADR 0005/0008）。
    来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    fault = sqlite3.OperationalError("认领库不可写")

    def boom(*args, **kwargs):
        raise fault

    db.claim_relation_brew_targets = boom
    with pytest.raises(sqlite3.OperationalError) as ei:
        run_month_end_relation_brew(db, state, _brew_fn_factory([]))
    assert ei.value is fault


def test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure(game):
    """apply 落定的 DB/schema 错误是落库侧错（ADR 0005）：响亮上抛，不走单条降级、
    不再重复 mark 补降级。来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="毕自严", target="王绍徽", kind="站台",
              context="毕自严当面替王绍徽担名。", origin="audience:turn-1")

    fault = sqlite3.OperationalError("落定库不可写")

    def boom(*args, **kwargs):
        raise fault

    db.apply_relation_brew_result = boom
    marked: list = []
    original_mark = db.mark_relation_brew_pending

    def spy_mark(**kwargs):
        marked.append(kwargs)
        return original_mark(**kwargs)

    db.mark_relation_brew_pending = spy_mark
    with pytest.raises(sqlite3.OperationalError) as ei:
        run_month_end_relation_brew(db, state, _brew_fn_factory([]))
    assert ei.value is fault
    assert marked == []  # 宽吞与重复补降级已删


def test_mark_failure_after_llm_failure_propagates_loudly(game):
    """LLM 单条失败（声明类型 LLMUnavailable）本身合法降级，但降级留痕的 pending
    写若遇 DB 错误同样响亮上抛。来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    def failing_brew(payload_json: str) -> str:
        raise LLMUnavailable("酿制裁判接口不可用")

    fault = sqlite3.OperationalError("pending 库不可写")

    def boom(*args, **kwargs):
        raise fault

    db.mark_relation_brew_pending = boom
    with pytest.raises(sqlite3.OperationalError) as ei:
        run_month_end_relation_brew(db, state, failing_brew)
    assert ei.value is fault


def test_brew_program_error_propagates_loudly_not_degraded(game):
    """判词残留项②：_brew_one 宽吞拆类——brew_fn 内的程序错（KeyError 等非 LLM
    失败声明类型）不得被吞成单条降级留痕，必须响亮上抛（ADR 0005）；durable
    claim 已在册，恢复凭据不丢。来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    fault = KeyError("酿制手程序错误")

    def buggy_brew(payload_json: str) -> str:
        raise fault

    with pytest.raises(KeyError) as ei:
        run_month_end_relation_brew(db, state, buggy_brew)
    assert ei.value is fault
    # 响亮上扑而非降级：无 degraded 留痕；认领先行的 pending 凭据已持久在册。
    assert [(row["source"], row["target"]) for row in db.get_relation_brew_pending()] == [
        ("温体仁", "周延儒")
    ]


def test_brew_fn_value_error_is_program_error_propagates_loudly(game):
    """判词机械反例（确认庭 r5 残余）：_brew_fn 自身抛出的裸 ValueError 是程序错
    ——降级面按结构位置分界而非异常类型，LLM 调用缝只收声明类型 LLMUnavailable，
    调用段的 ValueError/KeyError 等一律响亮上抛（ADR 0005），不得吞成单条降级；
    durable claim 已在册，恢复凭据不丢。来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, _ = game
    _add_edge(db, state, source="温体仁", target="周延儒", kind="结怨",
              context="温体仁当殿讦周延儒。", origin="audience:turn-1")

    fault = ValueError("酿制手程序错误")

    def buggy_brew(payload_json: str) -> str:
        raise fault

    with pytest.raises(ValueError) as ei:
        run_month_end_relation_brew(db, state, buggy_brew)
    assert ei.value is fault
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


# -------------------------------- 庭裁 Z1：畸形酿制产出严格拒收（不修补不改写）


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
        # 固定四工人时第 5 条进不了缝 → wait 超时 BrokenBarrierError，秒级报红。
        barrier.wait(timeout=2.0)
        return json.dumps(
            _script(recent=f"{payload['source']}与{payload['target']}协作在案。"),
            ensure_ascii=False,
        )

    leg = MonthEndRelationBrewLeg(db, state, parallel_brew)
    assert leg.prepare()
    leg.brew()
    report = leg.persist()
    assert len(report["brewed"]) == 5
    assert len(set(threads)) == 5
    for source, target in pairs:
        assert db.get_relation_summary(source, target)["recent_segment"] == (
            f"{source}与{target}协作在案。"
        )
