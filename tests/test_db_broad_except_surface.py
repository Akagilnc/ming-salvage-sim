"""#14 调试盲区：db.py 的静默 `except Exception:` JSON 回退路加 tlog 留痕。

契约（行为不变 + 可观测）：当某列存的 JSON 损坏时——
  1) 回退行为保持原样（默认回空 / 跳过该项），不抛、不崩；
  2) **同时** 经 tlog 响亮留痕（不再静默吞，给调试一条线索）。

覆盖的回退形状：
  - `list_pending_decisions`：options_json 损坏 → 回 []（默认回退）；choice_json 损坏 → 回 None（崩溃路修复）；
  - `legacy_modifiers`：损坏 → 跳过该 legacy（`continue` 变体）；
  - `get_relevant_event_memories` / `get_memories_by_keywords`：tags 损坏 → result 回退 []（崩溃路修复）；
  - `get_resolve_context`：simulator_payload 等损坏 → 回退默认；extracted_delta 损坏（ready=1）→ 回 None 逼重抽。
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


def test_pending_decisions_corrupt_choice_json_returns_none_and_surfaces(game, monkeypatch):
    db, _state, _content = game
    # 损坏 choice_json（options 合法）——修复前 result 构建处 `json.loads(choice)` 无保护会崩。
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (998, 0, "测试抉择", "", "[]", "{坏choice"),
    )
    db.conn.commit()

    msgs = _capture_tlog(monkeypatch)
    out = db.list_pending_decisions(998)

    assert len(out) == 1
    assert out[0]["choice"] is None  # 行为：损坏 choice 回退 None，不再崩
    assert any("choice_json 损坏" in m for m in msgs), msgs


def test_resolve_context_corrupt_payload_falls_back_and_surfaces(game, monkeypatch):
    db, _state, _content = game
    db.save_resolve_context(
        500, decree_text="旨", narrative="报",
        simulator_payload={"a": 1}, secret_orders={"在办": []}, relevant_memories=[],
    )
    db.conn.execute(
        "UPDATE pending_resolve_context SET simulator_payload_json = ? WHERE turn = ?",
        ("{坏payload", 500),
    )
    db.conn.commit()

    msgs = _capture_tlog(monkeypatch)
    ctx = db.get_resolve_context(500)

    assert ctx is not None
    assert ctx["simulator_payload"] == {}  # 行为：损坏回退默认 {}，不抛
    assert any("simulator_payload JSON 损坏" in m for m in msgs), msgs


def test_resolve_context_corrupt_extracted_returns_none_and_surfaces(game, monkeypatch):
    db, _state, _content = game
    # 显式传 extracted（非 None）→ ready=1，get 时 extracted 可见路径。
    db.save_resolve_context(
        501, decree_text="旨", narrative="报",
        simulator_payload={}, extracted={"国库": 1},
    )
    db.conn.execute(
        "UPDATE pending_resolve_context SET extracted_delta_json = ? WHERE turn = ?",
        ("{坏delta", 501),
    )
    db.conn.commit()

    msgs = _capture_tlog(monkeypatch)
    ctx = db.get_resolve_context(501)

    assert ctx is not None
    assert ctx["extracted"] is None  # 行为：ready=1 但损坏 → 回 None 逼重抽（cmr r4 设计）
    assert any("extracted_delta JSON 损坏" in m for m in msgs), msgs


def _insert_corrupt_tags_memory(db, *, subject_type, subject_id, turn, tags_raw, suffix):
    """插一条 tags 列为损坏 JSON 的 event_memory（绕过正常写入的 json.dumps）。"""
    db.conn.execute(
        "INSERT INTO event_memories "
        "(subject_type, subject_id, turn, year, period, event_type, title, "
        " importance, tags, source_kind, source_id) "
        "VALUES (?, ?, ?, 1, 1, 'test', '损坏标签事件', 5, ?, 'test', ?)",
        (subject_type, subject_id, turn, tags_raw, suffix),
    )
    db.conn.commit()


def test_relevant_memories_corrupt_tags_no_crash_and_surfaces(game, monkeypatch):
    db, _state, _content = game
    # 损坏 tags 的 character 行——经 subject_id 精确匹配被选中，importance=5 过滤存活。
    db.conn.execute("DELETE FROM event_memories")  # 清空，确保被测行入 result[:limit]
    db.conn.commit()
    _insert_corrupt_tags_memory(
        db, subject_type="character", subject_id="测试人物甲",
        turn=10, tags_raw="[坏掉的tags", suffix="r1",
    )

    msgs = _capture_tlog(monkeypatch)
    # 修复前：result 构建循环二次 json.loads 损坏 tags → 抛异常崩库。
    out = db.get_relevant_event_memories("测试人物甲", "", "", turn=12, ignore_expiry=True)

    assert len(out) == 1
    assert out[0]["tags"] == []  # 行为：损坏 tags 回退空 list，不再崩
    assert any("tags JSON 损坏" in m for m in msgs), msgs


def test_keyword_memories_corrupt_tags_no_crash_and_surfaces(game, monkeypatch):
    db, _state, _content = game
    db.conn.execute("DELETE FROM event_memories")
    db.conn.commit()
    # tags 原文含锚词「搜索锚」供 SQL `tags LIKE` 命中，但整体非合法 JSON。
    _insert_corrupt_tags_memory(
        db, subject_type="court", subject_id="x",
        turn=10, tags_raw='["搜索锚" 坏JSON', suffix="r2",
    )

    msgs = _capture_tlog(monkeypatch)
    out = db.get_memories_by_keywords(["搜索锚"], turn=12, ignore_expiry=True)

    assert len(out) == 1
    assert out[0]["tags"] == []  # 行为：损坏 tags 回退空 list，不再崩
    assert any("tags JSON 损坏" in m for m in msgs), msgs


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
