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
        return ChatTurnResult(
            answer=(
                f"臣{minister_name}领旨。与倪元璐、黄道周一刚一柔分工协作，"
                f"细缝在而事可办；户部接应钱粮，臣任之。"
            ),
        )

    monkeypatch.setattr(GameSession, "chat", _fake_chat)

    class _BeatJudge(_CannedJudge):
        def run(self, prompt):
            judge_calls["n"] += 1
            return super().run(prompt)

    def _fake_agent(_cfg):
        return _BeatJudge({"events": [{
            "施动者": "杨嗣昌",
            "受动者": "倪元璐",
            "类目": "协作",
            "语境": "杨嗣昌与倪元璐当面分工协作。",
        }]})

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
    # 跨拍摘要水位/年月递进（typed；不锁自由文本）
    brew_cals = []
    for beat in result["beats"]:
        for ptr in beat.get("summaries_after_settle") or []:
            if {ptr.get("source"), ptr.get("target")} == {"杨嗣昌", "倪元璐"}:
                assert int(ptr.get("last_event_id") or 0) > 0
                brew_cals.append((
                    int(ptr.get("last_brewed_year") or 0),
                    int(ptr.get("last_brewed_period") or 0),
                ))
    assert brew_cals and brew_cals[-1][0] > 0
    assert brew_cals[-1] >= brew_cals[0]
