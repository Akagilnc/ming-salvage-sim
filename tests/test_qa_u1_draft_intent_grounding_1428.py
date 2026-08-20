"""#1428 拟诏抽取接地：capture/召对 缝把 content.characters name+aliases 作结构化事实喂抽取。

finding：LLM 把「毕自严」截成「毕自」→ _canonical_minister_key 不做子串 → 409。
修法：接地=结构化事实注入（禁散文守门族 ADR 0142）；未匹配参与人仍整单 409。
事实块资格与 canon 同口径（ming ∧ 非后宫 ∧ 非 candidate）。
"""

from __future__ import annotations

import json
import types

import pytest

from ming_sim.session import GameSession

_ROSTER_BLOCK_HEADER = "【在册人物规范名+别名】"


def _biziyan_in_content(content) -> object:
    ch = content.characters.get("毕自严")
    assert ch is not None, "夹具名册须含毕自严"
    return ch


def _assert_biziyan_roster_block(prompt: str, ch) -> None:
    """事实块头 + 毕自严规范名/别名（仅能来自新块的标记，禁弱断言）。"""
    assert _ROSTER_BLOCK_HEADER in prompt
    assert "毕自严（别名：" in prompt
    for alias in ("毕尚书", "南户部", "毕户部"):
        assert alias in prompt
    # 冗余：content 别名亦须可见（seed 漂移时仍钉夹具）
    for alias in (ch.aliases or []):
        a = str(alias).strip()
        if a and a != "毕自严":
            assert a in prompt


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
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩", "未仕")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )


def test_capture_feeds_character_name_aliases_into_extract_prompt(game, monkeypatch):
    """capture 须把 content.characters 的 name+aliases 注入 extract_draft_intent prompt。"""
    import ming_sim.cli_backend as cli_backend

    db, _state, content = game
    ch = _biziyan_in_content(content)
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
    _assert_biziyan_roster_block(seen[0], ch)


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
    _assert_biziyan_roster_block(seen[0], ch)


def test_roster_facts_exclude_ineligible_include_biziyan(game):
    """事实块资格=可召单真源：外藩别名/后宫/宗藩/未仕不入；毕自严+别名仍在。"""
    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import _is_summonable_court_minister

    _db, _state, content = game
    ch = _biziyan_in_content(content)
    facts = cli_backend._draft_intent_character_roster_facts(content)
    assert _ROSTER_BLOCK_HEADER in facts
    assert "毕自严（别名：" in facts
    for alias in ("毕尚书", "南户部", "毕户部"):
        assert alias in facts
    # 负向：外藩别名、后宫规范名/别名、未仕不得入块（#1317 r2 与可召谓词同口径）
    assert "黄台吉" not in facts
    assert "皇太极" not in facts
    assert "周皇后" not in facts
    assert "中宫" not in facts
    assert "史可法" not in facts
    # 体积：不得倾倒全表；行数=可召谓词命中数（单真源，禁手写第二份过滤）
    line_count = sum(1 for line in facts.splitlines() if line and not line.startswith("【"))
    assert line_count < len(content.characters)
    assert line_count == sum(
        1
        for c in content.characters.values()
        if _is_summonable_court_minister(c)
        and str(getattr(c, "name", None) or "").strip()
    )
    # seed 漂移防护
    for alias in (ch.aliases or []):
        a = str(alias).strip()
        if a and a != "毕自严":
            assert a in facts


def test_materialize_draft_grounds_roster_and_biziyan_zero_409(game, monkeypatch):
    """召对 _materialize_draft：抽取 prompt 含名册事实块；毕自严全名过拟旨零 409。"""
    import ming_sim.cli_backend as cb

    db, state, content = game
    ch_bi = _biziyan_in_content(content)
    minister = _active_minister(db, content)
    seen: list[str] = []

    def backend(prompt, llm_config=None, tag=""):
        if tag == "draft_intent":
            seen.append(prompt)
            return (
                json.dumps(
                    {
                        "拟旨意图": "拟旨",
                        "动作类型": "policy",
                        "目标类型": "issue",
                        "目标ID": "liao-pay",
                        "正文": "着毕自严核拨辽饷，不得加派于民。",
                        "参与人": [
                            {"character_id": "毕自严", "tier": "主办", "role": "核辽饷"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                1,
            )
        if tag == "appointment":
            return (
                json.dumps({"任免动作": "无", "姓名": "", "官职": ""}, ensure_ascii=False),
                1,
            )
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", backend)
    # 串行旁路静默，避免无关抽取干扰
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")

    sess = _fake_session(db, state, content)
    GameSession.apply_cli_conversation_actions(
        sess, minister,
        player_message="着毕自严核拨辽饷，卿其拟旨。",
        answer="臣遵旨：着毕自严核拨辽饷，不得加派于民。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    assert seen, "_materialize_draft 须调用 extract_draft_intent"
    _assert_biziyan_roster_block(seen[0], ch_bi)
    assert "黄台吉" not in seen[0]
    assert "周皇后" not in seen[0]

    pending = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert pending, "拟旨须落 directive"
    payload = json.loads(pending[-1]["payload_json"])
    ids = [
        str(item.get("character_id") or "")
        for item in (payload.get("participant_roster") or [])
        if isinstance(item, dict)
    ]
    assert ids == ["毕自严"]
    assert "毕自" not in ids
