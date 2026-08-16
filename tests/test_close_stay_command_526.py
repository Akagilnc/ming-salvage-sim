"""#526 / #471 S10 收夜口令 + 留侍口令。

Seams:
- 口令常量封闭集 / 结构化判词缝（非 ACTION_CLUSTERS、非第二 parser）
- audience_night.close_night 收夜链（收夜=封窗=提交）
- #500 故事账 + present_names_at 在场真源
- #515 P5：判词缝脚本化 + 与回话并行 barrier/毒化

不断言 LLM 语义；「令退下」归 #500，本片不 own。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import ming_sim.audience_night as an
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.session import GameSession

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}

# 闲聊负例：不得误触收夜
_CHAT_NEGATIVES = (
    "卿且坐。",
    "边饷如何？",
    "今日天气如何？",
    "退了再说军饷的事。",  # 含「退」字但非收夜口令
)


def _active_minister(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )


def _session(db, state, content, *, reply="臣领旨。", tools=None):
    class FakeAgent:
        def run(self, _msg):
            return SimpleNamespace(content=reply, tools=list(tools or []))

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda _c: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = set()
    sess._retrieve_memories_for_message = lambda message: message
    sess._audience_prompt_for_message = lambda message, character, chat_turn_id=0: message
    sess._start_cli_action_intent = lambda *a, **k: None
    sess._finish_cli_action_intent = lambda *a, **k: []
    sess.start_exit_scene_from_dismiss_tools = lambda *a, **k: None
    return sess


def _silence_action_extractors(monkeypatch):
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "无", "draft_text": "", "target_candidate": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)


def _open_with_minister(db, state, content):
    """开夜+入殿；不建 generating 轮——单测 chat_turn_id=0 路径当场收夜。"""
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, minister.name)
    return minister, nid


# ── AC：高置信收夜话语 → 收夜提交全程 ──────────────────────────────────


@pytest.mark.parametrize("utterance", ["退朝", "今日且到此"])
def test_high_confidence_close_command_submits_full_chain(game, monkeypatch, utterance):
    """高置信口令 → close_night：夜 closed + 已应允候选提交（封窗=提交）。"""
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    text = "着户部核边饷，限三月完报。"
    pid = db.stage_directive_candidate(
        state.turn, minister.name,
        payload={**_POLICY_FIELDS, "text": text, "actor": minister.name},
    )
    assert an.mark_actions_night_approved(db, [pid], night_id=nid) == 1

    sess = _session(db, state, content, reply="臣等恭送。")
    # 判词缝：确定性封闭集应直接给出 close；也允许脚本化注入同形
    result = sess.chat(minister.name, utterance)

    assert result.court_action == "court_break"
    night = an.get_night(db, nid)
    assert night is not None and night["status"] == "closed"
    closes = [
        e for e in an.list_ledger(db, nid)
        if an.TAG_CLOSE_NIGHT in (e.get("tags") or [])
    ]
    assert closes, "收夜账应落"
    # 已应允候选收夜提交：不再滞留 night_approved pending；pending 终态 committed
    assert not db.list_night_approved_pending(nid, kind="directive")
    prow = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pid,),
    ).fetchone()
    assert prow is not None and prow["status"] == "committed"
    # 收夜=落案卷/draft（ADR 0055：效果判后物化；此处不断言 issued）
    drafts = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE turn=?", (int(state.turn),),
    ).fetchall()
    assert any((r["text"] == text and r["status"] == "draft") for r in drafts), drafts


# ── AC：含糊 → 戏内确认、不直接收夜 ────────────────────────────────────


def test_ambiguous_close_asks_in_character_without_closing(game, monkeypatch):
    """真实话语路径须自产 ambiguous_close——禁止 monkeypatch/scripted 顶替生产识别。"""
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    sess = _session(db, state, content, reply="臣……")

    result = sess.chat(minister.name, "今日就到这里吧？")

    assert an.recognize_audience_command("今日就到这里吧？") == an.CMD_AMBIGUOUS_CLOSE
    assert result.court_action != "court_break"
    assert an.get_night(db, nid)["status"] == "open"
    assert "陛下是要退朝么" in (result.answer or "")
    closes = [e for e in an.list_ledger(db, nid) if an.TAG_CLOSE_NIGHT in (e.get("tags") or [])]
    assert closes == []


def test_close_night_failure_does_not_silent_court_break(game, monkeypatch):
    """收夜提交失败不得静默保留 court_break 成功信号（ADR 0005）。"""
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    sess = _session(db, state, content, reply="臣等恭送。")

    def _boom(*_a, **_k):
        raise an.AudienceNightError("close boom", code="test_close_boom")

    monkeypatch.setattr(an, "close_night", _boom)
    with pytest.raises(an.AudienceNightError, match="close boom"):
        sess.chat(minister.name, "退朝")

    assert an.get_night(db, nid)["status"] == "open"
    closes = [e for e in an.list_ledger(db, nid) if an.TAG_CLOSE_NIGHT in (e.get("tags") or [])]
    assert closes == []


def test_close_night_after_chat_propagates_failure(game, monkeypatch):
    """epilogue 收夜失败须上抛，不得 return/pass 成成功。"""
    db, state, content = game
    minister, nid = _open_with_minister(db, state, content)
    sess = _session(db, state, content)
    assert an.get_night(db, nid)["status"] == "open"

    def _boom(*_a, **_k):
        raise an.AudienceNightError("epilogue boom", code="test_epilogue_boom")

    monkeypatch.setattr(an, "close_night", _boom)
    with pytest.raises(an.AudienceNightError, match="epilogue boom"):
        sess.close_night_after_chat_if_needed("court_break")
    assert an.get_night(db, nid)["status"] == "open"


# ── AC：闲聊负例零误触 ────────────────────────────────────────────────


@pytest.mark.parametrize("utterance", _CHAT_NEGATIVES)
def test_chat_negatives_do_not_close_night(game, monkeypatch, utterance):
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    sess = _session(db, state, content, reply="臣回奏。")

    result = sess.chat(minister.name, utterance)

    assert result.court_action != "court_break"
    assert an.get_night(db, nid)["status"] == "open"
    assert "陛下是要退朝么" not in (result.answer or "")


# ── AC：留侍口令 → 叙事账、在场不变 ────────────────────────────────────


def test_stay_attend_writes_narrative_ledger_presence_unchanged(game, monkeypatch):
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    before = an.present_names_at(db, nid)
    assert minister.name in before
    seq_before = int(an.list_ledger(db, nid)[-1]["seq"])

    sess = _session(db, state, content, reply="臣遵旨侍立。")
    result = sess.chat(minister.name, "留下听着")

    assert result.court_action in ("", "stay_attend", "handled")
    after = an.present_names_at(db, nid)
    assert after == before  # 在场集合不变——不得制造进出事件
    last = an.list_ledger(db, nid)[-1]
    assert int(last["seq"]) > seq_before
    assert an.TAG_STAY_ATTEND in (last.get("tags") or [])
    assert minister.name in (last.get("person_names") or [])
    # 不得落告退
    assert an.TAG_EXIT not in (last.get("tags") or [])
    assert an.get_night(db, nid)["status"] == "open"


def test_stay_attend_engine_seam_no_presence_delta(game):
    """引擎 seam：stay_attend_in_audience 落账且 _presence_delta 为 None。"""
    db, state, content = game
    minister = _active_minister(db, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, minister.name)
    before = an.present_names_at(db, nid)

    entry_id = an.stay_attend_in_audience(db, minister.name, night_id=nid)
    assert entry_id
    entry = an.list_ledger(db, nid)[-1]
    assert an.TAG_STAY_ATTEND in entry["tags"]
    assert an._presence_delta(entry) is None
    assert an.present_names_at(db, nid) == before


# ── 结构化判词缝（确定性封闭集）────────────────────────────────────────


def test_recognize_closed_set_high_confidence_ambiguous_and_stay():
    assert an.recognize_audience_command("退朝") == an.CMD_CLOSE_NIGHT
    assert an.recognize_audience_command("今日且到此") == an.CMD_CLOSE_NIGHT
    assert an.recognize_audience_command("今日就到这里吧？") == an.CMD_AMBIGUOUS_CLOSE
    assert an.recognize_audience_command("留下听着") == an.CMD_STAY_ATTEND
    assert an.recognize_audience_command("卿且坐。") == an.CMD_NONE


def test_normalize_bad_shape_is_none_not_machine_effect():
    """坏 shape 由单一窄归一边界 → none；不宽吞代码异常。"""
    assert an.normalize_audience_command_verdict({"not": "a_verdict"}) == an.CMD_NONE
    assert an.normalize_audience_command_verdict("close_night") == an.CMD_CLOSE_NIGHT


# ── 表驱动：真实话语 → 机械面（无 Future / 无 scripted 注入）──────────────


_COMMAND_TABLE_CASES = (
    # utterance, expect_close, expect_stay, expect_ask
    ("退朝", True, False, False),
    ("今日且到此", True, False, False),
    ("留下听着", False, True, False),
    ("今日就到这里吧？", False, False, True),
    ("卿且坐。", False, False, False),
)
_COMMAND_TABLE_IDS = (
    "close_tuichao",
    "close_jinyi",
    "stay_attend",
    "ambiguous_close",
    "chat_none",
)


@pytest.mark.parametrize(
    ("utterance", "expect_close", "expect_stay", "expect_ask"),
    _COMMAND_TABLE_CASES,
    ids=_COMMAND_TABLE_IDS,
)
def test_audience_command_table_via_chat(
    game, monkeypatch, utterance, expect_close, expect_stay, expect_ask,
):
    """真实识别接缝：同步封闭集 → chat 机械面；无并行 Future 要求。"""
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    before_present = an.present_names_at(db, nid)
    sess = _session(db, state, content, reply="臣在。")

    result = sess.chat(minister.name, utterance)

    if expect_close:
        assert result.court_action == "court_break"
        assert an.get_night(db, nid)["status"] == "closed"
    else:
        assert an.get_night(db, nid)["status"] == "open"
        if expect_stay:
            last = an.list_ledger(db, nid)[-1]
            assert an.TAG_STAY_ATTEND in (last.get("tags") or [])
            assert an.present_names_at(db, nid) == before_present
        if expect_ask:
            assert "陛下是要退朝么" in (result.answer or "")
        if not expect_stay and not expect_ask:
            assert result.court_action != "court_break"
            assert "陛下是要退朝么" not in (result.answer or "")


def test_bad_shape_command_recognize_zero_machine_effect(game, monkeypatch):
    """坏 shape 归一 none：保留回话、不收夜、不落留侍、不追问。"""
    db, state, content = game
    _silence_action_extractors(monkeypatch)
    minister, nid = _open_with_minister(db, state, content)
    before_present = an.present_names_at(db, nid)
    seq_before = int(an.list_ledger(db, nid)[-1]["seq"])

    monkeypatch.setattr(an, "recognize_audience_command", lambda message: {"not": "a_verdict"})
    sess = _session(db, state, content, reply="臣惶恐。")
    result = sess.chat(minister.name, "退朝")

    assert "臣惶恐" in (result.answer or "")
    assert an.get_night(db, nid)["status"] == "open"
    assert an.present_names_at(db, nid) == before_present
    assert int(an.list_ledger(db, nid)[-1]["seq"]) == seq_before
    assert "陛下是要退朝么" not in (result.answer or "")
    assert result.court_action != "court_break"


def test_close_stay_not_in_action_clusters():
    """口令不得登记进 ACTION_CLUSTERS。"""
    import ming_sim.action_materialize  # noqa: F401
    from ming_sim.action_clusters import ACTION_CLUSTERS, KNOWN_KINDS

    banned = {"close_night", "stay_attend", "收夜", "留侍", "court_break"}
    kinds = {c.kind for c in ACTION_CLUSTERS} | set(KNOWN_KINDS)
    labels = {c.label_zh for c in ACTION_CLUSTERS}
    assert not (banned & kinds)
    assert not (banned & labels)
