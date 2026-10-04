def test_seal_rejects_new_claim_after_lifecycle(web_game):
    """生命周期 seal 后新领票拒入（旧 _draining 语义）。"""
    game = web_game
    q = game._runtime_write_queue()
    q.seal()
    assert game._mark_pending_write() is None
    q.unseal()
    t = game._mark_pending_write()
    assert t is not None
    game._complete_pending_write(t)
