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
    max_retries = int(cli_backend.DRAFT_INTENT_HEAL_RETRIES)
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
    """纠错轮保留毕自严 + 原文可接地的替换名 → 自愈成功落库（防过严误伤）。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    # 替换名须出现在原始输入（同人接地）；抄写错把替换名写成不存在之人
    text = f"着{replacement}与毕自严核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if _CORRECTION_MARK in prompt:
            # 同序一一对应：失败槽→替换名，合法槽位置不变
            person = [replacement, "毕自严"]
        else:
            person = ["不存在之人甲", "毕自严"]
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == [replacement, "毕自严"]
    assert len(calls) == 2

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_ungrounded_replacement_escalates(game, monkeypatch):
    """不存在之人甲→任意在册人（原文无接地）→ escalate，禁当抄写纠错落库。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    text = "着不存在之人甲与毕自严核拨辽饷"
    assert replacement not in text
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        if _CORRECTION_MARK in prompt:
            person = ["毕自严", replacement]
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
    # 替换名与 alias 均须在原文（接地 + alias 守恒）
    text = f"着{replacement}与{alias}核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if _CORRECTION_MARK in prompt:
            # 同序：失败槽→replacement，合法 alias 槽→规范名
            person = [replacement, ch.name]
        else:
            person = ["不存在之人甲", alias]
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == [replacement, ch.name]
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
    max_retries = int(cli_backend.DRAFT_INTENT_HEAL_RETRIES)

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
    # 替换工人名须在原文（同人接地）
    text = f"着{replacement}核拨辽饷，由{alias}委派"
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


def test_capture_escalate_report_timeout_raises_llm_unavailable(game, monkeypatch):
    """回禀路径超时 → typed LLMUnavailable（#1452 单源），不落固定戏内文案。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

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
    # 极短总罩：extract 立刻 escalate 后回禀几乎无剩余预算 → LLMUnavailable
    with pytest.raises(LLMUnavailable) as ei:
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content, capture_timeout_s=0.2,
        )
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert "慢回禀不该露脸" not in ei.value.message
    assert "臣查朝籍" not in ei.value.message
    assert "TimeoutError" not in ei.value.message
    assert len(db.list_directives(state) or []) == 0


def test_compose_escalate_report_timeout_s_zero_raises_llm_unavailable():
    """timeout_s≤0 → typed LLMUnavailable，零 LLM、零固定戏内文案。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.exceptions import LLMUnavailable
    from ming_sim.llm_model import CLI_RUNNER_PLAYER_MESSAGE

    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("timeout_s≤0 不得调后端")

    # 不依赖 monkeypatch fixture：直接临时替换
    real = cli_backend._run_backend_for_config
    cli_backend._run_backend_for_config = boom  # type: ignore[assignment]
    try:
        with pytest.raises(LLMUnavailable) as ei:
            cli_backend.compose_unknown_participant_inworld_report(
                ["不存在之人甲"], timeout_s=0.0,
            )
    finally:
        cli_backend._run_backend_for_config = real  # type: ignore[assignment]
    assert ei.value.message == CLI_RUNNER_PLAYER_MESSAGE
    assert "臣查朝籍" not in ei.value.message
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
    assert len(draft_calls) == 1 + int(cb.DRAFT_INTENT_HEAL_RETRIES)


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


@pytest.mark.parametrize("invalid_kind", ["wrong_count", "duplicate_text"])
def test_materialize_invalid_batch_skips_discarded_locality(
    game, monkeypatch, invalid_kind,
):
    """被整批拒收的多旨不再让坏属地进入后处理。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    calls = {"n": 0}
    item = {
        "正文": "着户部清查三边粮饷。",
        "动作类型": "policy",
        "目标类型": "region",
        "目标ID": "shaanxi",
        "颁布方式": "普通",
        "施行范围": "无",
    }
    values = [dict(item), dict(item)]
    if invalid_kind == "wrong_count":
        values.append({**item, "正文": "着兵部核查九边军械。"})

    def backend(_prompt, llm_config=None, tag=""):
        if tag != "draft_intent":
            return ("{}", 1)
        calls["n"] += 1
        return (json.dumps({"成品旨稿": values}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)
    sess = _fake_session(db, state, content)

    GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="分别拟两道旨。",
        answer="臣已拟妥。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "draft"}, {"kind": "draft"}],
    )

    assert calls["n"] == 1
    assert not [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]


def test_batch_locality_heal_preserves_valid_sibling(game, monkeypatch):
    import ming_sim.cli_backend as cb

    db, _state, content = game
    calls = {"n": 0}

    replies = [
        {
            "成品旨稿": [
                {
                    "正文": "着依前议施行。",
                    "目标案卷ID": 1,
                    "颁布方式": "普通",
                },
                {
                    "正文": "着户部办理陕西事务。",
                    "动作类型": "policy",
                    "目标类型": "region",
                    "目标ID": "shaanxi",
                    "颁布方式": "普通",
                    "施行范围": first_scope,
                    "参与人": [],
                },
                {
                    "正文": "着户部整饬全国政务。",
                    "动作类型": "policy",
                    "目标类型": "policy",
                    "目标ID": "national-policy",
                    "颁布方式": "普通",
                    "施行范围": second_scope,
                    "参与人": [],
                },
            ]
        }
        for first_scope, second_scope in (
            ("无", "无"), ("单省", "全国"), ("单省", "无"),
        )
    ]

    def backend(_prompt, llm_config=None, tag=""):
        assert tag == "draft_intent"
        reply = replies[calls["n"]]
        calls["n"] += 1
        return json.dumps(reply, ensure_ascii=False), 1

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_semantic_heal(
        "分别拟两道旨。", "臣已拟妥。",
        db=db, content=content, draft_count=3,
    )

    assert calls["n"] == 3
    assert [
        draft["locality_scope"] for draft in result["drafts"][1:]
    ] == ["单省", "无"]


def test_materialize_locality_exhaustion_rejects_only_draft(game, monkeypatch):
    """召对属地纠错耗尽只拒草案；该轮结构化结果仍正常返回。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    calls = {"n": 0}
    payload = _ok_payload(person="毕自严")
    payload.update({"目标类型": "region", "目标ID": "shaanxi", "施行范围": "无"})

    def backend(_prompt, llm_config=None, tag=""):
        if tag != "draft_intent":
            return ("{}", 1)
        calls["n"] += 1
        return (json.dumps(payload, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    _silence_side_extractors(monkeypatch, cb)
    sess = _fake_session(db, state, content)
    result = GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着毕自严办理陕西事务，卿其拟旨。",
        answer="臣已拟妥。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    assert calls["n"] == 1 + cb.DRAFT_INTENT_HEAL_RETRIES
    assert not [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert "unknown_participant_escalate" not in result


def test_materialize_does_not_swallow_untyped_value_error(game, monkeypatch):
    """召对拒收边界只接 typed locality，不接普通 ValueError。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    minister = _active_minister(db, content)
    monkeypatch.setattr(
        cb, "extract_draft_intent_with_semantic_heal",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("untyped failure")),
    )
    _silence_side_extractors(monkeypatch, cb)

    with pytest.raises(ValueError, match="untyped failure"):
        GameSession.apply_cli_conversation_actions(
            _fake_session(db, state, content), minister,
            player_message="卿其拟旨。", answer="臣已拟妥。",
            has_directive=False, secret_order_id=None,
            preclassified_intent={"kind": "draft"},
        )


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
    result = cb.extract_draft_intent_with_semantic_heal(
        "两道旨着毕自严核拨辽饷", "臣遵拟。",
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


def test_heal_second_fail_keeps_first_prior_valid(game, monkeypatch):
    """两轮失败后首抽合法 participant 不丢：基线冻结，终轮洗掉首抽合法侧仍 escalate。

    若每败覆写 prior_ids，第二轮只吐假名会洗掉毕自严，第三轮仅替换名会误自愈。
    """
    import ming_sim.cli_backend as cb

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    text = f"着不存在之人甲与毕自严核拨辽饷"
    n = {"c": 0}

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        n["c"] += 1
        if n["c"] == 1:
            person = ["不存在之人甲", "毕自严"]
        elif n["c"] == 2:
            # 第二轮另吐假名——旧码会覆写 prior，洗掉毕自严
            person = ["另一个不存在之人"]
        else:
            # 终轮只给在册替换、丢掉首抽合法毕自严
            person = [replacement]
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    with pytest.raises(ValueError) as ei:
        cb.capture_manual_directive_payload(text, None, db=db, content=content)
    _assert_inworld_escalate(str(ei.value), "不存在之人甲")
    assert len(db.list_directives(state) or []) == 0
    assert n["c"] == 1 + int(cb.DRAFT_INTENT_HEAL_RETRIES)


def test_heal_keeps_first_extract_non_roster_fields(game, monkeypatch):
    """纠错轮 amount/target/mode/text 漂移时仍保首抽（单条）。"""
    import ming_sim.cli_backend as cb

    db, _state, content = game
    _biziyan(content)
    text = "着毕自严核拨辽饷五十万"

    def _payload(person: str, *,
                 amount, target_id, mode, body, action="grant_allocation"):
        target_key = "目标" if action == "grant_allocation" else "目标ID"
        canonical_mode = {
            "普通": "ordinary", "中旨直发": "midzhi",
        }.get(mode, mode) if action == "grant_allocation" else mode
        return {
            "拟旨意图": "拟旨",
            "动作类型": action,
            "目标类型": "issue",
            target_key: target_id,
            "正文": body,
            "颁布方式": canonical_mode,
            "金额": amount,
            "账户": "太仓",
            "执行面": "immediate",
            "期限月数": 3,
            "参与人": [{"character_id": person, "tier": "主办", "role": "核辽饷"}],
        }

    def backend(prompt, *_a, tag="", **_k):
        if _CORRECTION_MARK in prompt:
            # 纠错顺带改金额/目标/颁布/正文/期限
            return (json.dumps(_payload(
                "毕自严",
                amount=999,
                target_id="other-issue",
                mode="中旨直发",
                body="已被纠错轮改写的正文",
                action="policy",
            ), ensure_ascii=False), 1)
        return (json.dumps(_payload(
            "毕自",
            amount=50,
            target_id="liao-pay",
            mode="普通",
            body="着毕自严核拨辽饷五十万。",
        ), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_semantic_heal(
        text, text, db=db, content=content,
    )
    ids = [
        str(i.get("character_id") or "")
        for i in (result.get("participant_roster") or [])
    ]
    assert ids == ["毕自严"]
    # 非参与人字段保首抽（单条 draft_text 源=minister_reply，不随 LLM 正文漂）
    assert result.get("amount") == 50
    assert result.get("target_id") == "liao-pay"
    assert result.get("mode") == "ordinary"
    assert result.get("draft_text") == text
    assert result.get("dossier_action_type") == "grant_allocation"
    assert result.get("deadline_months") == 3
    assert result.get("account") == "太仓"
    # 纠错轮的漂移值不得落库
    assert result.get("amount") != 999
    assert result.get("target_id") != "other-issue"


def test_batch_heal_keeps_first_extract_non_roster_fields(game, monkeypatch):
    """批抽：纠错轮漂移 amount/target/mode/正文/批序字段时仍保首抽。"""
    import ming_sim.cli_backend as cb

    db, _state, content = game
    _biziyan(content)

    def _batch(person: str, *,
               body1, target1, mode1, amount1,
               body2, target2, mode2):
        return {
            "成品旨稿": [
                {
                    "正文": body1,
                    "动作类型": "grant_allocation",
                    "目标类型": "issue",
                    "目标": target1,
                    "颁布方式": {
                        "普通": "ordinary", "中旨直发": "midzhi",
                    }.get(mode1, mode1),
                    "金额": amount1,
                    "账户": "太仓",
                    "执行面": "immediate",
                    "期限月数": 2,
                    "参与人": [
                        {"character_id": person, "tier": "主办", "role": "核"},
                    ],
                },
                {
                    "正文": body2,
                    "动作类型": "military_order",
                    "目标类型": "army",
                    "目标ID": target2,
                    "颁布方式": mode2,
                    "期限月数": 4,
                    "参与人": [],
                },
            ]
        }

    def backend(prompt, llm_config=None, tag=""):
        if _CORRECTION_MARK in prompt:
            # 漂移 + 甚至调换批序语义字段
            return (json.dumps(_batch(
                "毕自严",
                body1="纠错轮改写其一",
                target1="drift-issue",
                mode1="中旨直发",
                amount1=777,
                body2="纠错轮改写其二",
                target2="drift-army",
                mode2="中旨直发",
            ), ensure_ascii=False), 1)
        return (json.dumps(_batch(
            "毕自",
            body1="着毕自严核拨辽饷。",
            target1="liao-pay",
            mode1="普通",
            amount1=50,
            body2="着边军整饬器械。",
            target2="guanning",
            mode2="普通",
        ), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_semantic_heal(
        "两道旨着毕自严核拨并整饬", "臣遵拟。",
        db=db, content=content, draft_count=2,
    )
    drafts = result.get("drafts") or []
    assert len(drafts) == 2
    d0, d1 = drafts[0], drafts[1]
    ids = [
        str(i.get("character_id") or "")
        for i in (d0.get("participant_roster") or [])
    ]
    assert ids == ["毕自严"]
    # 首抽字段保留
    assert d0.get("draft_text") == "着毕自严核拨辽饷。"
    assert d0.get("target_id") == "liao-pay"
    assert d0.get("mode") == "ordinary"
    assert d0.get("amount") == 50
    assert d0.get("deadline_months") == 2
    assert d1.get("draft_text") == "着边军整饬器械。"
    assert d1.get("target_id") == "guanning"
    assert d1.get("mode") == "ordinary"
    assert d1.get("deadline_months") == 4


def test_capture_bi_shangshu_alias_grounds_and_heals(game, monkeypatch):
    """毕尚书→毕自严：原文别名接地 → 自愈（正测，alias 钉不回退）。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    ch = _biziyan(content)
    assert "毕尚书" in (getattr(ch, "aliases", None) or []), "夹具须含毕尚书别名"
    text = "着毕尚书核拨辽饷"
    calls: list[str] = []

    def backend(prompt, *_a, tag="", **_k):
        calls.append(prompt)
        if tag == "participant_escalate_report":
            raise AssertionError("别名接地自愈不得 escalate")
        person = "毕自严" if _CORRECTION_MARK in prompt else "毕自"
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(i["character_id"]) for i in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
    assert len(calls) == 2


def test_player_bi_shangshu_su_bo_xiang_alias_grounds_and_heals(game, monkeypatch):
    """r10 正向：玩家输入含别名「毕尚书速拨饷」→ 自愈照常（禁依赖 minister_reply）。"""
    import ming_sim.cli_backend as cb

    db, _state, content = game
    ch = _biziyan(content)
    assert "毕尚书" in (getattr(ch, "aliases", None) or []), "夹具须含毕尚书别名"
    player = "毕尚书速拨饷"
    # 大臣回话故意不含可接地线索——只许玩家输入 + 首抽失败引用接地
    minister_reply = "臣领旨，即按名册改正拟就。"

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            raise AssertionError("玩家别名接地不得 escalate")
        person = "毕自严" if _CORRECTION_MARK in prompt else "毕自"
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_semantic_heal(
        player, minister_reply, db=db, content=content,
    )
    ids = [
        str(i.get("character_id") or "")
        for i in (result.get("participant_roster") or [])
    ]
    assert ids == ["毕自严"]


def test_minister_reply_only_grounding_escalates(game, monkeypatch):
    """r10 负向：同人依据只在 minister_reply → escalate 不自愈（ADR 0142）。

    player_message / 结构化首抽失败引用都接不上替换名时，禁从大臣散文抠同人。
    """
    import ming_sim.cli_backend as cb

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    # 玩家话与失败槽均无替换名；仅大臣回话点名
    player = "着不存在之人甲核拨辽饷"
    minister_reply = f"臣以为可改委{replacement}专办此事。"
    assert replacement not in player
    assert replacement in minister_reply

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        if _CORRECTION_MARK in prompt:
            person = replacement
        else:
            person = "不存在之人甲"
        return (json.dumps(_ok_payload(person=person), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    with pytest.raises(cb.UnknownParticipantEscalate) as ei:
        cb.extract_draft_intent_with_semantic_heal(
            player, minister_reply, db=db, content=content,
        )
    assert "不存在之人甲" in ei.value.names
    assert len(db.list_directives(state) or []) == 0


def test_heal_freezes_first_roster_shape_against_drift(game, monkeypatch):
    """r10/r11：同序纠错只改失败槽 id；tier/role 冻结为首抽，尾部未接地增人丢弃。"""
    import ming_sim.cli_backend as cb

    db, _state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    # 未接地增人（不在玩家输入）——可忽略、不进池
    extra = _active_minister(db, content, exclude=replacement).name
    player = f"着不存在之人甲与毕自严核拨辽饷，可令{replacement}主事"
    minister_reply = "臣遵拟。"
    assert extra not in player

    def _payload(roster):
        return {
            "拟旨意图": "拟旨",
            "动作类型": "policy",
            "目标类型": "issue",
            "目标ID": "liao-pay",
            "正文": "着核拨辽饷。",
            "参与人": roster,
        }

    first_roster = [
        {"character_id": "不存在之人甲", "tier": "主办", "role": "核辽饷"},
        {"character_id": "毕自严", "tier": "协办", "role": "监核"},
    ]
    # 同序修补 + 改 tier/role + 尾部未接地增人
    fixed_roster = [
        {"character_id": replacement, "tier": "知情", "role": "被篡改职分"},
        {"character_id": "毕自严", "tier": "主办", "role": "新职分"},
        {"character_id": extra, "tier": "协办", "role": "增人"},
    ]

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            raise AssertionError("形状冻结自愈不得 escalate")
        roster = fixed_roster if _CORRECTION_MARK in prompt else first_roster
        return (json.dumps(_payload(roster), ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    result = cb.extract_draft_intent_with_semantic_heal(
        player, minister_reply, db=db, content=content,
    )
    roster = result.get("participant_roster") or []
    assert len(roster) == 2, roster
    assert [str(i.get("character_id") or "") for i in roster] == [
        replacement, "毕自严",
    ]
    assert str(roster[0].get("tier") or "") == "主办"
    assert str(roster[0].get("role") or "") == "核辽饷"
    assert str(roster[1].get("tier") or "") == "协办"
    assert str(roster[1].get("role") or "") == "监核"
    assert extra not in [str(i.get("character_id") or "") for i in roster]


def test_minister_reply_only_assignee_falls_to_default(monkeypatch):
    """r11 负钉：承办人线索只在 minister_reply → 不采信，退默认（ADR 0142）。"""
    import inspect

    import ming_sim.cli_backend as cb

    # r12：私有选择缝签名不接自由文本（ADR 0117）
    params = inspect.signature(cb._choose_assignee).parameters
    assert "minister_reply" not in params and "content" not in params
    assert list(params) == [
        "assignee_llm", "player_command", "default_assignee",
    ]

    monkeypatch.setattr(
        cb, "_run_backend",
        lambda p: (
            json.dumps({
                "标题": "密查",
                "内容": "查辽东军饷有无侵冒，三月内回奏",
                "承办人": "",
                "期限月数": 3,
                "标签": ["辽饷"],
            }, ensure_ascii=False),
            1,
        ),
    )
    acts = cb.resolve_minister_actions(
        "臣领密旨，可授李若琏暗查。",
        "密令如下：查辽东军饷有无侵冒，三月内回奏",
        default_assignee="王在晋",
    )
    so = acts["secret_order"]
    assert so is not None
    assert so["assignee"] == "王在晋"


def test_grounded_extra_front_must_not_fill_failed_slot(game, monkeypatch):
    """r11 负钉：接地增人前置不得顶失败槽（禁聚合池按序回填）。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    extra = _active_minister(db, content, exclude=replacement).name
    # 两人都在玩家输入中可接地
    player = f"着不存在之人甲核拨辽饷；可令{extra}与{replacement}会商"
    minister_reply = "臣遵拟。"

    first_roster = [
        {"character_id": "不存在之人甲", "tier": "主办", "role": "核辽饷"},
    ]
    # 纠错轮：接地增人在前、真替换在后——旧聚合池会误把 extra 填进失败槽
    drifted = [
        {"character_id": extra, "tier": "主办", "role": "核辽饷"},
        {"character_id": replacement, "tier": "协办", "role": "会商"},
    ]

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        roster = drifted if _CORRECTION_MARK in prompt else first_roster
        return (
            json.dumps({
                "拟旨意图": "拟旨",
                "动作类型": "policy",
                "目标类型": "issue",
                "目标ID": "liao-pay",
                "正文": "着核拨辽饷。",
                "参与人": roster,
            }, ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    with pytest.raises(cb.UnknownParticipantEscalate) as ei:
        cb.extract_draft_intent_with_semantic_heal(
            player, minister_reply, db=db, content=content,
        )
    assert "不存在之人甲" in ei.value.names
    assert len(db.list_directives(state) or []) == 0


def test_two_unknown_refs_escalates_first_error_stop(game, monkeypatch):
    """r11 负钉：两个不同未知引用（validator 首错即停）→ 对应不明 escalate。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    _biziyan(content)
    r1 = _active_minister(db, content).name
    r2 = _active_minister(db, content, exclude=r1).name
    player = f"着不存在之人甲与不存在之人乙核拨辽饷，可令{r1}、{r2}分办"
    minister_reply = "臣遵拟。"

    first_roster = [
        {"character_id": "不存在之人甲", "tier": "主办", "role": "核辽饷"},
        {"character_id": "不存在之人乙", "tier": "协办", "role": "分办"},
    ]
    # 纠错轮即使两槽都换成接地新人——多未知仍对应不明
    fixed = [
        {"character_id": r1, "tier": "主办", "role": "核辽饷"},
        {"character_id": r2, "tier": "协办", "role": "分办"},
    ]

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无不存在之人，乞陛下明示。", 1)
        roster = fixed if _CORRECTION_MARK in prompt else first_roster
        return (
            json.dumps({
                "拟旨意图": "拟旨",
                "动作类型": "policy",
                "目标类型": "issue",
                "目标ID": "liao-pay",
                "正文": "着核拨辽饷。",
                "参与人": roster,
            }, ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    with pytest.raises(cb.UnknownParticipantEscalate) as ei:
        cb.extract_draft_intent_with_semantic_heal(
            player, minister_reply, db=db, content=content,
        )
    # 首错即停至少钉到甲；不得静默按池回填两槽
    assert "不存在之人甲" in ei.value.names
    assert len(db.list_directives(state) or []) == 0


def test_cross_drafts_dual_unknown_escalates(game):
    """r13 定向负钉：两 draft 各一未知 → 全局失败槽=2 → _backfill 咬死全局闸返 None。

    每 draft 局部失败槽恰=1，局部一一对应会各自成功；无全局闸会静默双修。
    直接构造 baseline/correction 调 _backfill_healed_participant_refs（不经 e2e
    先行拒绝旁路），mutation：删/旁路全局 ≠1 闸 → 本钉须红。
    """
    import ming_sim.cli_backend as cb

    db, _state, content = game
    _biziyan(content)
    r1 = _active_minister(db, content).name
    r2 = _active_minister(db, content, exclude=r1).name
    player = (
        f"两道旨：着不存在之人甲核拨辽饷、着不存在之人乙整饬边军；"
        f"可令{r1}、{r2}分办"
    )

    def _drafts(roster0, roster1):
        return {
            "drafts": [
                {
                    "draft_text": "着核拨辽饷。",
                    "participant_roster": roster0,
                },
                {
                    "draft_text": "着边军整饬器械。",
                    "participant_roster": roster1,
                },
            ]
        }

    baseline = _drafts(
        [{"character_id": "不存在之人甲", "tier": "主办", "role": "核"}],
        [{"character_id": "不存在之人乙", "tier": "主办", "role": "整"}],
    )
    # 纠错轮两槽都换成接地新人——按单 roster 独立计数会分别通过
    correction = _drafts(
        [{"character_id": r1, "tier": "主办", "role": "核"}],
        [{"character_id": r2, "tier": "主办", "role": "整"}],
    )

    # 前置：全局=2，各 draft 局部=1（证明「无全局闸则双修成功」的前提成立）
    assert cb._count_failed_person_slots(baseline, db=db, content=content) == 2
    assert cb._count_failed_person_slots_in_roster(
        baseline["drafts"][0]["participant_roster"], db=db, content=content,
    ) == 1
    assert cb._count_failed_person_slots_in_roster(
        baseline["drafts"][1]["participant_roster"], db=db, content=content,
    ) == 1
    pending = ["不存在之人甲", "不存在之人乙"]
    for i, (bd, cd) in enumerate(zip(baseline["drafts"], correction["drafts"])):
        local = cb._patch_roster_slots_one_to_one(
            bd["participant_roster"],
            cd["participant_roster"],
            player_message=player,
            failed_slot_refs=pending,
            db=db,
            content=content,
        )
        assert local is not None, f"draft[{i}] 局部一一对应须成功（否则负钉前提崩）"

    # 定向钉：全局闸 ≠1 → backfill 必须拒修（禁分别局部修补落库）
    out = cb._backfill_healed_participant_refs(
        baseline,
        correction,
        pending_unknown=pending,
        player_message=player,
        db=db,
        content=content,
    )
    assert out is None


def test_single_unknown_with_institution_heals(game, monkeypatch):
    """r12 负钉：单未知 + 机构项 → 机构不算失败槽，唯一人物失败槽同下标修补。"""
    import ming_sim.cli_backend as cb

    db, _state, content = game
    _biziyan(content)
    replacement = _active_minister(db, content).name
    player = f"着不存在之人甲与户部核拨辽饷，可令{replacement}主事"
    minister_reply = "臣遵拟。"

    first_roster = [
        {"character_id": "不存在之人甲", "tier": "主办", "role": "核辽饷"},
        {"character_id": "户部", "tier": "协办", "role": "会核"},
    ]
    fixed_roster = [
        {"character_id": replacement, "tier": "主办", "role": "核辽饷"},
        {"character_id": "户部", "tier": "协办", "role": "会核"},
    ]

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            raise AssertionError("机构项不得抬升失败槽数导致 escalate")
        roster = fixed_roster if _CORRECTION_MARK in prompt else first_roster
        return (
            json.dumps({
                "拟旨意图": "拟旨",
                "动作类型": "policy",
                "目标类型": "issue",
                "目标ID": "liao-pay",
                "正文": "着核拨辽饷。",
                "参与人": roster,
            }, ensure_ascii=False),
            1,
        )

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    # 机构排除后全局失败槽=1，应正常修补
    assert cb._count_failed_person_slots(
        {"participant_roster": first_roster}, db=db, content=content,
    ) == 1
    result = cb.extract_draft_intent_with_semantic_heal(
        player, minister_reply, db=db, content=content,
    )
    ids = [
        str(i.get("character_id") or "")
        for i in (result.get("participant_roster") or [])
    ]
    assert ids == [replacement]
    assert "户部" not in ids


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
