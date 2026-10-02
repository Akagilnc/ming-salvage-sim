"""Army cards omit private numeric/state fields without rewriting durable rows."""


def test_army_cards_are_read_only_projections(read_game):
    db, _state, _content = read_game
    before = [dict(row) for row in db.conn.execute("SELECT * FROM armies ORDER BY id")]

    cards = db.army_payload()

    assert {card["id"] for card in cards} == {row["id"] for row in before}
    for card in cards:
        assert {"status", "morale", "loyalty", "arrears"}.isdisjoint(card)
    after = [dict(row) for row in db.conn.execute("SELECT * FROM armies ORDER BY id")]
    assert after == before
