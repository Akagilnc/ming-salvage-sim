"""#642 族尾收口：本片独有 CI——锚③召对写口徐杨协作 + 闸脚本生产缝主干。

既有指针（不平行重测）：
- 锚① seed 网：`tests/test_relation_seed_638.py`
- 锚② 活模型语义：闸级 `scripts/family_tail_relation_acceptance_642.py --anchor yang`
  （CI 只证 close_night 判官 Future + 按月 settle 主干，不直写三拍边）
- 锚④ prior 机械：`tests/test_relation_read_640.py` + `tests/test_relation_brew_636.py`
  + 本文件 coda mechanical-only
- R1 双表面：`tests/test_relation_store_632.py::test_relation_edges_survive_restore`
- R2：`tests/test_relation_brew_636.py::test_r2_commit_join_before_persist_*`
- R3 / DoD 面4：seed_638 / capture_633
"""

from __future__ import annotations

import json
import threading

from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
import ming_sim.issues as issues_mod
from ming_sim.models import LLMConfig
from ming_sim.relation_brew import FOUNDINGS_KEY, MonthEndRelationBrewLeg, RECENT_KEY
from ming_sim.relation_judge import run_summon_relation_judge, summon_edge_origin
from ming_sim.relations import MINISTER_EDGE_KINDS
from ming_sim.session import ChatTurnResult, GameSession


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


def _gate_cfg() -> LLMConfig:
    return LLMConfig(api_key="x", base_url="http://x", model="x", channel="api")


def _bind_content() -> GameContent:
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    return content


def test_coda_acceptance_mechanical_only_skips_live_llm(monkeypatch):
    """锚④闸路径：prior 机械成立；不调用语义活模型。"""
    import scripts.family_tail_relation_acceptance_642 as gate

    def _boom(*_a, **_k):
        raise AssertionError("coda must not call live semantic LLM")

    monkeypatch.setattr(gate, "_llm_json_verdict", _boom)
    monkeypatch.setattr(gate, "run_agent_text", _boom)
    monkeypatch.setattr(gate, "create_chat_model", _boom)

    result = gate._run_coda_anchor(_gate_cfg(), _bind_content())
    assert result["anchor"] == "coda"
    assert result["checks"] == {"mechanical_ok": True}
    assert result["mechanical"]["prior_has_founding"] is True
    assert "semantic_pass" not in result["checks"]
    assert "semantic" not in result


def test_yang_acceptance_tracer_production_chain_not_direct_write(monkeypatch):
    """锚②最短生产缝：召对→close_night 判官 Future→按月 settle/brew；禁 gate642 自证写边。

    canned 只替 LLM 体；attach/persist/close_night/settle 走真实入口。
    typed 断言水位/origin/edge/摘要年月递进；不锁自由文本、不另造 executor。
    """
    import ming_sim.agents as agents_mod
    import scripts.family_tail_relation_acceptance_642 as gate

    content = _bind_content()
    cfg = _gate_cfg()
    judge_calls = {"n": 0}
    chat_calls = {"n": 0}
    brew_calls = {"n": 0}
    direct_write_origins: list[str] = []

    real_record = GameDB.record_relation_edge_event

    def _spy_record(self, *args, **kwargs):
        origin = str(kwargs.get("origin") or "")
        if origin.startswith("gate642:"):
            direct_write_origins.append(origin)
        return real_record(self, *args, **kwargs)

    monkeypatch.setattr(GameDB, "record_relation_edge_event", _spy_record)

    def _fake_chat(self, minister_name, message, *, chat_turn_id=0):
        # 三拍答问只驱动真实召对入口；边事件由 canned 判官按拍递进，不锁答词。
        chat_calls["n"] += 1
        n = chat_calls["n"]
        if n <= 1:
            answer = (
                f"臣{minister_name}领旨。臣与倪元璐、黄道周清丈路线相左，"
                f"钱粮权宜与刚直硬顶当面掣肘，细缝已现。"
            )
        elif n == 2:
            answer = (
                f"臣{minister_name}领旨。与倪元璐、黄道周一刚一柔分工协作，"
                f"细缝在而事可办；户部接应钱粮，臣任之。"
            )
        else:
            answer = (
                f"臣{minister_name}领旨。与倪黄互看册证、分歧并呈，"
                f"旧隙不必抹平，事要办成。"
            )
        return ChatTurnResult(answer=answer)

    monkeypatch.setattr(GameSession, "chat", _fake_chat)

    # 张力→配合→演进：三拍 canned 判官经 close_night Future 真实写边，不直写。
    _BEAT_EVENTS = (
        {"events": [
            {"施动者": "杨嗣昌", "受动者": "倪元璐", "类目": "使绊",
             "语境": "杨嗣昌与倪元璐清丈路线相左当面掣肘。"},
            {"施动者": "杨嗣昌", "受动者": "黄道周", "类目": "使绊",
             "语境": "杨嗣昌与黄道周清丈路线相左当面掣肘。"},
        ]},
        {"events": [
            {"施动者": "杨嗣昌", "受动者": "倪元璐", "类目": "协作",
             "语境": "杨嗣昌与倪元璐当面一刚一柔分工协作。"},
            {"施动者": "杨嗣昌", "受动者": "黄道周", "类目": "协作",
             "语境": "杨嗣昌与黄道周当面一刚一柔分工协作。"},
        ]},
        {"events": [
            {"施动者": "杨嗣昌", "受动者": "倪元璐", "类目": "协作",
             "语境": "杨嗣昌与倪元璐推进互看册证、分歧并呈御前。"},
            {"施动者": "杨嗣昌", "受动者": "黄道周", "类目": "协作",
             "语境": "杨嗣昌与黄道周推进互看册证、分歧并呈御前。"},
        ]},
    )

    class _BeatJudge:
        def run(self, prompt):
            del prompt
            idx = judge_calls["n"]
            judge_calls["n"] += 1
            payload = _BEAT_EVENTS[min(idx, len(_BEAT_EVENTS) - 1)]
            from types import SimpleNamespace
            return SimpleNamespace(
                content=json.dumps(payload, ensure_ascii=False),
            )

    def _fake_agent(_cfg):
        return _BeatJudge()

    monkeypatch.setattr(agents_mod, "create_relation_judge_agent", _fake_agent)

    def _fake_runner(_cfg, _agno):
        def _create(state, db, *, settled_turn, settled_year, settled_period):
            def _brew_fn(payload_json: str) -> str:
                brew_calls["n"] += 1
                return json.dumps(
                    {FOUNDINGS_KEY: [], RECENT_KEY: "近况重酿（canned）。"},
                    ensure_ascii=False,
                )

            return MonthEndRelationBrewLeg(
                db, state, _brew_fn,
                settled_turn=settled_turn,
                settled_year=settled_year,
                settled_period=settled_period,
            )

        return _create

    monkeypatch.setattr(gate, "_make_relation_brew_runner", _fake_runner)
    monkeypatch.setattr(
        gate, "_llm_json_verdict",
        lambda *_a, **_k: {"pass": True, "reason": "canned semantic"},
    )

    result = gate._run_yang_anchor(cfg, content)
    structural = result["structural"]
    assert result["checks"]["structural_ok"] is True, structural
    assert result["checks"]["semantic_pass"] is True
    assert judge_calls["n"] == 3
    assert len(result["settles"]) == 3
    assert brew_calls["n"] >= 1
    assert result["summon_edge_ids"], result
    assert not direct_write_origins, direct_write_origins
    assert structural["judge_watermark_done"] is True
    assert structural["origins_bind_chat_turn"] is True
    assert structural["edge_ids_present"] is True
    assert structural["month_advanced_each_settle"] is True
    assert structural["summary_brew_progressed"] is True
    assert all(
        str((beat.get("judge") or {}).get("relation_judge_status") or "") == "done"
        for beat in result["beats"]
    )
    assert all(
        "|chat_turn:" in str(origin)
        for beat in result["beats"]
        for origin in (beat.get("judge") or {}).get("origins") or []
    )
    # 三拍真实年月序列（turn + year/period，非单点自比）
    settle_cals = [
        (int(s["settled_year"]), int(s["settled_period"]), int(s["settled_turn"]))
        for s in result["settles"]
    ]
    assert settle_cals == [(1627, 10, 1), (1627, 11, 2), (1627, 12, 3)], settle_cals
    # 时序：第二拍召对调用前 face_before 已含杨↔倪/黄（第一拍张力回写后读面）
    assert len(result["beats"]) == 3
    beat2_face = result["beats"][1]["face_before"]
    face_pairs = [
        p for p in (beat2_face.get("pairs") or [])
        if "杨嗣昌" in (p.get("source"), p.get("target"))
        and ({"倪元璐", "黄道周"} & {p.get("source"), p.get("target")})
    ]
    assert face_pairs, beat2_face
    # 张力→配合→演进：各拍召对回写类目
    kind_seq = [
        sorted({
            str(e.get("event_kind") or "")
            for e in (beat.get("edges_from_this_turn") or [])
        })
        for beat in result["beats"]
    ]
    assert kind_seq[0] == ["使绊"], kind_seq
    assert kind_seq[1] == ["协作"], kind_seq
    assert kind_seq[2] == ["协作"], kind_seq
    # 同 pair 三拍摘要快照：last_event_id 与 last_brewed 年月均递进
    yang_ni: list[dict] = []
    for beat in result["beats"]:
        hit = next(
            (
                p for p in beat.get("summaries_after_settle") or []
                if (p.get("source"), p.get("target")) == ("杨嗣昌", "倪元璐")
            ),
            None,
        )
        assert hit is not None, beat.get("summaries_after_settle")
        yang_ni.append(hit)
    assert len(yang_ni) == 3
    event_ids = [int(p["last_event_id"]) for p in yang_ni]
    brew_cals = [
        (int(p["last_brewed_year"]), int(p["last_brewed_period"])) for p in yang_ni
    ]
    assert event_ids[0] > 0 and event_ids[-1] > event_ids[0]
    assert event_ids == sorted(event_ids)
    assert brew_cals == [(1627, 10), (1627, 11), (1627, 12)], brew_cals
