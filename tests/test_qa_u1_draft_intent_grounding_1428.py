"""#1428 拟诏抽取接地：capture 缝把 content.characters name+aliases 作结构化事实喂抽取。

finding：LLM 把「毕自严」截成「毕自」→ _canonical_minister_key 不做子串 → 409。
修法：接地=结构化事实注入（禁散文守门族 ADR 0142）；未匹配参与人仍整单 409。
"""

from __future__ import annotations

import json

import pytest


def _biziyan_in_content(content) -> object:
    ch = content.characters.get("毕自严")
    assert ch is not None, "夹具名册须含毕自严"
    return ch


def test_capture_feeds_character_name_aliases_into_extract_prompt(game, monkeypatch):
    """capture 须把 content.characters 的 name+aliases 注入 extract_draft_intent prompt。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    ch = _biziyan_in_content(content)
    aliases = [str(a).strip() for a in (ch.aliases or []) if str(a).strip()]
    text = "着毕自严核拨辽饷"
    seen: list[str] = []

    def backend(prompt, *_a, **_k):
        seen.append(prompt)
        return (
            json.dumps(
                {
                    "拟旨意图": "拟旨",
                    "动作类型": "policy",
                    "目标类型": "issue",
                    "目标ID": "liao-pay",
                    "参与人": [{"character_id": "毕自严", "tier": "主办"}],
                },
                ensure_ascii=False,
            ),
            1,
        )

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    cli_backend.capture_manual_directive_payload(text, None, db=db, content=content)

    assert seen, "capture 须调用抽取"
    prompt = seen[0]
    assert "毕自严" in prompt
    # aliases 作为事实进 prompt（至少一条非本名的别名，若有）
    non_self = [a for a in aliases if a != "毕自严"]
    if non_self:
        assert any(a in prompt for a in non_self), f"别名须入 prompt，got none of {non_self}"
    # 参与人口径钉规范名，禁截短——结构化契约提示，非散文 regex 守门
    assert "规范名" in prompt


def test_capture_biziyan_full_name_zero_409(game, monkeypatch):
    """毕自严全名过 capture：零 409，roster 落规范名。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    _biziyan_in_content(content)
    text = "着毕自严核拨辽饷，不得加派于民"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "liao-pay",
        "参与人": [{"character_id": "毕自严", "tier": "主办", "role": "核辽饷"}],
    }
    monkeypatch.setattr(
        cli_backend,
        "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    ids = [str(item["character_id"]) for item in (payload.get("participant_roster") or [])]
    assert ids == ["毕自严"]
    assert "毕自" not in ids  # 「毕自」类截断不得落库

    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0


def test_capture_truncation_style_name_still_whole_order_409(game, monkeypatch):
    """owner 分叉未拍：LLM 若仍吐截断名「毕自」，整单 409 语义不变（禁放宽失配）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    _biziyan_in_content(content)
    text = "着毕自严核拨辽饷"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "liao-pay",
        "参与人": [{"character_id": "毕自", "tier": "主办"}],
    }
    monkeypatch.setattr(
        cli_backend,
        "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    with pytest.raises(ValueError, match="参与人物不存在"):
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )


def test_capture_unknown_person_still_409(game, monkeypatch):
    """不存在之人仍整单 409（ADR 0053 缝不松）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着不存在之人甲核太仓"
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "x",
        "参与人": [{"character_id": "不存在之人甲", "tier": "主办"}],
    }
    monkeypatch.setattr(
        cli_backend,
        "_run_backend_for_config",
        lambda *_a, **_k: (json.dumps(response, ensure_ascii=False), 1),
    )
    with pytest.raises(ValueError, match="参与人物不存在"):
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )


def test_extract_draft_intent_prompt_grounds_roster_when_content_given(game, monkeypatch):
    """extract_draft_intent 直接接 content 时，prompt 含 name+aliases 事实块。"""
    import ming_sim.cli_backend as cli_backend

    _db, _state, content = game
    ch = _biziyan_in_content(content)
    seen: list[str] = []

    def backend(prompt, *_a, **_k):
        seen.append(prompt)
        return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    cli_backend.extract_draft_intent(
        "拟旨吧", "臣遵旨。", content=content,
    )
    assert seen
    prompt = seen[0]
    assert "毕自严" in prompt
    for alias in (ch.aliases or []):
        a = str(alias).strip()
        if a and a != "毕自严":
            assert a in prompt
            break
