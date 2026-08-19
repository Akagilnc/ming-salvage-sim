"""#1279 拟诏部院归一：capture seam 不把机构/自称/集体名抽成人物参与人。

不变式：人物参与人抽取只产 characters 名册可解析的人名；非人名实体不产人物参与人行。
禁放松 ADR 0053 主键校验缝（db.py _validate_participant_roster_references）。
"""

from __future__ import annotations

import asyncio
import json
import types

import pytest


def _mock_draft_intent(monkeypatch, *, text: str, roster):
    import ming_sim.cli_backend as cli_backend

    response = {
        "拟旨意图": "拟旨",
        "动作类型": "policy",
        "目标类型": "issue",
        "目标ID": "treasury-audit",
        "参与人": roster,
    }

    def backend(prompt, *_args, **_kwargs):
        emperor = prompt.split("【皇帝】", 1)[1].split("【大臣回话】", 1)[0]
        if "请据此拟旨" not in emperor or text not in emperor:
            return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)
        return (json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)


def _web_create(game_tuple, monkeypatch, text: str):
    import web_app
    from ming_sim.session import GameSession

    db, state, content = game_tuple
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    web_game = types.SimpleNamespace(
        db=db, state=state, content=content, session=session,
        directive_rows=lambda: db.list_directives(
            state, statuses=("pending", "draft"),
        ),
        directive_payload=lambda row: dict(row),
    )
    monkeypatch.setattr(web_app, "get_game", lambda: web_game)
    return asyncio.run(web_app.api_create_directive(
        web_app.DirectiveRequest(text=text),
    ))


def test_capture_manual_directive_drops_ministry_name_as_participant(game, monkeypatch):
    """着户部… 不得把「户部」当人物参与人拒收；成案零 409。"""
    import ming_sim.cli_backend as cli_backend

    db, state, content = game
    text = "着户部核清太仓实存，边饷优先"
    _mock_draft_intent(
        monkeypatch, text=text,
        roster=[{"character_id": "户部", "tier": "主办", "role": "核太仓"}],
    )

    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    roster = payload.get("participant_roster") or []
    assert all(str(item.get("character_id") or "") != "户部" for item in roster)

    from ming_sim.session import GameSession
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    session.llm_config = None
    session.content = content
    dv = session.add_directive(text, dossier_payload=payload)
    assert dv.id > 0
    assert db.list_directives(state)


def test_web_create_directive_accepts_ministry_subject_without_409(game, monkeypatch):
    """Web POST /api/directives：着户部… 不得 409「参与人物不存在：户部」。"""
    db, _state, _content = game
    text = "着户部核清太仓实存，边饷优先"
    _mock_draft_intent(
        monkeypatch, text=text,
        roster=[{"character_id": "户部", "tier": "主办"}],
    )

    result = _web_create(game, monkeypatch, text)
    assert result["directive"]["id"] > 0
    assert result["directive"]["text"] == text
    # ADR 0053 缝仍在：未知真名仍应拒——此处仅断言部院名不撞墙。
    assert db.list_directives(game[1])


def test_capture_manual_directive_keeps_real_person_participant(game, monkeypatch):
    """着毕自严… 仍照常抽人（名册可解析人名保留）。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着毕自严核清太仓实存，边饷优先"
    _mock_draft_intent(
        monkeypatch, text=text,
        roster=[{"character_id": "毕自严", "tier": "主办", "role": "核太仓"}],
    )

    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    roster = payload.get("participant_roster") or []
    assert [item["character_id"] for item in roster] == ["毕自严"]


@pytest.mark.parametrize("name", ["陛下", "皇帝", "朝廷", "内阁", "都察院", "兵部"])
def test_capture_manual_directive_drops_collective_and_institution_names(
    game, monkeypatch, name,
):
    """自称/集体名与部院机构名均不成为人物参与人。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = f"着{name}核办边饷"
    _mock_draft_intent(
        monkeypatch, text=text,
        roster=[
            {"character_id": name, "tier": "主办"},
            {"character_id": "毕自严", "tier": "协办"},
        ],
    )

    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    roster = payload.get("participant_roster") or []
    ids = [str(item["character_id"]) for item in roster]
    assert name not in ids
    assert ids == ["毕自严"]


def test_adr0053_unknown_person_still_rejected_at_capture(game, monkeypatch):
    """禁放松主键校验：真正不存在的人名仍在 capture seam 拒收。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    text = "着不存在之人核太仓"
    _mock_draft_intent(
        monkeypatch, text=text,
        roster=[{"character_id": "不存在之人甲", "tier": "主办"}],
    )

    with pytest.raises(ValueError, match="参与人物不存在"):
        cli_backend.capture_manual_directive_payload(
            text, None, db=db, content=content,
        )
