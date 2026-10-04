def test_restore_main_db_path_config_remove_failure_is_loud(monkeypatch, tmp_path):
    """#1749 / ADR 0005：active_db.txt 删除失败须上抛，禁静默改写成 env/default 另一身份。"""
    monkeypatch.setattr(web_app, "user_data_path", lambda *parts: str(tmp_path.joinpath(*parts)))
    active_file = web_app._active_db_path_file()
    with open(active_file, "w", encoding="utf-8") as f:
        f.write(str(tmp_path / "new.db"))
    monkeypatch.setenv("MING_SIM_DB", str(tmp_path / "new.db"))
    monkeypatch.setattr(
        web_app.os, "remove",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("locked")),
    )

    with pytest.raises(PermissionError, match="locked"):
        web_app._restore_main_db_path_config((False, "", False, ""))

    # 失败后不得把身份改写成默认 ming_sim.db
    with open(active_file, "r", encoding="utf-8") as f:
        assert f.read().strip() == str(tmp_path / "new.db")
