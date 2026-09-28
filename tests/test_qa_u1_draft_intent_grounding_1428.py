"""#1428 手拟仍需结构化参与人准入：在册规范名可落档，截断/幻影名不可。"""

from __future__ import annotations

import json

import pytest

from ming_sim.session import GameSession

def _biziyan_in_content(content) -> object:
    ch = content.characters.get("毕自严")
    assert ch is not None, "夹具名册须含毕自严"
    return ch


def test_capture_biziyan_full_name_zero_409(game, monkeypatch):
    """毕自严全名过 capture：零 409，roster 落规范名。"""
    import ming_sim.cli_backend as cli_backend

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
    """纠错耗尽仍吐截断名「毕自」→ 人话兜底拒收（ADR 0053 缝不松；#1274 V-1）。"""
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

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「毕自」，乞陛下明示。", 1)
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError):
        cli_backend.capture_manual_directive_payload(text, None, db=db, content=content)


def test_capture_unknown_person_still_409(game, monkeypatch):
    """纠错耗尽仍吐不存在之人 → 人话兜底拒收（ADR 0053 缝不松；#1274 V-1）。"""
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

    def backend(prompt, *_a, tag="", **_k):
        if tag == "participant_escalate_report":
            return ("通政司启：朝中查无「不存在之人甲」，乞陛下明示。", 1)
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    with pytest.raises(ValueError):
        cli_backend.capture_manual_directive_payload(text, None, db=db, content=content)
