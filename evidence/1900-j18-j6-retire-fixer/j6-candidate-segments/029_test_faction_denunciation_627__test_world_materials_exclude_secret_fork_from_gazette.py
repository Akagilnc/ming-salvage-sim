def test_world_materials_exclude_secret_fork_from_gazette(game, tmp_path):
    import json
    from ming_sim.materials import prepare_world_materials, read_material

    db, state, content = game
    owner = next(iter(_chars_by_faction(db).values()))[0]["name"]
    public_id = _subject_dossier(db, state, owner=owner, token="public")
    from tests.dossier_test_helpers import create_test_secret_order
    order_id = create_test_secret_order(db, state, owner, "密查", "查账", [])
    secret_id = int(db.get_dossier_for_secret_order(order_id)["id"])
    db.conn.execute("UPDATE decree_dossiers SET status='executing' WHERE id=?", (secret_id,))
    db.conn.commit()
    _make_forked(db, state, public_id)
    _make_forked(db, state, secret_id)

    prepared = prepare_world_materials(
        db, state, dest_root=tmp_path / "gazette",
        exclude_secret_order_dossiers=True,
    )
    facts = json.loads(read_material(prepared.root, "盘面/派系检举事实.txt"))
    assert {item["dossier_id"] for item in facts["forked_dossiers"]} == {public_id}
