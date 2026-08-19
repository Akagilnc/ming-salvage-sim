"""#1279 / QA A-2 拟诏部院归一：capture seam 人物参与人 raw 层三分流。

不变式：
- 裸机构 token 整词 fullmatch（六部/都察院/内阁/寺监院府/厂卫/六科…）→ 不产人物行
  （禁 canon 后放行：司礼监/锦衣卫/东厂 恰为人名 alias；词表按明代衙门闭集扩）
- 自称/集体闭集（陛下/皇帝/朝廷/朕…）→ 不产
- 带姓称谓别名（韩阁老/毕户部/温阁老/曹太监/王兵部…）→ 走 canon 留人名
- 禁复用 _is_institution_like_name 子串字集判参与人
- 禁放松 ADR 0053 主键校验缝（db.py _validate_participant_roster_references）
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


def _capture_ids(game, monkeypatch, *, text: str, roster):
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    _mock_draft_intent(monkeypatch, text=text, roster=roster)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    return [str(item["character_id"]) for item in (payload.get("participant_roster") or [])]


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
    ids = _capture_ids(
        game, monkeypatch,
        text="着毕自严核清太仓实存，边饷优先",
        roster=[{"character_id": "毕自严", "tier": "主办", "role": "核太仓"}],
    )
    assert ids == ["毕自严"]


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("韩阁老", "韩爌"),
        ("毕户部", "毕自严"),
        ("温阁老", "温体仁"),
        ("曹太监", "曹化淳"),
        ("王兵部", "王在晋"),
    ],
)
def test_capture_manual_directive_keeps_surname_title_aliases(
    game, monkeypatch, alias, canonical,
):
    """带姓称谓别名不得当机构丢；走 canon 留人名（回归别名面，不只钉 aliases[0] 本名）。"""
    ids = _capture_ids(
        game, monkeypatch,
        text=f"着{alias}核办边饷",
        roster=[{"character_id": alias, "tier": "主办"}],
    )
    assert ids == [canonical]


@pytest.mark.parametrize(
    "name",
    [
        "陛下", "皇帝", "朝廷",
        "户部", "兵部", "内阁", "都察院",
        "司礼监", "锦衣卫", "东厂", "西厂",
        # r2 词表空洞亲证：闭集外明代衙门整词 → 不产人物行、零 409
        "大理寺", "翰林院", "钦天监", "通政使司", "通政司",
        "太仆寺", "光禄寺", "鸿胪寺", "太常寺",
        "国子监", "太医院", "宗人府", "五军都督府", "六科",
    ],
)
def test_capture_manual_directive_drops_collective_and_institution_names(
    game, monkeypatch, name,
):
    """自称/集体与裸机构整词均不成为人物参与人（含厂卫——禁 canon 后放行）。"""
    ids = _capture_ids(
        game, monkeypatch,
        text=f"着{name}核办边饷",
        roster=[
            {"character_id": name, "tier": "主办"},
            {"character_id": "毕自严", "tier": "协办"},
        ],
    )
    assert name not in ids
    assert "王承恩" not in ids
    assert "田尔耕" not in ids
    assert "魏忠贤" not in ids
    assert ids == ["毕自严"]


def test_non_person_filter_does_not_use_institution_substring_class():
    """参与人缝禁复用 _is_institution_like_name 子串字集（防韩阁老含「阁」被误伤）。"""
    import ming_sim.cli_backend as cli_backend

    # assignee-hint 子串仍拒识带机关字的线索（本职不变）
    assert cli_backend._is_institution_like_name("韩阁老") is True
    assert cli_backend._is_institution_like_name("毕户部") is True
    # 参与人 raw 三分流：带姓称谓别名不是裸机构，不得判非人
    assert cli_backend._is_non_person_participant_name("韩阁老") is False
    assert cli_backend._is_non_person_participant_name("毕户部") is False
    assert cli_backend._is_non_person_participant_name("曹太监") is False
    # 裸机构整词 / 自称仍非人（含 r2 扩入的寺监院府）
    assert cli_backend._is_non_person_participant_name("司礼监") is True
    assert cli_backend._is_non_person_participant_name("户部") is True
    assert cli_backend._is_non_person_participant_name("陛下") is True
    assert cli_backend._is_non_person_participant_name("大理寺") is True
    assert cli_backend._is_non_person_participant_name("翰林院") is True
    assert cli_backend._is_non_person_participant_name("通政使司") is True
    assert cli_backend._is_non_person_participant_name("西厂") is True


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
