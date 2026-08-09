"""#566: production settlement owns the durable monthly progress rail."""


def _actor(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def _order(db, state, title="护行辽饷", tags=None, deadline=4):
    order_id = db.create_secret_order(
        state, _actor(db), title, "逐月办理", tags or ["护行"],
        deadline_months=deadline,
    )
    return order_id, int(db.get_dossier_for_secret_order(order_id)["id"])


def _settle(db, state, content, narrative="本月邸报", progress=None):
    from ming_sim.decree import settle_with_delta

    turn = state.turn
    extracted = {"dossier_progress_reports": [progress]} if progress else {}
    settle_with_delta(
        state, db, extracted, before_turn=turn, content=content, narrative=narrative,
    )
    return turn


def test_real_month_end_records_three_restoreable_reports_and_pushes_them(game):
    from ming_sim.db import GameDB

    db, state, content = game
    _order_id, dossier_id = _order(db, state)

    first_turn = _settle(db, state, content, progress={
        "dossier_id": dossier_id, "progress_band": "启程",
        "memorial_text": "首批出京，已对一处关防",
    })
    reopened = GameDB(db.path, content=content)
    db.close()
    db = reopened
    state = db.load_state()
    second_turn = _settle(db, state, content, progress={
        "dossier_id": dossier_id, "progress_band": "在途",
        "memorial_text": "据前月关防记录续报，已至山海关",
    })
    third_turn = _settle(db, state, content, progress={
        "dossier_id": dossier_id, "progress_band": "将达",
        "memorial_text": "据前两月记录续报，三批已会齐",
    })

    rows = db.list_dossier_progress(dossier_id)
    assert [row["turn"] for row in rows] == [first_turn, second_turn, third_turn]
    assert [row["progress_band"] for row in rows] == ["启程", "在途", "将达"]
    for row in rows:
        assert row["memorial_text"] not in db.get_turn_report(row["turn"])


def test_only_private_extractor_context_reads_canonical_history(game):
    from ming_sim.simulation import build_extractor_shared_context, build_simulator_payload

    db, state, content = game
    _order_id, dossier_id = _order(db, state, title="稽核漕账", tags=["稽核"])
    marker = "已核通州仓第一册566"
    _settle(db, state, content, progress={
        "dossier_id": dossier_id, "progress_band": "核账", "memorial_text": marker,
    })

    public = build_simulator_payload(state, db, "", "")
    private = build_extractor_shared_context(
        db, state, "", "", module="personnel_secret",
    )
    assert marker not in str(public)
    assert marker not in str(build_extractor_shared_context(db, state, "", "", module="issues"))
    pushed = next(item for item in private["monthly_dossier_reports"]
                  if item["dossier_id"] == dossier_id)
    assert pushed["progress"] == db.list_dossier_progress(dossier_id)


def test_titles_do_not_classify_long_orders_and_short_orders_do_not_report(game):
    db, state, content = game
    _, title_only = _order(db, state, title="保护堤岸", tags=["河工"])
    _, unrelated = _order(db, state, title="清查库藏", tags=["财政"])
    _, short = _order(db, state, tags=["护行"], deadline=1)

    _settle(db, state, content)
    assert db.list_dossier_progress(title_only) == []
    assert db.list_dossier_progress(unrelated) == []
    assert db.list_dossier_progress(short) == []


def test_only_an_existing_monthly_chain_gets_terminal_progress(game):
    db, state, content = game
    eligible_id, eligible = _order(db, state)
    ordinary_id, ordinary = _order(db, state, title="保护堤岸", tags=["河工"])
    _settle(db, state, content, progress={
        "dossier_id": eligible, "progress_band": "在途", "memorial_text": "已出京",
    })

    db.close_secret_order(eligible_id, "failed", "护行中止", state.turn)
    db.close_secret_order(ordinary_id, "failed", "河工中止", state.turn)

    assert db.list_dossier_progress(eligible)[-1]["is_terminal"] is True
    assert db.list_dossier_progress(ordinary) == []


def test_real_module_extractor_traces_private_context_through_settlement(game, monkeypatch):
    """Run the production four-agent extraction parser/merge before settlement."""
    import json
    import ming_sim.simulation as simulation
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    _, dossier_id = _order(db, state)
    context = simulation.build_extractor_shared_context(
        db, state, "本月邸报", "", module="personnel_secret",
    )
    assert context["monthly_dossier_reports"][0]["dossier_id"] == dossier_id

    def run_extractor(_agent, _prompt, tag):
        if tag == "extractor/personnel_secret":
            return json.dumps({
                "dossier_progress_reports": [{
                    "dossier_id": dossier_id,
                    "progress_band": "启程核验",
                    "memorial_text": "首批出京，已验关防",
                }],
                "metric_delta": {"民心": 99},
            }, ensure_ascii=False)
        return "{}"

    monkeypatch.setattr(simulation, "run_agent_text", run_extractor)
    agents = {module: object() for module in simulation.EXTRACTION_MODULES}
    extracted, _output, _input = simulation.extract_scores_by_modules_with_agno(
        agents, db, state, "本月邸报",
    )
    assert extracted["dossier_progress_reports"][0]["dossier_id"] == dossier_id
    assert extracted.get("metric_delta", {}) == {}
    settle_with_delta(
        state, db, extracted, before_turn=state.turn,
        content=content, narrative="本月邸报",
    )
    assert db.list_dossier_progress(dossier_id)[0]["memorial_text"] == "首批出京，已验关防"


def test_missing_bad_unknown_and_duplicate_reports_do_not_invent_progress(game):
    db, state, _content = game
    _, dossier_id = _order(db, state)
    assert db.record_monthly_dossier_progress(state.turn, None) == []
    assert db.record_monthly_dossier_progress(state.turn, {"dossier_id": dossier_id}) == []
    rows = db.record_monthly_dossier_progress(state.turn, [
        {"dossier_id": 999999, "progress_band": "伪", "memorial_text": "伪进展"},
        {"dossier_id": dossier_id, "progress_band": "", "memorial_text": "缺档"},
        {"dossier_id": dossier_id, "progress_band": "启程", "memorial_text": "首批出京"},
        {"dossier_id": dossier_id, "progress_band": "重复", "memorial_text": "不得覆盖"},
    ])
    assert len(rows) == 1
    assert db.list_dossier_progress(dossier_id)[0]["memorial_text"] == "首批出京"
