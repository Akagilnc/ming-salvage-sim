"""Active attendant identification used by session and audience-night flows."""

from dataclasses import replace

from ming_sim.mindreading import is_inner_court_attendant


def test_attendant_is_selected_by_office_not_name(game):
    _db, _state, content = game
    attendant = content.characters["王承恩"]
    assert is_inner_court_attendant(attendant)
    assert is_inner_court_attendant(
        replace(attendant, name="随驾新内官", aliases=[])
    )
    assert is_inner_court_attendant(
        replace(attendant, name="御前近臣", office="御前近臣", office_type="待铨")
    )
    minister = next(c for c in content.characters.values() if c.office_type == "礼部")
    assert not is_inner_court_attendant(minister)


def test_only_exact_attendant_slots_are_identified(game):
    _db, _state, content = game
    for name in ("王体乾", "曹化淳", "高起潜"):
        assert not is_inner_court_attendant(content.characters[name])
    candidate = replace(
        content.characters["王承恩"], office="御前近臣候补", office_type="司礼监"
    )
    assert not is_inner_court_attendant(candidate)
