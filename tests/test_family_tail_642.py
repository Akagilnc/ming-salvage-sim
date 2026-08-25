"""#642 族尾收口：仅本片独有 CI 机械面。

既有指针（不平行重测）：
- 锚① seed 网：`tests/test_relation_seed_638.py`（GameSession 新开档导入 +
  `project_relation_ledger` + 魏忠贤场边/摘要可读）
- 锚④ prior_events：`tests/test_relation_read_640.py` +
  `tests/test_relation_brew_636.py`（history 缝 + build_brew_input/prepare）
- DoD 面4 extractor：`tests/test_relation_capture_633.py`
  （`test_settlement_interaction_lands_directed_edge_with_origin_round` 等）
- R2：`tests/test_relation_brew_636.py::test_r2_commit_join_before_persist_*`
- R3 seed restore：`tests/test_relation_seed_638.py` 幂等/回滚/旧档

闸级语义：`scripts/family_tail_relation_acceptance_642.py`（与 #570 颁布闸域不同，不可并入）。
"""

from __future__ import annotations

import json
import threading

from ming_sim.db import GameDB
from ming_sim.relation_judge import run_summon_relation_judge, summon_edge_origin
from ming_sim.relation_read import project_relation_ledger
from ming_sim.relations import EMPEROR_NODE, MINISTER_EDGE_KINDS


class _CannedJudge:
    def __init__(self, payload):
        self.payload = (
            payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )
        self.calls = 0

    def run(self, prompt):
        from types import SimpleNamespace
        self.calls += 1
        return SimpleNamespace(content=self.payload)


def _make_turn(db, state, minister, question, answer):
    ctid = db.create_chat_turn(state, minister, "t642:s", 0, night_id=0)
    umid = db.append_chat_message(minister, int(state.turn), "user", question)
    db.update_chat_turn_messages(ctid, user_message_id=umid)
    mid = db.append_chat_message(minister, int(state.turn), "minister", answer)
    db.update_chat_turn_messages(ctid, minister_message_id=mid)
    return ctid


# ── 锚② 结构步：三拍边/读面闭环（加深语义仅闸级 LLM）────────────────


def test_anchor2_yang_three_beat_structural_read_write_loop(game):
    """锚② 结构面：读面→张力边→配合协作回写→知遇再深；旧张力不删。"""
    db, state, _content = game
    db.record_relation_edge_event(
        source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
        context="越次一召，擢杨嗣昌于五品郎中。",
        origin="anchor2:beat1", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    db.record_relation_edge_event(
        source="杨嗣昌", target="倪元璐", event_kind="使绊",
        context="清丈议上路线分歧，细缝初现。",
        origin="anchor2:beat2", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    yang_face = project_relation_ledger(db, viewer="杨嗣昌")
    yang_pairs = {(d["source"], d["target"]) for d in yang_face}
    assert (EMPEROR_NODE, "杨嗣昌") in yang_pairs
    assert ("杨嗣昌", "倪元璐") in yang_pairs
    tension = next(
        d for d in yang_face if (d["source"], d["target"]) == ("杨嗣昌", "倪元璐")
    )
    assert "细缝初现" in tension["recent_context"]
    db.record_relation_edge_event(
        source="杨嗣昌", target="倪元璐", event_kind="协作",
        context="一刚一柔分工，当面调和而不抹去前隙。",
        origin="anchor2:beat3-collab", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    db.record_relation_edge_event(
        source=EMPEROR_NODE, target="杨嗣昌", event_kind="知遇",
        context="清丈委任加重，圣眷再深。",
        origin="anchor2:beat3-zhiyu", turn=int(state.turn),
        year=int(state.year), period=int(state.period),
    )
    jun_yang = db.get_relation_edge_events(source=EMPEROR_NODE, target="杨嗣昌")
    assert sum(1 for e in jun_yang if e["event_kind"] == "知遇") >= 2
    yang_ni = db.get_relation_edge_events(source="杨嗣昌", target="倪元璐")
    kinds = {e["event_kind"] for e in yang_ni}
    assert "使绊" in kinds and "协作" in kinds
    assert any(e["context"] == "清丈议上路线分歧，细缝初现。" for e in yang_ni)
    for e in jun_yang + yang_ni:
        assert e["event_kind"] and e["context"].strip() and e["origin"]


# ── 锚③：召对判官落边生产缝生成徐杨协作 ─────────────────────────────


def test_anchor3_xuyang_collaboration_via_summon_judge(game):
    """锚③：真实召对判官链当场落协作边；端点覆盖徐光启与杨嗣昌；origin 绑源轮。"""
    db, state, _content = game
    # 北极星「徐杨相发明」：徐光启开局 offstage——fixture 推至在朝，合法端点。
    db.conn.execute(
        "UPDATE characters SET status='active', office=?, office_type=? "
        "WHERE name=?",
        ("礼部尚书兼东阁大学士", "内阁", "徐光启"),
    )
    db.conn.commit()
    roster = {r["name"] for r in db.current_court_roster_rows(state)}
    assert {"徐光启", "杨嗣昌"} <= roster
    ctid = _make_turn(
        db, state, "杨嗣昌",
        "卿与徐阁老清丈屯田之议，可相发明否？",
        "臣与徐阁老相发明，清丈隐田与屯田番薯可三合一。",
    )
    context = "杨嗣昌与徐光启在御前就清丈屯田番薯相发明，结成协作。"
    agent = _CannedJudge({"events": [{
        "施动者": "杨嗣昌", "受动者": "徐光启", "类目": "协作", "语境": context,
    }]})
    res = run_summon_relation_judge(
        db, state, llm_config=object(), write_gate=threading.Lock(), agent=agent,
    )
    assert not res.get("degraded") and not res.get("skipped"), res
    hit = [
        r for r in db.get_relation_edge_events(event_kind="协作")
        if {r["source"], r["target"]} == {"徐光启", "杨嗣昌"}
    ]
    assert len(hit) == 1
    row = hit[0]
    assert row["event_kind"] in MINISTER_EDGE_KINDS
    assert row["context"] == context
    assert int(row["turn"]) == int(state.turn)
    assert row["origin"].startswith(summon_edge_origin(ctid))
    path = db.path
    db.close()
    reopened = GameDB(path)
    again = [
        r for r in reopened.get_relation_edge_events(event_kind="协作")
        if {r["source"], r["target"]} == {"徐光启", "杨嗣昌"}
    ]
    assert len(again) == 1 and again[0]["context"] == context
    reopened.close()


# ── R1 双表面：边事件 + 摘要 restore（扩 store_632 仅边面）──────────


def test_r1_edges_and_summaries_survive_reopen(game):
    """R1：边/摘要提交后重开 DB 逐字段一致。"""
    db, state, _ = game
    db.record_relation_edge_event(
        source="温体仁", target="周延儒", event_kind="结怨",
        context="当殿讦奏。", origin="audience:r1",
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    last_id = db.get_relation_edge_events(source="温体仁", target="周延儒")[-1]["id"]
    db.apply_relation_brew_result(
        source="温体仁", target="周延儒", dimension="大臣",
        founding_segment="温周初隙。",
        recent_segment="朝堂侧目。",
        last_event_id=last_id,
        turn=int(state.turn), year=int(state.year), period=int(state.period),
    )
    edge = db.get_relation_edge_events(source="温体仁", target="周延儒")[0]
    summary = db.get_relation_summary("温体仁", "周延儒")
    path = db.path
    db.close()
    reopened = GameDB(path)
    edge2 = reopened.get_relation_edge_events(source="温体仁", target="周延儒")[0]
    summary2 = reopened.get_relation_summary("温体仁", "周延儒")
    for key in (
        "source", "target", "event_kind", "context", "origin",
        "year", "period", "turn",
    ):
        assert edge2[key] == edge[key]
    for key in (
        "founding_segment", "recent_segment", "last_event_id",
        "last_brewed_year", "last_brewed_period", "dimension",
    ):
        assert summary2[key] == summary[key]
    reopened.close()
