"""#1274 QA V-1 拟诏参与人自愈重试（owner 2026-08-20 三连拍板）。

宪法：查无此人不告诉皇帝、底下人偷偷划掉=篡改圣旨，绝对禁止。
自愈只许修 LLM 抄写错（修完仍是皇帝说的那个人）。

钉：
1. 抄写错 毕自→纠错→毕自严落库（capture + 召对）
2. 真不在册→戏内回禀 + 草案不落 + 原文不动（禁除名照落）
3. 重试上界（有界）；耗尽回禀
4. happy path 调用计数不变（P5）
5. LLM 挂死：capture→原文 special_decree；召对→RuntimeError 上抛
6. 批抽 drafts 分支 heal；召对耗尽不炸整轮
capture + 召对两路。
"""

from __future__ import annotations

import json
import time
import types

import pytest

from ming_sim.session import GameSession

_ROSTER_BLOCK_HEADER = "【在册人物规范名+别名】"
_CORRECTION_MARK = "名册无此人"
_ESCALATE_MARKS = ("乞陛下明示", "朝籍", "查无")


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


def _ok_payload(*, person: str | None | list[str] = "毕自严"):
    roster = []
    if isinstance(person, list):
        for i, name in enumerate(person):
            roster.append({
                "character_id": name,
                "tier": "主办" if i == 0 else "协办",
                "role": "核辽饷",
            })
    elif person is not None:
        roster = [{"character_id": person, "tier": "主办", "role": "核辽饷"}]
    return {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "liao-pay",
        "正文": "着毕自严核拨辽饷，不得加派于民。",
        "参与人": roster,
    }


def _assert_inworld_escalate(msg: str, *names: str) -> None:
    text = str(msg or "")
    for name in names:
        assert name in text
    assert any(m in text for m in _ESCALATE_MARKS), text
    # 禁原始 409 术语泄漏（F5）
    assert "参与人物不存在" not in text
    assert "系统已尝试" not in text


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
            assert _CORRECTION_MARK in prompt
            assert "毕自" in prompt
            assert _ROSTER_BLOCK_HEADER in prompt or "毕自严" in prompt
            assert "改正" in prompt
            assert "不得擅自除去" in prompt or "不得" in prompt
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


def test_capture_unknown_person_escalates_no_draft(game, monkeypatch):
    """真不在册→戏内回禀；草案不落；输入原文由调用方保留（capture 不吞文）。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    text = "着不存在之人甲核清太仓，边饷优先"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        return (
            json.dumps(_ok_payload(person="不存在之人甲"), ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    _assert_inworld_escalate(str(ei.value), "不存在之人甲")
    # 输入文未改（调用方仍持有原 text）
    assert text == "着不存在之人甲核清太仓，边饷优先"
    # 不得落库（直断计数 0，禁 before/after 同点恒真）
    assert len(db.list_directives(state) or []) == 0
    max_retries = int(cli_backend.DRAFT_PARTICIPANT_HEAL_RETRIES)
    # heal 环 1+retries；回禀产文可再 +1
    draft_calls = sum(1 for p in calls if "拟旨意图" in p or "参与人" in p or _CORRECTION_MARK in p or "请据此拟旨" in p or "信息抽取器" in p)
    assert draft_calls >= 1 + max_retries


def test_capture_unknown_then_removal_still_escalates(game, monkeypatch):
    """纠错路上 LLM 除名（空参与人）= 篡改 → 仍回禀，不照落。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着核清太仓"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            return ("通政司启：名册无「不存在之人甲」，乞陛下明示。", 1)
        if _CORRECTION_MARK in prompt:
            person = None  # 除名企图
        else:
            person = "不存在之人甲"
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    _assert_inworld_escalate(str(ei.value), "不存在之人甲")
    assert any(_CORRECTION_MARK in p for p in calls)


def test_capture_correction_drops_prior_valid_escalates(game, monkeypatch):
    """纠错轮只回替换名、丢掉本轮合法参与人 → escalate，不落草案。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    text = "着不存在之人甲与毕自严核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        if _CORRECTION_MARK in prompt:
            # 有替换，但顺手抹掉合法的毕自严
            person = [replacement]
        else:
            person = ["不存在之人甲", "毕自严"]
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    _assert_inworld_escalate(str(ei.value), "不存在之人甲")
    assert len(db.list_directives(state) or []) == 0
    assert any(_CORRECTION_MARK in p for p in calls)


def test_capture_correction_keeps_prior_valid_heals(game, monkeypatch):
    """纠错轮保留毕自严 + 正确替换名 → 自愈成功落库（防过严误伤）。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    text = "着不存在之人甲与毕自严核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if _CORRECTION_MARK in prompt:
            person = ["毕自严", replacement]
        else:
            person = ["不存在之人甲", "毕自严"]
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert "毕自严" in ids
    assert replacement in ids
    assert "不存在之人甲" not in ids
    assert len(calls) == 2

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_correction_alias_prior_valid_heals(game, monkeypatch):
    """首抽合法侧为 content 真 alias → 纠错轮回规范名+替换 → 须自愈落库。

    复现 r3 生/熟键错位：prior=「毕尚书」 validated=「毕自严」时
    不得因 alias⊄canon 误 escalate。
    """
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    ch = _biziyan(content)
    aliases = [
        str(a).strip()
        for a in (getattr(ch, "aliases", None) or [])
        if str(a).strip() and str(a).strip() != ch.name
    ]
    assert aliases, "夹具毕自严须带真实 aliases（禁硬编码假别名）"
    alias = aliases[0]
    replacement = _active_minister(db, content).name
    text = f"着不存在之人甲与{alias}核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if _CORRECTION_MARK in prompt:
            # 纠错轮：未知人→在册替换；alias→规范名
            person = [ch.name, replacement]
        else:
            person = ["不存在之人甲", alias]
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ch.name in ids
    assert replacement in ids
    assert alias not in ids or alias == ch.name
    assert "不存在之人甲" not in ids
    assert len(calls) == 2

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_heal_retry_bounded(game, monkeypatch):
    """重试上界：持续吐无效名 → 有界次后戏内回禀；调用次数有上界。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着毕自严核拨辽饷"
    calls: list[str] = []
    max_retries = int(cli_backend.DRAFT_PARTICIPANT_HEAL_RETRIES)

    def backend(prompt, *_a, tag="", **_k):
        calls.append(tag or "draft")
        if tag == "participant_escalate_report":
            return ("臣查朝籍未有「毕自」，乞陛下明示。", 1)
        return (json.dumps(_ok_payload(person="毕自"), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    _assert_inworld_escalate(str(ei.value), "毕自")
    draft_n = sum(1 for t in calls if t != "participant_escalate_report")
    assert draft_n == 1 + max_retries


def test_capture_happy_path_single_llm_call(game, monkeypatch):
    """happy path 零额外调用（P5：重试只在失败路）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    _biziyan(content)
    text = "着毕自严核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, **_k):
        calls.append(prompt)
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
    """纠错重试路上 LLM 挂死 → 原文 special_decree（零改参与人），不伪装查无回禀。"""
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
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    assert payload.get("dossier_action_type") == "special_decree"
    assert "participant_roster" not in payload  # 原文 special_decree，不夹参与人
    assert calls["n"] == 2


def test_capture_timeout_constant_is_30():
    """Q1：总罩 30 秒。"""
    import ming_sim.cli_backend as cli_backend

    assert cli_backend.MANUAL_DIRECTIVE_CAPTURE_TIMEOUT_S == 30.0


def test_capture_delegator_truncation_heals(game, monkeypatch):
    """委派人截断「毕自」→纠错「毕自严」须自愈，不得因键空间漏 delegator 误 escalate。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    ch = _biziyan(content)
    worker = _active_minister(db, content).name
    text = f"着{worker}核拨辽饷，由毕自严委派"
    calls: list[str] = []

    def _payload(person: str, delegator: str):
        return {
            "拟旨意图": "拟旨",
            "动作类型": "policy",
            "目标类型": "issue",
            "目标ID": "liao-pay",
            "正文": text,
            "参与人": [{
                "character_id": person,
                "tier": "协办",
                "role": "核辽饷",
                "delegator_id": delegator,
            }],
        }

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            raise AssertionError("委派人截断自愈不得 escalate")
        if _CORRECTION_MARK in prompt:
            assert "毕自" in prompt
            return (json.dumps(_payload(worker, ch.name), ensure_ascii=False), 1)
        return (json.dumps(_payload(worker, "毕自"), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    roster = payload.get("participant_roster") or []
    assert len(roster) == 1
    assert str(roster[0]["character_id"]) == worker
    assert str(roster[0].get("delegator_id") or "") == ch.name
    assert any(_CORRECTION_MARK in p for p in calls)
    assert len(calls) == 2

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_delegator_alias_prior_valid_heals(game, monkeypatch):
    """首抽合法委派人为 content 真 alias → 纠错轮回规范名 + 替换未知人 → 须自愈。

    复现键空间漏 delegator：prior 含 alias 委派人时须走 _canon 后再比，
    不得因 alias⊄new_ids 误 lost_prior_valid。
    """
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    ch = _biziyan(content)
    aliases = [
        str(a).strip()
        for a in (getattr(ch, "aliases", None) or [])
        if str(a).strip() and str(a).strip() != ch.name
    ]
    assert aliases, "夹具毕自严须带真实 aliases（禁硬编码假别名）"
    alias = aliases[0]
    replacement = _active_minister(db, content).name
    text = f"着不存在之人甲核拨辽饷，由{alias}委派"
    calls: list[str] = []

    def _payload(person: str, delegator: str):
        return {
            "拟旨意图": "拟旨",
            "动作类型": "policy",
            "目标类型": "issue",
            "目标ID": "liao-pay",
            "正文": text,
            "参与人": [{
                "character_id": person,
                "tier": "协办",
                "role": "核辽饷",
                "delegator_id": delegator,
            }],
        }

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            raise AssertionError("委派人 alias 守恒自愈不得 escalate")
        if _CORRECTION_MARK in prompt:
            # 未知人→在册替换；alias 委派人→规范名
            return (
                json.dumps(_payload(replacement, ch.name), ensure_ascii=False),
                1,
            )
        return (
            json.dumps(_payload("不存在之人甲", alias), ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    roster = payload.get("participant_roster") or []
    assert len(roster) == 1
    assert str(roster[0]["character_id"]) == replacement
    assert str(roster[0].get("delegator_id") or "") == ch.name
    assert "不存在之人甲" not in str(roster)
    assert len(calls) == 2

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_correction_drops_prior_valid_delegator_escalates(game, monkeypatch):
    """纠错轮丢掉本轮合法委派人 → escalate（delegator 入 prior/new 键空间）。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    _biziyan(content)
    worker = _active_minister(db, content).name
    text = "着不存在之人甲核拨辽饷，由毕自严委派"
    calls: list[str] = []

    def _payload(person: str, delegator: str | None):
        entry = {
            "character_id": person,
            "tier": "协办",
            "role": "核辽饷",
        }
        if delegator is not None:
            entry["delegator_id"] = delegator
        return {
            "拟旨意图": "拟旨",
            "动作类型": "policy",
            "目标类型": "issue",
            "目标ID": "liao-pay",
            "正文": text,
            "参与人": [entry],
        }

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        if _CORRECTION_MARK in prompt:
            # 有替换工人，但抹掉合法委派人毕自严
            return (json.dumps(_payload(worker, None), ensure_ascii=False), 1)
        return (
            json.dumps(_payload("不存在之人甲", "毕自严"), ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
    _assert_inworld_escalate(str(ei.value), "不存在之人甲")
    assert len(db.list_directives(state) or []) == 0
    assert any(_CORRECTION_MARK in p for p in calls)


def test_capture_escalate_report_timeout_falls_back_inworld(game, monkeypatch):
    """回禀路径超时 → 确定性戏内 fallback，不裸抛 TimeoutError 给玩家。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    text = "着不存在之人甲核清太仓"

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            time.sleep(1.5)
            return ("慢回禀不该露脸", 1)
        return (
            json.dumps(_ok_payload(person="不存在之人甲"), ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    # 极短总罩：extract 立刻 escalate 后回禀几乎无剩余预算 → fallback
    with pytest.raises(ValueError) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content, capture_timeout_s=0.2,
        )
    msg = str(ei.value)
    _assert_inworld_escalate(msg, "不存在之人甲")
    assert "慢回禀不该露脸" not in msg
    assert "TimeoutError" not in msg
    assert len(db.list_directives(state) or []) == 0


def test_compose_escalate_report_timeout_s_zero_is_fallback():
    """timeout_s≤0 直落确定性戏内文，零 LLM。"""
    import ming_sim.cli_backend as cli_backend

    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("timeout_s≤0 不得调后端")

    # 不依赖 monkeypatch fixture：直接临时替换
    real = cli_backend._run_backend_for_config
    cli_backend._run_backend_for_config = boom  # type: ignore[assignment]
    try:
        text = cli_backend.compose_unknown_participant_inworld_report(
            ["不存在之人甲"], timeout_s=0.0,
        )
    finally:
        cli_backend._run_backend_for_config = real  # type: ignore[assignment]
    _assert_inworld_escalate(text, "不存在之人甲")
    assert calls["n"] == 0


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


def test_materialize_unknown_escalates_report_no_draft(game, monkeypatch):
    """召对路：真不在册→不落草案、回话保留、戏内回禀（禁整轮回滚）。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    draft_calls: list[str] = []

    def backend(prompt, llm_config=None, tag=""):
        if tag == "participant_escalate_report":
            return (f"臣{minister.name}启：朝中查无不存在之人甲，乞陛下明示。", 1)
        if tag != "draft_intent":
            return ("{}", 1)
        draft_calls.append(prompt)
        return (
            json.dumps(_ok_payload(person="不存在之人甲"), ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    answer0 = "臣遵旨拟稿，已草就。"
    # 非流式路径：apply 后走 _cli_backend_fallback 会附回禀；此处直接测 apply 出参
    # + session post-pass 同构：手工附 cue 验证 out 信号。
    res = GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着不存在之人甲核清太仓，卿其拟旨。",
        answer=answer0,
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert not pending, "查无此人不得落草案"
    esc = res.get("unknown_participant_escalate") or {}
    report = str(esc.get("report") or "")
    _assert_inworld_escalate(report, "不存在之人甲")
    # 回话原文仍在（apply 不改 answer；post-pass 另附）
    cued = GameSession._ensure_unknown_participant_report_cue(answer0, report)
    assert answer0 in cued
    assert report in cued
    assert len(draft_calls) == 1 + int(cb.DRAFT_PARTICIPANT_HEAL_RETRIES)


def test_materialize_unknown_removal_attempt_escalates(game, monkeypatch):
    """召对：纠错后除名企图 → 回禀不落草案。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    n = {"c": 0}

    def backend(prompt, llm_config=None, tag=""):
        if tag == "participant_escalate_report":
            return ("臣启：朝中查无不存在之人甲，乞陛下明示。", 1)
        if tag != "draft_intent":
            return ("{}", 1)
        n["c"] += 1
        person = "不存在之人甲" if n["c"] == 1 else None
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    res = GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着核清太仓，卿其拟旨。",
        answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert not pending
    esc = res.get("unknown_participant_escalate") or {}
    _assert_inworld_escalate(str(esc.get("report") or ""), "不存在之人甲")


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
    """召对纠错重试 LLM 挂死 → 异常上抛（owner：该报），不装成查无回禀。"""
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


def test_batch_drafts_heal_truncation(game, monkeypatch):
    """F6：批抽 drafts 分支 — 毕自→毕自严 经 heal 校验。"""
    import ming_sim.cli_backend as cb

    db, _state, content = game
    _biziyan(content)
    calls: list[str] = []

    def backend(prompt, llm_config=None, tag=""):
        calls.append(prompt)
        if _CORRECTION_MARK in prompt:
            person = "毕自严"
        else:
            person = "毕自"
        # 批抽形状
        payload = {
            "成品旨稿": [
                {
                    "正文": "着毕自严核拨辽饷。",
                    "动作类型": "policy",
                    "目标类型": "issue",
                    "目标ID": "liao-pay",
                    "颁布方式": "普通",
                    "参与人": [{"character_id": person, "tier": "主办", "role": "核"}],
                },
                {
                    "正文": "着边军整饬器械。",
                    "动作类型": "military_order",
                    "目标类型": "army",
                    "目标ID": "guanning",
                    "颁布方式": "普通",
                    "参与人": [],
                },
            ]
        }
        return (json.dumps(payload, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_roster_heal(
        "两道旨", "臣遵拟。",
        db=db, content=content, draft_count=2,
    )
    drafts = result.get("drafts") or []
    assert len(drafts) == 2
    ids = [
        str(i.get("character_id") or "")
        for i in (drafts[0].get("participant_roster") or [])
    ]
    assert ids == ["毕自严"]
    assert len(calls) == 2


def test_session_post_pass_appends_escalate_report(game, monkeypatch):
    """非流式 session 路径：apply escalate 后 answer 附戏内回禀。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)

    def backend(prompt, llm_config=None, tag=""):
        if tag == "participant_escalate_report":
            return ("臣启：朝中查无不存在之人甲，乞陛下明示。", 1)
        if tag != "draft_intent":
            return ("{}", 1)
        return (
            json.dumps(_ok_payload(person="不存在之人甲"), ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)

    sess = _fake_session(db, state, content)
    result = types.SimpleNamespace(
        answer="臣遵旨拟就。",
        proposed_directive=None,
        pending_action_id=0,
        secret_order_id=None,
        pending_action_failures=[],
        directive_confirmation_ambiguous=None,
    )
    sess._cli_backend_fallback_actions(
        result, minister,
        player_message="着不存在之人甲核太仓，卿其拟旨。",
        preclassified_intent={"kind": "draft"},
    )
    assert "臣遵旨拟就" in (result.answer or "")
    _assert_inworld_escalate(result.answer or "", "不存在之人甲")
    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert not pending
