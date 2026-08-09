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


def _settle(db, state, content, narrative="本月邸报"):
    from ming_sim.decree import settle_with_delta

    turn = state.turn
    settle_with_delta(
        state, db, {}, before_turn=turn, content=content, narrative=narrative,
    )
    return turn


def test_real_month_end_records_three_restoreable_reports_and_pushes_them(game):
    from ming_sim.db import GameDB

    db, state, content = game
    _order_id, dossier_id = _order(db, state)

    first_turn = _settle(db, state, content)
    reopened = GameDB(db.path, content=content)
    db.close()
    db = reopened
    state = db.load_state()
    second_turn = _settle(db, state, content)
    third_turn = _settle(db, state, content)

    rows = db.list_dossier_progress(dossier_id)
    assert [row["turn"] for row in rows] == [first_turn, second_turn, third_turn]
    assert [row["progress_band"] for row in rows] == [
        "第1月在办", "第2月在办", "第3月在办",
    ]
    for row in rows:
        assert row["memorial_text"] in db.get_turn_report(row["turn"])


def test_simulator_push_and_inquiry_pull_share_canonical_history(game):
    from ming_sim.simulation import build_simulator_payload

    db, state, content = game
    _order_id, dossier_id = _order(db, state, title="稽核漕账", tags=["稽核"])
    _settle(db, state, content)

    pushed = next(item for item in build_simulator_payload(state, db, "", "")[
        "dossier_progress_nudge"
    ] if item["dossier_id"] == dossier_id)
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
    _settle(db, state, content)

    db.close_secret_order(eligible_id, "failed", "护行中止", state.turn)
    db.close_secret_order(ordinary_id, "failed", "河工中止", state.turn)

    assert db.list_dossier_progress(eligible)[-1]["is_terminal"] is True
    assert db.list_dossier_progress(ordinary) == []
