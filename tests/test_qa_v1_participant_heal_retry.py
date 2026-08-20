"""#1274 QA V-1 拟诏参与人自愈重试（owner 2026-08-20）。

finding：抽取产出参与人不在名册 → 整单 409 怼玩家。
owner：系统和 LLM 之间的对话，关玩家什么事；能重试解决的错不许丢给玩家。

钉：
1. 毕自→纠错重试→毕自严落库
2. 真不在册人名→LLM 除名后草案照落
3. 重试上界（有界 1-2 次）
4. happy path 调用计数不变（P5）
5. LLM 挂死仍报错（不吞进参与人 409）
capture + 召对两路。
"""

from __future__ import annotations

import json
import types

import pytest

from ming_sim.session import GameSession

_ROSTER_BLOCK_HEADER = "【在册人物规范名+别名】"
_CORRECTION_MARK = "名册无此人"


def _biziyan(content):
    ch = content.characters.get("毕自严")
    assert ch is not None, "夹具名册须含毕自严"
    return ch


def _fake_session(db, state, content):
    sess = GameSession.__new__(GameSession)
    sess.db, sess.state = db, state
    sess.content = content
    sess.registry = sess.agno_db = None
    sess.llm_config = types.SimpleNamespace(channel="cli", cli_runner="codex")
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    sess.temporary_characters = set()
    return sess


def _active_minister(db, content, *, exclude="毕自严"):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )


def _ok_payload(*, person: str | None = "毕自严"):
    roster = []
    if person is not None:
        roster = [{"character_id": person, "tier": "主办", "role": "核辽饷"}]
    return {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "liao-pay",
        "正文": "着毕自严核拨辽饷，不得加派于民。",
        "参与人": roster,
    }


# ── capture 路 ──────────────────────────────────────────────────────


def test_capture_truncation_bi_zi_heals_to_biziyan(game, monkeypatch):
    """毕自→纠错重试→毕自严落库；纠错 prompt 含无效名+名册事实+正向指令。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    _biziyan(content)
    text = "着毕自严核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, **_k):
        calls.append(prompt)
        if len(calls) == 1:
            person = "毕自"
        else:
            # 纠错路上须见无效名 + 正向指令 + 名册事实
            assert _CORRECTION_MARK in prompt
            assert "毕自" in prompt
            assert _ROSTER_BLOCK_HEADER in prompt or "毕自严" in prompt
            assert "改正" in prompt or "除去" in prompt
            person = "毕自严"
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
    assert len(calls) == 2  # 首抽失败 + 1 次纠错

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_unknown_person_removed_on_retry_lands_draft(game, monkeypatch):
    """真不在册人名→LLM 除名后草案照落（不 409）。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    text = "着核清太仓，边饷优先"
    calls: list[str] = []

    def backend(prompt, *_a, **_k):
        calls.append(prompt)
        if len(calls) == 1:
            person = "不存在之人甲"
        else:
            assert _CORRECTION_MARK in prompt
            assert "不存在之人甲" in prompt
            person = None  # 除名
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    roster = payload.get("participant_roster") or []
    assert all(
        str(i.get("character_id") or "") != "不存在之人甲" for i in roster
    )
    # 草案结构仍在（非 special_decree 空降）
    assert payload.get("dossier_action_type") == "policy"
    assert payload.get("target_id") == "liao-pay"

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0
    assert len(calls) == 2


def test_capture_heal_retry_bounded(game, monkeypatch):
    """重试上界：持续吐无效名 → 有界次后仍走错误兜底（人话），调用次数=1+上界。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着毕自严核拨辽饷"
    calls: list[str] = []
    max_retries = int(cli_backend.DRAFT_PARTICIPANT_HEAL_RETRIES)

    def backend(prompt, *_a, **_k):
        calls.append(prompt)
        return (json.dumps(_ok_payload(person="毕自"), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError, match=r"参与人物|名册|大臣"):
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    assert len(calls) == 1 + max_retries
    assert 1 <= max_retries <= 2
    # 纠错指令进了重试 prompt
    assert any(_CORRECTION_MARK in p for p in calls[1:])


def test_capture_happy_path_single_llm_call(game, monkeypatch):
    """happy path 零额外调用（P5：重试只在失败路）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    _biziyan(content)
    text = "着毕自严核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, **_k):
        calls.append(prompt)
        # 成功路上不得夹纠错块
        assert _CORRECTION_MARK not in prompt
        return (json.dumps(_ok_payload(person="毕自严"), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
    assert len(calls) == 1


def test_capture_llm_hang_on_retry_not_swallowed_as_participant_409(game, monkeypatch):
    """纠错重试路上 LLM 挂死 → 不得伪装成参与人 409；按既有 capture 失败路处理。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着毕自严核拨辽饷"
    calls = {"n": 0}

    def backend(prompt, *_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            return (json.dumps(_ok_payload(person="毕自"), ensure_ascii=False), 1)
        raise RuntimeError("simulated LLM hang")

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    # capture 外层对 extract 失败降级 special_decree（既有挂死/超时路），
    # 不得 raise 参与人物不存在。
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    assert payload.get("dossier_action_type") == "special_decree"
    assert calls["n"] == 2


# ── 召对 materialize 路 ─────────────────────────────────────────────


def _silence_side_extractors(monkeypatch, cb):
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")


def test_materialize_truncation_bi_zi_heals_to_biziyan(game, monkeypatch):
    """召对路：毕自→纠错→毕自严落 directive。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    _biziyan(content)
    minister = _active_minister(db, content)
    calls: list[str] = []

    def backend(prompt, llm_config=None, tag=""):
        if tag != "draft_intent":
            return ("{}", 1)
        calls.append(prompt)
        person = "毕自" if len(calls) == 1 else "毕自严"
        if len(calls) > 1:
            assert _CORRECTION_MARK in prompt
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着毕自严核拨辽饷，卿其拟旨。",
        answer="臣遵旨：着毕自严核拨辽饷，不得加派于民。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert pending, "纠错后拟旨须落 directive"
    payload = json.loads(pending[-1]["payload_json"])
    ids = [
        str(item.get("character_id") or "")
        for item in (payload.get("participant_roster") or [])
        if isinstance(item, dict)
    ]
    assert ids == ["毕自严"]
    assert len(calls) == 2


def test_materialize_unknown_removed_on_retry_lands(game, monkeypatch):
    """召对路：真不在册→除名后草案照落。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    calls: list[str] = []

    def backend(prompt, llm_config=None, tag=""):
        if tag != "draft_intent":
            return ("{}", 1)
        calls.append(prompt)
        person = "不存在之人甲" if len(calls) == 1 else None
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着核清太仓，卿其拟旨。",
        answer="臣遵旨拟稿。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert pending
    payload = json.loads(pending[-1]["payload_json"])
    ids = [
        str(item.get("character_id") or "")
        for item in (payload.get("participant_roster") or [])
        if isinstance(item, dict)
    ]
    assert "不存在之人甲" not in ids
    assert len(calls) == 2


def test_materialize_happy_path_single_draft_intent_call(game, monkeypatch):
    """召对 happy path：draft_intent 只调一次。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    _biziyan(content)
    minister = _active_minister(db, content)
    calls: list[str] = []

    def backend(prompt, llm_config=None, tag=""):
        if tag != "draft_intent":
            return ("{}", 1)
        calls.append(prompt)
        assert _CORRECTION_MARK not in prompt
        return (json.dumps(_ok_payload(person="毕自严"), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着毕自严核拨辽饷，卿其拟旨。",
        answer="臣遵旨：着毕自严核拨辽饷。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert pending
    assert len(calls) == 1


def test_materialize_llm_hang_on_retry_surfaces(game, monkeypatch):
    """召对纠错重试 LLM 挂死 → 异常上抛（owner：该报），不装成参与人 409。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    n = {"c": 0}

    def backend(prompt, llm_config=None, tag=""):
        if tag != "draft_intent":
            return ("{}", 1)
        n["c"] += 1
        if n["c"] == 1:
            return (json.dumps(_ok_payload(person="毕自"), ensure_ascii=False), 1)
        raise RuntimeError("simulated LLM hang")

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    with pytest.raises(RuntimeError, match="simulated LLM hang"):
        GameSession.apply_cli_conversation_actions(
            sess, minister,
            player_message="着毕自严核拨辽饷，卿其拟旨。",
            answer="臣遵旨。",
            has_directive=False, secret_order_id=None,
            preclassified_intent={"kind": "draft"},
        )
    assert n["c"] == 2
