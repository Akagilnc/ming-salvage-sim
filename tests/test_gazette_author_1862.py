"""#1862：邸报作者在过月暂停点一次写出标题和正文，随邸报入档后交回主链。"""

from __future__ import annotations


import json
import pytest

import ming_sim.month_chain as month_chain
import ming_sim.month_translate as month_translate
from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.models import LLMConfig
from tests.month_chain_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor, _stage_edict

_SECRET_DECL = "SECRET_DECL_1862"
_SECRET_FORECAST = "SECRET_FORECAST_1862"
_SECRET_FACT = "SECRET_FACT_1862"
_SECRET_REJ = "SECRET_REJ_1862"
_PUBLIC_FACT = "PUBLIC_FACT_1862"
_PUBLIC_REJ = "PUBLIC_REJ_1862"
_SECRET_BRIEF = "SECRET_BRIEF_BODY_1862"
_SECRET_AUDIENCE = "AUD_SECRET_SRC_1862"
_PRIVATE_KEEP = "AUD_PRIVATE_KEEP_1862"
_SECRET_DOSSIER_TEXT = "SECRET_DOSSIER_OPEN_1862"
_PLAIN_DOSSIER_TEXT = "PLAIN_DOSSIER_OPEN_1862"
_SECRET_DOSSIER_LEDGER = "SECRET_DOSSIER_LEDGER_1862"
_PLAIN_DOSSIER_LEDGER = "PLAIN_DOSSIER_LEDGER_1862"
_SECRET_DOSSIER_FACT = "SECRET_DOSSIER_FACT_1862"
_PLAIN_DOSSIER_FACT = "PLAIN_DOSSIER_FACT_1862"
_TITLE = "关山烽火"
_REPORT = "本月实况正文"


def _llm() -> LLMConfig:
    return LLMConfig(api_key="test", base_url="http://127.0.0.1:9", model="gazette-test")


def _session(db, state, content, monkeypatch):
    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_translate, "translate_month_segment", lambda *_a, **_k: {"effects": {}})
    session = make_light_session(db, state, content)
    session.llm_config = _llm()
    session._write_gate = session._write_queue.write_gate
    return session


def test_author_waits_until_rescript_is_done(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="请旨挡邸报", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _pending, ref = _stage_edict(db, state, minister, "陕西赈灾", "陕西赈灾", -1, affair.id)
    db.conn.execute(
        "UPDATE staged_declarations SET questions_json=? WHERE decree_ref=?",
        (
            '[{"title":"是否加赈","context":"c","options":[{"label":"加","hint":"h1"},{"label":"否","hint":"h2"}]}]',
            ref,
        ),
    )
    db.conn.commit()
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *_a, **_k: "")
    # 外部 LLM 边界：挡邸报作者；可见结果是请旨台阶段，不锁调用次数。
    monkeypatch.setattr(
        month_chain, "run_gazette_text",
        lambda *_a, **_k: (_TITLE, _REPORT),
    )
    session = _session(db, state, content, monkeypatch)
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.advanced is False




def test_gazette_failure_retries_report_only(game, monkeypatch):
    db, state, content = game
    minister = next(iter(content.characters.values())).name
    affair = db.affairs.open(
        name="重试可见", origin="旨意", year=state.year, period=state.period, turn=state.turn,
    )
    _stage_edict(db, state, minister, "宁远补饷", "宁远补饷", -1, affair.id)
    turn = int(state.turn)
    world_calls = []
    gazette_calls = {"n": 0}

    def world(*_a, **_k):
        world_calls.append(1)
        return "世界段一次"

    def gazette(*_a, **_k):
        gazette_calls["n"] += 1
        if gazette_calls["n"] == 1:
            raise LLMUnavailable("邸报写失败", stage="gazette")
        return _TITLE, _REPORT

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr(month_chain, "run_gazette_text", gazette)
    session = _session(db, state, content, monkeypatch)
    with pytest.raises(SettlementAbort) as caught:
        session.resolve_turn(allow_empty_decree=True)
    assert "邸报写失败" in str(caught.value.__cause__)
    charged = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0]
    assert charged == 1
    assert world_calls == [1]
    assert db.turn_reports.report_text(turn) == ""
    failure = month_chain.month_chain_call_failure(db, turn)
    assert failure["step"] == "gazette"

    result = session.resolve_turn(allow_empty_decree=True)
    assert result.advanced is True
    assert gazette_calls["n"] == 2
    assert world_calls == [1]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0] == 1
    archive = db.turn_reports.archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT


def test_author_excludes_secret_sources_from_structured_feed(game, monkeypatch):
    import ming_sim.agents as agents
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
    from tests.dossier_test_helpers import create_test_secret_order
    from ming_sim.declaration_dispatch import stage_declaration
    from ming_sim.materials import list_materials

    db, state, content = game
    name = next(iter(content.characters))
    affair = db.affairs.open(name="公开事务", origin="旨", year=state.year, period=state.period, turn=state.turn)
    oid = create_test_secret_order(db, state, name, "密题", "密令输入", [], deadline_months=1)
    secret = db.dossiers.get_for_secret_order(oid)["id"]
    plain = db.create_decree_dossier(state, action_type="policy", decree_text="公开输入", target_kind="issue", target_id="gazette-public")
    db.apply_dossier_promulgation(state, plain, "promulgated")
    origins = [f"affair:{affair.id}", f"dossier:{plain}", f"secret_order:{oid}", f"dossier:{secret}"]
    for origin in origins:
        if origin != origins[3]:
            stage_declaration(db, decree_ref=origin, turn=int(state.turn), declaration={"textual_facts": []}, forecast_text=origin)
            db.staged_declarations.mark_settled(origin)
        db.textual_facts.append(subject_kind="character", subject_id=name, body="实况输入", year=state.year, period=state.period, turn=state.turn, origin_ref=origin)
        db.conn.execute("INSERT INTO economy_ledger (turn,year,period,account,delta,balance_after,category,reason,origin_ref) VALUES (?,?,?,'国库',-1,1,'测试','输入',?)", (state.turn,state.year,state.period,origin))
        collector = RejectionCollector()
        collector.record("测试", RejectedItem({"origin_ref": origin}, "输入拒因", "invalid_shape", Provenance.player_decree), state.turn)
        collector.flush_to_db(db)
        db.insert_issue(state, kind="initiative", title="到期复核", origin_kind="decree", origin_ref=origin, commitment_kind="once", end_turn=state.turn)
    db.conn.commit()
    seen = {}
    def author(_config, prepared):
        seen["paths"] = list_materials(prepared.root)
        return object()
    def model(_agent, message, **_kw):
        seen["feed"] = json.loads(message)
        return json.dumps({"title": "标题输入", "report": "正文输入"})
    monkeypatch.setattr(agents, "create_gazette_author_agent", author)
    monkeypatch.setattr(agents, "run_agent_text", model)
    month_chain.run_gazette_text(db, state, _llm(), {"world_text": "世界输入"})
    assert not any(p.startswith("密令/") for p in seen["paths"])
    feed = seen["feed"]
    for key in ("landed", "rejections", "due_commitments"):
        rows = feed[key]
        refs = {str((r.get("item") or r).get("origin_ref") or "") for r in rows}
        assert set(origins[:2]) <= refs
        assert set(origins[2:]).isdisjoint(refs)
    assert {r["decree_ref"] for r in feed["nominal"]}.isdisjoint(origins[2:])
    assert feed["forecasts"] == origins[:2]
