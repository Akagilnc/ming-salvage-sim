"""#642 族尾收口：本片独有 CI——锚③召对写口徐杨协作。

既有指针（不平行重测）：
- 锚① seed 网：`tests/test_relation_seed_638.py`
- 锚② 结构/语义：闸级 `scripts/family_tail_relation_acceptance_642.py --anchor yang`
  （不在 CI 用直写 record 重言三拍）
- 锚④ prior：`tests/test_relation_read_640.py` + `tests/test_relation_brew_636.py`
- R1 双表面：`tests/test_relation_store_632.py::test_relation_edges_survive_restore`
- R2：`tests/test_relation_brew_636.py::test_r2_commit_join_before_persist_*`
- R3 / DoD 面4：seed_638 / capture_633
"""

from __future__ import annotations

import json
import threading

from ming_sim.db import GameDB
from ming_sim.relation_judge import run_summon_relation_judge, summon_edge_origin
from ming_sim.relations import MINISTER_EDGE_KINDS


class _CannedJudge:
    def __init__(self, payload):
        self.payload = (
            payload if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )

    def run(self, prompt):
        from types import SimpleNamespace
        return SimpleNamespace(content=self.payload)


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

    ctid = db.create_chat_turn(state, "杨嗣昌", "t642:s", 0, night_id=0)
    umid = db.append_chat_message("杨嗣昌", int(state.turn), "user", "卿与徐阁老可相发明否？")
    db.update_chat_turn_messages(ctid, user_message_id=umid)
    mid = db.append_chat_message(
        "杨嗣昌", int(state.turn), "minister",
        "臣与徐阁老相发明，清丈隐田与屯田番薯可三合一。",
    )
    db.update_chat_turn_messages(ctid, minister_message_id=mid)

    context = "杨嗣昌与徐光启在御前就清丈屯田番薯相发明，结成协作。"
    res = run_summon_relation_judge(
        db, state, llm_config=object(), write_gate=threading.Lock(),
        agent=_CannedJudge({"events": [{
            "施动者": "杨嗣昌", "受动者": "徐光启", "类目": "协作", "语境": context,
        }]}),
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
