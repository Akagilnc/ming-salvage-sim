def test_empty_startup_catchup_claims_zero_tickets(web_game):
    """#1353 r7：无待补时 startup catch-up 不领票——禁 residual pending 竞态。"""
    game = web_game
    q = game._runtime_write_queue()
    # fresh WebGame 无未抽回话；init 时 spawn 必须早退，队列空。
    assert q.inflight_count() == 0
    assert int(game._pending_writes_count) == 0
    # 显式再调仍不领票。
    game._spawn_startup_extraction_catch_up()
    assert q.inflight_count() == 0
