"""#636 关系摘要层 S5：两段式存储＋月末增量重酿腿。

验收锚（结构面）：
- 无新事件又无 pending 的月份零重酿调用、水位不变。
- 翻转可回溯：重酿输入必含新边事件 origin。
- 失败月进持久 pending-backlog，下月补酿。
- 故障注入响亮／畸形产出拒收降级（不锁段正文）。
- 批内并行不串行（线程数结构）＋摘要行结构化字段写入。
"""

from __future__ import annotations

from types import SimpleNamespace
import httpx
import json
import sqlite3
import threading

import pytest
from openai import APIConnectionError, APITimeoutError

from ming_sim.faction_brew import STANCE_KEY, VIEW_FACTION_STANCE
from ming_sim.exceptions import LLMUnavailable
from ming_sim.relation_brew import (
    FOUNDINGS_KEY,
    RECENT_KEY,
    build_brew_input,
    relation_dimension,
    run_month_end_relation_brew,
)
from ming_sim.relations import EMPEROR_NODE


@pytest.mark.parametrize("error_type", [APITimeoutError, APIConnectionError])
def test_provider_fault_becomes_typed_brew_failure(monkeypatch, error_type):
    """生产调用缝仅把已知 provider 故障译成声明类型，保留原始 cause。"""
    from ming_sim.mechanical_tail import _brew_fn_for_session

    fault = error_type(request=httpx.Request("POST", "https://llm.invalid/v1"))
    monkeypatch.setattr("ming_sim.agents.create_relation_brew_agent", lambda *_a: object())
    def fail(*_a, **_kw):
        raise fault
    monkeypatch.setattr("ming_sim.agents.run_agent_text", fail)
    brew = _brew_fn_for_session(SimpleNamespace(llm_config=object(), agno_db=None))
    with pytest.raises(LLMUnavailable) as caught:
        brew(json.dumps({"source": "甲", "target": "乙"}))
    assert caught.value.__cause__ is fault


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

    # 成功月重跑结算（跨月推进、无新事件、无 pending）：零重酿调用、水位不变。
    calls.clear()
    state.turn += 1
    state.period += 1
    report = run_month_end_relation_brew(db, state, brew_fn)

    assert report["selected"] == 0
    assert calls == []
    after = db.get_relation_summary("毕自严", "王绍徽")
    # 无事月：水位／dimension 不变；不跨月等值自由正文段。
    assert int(after["last_event_id"]) == int(before["last_event_id"])
    assert after["dimension"] == before["dimension"]


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
    assert payload["new_events"]
    assert payload["new_events"][0]["origin"] == "audience:turn-2"
    assert payload["new_events"][0]["event_kind"] == "辜负"
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
    new_hits = [e for e in payload["new_events"] if e["origin"] == "audience:turn-1"]
    prior_hits = [e for e in payload["prior_events"] if e["origin"] == "audience:turn-1"]
    assert len(new_hits) + len(prior_hits) == 1
    assert len(new_hits) == 1 and prior_hits == []
    assert db.get_relation_brew_pending() == []
    summary = db.get_relation_summary("温体仁", "周延儒")
    assert summary["dimension"] == "大臣"
    assert int(summary["last_event_id"]) >= int(failed_id)


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
    row = payload["prior_events"][0]
    assert set(row) == {"event_kind", "context", "origin", "year", "period"}
    assert row["event_kind"] == "知遇"
    assert row["origin"] == "seed:founding"
    assert (row["year"], row["period"]) == (1628, 11)
    assert "id" not in row
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
    run_month_end_relation_brew(db, state, brew_fn)
    seeded = db.get_relation_summary(source, target)
    assert seeded["dimension"] == "君臣"
    assert int(seeded["last_event_id"]) > 0

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
    run_month_end_relation_brew(db, state, brew_fn)
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
    first_event_id = int(first["last_event_id"])

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
    # 拒收而非择取：水位不因畸形产出推进；pending 在册。不锁段正文。
    assert int(second["last_event_id"]) == first_event_id
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

    # 标准库 Barrier 默认 timeout：串行／容量不足时 wait 超时 → BrokenBarrierError 报红退出。
    barrier = threading.Barrier(len(pairs), timeout=5)
    threads: list = []

    def parallel_brew(payload_json: str) -> str:
        payload = json.loads(payload_json)
        threads.append(threading.current_thread().name)
        barrier.wait(timeout=5)  # 第 5 条排不到缝即在此超时破裂
        return json.dumps(
            _script(recent=f"{payload['source']}与{payload['target']}协作在案。"),
            ensure_ascii=False,
        )

    report = run_month_end_relation_brew(db, state, parallel_brew, parallel=True)
    assert len(report["brewed"]) == 5
    assert len(set(threads)) == 5
    for source, target in pairs:
        summary = db.get_relation_summary(source, target)
        assert summary["dimension"] == "大臣"
        assert int(summary["last_event_id"]) > 0
