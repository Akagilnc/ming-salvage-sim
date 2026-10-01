"""持久 JSON 损坏必须拒绝读取，不许回空后继续消费。

覆盖：
  - `list_pending_decisions`：options_json / choice_json 损坏即拒；
  - `legacy_modifiers`：modifiers 损坏即拒；
  - 恢复上下文：损坏即拒绝恢复。
"""

import pytest

import ming_sim.db as db_mod

def _capture_tlog(monkeypatch):
    """把 db 模块级 tlog 换成捕获器，返回收集到的消息 list。"""
    msgs: list[str] = []
    monkeypatch.setattr(db_mod, "tlog", lambda m: msgs.append(m))
    return msgs

def test_pending_decisions_corrupt_options_json_refuses(game):
    db, _state, _content = game
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, '', 'pending')",
        (999, 0, "测试抉择", "", "{不是合法JSON"),
    )
    db.conn.commit()

    with pytest.raises(ValueError, match="options_json"):
        db.list_pending_decisions(999)

def test_pending_decisions_corrupt_choice_json_refuses(game):
    db, _state, _content = game
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (998, 0, "测试抉择", "", "[]", "{坏choice"),
    )
    db.conn.commit()

    with pytest.raises(ValueError, match="choice_json"):
        db.list_pending_decisions(998)

def test_resolve_context_corrupt_payload_refuses_restore(game, monkeypatch):
    """恢复材料读不出来就必须拒绝恢复，不许回退空对象继续（#1889 / 失败诚实宪法）。

    原实现打印 WARN 后返回 ``simulator_payload={}`` —— 把「记录已损」伪装成
    「本月没有过月上下文」照常恢复，玩家看不出恢复丢了整段事实。
    """
    db, _state, _content = game
    db.save_resolve_context(
        500, decree_text="旨", simulator_payload={"a": 1},
    )
    db.conn.execute(
        "UPDATE pending_resolve_context SET simulator_payload_json = ? WHERE turn = ?",
        ("{坏payload", 500),
    )
    db.conn.commit()

    _capture_tlog(monkeypatch)
    with pytest.raises(ValueError, match="simulator_payload"):
        db.resolve_contexts.get(500)


def test_legacy_modifiers_corrupt_json_refuses(game):
    db, state, _content = game
    baseline = db.legacy_modifiers(state).get("国库", 0)

    lid = db.insert_legacy(state, name="测试遗产", modifiers={"国库": 10})
    db._legacy_mod_cache = None
    assert db.legacy_modifiers(state).get("国库", 0) == baseline + 10

    db.conn.execute("UPDATE legacies SET modifiers = ? WHERE id = ?", ("{坏掉的JSON", lid))
    db.conn.commit()
    db._legacy_mod_cache = None

    with pytest.raises(ValueError, match="modifiers"):
        db.legacy_modifiers(state)
