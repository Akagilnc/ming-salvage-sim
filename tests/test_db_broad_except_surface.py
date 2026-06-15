"""#14 调试盲区：db.py 的静默 `except Exception:` JSON 回退路加 tlog 留痕。

契约（行为不变 + 可观测）：当某列存的 JSON 损坏时——
  1) 回退行为保持原样（默认回空 / 跳过该项），不抛、不崩；
  2) **同时** 经 tlog 响亮留痕（不再静默吞，给调试一条线索）。

挑两种回退形状各测一站：
  - `list_pending_decisions`：损坏 → 该项 options 回 []（默认回退变体）；
  - `legacy_modifiers`：损坏 → 跳过该 legacy（`continue` 变体）。
"""

import ming_sim.db as db_mod


def _capture_tlog(monkeypatch):
    """把 db 模块级 tlog 换成捕获器，返回收集到的消息 list。"""
    msgs: list[str] = []
    monkeypatch.setattr(db_mod, "tlog", lambda m: msgs.append(m))
    return msgs


def test_pending_decisions_corrupt_options_json_falls_back_and_surfaces(game, monkeypatch):
    db, _state, _content = game
    # 直接写一行损坏 options_json（非合法 JSON），绕过 save_pending_decisions 的 json.dumps。
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, '', 'pending')",
        (999, 0, "测试抉择", "", "{不是合法JSON"),
    )
    db.conn.commit()

    msgs = _capture_tlog(monkeypatch)
    out = db.list_pending_decisions(999)

    # 行为保持：不抛，该项 options 回退空 list
    assert len(out) == 1
    assert out[0]["options"] == []
    # 可观测：tlog 留痕，且点名是 options_json 损坏
    assert any("options_json 损坏" in m for m in msgs), msgs


def test_legacy_modifiers_corrupt_json_skips_and_surfaces(game, monkeypatch):
    db, state, _content = game
    # 种子档可能已有 active legacy（国库基线非 0），故测 delta：以「插入贡献 +10 →
    # 损坏后贡献归零、回到基线」证明损坏项被跳过，而非比绝对值。
    baseline = db.legacy_modifiers(state).get("国库", 0)

    lid = db.insert_legacy(state, name="测试遗产", modifiers={"国库": 10})
    db._legacy_mod_cache = None
    assert db.legacy_modifiers(state).get("国库", 0) == baseline + 10  # sanity：合法时确实计入

    # 就地把 modifiers 列改成损坏 JSON
    db.conn.execute("UPDATE legacies SET modifiers = ? WHERE id = ?", ("{坏掉的JSON", lid))
    db.conn.commit()
    db._legacy_mod_cache = None  # active 集没变，但内容改了，手动失效缓存

    msgs = _capture_tlog(monkeypatch)
    mods = db.legacy_modifiers(state)

    # 行为保持：损坏的 legacy 被跳过，不抛，其 +10 贡献消失、国库回到基线
    assert mods.get("国库", 0) == baseline
    # 可观测：tlog 留痕，且点名是 legacy modifiers 损坏
    assert any("legacy modifiers JSON 损坏" in m for m in msgs), msgs
