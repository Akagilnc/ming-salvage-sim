"""#14 调试盲区：db.py 的静默 `except Exception:` JSON 回退路。

契约（外部行为）：当某列存的 JSON 损坏时，回退行为保持原样
（默认回空 / 跳过该项），不抛、不崩。不锁 tlog／诊断信号。

覆盖的回退形状：
  - `list_pending_decisions`：options_json 损坏 → 回 []（默认回退）；choice_json 损坏 → 回 None（崩溃路修复）；
  - `legacy_modifiers`：损坏 → 跳过该 legacy（`continue` 变体）；
  - `get_resolve_context`：simulator_payload 等损坏 → 回退默认。
"""


def test_pending_decisions_corrupt_options_json_falls_back(game):
    db, _state, _content = game
    # 直接写一行损坏 options_json（非合法 JSON），绕过 save_pending_decisions 的 json.dumps。
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, '', 'pending')",
        (999, 0, "测试抉择", "", "{不是合法JSON"),
    )
    db.conn.commit()

    out = db.list_pending_decisions(999)

    # 行为保持：不抛，该项 options 回退空 list
    assert len(out) == 1
    assert out[0]["options"] == []


def test_pending_decisions_corrupt_choice_json_returns_none(game):
    db, _state, _content = game
    # 损坏 choice_json（options 合法）——修复前 result 构建处 `json.loads(choice)` 无保护会崩。
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (998, 0, "测试抉择", "", "[]", "{坏choice"),
    )
    db.conn.commit()

    out = db.list_pending_decisions(998)

    assert len(out) == 1
    assert out[0]["choice"] is None  # 行为：损坏 choice 回退 None，不再崩


def test_resolve_context_corrupt_payload_falls_back(game):
    db, _state, _content = game
    db.save_resolve_context(
        500, decree_text="旨", simulator_payload={"a": 1},
    )
    db.conn.execute(
        "UPDATE pending_resolve_context SET simulator_payload_json = ? WHERE turn = ?",
        ("{坏payload", 500),
    )
    db.conn.commit()

    ctx = db.get_resolve_context(500)

    assert ctx is not None
    assert ctx["simulator_payload"] == {}  # 行为：损坏回退默认 {}，不抛


def test_legacy_modifiers_corrupt_json_skips(game):
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

    mods = db.legacy_modifiers(state)

    # 行为保持：损坏的 legacy 被跳过，不抛，其 +10 贡献消失、国库回到基线
    assert mods.get("国库", 0) == baseline
