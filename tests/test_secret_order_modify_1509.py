"""#1509 online findings：密令「修改」确认缝——点名/保字段/P5 无二调/非密令不吞/去前缀。

r2：目标编号取自同次 confirmation 结构化 JSON stub，不从消息字面机械解析。
r3：真实 chat 编排路（preclassification → apply）须保留同次 target_ids。
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("no active minister")


def _sess(db, state):
    return types.SimpleNamespace(
        db=db, state=state,
        llm_config=types.SimpleNamespace(channel="cli"),
        registry=None, content=None,
    )


def test_modify_target_from_stub_id_not_message_literal(game, monkeypatch):
    """#1509 r2：目标取自 confirmation stub 编号，而非消息字面「第二道」/title。

    消息写「修改第二道」且含第二道 title 线索；stub 却返回第一道 id → 只改第一道。
    若仍走消息机械解析会误改第二道，本测必红。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁"], "deadline_months": 3,
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
        },
    )
    assert id1 != id2

    captured_prompts: list = []

    def _stub_backend(prompt, llm_config=None, tag=""):
        captured_prompts.append((tag, prompt))
        # 故意与消息字面「第二道」「暗结蒙古」相反：点名第一道
        return (
            json.dumps(
                {"确认": "修改", "目标编号": [id1], "新内容": "暗结蒙古那道改成只查饷银去向"},
                ensure_ascii=False,
            ),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", _stub_backend)
    monkeypatch.setattr(
        cb, "_extract_secret_order",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("P5: 修改不得二次串行 _extract_secret_order"),
        ),
    )

    out = GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        # 字面「第二道」+ 第二道 title——旧机械 resolver 会选 id2
        player_message="修改第二道：暗结蒙古那道改成只查饷银去向",
        answer="臣遵旨改。",
        has_directive=False, secret_order_id=None,
    )
    assert "directive_confirmation_ambiguous" not in out

    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    # stub 点名 id1 → 第一道改、第二道不动（反证非消息字面）
    # 去前缀后材料：_strip 吃掉「修改第二道：」
    assert p1["content"] == "暗结蒙古那道改成只查饷银去向"
    assert p2["content"] == "暗结蒙古诸部"
    assert p2["title"] == "暗结蒙古"
    # confirmation 列表须带方括号 id，供 stub/LLM 合法编号校验
    assert captured_prompts and captured_prompts[0][0] == "confirmation"
    prompt = captured_prompts[0][1]
    assert f"[{id1}]" in prompt and f"[{id2}]" in prompt


def test_modify_does_not_claim_success_when_row_left_pending(game, monkeypatch):
    """#1509：UPDATE 窗口间行已离开 pending → 不得虚报已修改。

    模拟读后写前 status 被并发改走：WHERE status='pending' 命中 0 行时，
    响应不得带 pending_action_id，库内 payload 保持原样。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    pid = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁"], "deadline_months": 3,
        },
    )
    original = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,),
    ).fetchone()[0]

    real_execute = db.conn.execute

    def _race_then_update(sql, params=None):
        sql_s = str(sql)
        if (
            "UPDATE pending_actions SET payload_json" in sql_s
            and "status='pending'" in sql_s
        ):
            # 同调用读写窗口：UPDATE 前把行踢出 pending
            real_execute(
                "UPDATE pending_actions SET status='held_over' WHERE id=?",
                (int(params[1]),),
            )
        return real_execute(sql, params) if params is not None else real_execute(sql)

    monkeypatch.setattr(db.conn, "execute", _race_then_update)
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (
            json.dumps({"确认": "修改", "新内容": "只查饷银去向"}, ensure_ascii=False), 1,
        ),
    )
    monkeypatch.setattr(
        cb, "_extract_secret_order",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("P5: 修改不得二次串行 _extract_secret_order"),
        ),
    )

    out = GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改：只查饷银去向，不查动向",
        answer="臣遵旨改。",
        has_directive=False, secret_order_id=None,
    )
    # 库未接受 → 不得声称修改成功
    assert not out.get("pending_action_id"), out
    row = db.conn.execute(
        "SELECT payload_json, status FROM pending_actions WHERE id=?", (pid,),
    ).fetchone()
    assert row[0] == original
    assert row[1] == "held_over"
    # 确认族仍提前返回，不落新建
    assert "directive_confirmation_ambiguous" not in out


def test_modify_multi_without_target_id_is_ambiguous(game, monkeypatch):
    """多候选 + 修改但无合法目标编号 → ambiguity，两道都不改。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁"], "deadline_months": 3,
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
        },
    )
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (json.dumps({"确认": "修改", "目标编号": []}, ensure_ascii=False), 1),
    )
    out = GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改：都改成只查饷银",
        answer="臣请皇上明示改哪一道。",
        has_directive=False, secret_order_id=None,
    )
    amb = out.get("directive_confirmation_ambiguous") or {}
    cands = {int(c["id"]) for c in (amb.get("candidates") or [])}
    assert cands == {id1, id2}
    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    assert p1["content"] == "密察关宁欠饷"
    assert p2["content"] == "暗结蒙古诸部"


def test_modify_multi_named_targets_is_ambiguous_no_batch_overwrite(game, monkeypatch):
    """#1509-F1：多候选 + 修改点名多个合法编号 → ambiguous，禁止整族覆写。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁"], "deadline_months": 3,
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
        },
    )
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (
            json.dumps({"确认": "修改", "目标编号": [id1, id2]}, ensure_ascii=False), 1,
        ),
    )
    out = GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改：两道都改成只查饷银",
        answer="臣请皇上明示改哪一道。",
        has_directive=False, secret_order_id=None,
    )
    amb = out.get("directive_confirmation_ambiguous") or {}
    cands = {int(c["id"]) for c in (amb.get("candidates") or [])}
    assert cands == {id1, id2}, amb
    assert "pending_action_id" not in out
    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    assert p1["content"] == "密察关宁欠饷"
    assert p2["content"] == "暗结蒙古诸部"


def test_modify_preserves_fields_targets_one_no_second_extract(game, monkeypatch):
    """F1 点名第二道 / F2 保留未提及字段 / F3 P5 无二次 extract / F5 去前缀正文。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁", "欠饷"], "deadline_months": 3,
            "excluded_names": ["魏忠贤"], "excluded_offices": ["内阁"],
            "dossier_links": [{"target_dossier_id": 1, "relation_type": "稽核"}],
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
            "excluded_names": [], "excluded_offices": [], "dossier_links": [],
        },
    )

    extract_calls: list = []

    def _boom(*_a, **_k):
        extract_calls.append(1)
        raise AssertionError("P5: 修改不得二次串行 _extract_secret_order")

    monkeypatch.setattr(cb, "_extract_secret_order", _boom)
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        # 目标编号显式点名 id2（不靠消息「第二道」）
        lambda *a, **k: (
            json.dumps(
                {"确认": "修改", "目标编号": [id2], "新内容": "只查饷银去向，不查动向"},
                ensure_ascii=False,
            ),
            1,
        ),
    )

    GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改第二道：只查饷银去向，不查动向",
        answer="臣遵旨改。",
        has_directive=False, secret_order_id=None,
    )
    assert extract_calls == []

    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    # F1：未点名的第一道不动
    assert p1["content"] == "密察关宁欠饷"
    assert p1["tags"] == ["关宁", "欠饷"]
    assert p1["deadline_months"] == 3
    assert p1["excluded_names"] == ["魏忠贤"]
    assert p1["dossier_links"]
    # F2+F5：第二道正文去前缀更新；未提及 tags/deadline 保留
    assert p2["content"] == "只查饷银去向，不查动向"
    assert "修改" not in p2["content"]
    assert p2["tags"] == ["蒙古"]
    assert p2["deadline_months"] == 2
    assert p2["title"] == "暗结蒙古"


def test_modify_empty_typed_body_keeps_candidate_and_reports_no_success(game, monkeypatch):
    """空正文 fail-closed：候选原样保留，且不回填 pending_action_id。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    pending_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={"title": "密察关宁", "content": "原正文", "assignee": name},
    )
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (
            json.dumps({"确认": "修改", "目标编号": [pending_id], "新内容": ""}), 1,
        ),
    )

    out = GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch, player_message="修改", answer="臣候旨。",
        has_directive=False, secret_order_id=None,
    )
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()[0])
    assert payload["content"] == "原正文"
    assert "pending_action_id" not in out
    assert out["directive_confirmation_ambiguous"]["candidates"][0]["id"] == pending_id


def test_non_secret_modify_does_not_swallow_directive(game, monkeypatch):
    """F4：仅有 directive 时「修改」不得提前吞掉；候选仍在。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    did = db.upsert_pending_directive(
        state.turn, name,
        payload={
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "test-policy",
            "text": "草案：着户部清查三边粮饷。",
            "actor": name,
        },
    )
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (json.dumps({"确认": "修改"}, ensure_ascii=False), 1),
    )
    GameSession.apply_cli_conversation_actions(
        _sess(db, state), ch,
        player_message="修改：把清查改成三月完报",
        answer="臣记下了。",
        has_directive=False, secret_order_id=None,
    )
    pend = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pend) == 1
    assert int(pend[0]["id"]) == did


def test_action_classifier_schema_carries_modify_contract():
    """并行 preclassifier 的登记 schema 包含修改枚举、正文与 typed 唯一目标。"""
    from ming_sim.action_clusters import classifier_json_fields_prompt

    schema, _ = json.JSONDecoder().raw_decode(classifier_json_fields_prompt())
    assert "修改" in schema["确认"]
    assert "新内容" in schema
    assert "目标编号" in schema


def test_extract_confirmation_intent_returns_target_ids(monkeypatch):
    """confirmation JSON 契约：确认枚举 + 合法目标编号（非法 id 丢弃）。"""
    def _semantic(prompt, llm_config=None, tag=""):
        assert tag == "confirmation"
        assert "[42]" in prompt and "[99]" in prompt
        return (
            json.dumps(
                {"确认": "修改", "目标编号": [42, 7, "99"]},
                ensure_ascii=False,
            ),
            1,
        )

    monkeypatch.setattr(cb, "_run_json_extractor_for_config", _semantic)
    result = cb.extract_confirmation_intent(
        player_message="修改第二道：只查饷银",
        minister_reply="臣候旨。",
        pending_summaries=["[42] 新建密令：密察关宁", "[99] 新建密令：暗结蒙古"],
        llm_config=types.SimpleNamespace(channel="api"),
    )
    assert result["confirmation"] == "修改"
    # 7 不在合法集合；42/99 保留
    assert result["target_ids"] == [42, 99]


def _chat_shell(db, state, content, *, channel="cli"):
    """轻量 GameSession.chat 壳：走真实 preclassification/chat 接缝。"""

    class Agent:
        def run(self, _message):
            return SimpleNamespace(content="臣遵旨改。", tools=[])

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

        def refresh(self, _name):
            return None

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = Registry()
    sess.llm_config = SimpleNamespace(channel=channel)
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message, *a, **k: message
    # 分类器未跑：强制走 _confirmation_intent_for_preexisting_pending 真缝
    sess._start_cli_action_intent = lambda *_a, **_k: None
    sess._finish_cli_action_intent = lambda *_a, **_k: None
    return sess


def _stage_two_secret_pending(db, state, name):
    id1 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "密察关宁", "content": "密察关宁欠饷", "assignee": name,
            "tags": ["关宁"], "deadline_months": 3,
        },
    )
    id2 = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name,
        target_id=None,
        payload={
            "title": "暗结蒙古", "content": "暗结蒙古诸部", "assignee": name,
            "tags": ["蒙古"], "deadline_months": 2,
        },
    )
    return id1, id2


def test_chat_path_modify_uses_stub_id_not_message_literal(game, monkeypatch):
    """#1509 r3 反证：真实 chat 路，消息写『第二道』、判词返 id1 → 只改 id1。

    覆盖 preclassification 丢 _named 的真病：若 target_ids 未过缝，
    intent 非 None 分支 confirm_named_ids 空 → 必落 ambiguity、两道都不改。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    id1, id2 = _stage_two_secret_pending(db, state, name)
    assert id1 != id2

    confirm_calls: list = []

    def _stub_backend(prompt, llm_config=None, tag=""):
        confirm_calls.append(tag)
        # 故意与消息字面「第二道」相反：点名第一道
        return (
            json.dumps(
                {"确认": "修改", "目标编号": [id1], "新内容": "暗结蒙古那道改成只查饷银去向"},
                ensure_ascii=False,
            ),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", _stub_backend)
    monkeypatch.setattr(
        cb, "_extract_secret_order",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("P5: 修改不得二次串行 _extract_secret_order"),
        ),
    )

    sess = _chat_shell(db, state, content)
    # 字面『第二道』+ 第二道 title——旧机械 resolver / 丢编号缝都会错
    GameSession.chat(sess, name, "修改第二道：暗结蒙古那道改成只查饷银去向")

    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    assert p1["content"] == "暗结蒙古那道改成只查饷银去向"
    assert p2["content"] == "暗结蒙古诸部"
    assert p2["title"] == "暗结蒙古"
    # 只许同次 confirmation 一次；禁第二次 LLM
    assert confirm_calls.count("confirmation") == 1
    assert all(t == "confirmation" for t in confirm_calls)


def test_chat_path_modify_without_target_id_is_ambiguous(game, monkeypatch):
    """#1509 r3：真实 chat 路，多候选修改无合法编号 → 含糊，两道都不改。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    id1, id2 = _stage_two_secret_pending(db, state, name)

    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: (
            json.dumps({"确认": "修改", "目标编号": []}, ensure_ascii=False), 1,
        ),
    )
    monkeypatch.setattr(
        cb, "_extract_secret_order",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("P5: 含糊修改不得二次 _extract_secret_order"),
        ),
    )

    sess = _chat_shell(db, state, content)
    result = GameSession.chat(sess, name, "修改：都改成只查饷银")

    amb = getattr(result, "directive_confirmation_ambiguous", None) or {}
    # chat 结果字段名可能在 result 上，也可能只反映 DB 未改
    p1 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id1,),
        ).fetchone()[0]
    )
    p2 = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (id2,),
        ).fetchone()[0]
    )
    assert p1["content"] == "密察关宁欠饷"
    assert p2["content"] == "暗结蒙古诸部"
    # 若 result 透出 ambiguous，编号集合须覆盖两道
    if amb:
        cands = {int(c["id"]) for c in (amb.get("candidates") or [])}
        assert cands == {id1, id2}
