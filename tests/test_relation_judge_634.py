"""#634 [479·S3] 召对口：召对判官当场记边事件（与回话并行）。

验收对表（冻结票面八项 + ID-12 修正案 + 庭裁 r1/r2）：
- 召对内当面站台/结怨发生的当回合，边事件行即可查（TD-1）。
- 判官腿与回话并行：判官拍不依赖本轮回话输出（TD-9/P5 的核心可测面）。
- 回话内新生事件由收夜扫尾在召对结束前补落（收夜扫尾覆盖）。
- 同一当面事件不因多拍/收夜扫尾重复落库（已判水位＋写口幂等，0082/r2 F2③）。
- 撤回联动（0038 白名单③）：撤回删该轮边事件＋水位回退；重发重判不重复不遗漏。
- 判官漏判不阻塞召对主链；无互动时零事件。
- ID-12：判官输入面经 project_relation_ledger(viewer=None) 单一接缝——全知机面，
  与角色裁切面不混用；上下文含账本读面、有账与无账行为可辨。
- r1 F1：判官 context 经 canonical 写口字节原样落库。
- r2 F2：方向三元组与单向基数——施动者→受动者恰一行、多方=牵头→各参与方。
"""

from __future__ import annotations

import inspect
import json
import threading
from types import SimpleNamespace

import ming_sim.agents as agents_mod
import ming_sim.audience_night as an
import ming_sim.relation_read as relation_read_mod
from ming_sim.relation_judge import (
    build_relation_judge_prompt,
    run_summon_relation_judge,
    summon_edge_origin,
)
import pytest


# ── 测试替身/工具 ────────────────────────────────────────────────────


class _CannedJudge:
    """按剧本返回 JSON 的判官替身；记录调用次数与收到的 prompt。"""

    def __init__(self, payload, *, db=None, retire_turn_id=0):
        self.payload = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        self.calls = 0
        self.prompts: list[str] = []
        self._db = db
        self._retire_turn_id = int(retire_turn_id)

    def run(self, prompt):
        self.calls += 1
        self.prompts.append(str(prompt))
        if self._db is not None and self._retire_turn_id:
            # 在飞判官拍中途轮被撤/失败（ADR 0038 终结异步残余的机械注入点）。
            self._db.fail_chat_turn(self._retire_turn_id)
        return SimpleNamespace(content=self.payload)


def _roster_names(db, state, n=2):
    names = sorted(row["name"] for row in db.current_court_roster_rows(state))
    assert len(names) >= n
    return names[:n]


def _make_turn(db, state, minister, question, answer, *, night_id=0):
    """生产同形地落一轮已完成对话（问话+回话入档，active）。"""
    ctid = db.create_chat_turn(state, minister, "t634:s", 0, night_id=int(night_id))
    umid = db.append_chat_message(minister, int(state.turn), "user", question)
    db.update_chat_turn_messages(ctid, user_message_id=umid)
    if answer is not None:
        mid = db.append_chat_message(minister, int(state.turn), "minister", answer)
        db.update_chat_turn_messages(ctid, minister_message_id=mid)
    return ctid


def _run(db, state, agent, *, llm_config=None):
    return run_summon_relation_judge(
        db, state, llm_config=llm_config if llm_config is not None else object(),
        write_gate=threading.Lock(), agent=agent,
    )


def _judge_status(db, ctid):
    row = db.conn.execute(
        "SELECT relation_judge_status FROM chat_turns WHERE id=?", (int(ctid),),
    ).fetchone()
    return str(row[0])


def _event_items(source, target, kind, context):
    return {"events": [
        {"施动者": source, "受动者": target, "类目": kind, "语境": context},
    ]}


# ── ID-12：判官输入面＝全知机面单一接缝 ──────────────────────────────


def test_factory_defers_output_contract_to_per_beat_prompt(game):
    """多轮字段契约只有逐拍 prompt 一份真源，factory 不再发布平行旧 shape。"""
    factory_source = inspect.getsource(agents_mod.create_relation_judge_agent)
    assert '"events"' not in factory_source
    assert "严格遵循本次调用给出的输出契约" in factory_source

    db, state, _content = game
    a, _b = _roster_names(db, state)
    first = _make_turn(db, state, a, "先问", "先答")
    second = _make_turn(db, state, a, "再问", "再答")
    prompt = build_relation_judge_prompt(db, db.list_unjudged_completed_chat_turns())
    assert '"源轮":12' in prompt
    assert f"轮 #{first}" in prompt and f"轮 #{second}" in prompt
    assert "每项的源轮必须是该事件实际发生的轮号" in prompt


def test_judge_prompt_contains_ledger_face_with_and_without_accounts(game):
    """ID-12①：判官上下文含账本读面；有账与无账行为可辨。"""
    db, state, content = game
    a, b = _roster_names(db, state)
    db.record_relation_edge_event(
        source=a, target=b, event_kind="使绊",
        context=f"{a}在户部用度上挡了{b}的路。", origin="盘面自发",
    )
    ctid = _make_turn(db, state, a, "卿以为如何？", "臣以为可。")
    rows = db.list_unjudged_completed_chat_turns()
    assert [int(r["id"]) for r in rows] == [int(ctid)]
    prompt = build_relation_judge_prompt(db, rows)
    # 有账：读面含 DTO 五字段的可见内容（summary 段/recent_context 原文）
    assert f"{a} → {b}" in prompt
    assert f"{a}在户部用度上挡了{b}的路。" in prompt
    # 无账：显式缺席标记，不静默空白（清空流水与摘要后重建读面）
    db.conn.execute("DELETE FROM relation_edge_events")
    db.conn.execute("DELETE FROM relation_summaries")
    db.conn.commit()
    prompt_empty = build_relation_judge_prompt(db, rows)
    assert "无关系账记录" in prompt_empty


def _make_turn_row_only(db):
    """构造一个不在库中的空窗行仅用于组 prompt 的最小桩。"""
    return {"id": 0, "minister_name": "", "turn": 0, "user_message_id": None,
            "minister_message_id": None}


def test_judge_machine_face_is_viewer_none_never_character_cut(game, monkeypatch):
    """ID-12②：判官机面为 viewer=None 全知面，与角色裁切面不混用。"""
    db, state, content = game
    seen_viewers = []
    real = relation_read_mod.project_relation_ledger

    def spy(d, *, viewer):
        seen_viewers.append(viewer)
        return real(d, viewer=viewer)

    monkeypatch.setattr(relation_read_mod, "project_relation_ledger", spy)
    a, _b = _roster_names(db, state)
    _make_turn(db, state, a, "问", "答")
    rows = db.list_unjudged_completed_chat_turns()
    build_relation_judge_prompt(db, rows)
    assert seen_viewers == [None]


# ── TD-1 当回合落库 ＋ r2 F2 方向三元组 ──────────────────────────────


def test_beat_judge_writes_directed_edge_same_round(game):
    db, state, content = game
    a, b = _roster_names(db, state)
    ctid = _make_turn(db, state, a, "卿等当面议一议。", "臣当面表态。")
    agent = _CannedJudge(_event_items(a, b, "站台", f"{a}当面替{b}站台。"))
    res = _run(db, state, agent)
    assert not res.get("degraded") and not res.get("skipped")
    rows = db.get_relation_edge_events(source=a, target=b)
    assert len(rows) == 1
    row = rows[0]
    # r2 F2①：断言 source/target/kind 三元组；负向=无反向行
    assert (row["source"], row["target"], row["event_kind"]) == (a, b, "站台")
    assert db.get_relation_edge_events(source=b, target=a) == []
    # TD-1：当回合落库，origin 回指本回合＋源轮绑定（chat_turn）
    assert int(row["turn"]) == int(state.turn)
    assert row["origin"] == summon_edge_origin(ctid) + f"|round:{state.turn}"
    # r1 F1：context 经 canonical 写口字节原样
    assert row["context"] == f"{a}当面替{b}站台。"
    assert _judge_status(db, ctid) == "done"


def test_bidirectional_grudge_keeps_two_explicit_directed_events(game):
    """双向结怨来自两项事实，各恰一行；单项有向边不会被写端自动镜像。"""
    db, state, _content = game
    a, b = _roster_names(db, state)
    ctid = _make_turn(db, state, a, "当面对质", "二人互相斥责")
    res = _run(db, state, _CannedJudge({"events": [
        {"源轮": ctid, "施动者": a, "受动者": b, "类目": "结怨", "语境": "甲斥乙。"},
        {"源轮": ctid, "施动者": b, "受动者": a, "类目": "结怨", "语境": "乙斥甲。"},
    ]}))
    assert not res.get("degraded")
    rows = db.get_relation_edge_events(event_kind="结怨")
    assert [(r["source"], r["target"], r["context"]) for r in rows] == [
        (a, b, "甲斥乙。"), (b, a, "乙斥甲。"),
    ]
    assert {r["origin"] for r in rows} == {
        summon_edge_origin(ctid) + f"|round:{state.turn}",
    }


def test_multiparty_event_is_lead_to_each_participant_only(game):
    """r2 F2②：多方事件=牵头→各参与方各一行；无参与方互连行、无反向行。"""
    db, state, content = game
    lead, other_a, other_b = _roster_names(db, state, n=3)
    _make_turn(db, state, lead, "议", "答")
    agent = _CannedJudge({"events": [{
        "施动者": lead, "受动者": [other_a, other_b], "类目": "联名",
        "语境": f"{lead}牵头当面联署。",
    }]})
    res = _run(db, state, agent)
    assert not res.get("degraded")
    rows = db.get_relation_edge_events(event_kind="联名")
    triplets = {(r["source"], r["target"]) for r in rows}
    assert triplets == {(lead, other_a), (lead, other_b)}
    assert len(rows) == 2
    assert db.get_relation_edge_events(source=other_a, target=other_b) == []


def test_context_stored_byte_identical_through_judge_chain(game):
    """r1 F1：含首尾空白+换行的判官 context 写入→读回字节相等。"""
    db, state, content = game
    a, b = _roster_names(db, state)
    _make_turn(db, state, a, "问", "答")
    raw_context = f"\n  {a}当面替{b}站台。  \n"
    agent = _CannedJudge(_event_items(a, b, "站台", raw_context))
    res = _run(db, state, agent)
    assert not res.get("degraded")
    rows = db.get_relation_edge_events(source=a, target=b)
    assert len(rows) == 1 and rows[0]["context"] == raw_context


# ── 已判水位＋写口幂等（0082 / r2 F2③）─────────────────────────────


def test_multi_turn_events_keep_distinct_source_origins_for_independent_undo(game):
    """多轮批判读按真实源轮归因；撤一轮不得误删另一轮事实。"""
    db, state, content = game
    a, b = _roster_names(db, state)
    first = _make_turn(db, state, a, "先议", "先表态")
    second = _make_turn(db, state, b, "再议", "再表态")
    agent = _CannedJudge({"events": [
        {"源轮": first, "施动者": a, "受动者": b, "类目": "站台", "语境": "第一轮。"},
        {"源轮": second, "施动者": b, "受动者": a, "类目": "结怨", "语境": "第二轮。"},
    ]})
    res = _run(db, state, agent)
    assert res["origins"] == [summon_edge_origin(first), summon_edge_origin(second)]
    db.undo_chat_turn(second)
    rows = db.get_relation_edge_events()
    assert [(r["source"], r["target"], r["context"]) for r in rows] == [(a, b, "第一轮。")]
    db.undo_chat_turn(first)
    assert db.get_relation_edge_events() == []


def test_event_and_watermark_rollback_together_on_crash(game, monkeypatch):
    """边写后、水位提交前崩溃时，两者作为一个恢复单元全部回滚。"""
    db, state, content = game
    a, b = _roster_names(db, state)
    ctid = _make_turn(db, state, a, "问", "答")
    real_mark = db.mark_relation_judge_done

    def crash(_ids):
        raise RuntimeError("injected crash before watermark")

    monkeypatch.setattr(db, "mark_relation_judge_done", crash)
    with pytest.raises(RuntimeError, match="injected crash"):
        _run(db, state, _CannedJudge(_event_items(a, b, "协作", "原子事件。")))
    assert db.get_relation_edge_events() == []
    assert _judge_status(db, ctid) == ""
    monkeypatch.setattr(db, "mark_relation_judge_done", real_mark)


def test_watermark_prevents_rejudging_and_replay_is_absorbed(game):
    db, state, content = game
    a, b = _roster_names(db, state)
    _make_turn(db, state, a, "问", "答")
    agent = _CannedJudge(_event_items(a, b, "结怨", f"{a}当面与{b}结怨。"))
    res1 = _run(db, state, agent)
    assert agent.calls == 1 and len(db.get_relation_edge_events()) >= 1

    # 多拍重看：水位后窗口为空 → 零 LLM 零写入
    res2 = _run(db, state, agent)
    assert res2.get("skipped") == "no_window"
    assert agent.calls == 1

    # 强制重窗（模拟崩溃后未标 done 的重放）：同一输出经 UNIQUE 幂等吸收，行数不变
    db.conn.execute("UPDATE chat_turns SET relation_judge_status=''")
    db.conn.commit()
    res3 = _run(db, state, agent)
    assert not res3.get("degraded")
    assert len(db.get_relation_edge_events(source=a, target=b)) == 1


# ── 无互动零事件／坏项逐条拒收 ──────────────────────────────────────


def test_no_interaction_means_zero_events_but_window_marked_done(game):
    db, state, content = game
    a, _b = _roster_names(db, state)
    ctid = _make_turn(db, state, a, "今日天气如何？", "回陛下，晴。")
    agent = _CannedJudge({"events": []})
    res = _run(db, state, agent)
    assert not res.get("degraded")
    assert db.get_relation_edge_events() == []
    assert _judge_status(db, ctid) == "done"


def test_empty_window_costs_zero_llm(game, monkeypatch):
    db, state, content = game
    factory_calls = []
    monkeypatch.setattr(
        agents_mod, "create_relation_judge_agent",
        lambda cfg: factory_calls.append(cfg),
    )
    a, _b = _roster_names(db, state)
    _make_turn(db, state, a, "问", "答")
    agent = _CannedJudge({"events": []})
    _run(db, state, agent)  # 判完清窗
    assert factory_calls == []
    res = _run(db, state, None)  # 空窗连 agent 都不该建
    assert res.get("skipped") == "no_window"
    assert factory_calls == []


def test_garbage_items_rejected_per_item_good_item_still_lands(game):
    db, state, content = game
    a, b = _roster_names(db, state)
    _make_turn(db, state, a, "问", "答")
    agent = _CannedJudge({"events": [
        {"施动者": a, "受动者": b, "类目": "协作", "语境": f"{a}与{b}当面约定协作。"},
        {"施动者": a, "受动者": "查无此人", "类目": "站台", "语境": "幻觉端点。"},
        {"施动者": a, "受动者": b, "类目": "吹牛", "语境": "未知类目。"},
        {"施动者": a, "受动者": a, "类目": "站台", "语境": "自指。"},
        "not-a-dict",
    ]})
    res = _run(db, state, agent)
    assert not res.get("degraded")
    assert len(res["rejected"]) == 4
    rows = db.get_relation_edge_events()
    assert [(r["source"], r["target"], r["event_kind"]) for r in rows] == [(a, b, "协作")]


def test_minister_kinds_only_imperial_kinds_rejected(game):
    db, state, content = game
    a, b = _roster_names(db, state)
    _make_turn(db, state, a, "问", "答")
    agent = _CannedJudge(_event_items(a, b, "知遇", "君臣类目不归召对口。"))
    res = _run(db, state, agent)
    assert len(res["rejected"]) == 1
    assert db.get_relation_edge_events() == []


# ── 判官漏判不阻塞主链／在飞残余终结 ────────────────────────────────


def test_judge_failure_degrades_loudly_and_leaves_window_open(game):
    db, state, content = game
    a, _b = _roster_names(db, state)
    ctid = _make_turn(db, state, a, "问", "答")

    class _Boom:
        def run(self, prompt):
            raise RuntimeError("provider down")

    res = _run(db, state, _Boom())
    assert res.get("degraded")
    assert _judge_status(db, ctid) == ""
    assert db.get_relation_edge_events() == []


def test_retired_turn_mid_flight_aborts_batch_without_write(game):
    """0038 终结异步残余：写入前校验目标轮存活；被撤/失败轮的批零写入零标记。"""
    db, state, content = game
    a, b = _roster_names(db, state)
    ctid = _make_turn(db, state, a, "问", "答")
    agent = _CannedJudge(
        _event_items(a, b, "站台", "迟到的事件。"),
        db=db, retire_turn_id=ctid,
    )
    res = _run(db, state, agent)
    assert res.get("skipped") == "turn_retired"
    assert db.get_relation_edge_events() == []
    assert _judge_status(db, ctid) != "done"


# ── 撤回联动（0038 白名单③）────────────────────────────────────────


def test_undo_deletes_bound_edges_and_rejudging_after_resend_is_clean(game):
    db, state, content = game
    a, b = _roster_names(db, state)
    q, ans = "卿等当面议一议。", "臣当面表态。"
    ctid = _make_turn(db, state, a, q, ans)
    agent = _CannedJudge(_event_items(a, b, "站台", f"{a}当面替{b}站台。"))
    _run(db, state, agent)
    assert len(db.get_relation_edge_events(source=a, target=b)) == 1

    db.undo_chat_turn(ctid)
    # 撤回该轮后该轮边事件不复存在；undone 轮不再进窗口（水位回退语义）
    assert db.get_relation_edge_events() == []
    assert db.list_unjudged_completed_chat_turns() == []

    # 该轮重发后重判不重复不遗漏
    ctid2 = _make_turn(db, state, a, q, ans)
    res = _run(db, state, agent)
    assert not res.get("degraded")
    rows = db.get_relation_edge_events(source=a, target=b)
    assert len(rows) == 1
    assert rows[0]["origin"].startswith(summon_edge_origin(ctid2))
    assert _judge_status(db, ctid2) == "done"


# ── 收夜扫尾覆盖 ─────────────────────────────────────────────────────


def test_close_night_sweep_covers_residual_before_closed(game, monkeypatch):
    """回话内新生事件在召对结束前完成落库（收夜扫尾只补残段）。"""
    db, state, content = game
    a, b = _roster_names(db, state)
    night = an.open_night(db, state)
    nid = int(night["id"])
    ctid = _make_turn(db, state, a, "卿还有何奏？", "臣附议。", night_id=nid)
    # 抽取腿离线中和（本片不涉）：标 done 防抽取 drain 挡在扫尾之前。
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done' WHERE id=?", (int(ctid),),
    )
    db.conn.commit()
    monkeypatch.setattr(
        agents_mod, "create_relation_judge_agent",
        lambda cfg: _CannedJudge(_event_items(a, b, "协作", f"{a}答话里当场与{b}结成协作。")),
    )
    result = an.close_night(
        db, state, night_id=nid, body="退朝。", llm_config=object(),
    )
    assert result["closed"] is True
    final = an.get_night(db, nid)
    assert final["status"] == an.NIGHT_STATUS_CLOSED
    rows = db.get_relation_edge_events(source=a, target=b)
    assert [(r["event_kind"],) for r in rows] == [("协作",)]
    assert _judge_status(db, ctid) == "done"


# ── origin 拼装器契约 ────────────────────────────────────────────────


def test_summon_edge_origin_shape():
    assert summon_edge_origin(7) == "召对判官|chat_turn:7"
