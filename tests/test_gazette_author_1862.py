from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation
import json
import pytest
import ming_sim.month_chain as month_chain
from ming_sim.exceptions import LLMUnavailable
from ming_sim.materials import list_materials
from ming_sim.models import LLMConfig
from tests.month_chain_helpers import make_light_session
from tests.test_month_chain_1843 import _forbid_extractor, _stage_edict
"""#1862：邸报作者在过月暂停点一次写出标题和正文，随邸报入档后交回主链。"""





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
    monkeypatch.setattr("ming_sim.month_translate._default_month_translate_runner", lambda *_a, **_k: {"effects": {}})
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
        "ming_sim.agents.run_agent_text",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("未批红不得调用邸报模型")),
    )
    session = _session(db, state, content, monkeypatch)
    held = session.resolve_turn(allow_empty_decree=True)
    assert held.stage == "rescript"
    assert held.advanced is False




def test_gazette_failure_retries_report_only(web_game, monkeypatch):
    import asyncio
    import httpx
    import web_app
    from tests.month_chain_helpers import canned_full_settlement
    from tests.sse_helpers import parse_sse_event_pairs

    db, state, content = web_game.db, web_game.state, web_game.content
    canned_full_settlement(monkeypatch)
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
        return json.dumps({"title": _TITLE, "report": _REPORT})

    monkeypatch.setattr(month_chain, "run_world_segment_text", world)
    monkeypatch.setattr("ming_sim.agents.run_agent_text", gazette)

    async def retreat():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=web_app.app), base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/decree/advance_without_edict/stream", json={"expected_turn": turn},
            )
        assert response.status_code == 200
        return parse_sse_event_pairs(response.text)

    first = asyncio.run(retreat())
    assert first[-1][0] == "error", first
    detail = first[-1][1]
    assert detail["stage"] == "gazette"
    assert detail["code"] == "llm_unavailable"
    assert detail["status_code"] is None
    assert detail["turn"] == turn
    assert detail["error_pack_path"]
    assert int(state.turn) == turn
    assert web_game.state_payload()["turn"]["phase"] == "settling"
    charged = db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0]
    assert charged == 1
    assert world_calls == [1]
    assert db.turn_reports.report_text(turn) == ""
    failure = month_chain.month_chain_call_failure(db, turn)
    assert failure["step"] == "gazette"

    retried = asyncio.run(retreat())
    kind, result = retried[-1]
    assert kind == "done", retried
    assert result["advanced"] is True
    assert int(state.turn) == turn + 1
    assert month_chain.month_chain_call_failure(db, turn) is None
    assert gazette_calls["n"] == 2
    assert world_calls == [1]
    assert db.conn.execute(
        "SELECT COUNT(*) FROM economy_ledger WHERE category='宁远补饷'",
    ).fetchone()[0] == 1
    # 重试后作者返回题名／正文原样进归档
    archive = db.turn_reports.archive(turn)
    assert archive["title"] == _TITLE
    assert archive["report"] == _REPORT


@pytest.mark.parametrize("streaming", [True, False])
def test_author_excludes_secret_sources_from_public_materials(game, monkeypatch, streaming):
    import ming_sim.agents as agents
    from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
    from tests.dossier_test_helpers import create_test_secret_order
    from ming_sim.declaration_dispatch import stage_declaration
    from agno.run.agent import RunContentEvent, RunOutput

    db, state, content = game
    name = next(iter(content.characters))
    affair = db.affairs.open(name="公开事务", origin="旨", year=state.year, period=state.period, turn=state.turn)
    oid = create_test_secret_order(db, state, name, "密题", "密令输入", [], deadline_months=1)
    secret = db.dossiers.get_for_secret_order(oid)["id"]
    plain = db.create_decree_dossier(state, action_type="policy", decree_text="公开输入", target_kind="issue", target_id="gazette-public")
    apply_dossier_promulgation(db, state, plain, "promulgated")
    db.dossiers.set_affair_id_if_unbound(plain, affair.id)
    db.dossiers.set_affair_id_if_unbound(secret, affair.id)
    origins = [f"affair:{affair.id}", f"dossier:{plain}", f"secret_order:{oid}", f"dossier:{secret}"]
    for origin in origins:
        if origin != origins[3]:
            stage_declaration(db, decree_ref=origin, turn=int(state.turn), declaration={"textual_facts": []}, forecast_text=origin)
            db.staged_declarations.mark_terminal(origin)
        db.textual_facts.append(subject_kind="character", subject_id=name, body=f"fact:{origin}", year=state.year, period=state.period, turn=state.turn, origin_ref=origin)
        db.conn.execute("INSERT INTO economy_ledger (turn,year,period,account,delta,balance_after,category,reason,origin_ref) VALUES (?,?,?,'国库',-1,1,'测试',?,?)", (state.turn,state.year,state.period,f"ledger:{origin}",origin))
        collector = RejectionCollector()
        collector.record("测试", RejectedItem({"origin_ref": origin}, "输入拒因", "invalid_shape", Provenance.player_decree), state.turn)
        collector.flush_to_db(db)
        db.insert_issue(state, kind="initiative", title="到期复核", origin_kind="decree", origin_ref=origin, commitment_kind="once", end_turn=state.turn)
    db.conn.commit()
    seen = {}
    previews = []
    product = {"title": "标题输入", "report": '\n  字"\\\n正文  '}

    class AuthorModel:
        supports_stream = streaming

        def run(self, message, **kwargs):
            seen["feed"] = json.loads(message)
            raw = json.dumps(product, ensure_ascii=False)
            if not streaming:
                assert not kwargs
                return RunOutput(content=raw)
            assert kwargs == {"stream": True, "stream_events": True, "yield_run_output": True}

            def events():
                for piece in raw:
                    yield RunContentEvent(content=piece)
                # The callback has already received structured report content,
                # before the SDK terminal and before any report can be archived.
                assert previews[-1] == {"report": product["report"]}
                yield RunOutput(content=raw)
            return events()

    # 观测真实 prepare→写手过滤结果，不 helper 自证、不盯正文。
    import ming_sim.materials as materials_mod
    kept_fact_origins: list[str] = []
    kept_history_origins: list[str] = []
    real_keep = materials_mod._keep_fact
    real_hist = materials_mod._world_history_row_visible

    def spy_keep(fact, include_fact):
        ok = real_keep(fact, include_fact)
        if ok:
            kept_fact_origins.append(str(getattr(fact, "origin_ref", "") or ""))
        return ok

    def spy_hist(db_, row, secret_turn_ids, public_only):
        ok = real_hist(db_, row, secret_turn_ids, public_only)
        if ok and public_only:
            for key in ("origin_ref", "origin", "source_id"):
                value = str(row.get(key) or "")
                if value:
                    kept_history_origins.append(value)
        return ok

    monkeypatch.setattr(materials_mod, "_keep_fact", spy_keep)
    monkeypatch.setattr(materials_mod, "_world_history_row_visible", spy_hist)

    def author(_config, prepared):
        seen["paths"] = list_materials(prepared.root)
        return AuthorModel()
    monkeypatch.setattr(agents, "create_gazette_author_agent", author)
    title, report = month_chain.run_gazette_text(db, state, _llm(), on_gazette=previews.append)
    assert (title, report) == (product["title"], product["report"])
    assert previews[-1] == {"report": report}
    assert not any(p.startswith("密令/") for p in seen["paths"])
    feed = seen["feed"]
    # Landed facts and ledger history now come from the public material tree;
    # no nominal/forecast/rejection parallel feed is restored.
    refs = {item["origin_ref"] for item in feed["due_commitments"]}
    assert set(origins[:2]) <= refs
    assert set(origins[2:]).isdisjoint(refs)
    assert {"landed", "nominal", "forecasts", "rejections"}.isdisjoint(feed)
    public_origins, secret_origins = set(origins[:2]), set(origins[2:])
    assert public_origins <= set(kept_fact_origins)
    assert secret_origins.isdisjoint(kept_fact_origins)
    assert public_origins & set(kept_history_origins)
    assert secret_origins.isdisjoint(kept_history_origins)
    assert any(
        part.startswith(f"affair-{affair.id}-")
        for path in seen["paths"] for part in str(path).split("/")
    )
