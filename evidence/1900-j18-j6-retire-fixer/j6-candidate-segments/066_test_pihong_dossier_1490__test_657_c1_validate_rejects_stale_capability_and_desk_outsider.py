def test_657_c1_validate_rejects_stale_capability_and_desk_outsider(game):
    """C1.5 stale capability；desk 外键整批拒。"""
    from ming_sim import rescript_actions as ra
    db, state, _content = game
    urgent, opts = _plant_urgent_desk(db, state)
    key = urgent['decision_key']
    with pytest.raises(ValueError):
        ra.validate_all([urgent], [{'decision_key': key, 'action': 'follow_draft', 'draft_capability': 'not-a-real-cap', 'label': opts[0]['label']}])
    with pytest.raises(ValueError):
        ra.validate_all([urgent], [{'decision_key': 'rescript_draft:999:0', 'action': 'hold', 'label': '留中'}])
