"""#566: long secret-order dossiers keep one durable monthly report rail."""

def _actor(db):
    return str(db.conn.execute(
        "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
    ).fetchone()["name"])


def test_long_protection_order_records_three_restoreable_monthly_reports(game):
    from ming_sim.db import GameDB

    db, state, content = game
    order_id = db.create_secret_order(
        state, _actor(db), "护行辽饷", "护送三批辽饷并逐路对账", ["护行"],
        deadline_months=4,
    )
    dossier_id = db.get_dossier_for_secret_order(order_id)["id"]
    expected = []
    for turn, band, text in (
        (state.turn, "启程", "首批出京，已对一处关防"),
        (state.turn + 1, "在途", "行至山海关，累计对账两次"),
        (state.turn + 2, "将达", "三批会齐，累计对账三次"),
    ):
        db.record_dossier_progress(dossier_id, turn, band, text)
        expected.append((turn, band, text))

    reopened = GameDB(db.path, content=content)
    try:
        rows = reopened.list_dossier_progress(dossier_id)
        assert [(r["turn"], r["progress_band"], r["memorial_text"]) for r in rows] == expected
    finally:
        reopened.close()


def test_monthly_push_and_pull_read_the_same_progress_rows(game):
    db, state, _content = game
    order_id = db.create_secret_order(
        state, _actor(db), "稽核漕账", "逐仓稽核漕粮账册", ["稽核"],
        deadline_months=3,
    )
    dossier_id = db.get_dossier_for_secret_order(order_id)["id"]
    db.record_dossier_progress(dossier_id, state.turn, "核账", "已核通州仓第一册")

    pull_rows = db.list_dossier_progress(dossier_id)
    pushed = next(
        row for row in db.list_monthly_dossier_progress_nudges()
        if row["dossier_id"] == dossier_id
    )

    assert pushed["progress"] == pull_rows


def test_short_secret_order_is_not_forced_into_monthly_reporting(game):
    db, state, _content = game
    order_id = db.create_secret_order(
        state, _actor(db), "传取密函", "即刻传取密函", ["传令"], deadline_months=1,
    )
    dossier_id = db.get_dossier_for_secret_order(order_id)["id"]

    assert dossier_id not in {
        row["dossier_id"] for row in db.list_monthly_dossier_progress_nudges()
    }


def test_abnormal_close_appends_terminal_progress_in_same_transaction(game):
    db, state, _content = game
    order_id = db.create_secret_order(
        state, _actor(db), "护行辽饷", "护送辽饷", ["护行"], deadline_months=4,
    )
    dossier_id = db.get_dossier_for_secret_order(order_id)["id"]
    db.record_dossier_progress(dossier_id, state.turn, "在途", "已出京")

    db.close_secret_order(order_id, "failed", "承办人身故，护行中止", state.turn + 1)

    rows = db.list_dossier_progress(dossier_id)
    assert rows[-1]["is_terminal"] is True
    assert rows[-1]["memorial_text"] == "承办人身故，护行中止"
    assert db.get_decree_dossier(dossier_id)["status"] == "closed"
