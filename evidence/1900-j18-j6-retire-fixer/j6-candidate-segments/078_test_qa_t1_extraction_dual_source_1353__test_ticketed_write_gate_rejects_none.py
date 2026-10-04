def test_ticketed_write_gate_rejects_none(web_game):
    """无票不得回落裸 runtime write_gate。"""
    game = web_game
    with pytest.raises(RuntimeError):
        game._ticketed_write_gate(None)  # type: ignore[arg-type]
