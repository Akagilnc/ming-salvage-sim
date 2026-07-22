"""#515 S0：动作分类器扩展挂点 + 识别兜底 + 脚本化判词契约基座。

Seams under test:
- ming_sim.action_clusters（登记表 / list 归一 / strict shape）
- classify_cli_action_intent 输出 list 契约（经 monkeypatch 注入）
- apply_cli_conversation_actions 真入口（零 LLM）
- 并行：_start/_finish + 可控 future
- 撤回：经 hook stage 的 pending 进 chat_turn 前像链

不断言 LLM 语义正确率；不造第二套 undo。
"""

from __future__ import annotations

import json
import threading
import types
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import ming_sim.cli_backend as cb
from ming_sim import audience_night as an
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    ActionCandidateShapeError,
    KIND_TO_LABEL,
    LABEL_TO_KIND,
    assert_action_candidate_shape,
    candidates_from_classifier_payload,
    classifier_action_types_prompt,
    inject_scripted_candidates,
    normalize_intent_candidates,
    primary_intent,
    validate_action_candidate_shape,
)
from ming_sim.session import GameSession


# ── 登记表 = 单一扩展挂点 ──────────────────────────────────────────────


def test_registry_hosts_six_mechanical_clusters_and_drives_prompt_enum():
    kinds = {c.kind for c in ACTION_CLUSTERS}
    labels = {c.label_zh for c in ACTION_CLUSTERS}
    assert kinds == {"none", "confirmation", "secret", "cultivate", "appointment", "draft"}
    assert labels == {"无", "确认", "密令动作", "调教", "任免", "拟旨"}
    prompt = classifier_action_types_prompt()
    for lab in labels:
        assert lab in prompt
    # label ↔ kind 双向同源，禁止第二份清单漂移
    assert LABEL_TO_KIND["拟旨"] == "draft"
    assert KIND_TO_LABEL["appointment"] == "任免"
    assert any(c.answer_class for c in ACTION_CLUSTERS if c.kind == "confirmation")
    assert not any(c.answer_class for c in ACTION_CLUSTERS if c.kind == "draft")


# ── typed shape：严格拒 / 软判降 [] ───────────────────────────────────


def test_strict_shape_rejects_unknown_kind_and_out_of_enum_subfield():
    ok, reason = validate_action_candidate_shape({"kind": "treasury"})
    assert ok is False
    assert "unknown" in reason
    with pytest.raises(ActionCandidateShapeError):
        assert_action_candidate_shape({"动作类型": "拨帑"})
    with pytest.raises(ActionCandidateShapeError):
        inject_scripted_candidates({"kind": "appointment", "appoint_action": "流放"})


def test_soft_llm_path_degrades_bad_shape_to_empty_list():
    assert candidates_from_classifier_payload({"动作类型": "拨帑"}, soft=True) == []
    assert candidates_from_classifier_payload({"kind": "nope"}, soft=True) == []
    assert candidates_from_classifier_payload("not-json-obj", soft=True) == []
    # 合法单条 → 长度 1 列表
    got = candidates_from_classifier_payload({"动作类型": "拟旨"}, soft=True)
    assert len(got) == 1
    assert got[0]["kind"] == "draft"
    # kind=none → []（无机械后果）
    assert candidates_from_classifier_payload({"动作类型": "无"}, soft=True) == []


def test_normalize_preserves_none_vs_empty_list_semantics():
    assert normalize_intent_candidates(None) is None
    assert normalize_intent_candidates({"kind": "none"}) == []
    assert normalize_intent_candidates([{"kind": "draft"}])[0]["kind"] == "draft"
    assert primary_intent(None) is None
    assert primary_intent([])["kind"] == "none"
    assert primary_intent([{"kind": "secret", "secret_action": "催办"}])["kind"] == "secret"


# ── 识别兜底：脚本判词 → apply 真入口 零写 / 正写 ─────────────────────


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db,
        state=state,
        registry=None,
        content=content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    return s


def _count_pending(db, turn) -> int:
    return len(db.list_pending_actions(int(turn)))


def test_unrecognized_scripted_verdict_zero_writes(game, monkeypatch):
    """不可识别 / 空候选 → 零 pending 写入（负向兜底）。"""
    db, state, content = game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
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
    sess = _bind_apply(db, state, content)
    before = _count_pending(db, state.turn)
    # 注入 [] = 分类器已跑、无动作
    out = sess.apply_cli_conversation_actions(
        minister, "今日天气如何？", "臣不敢妄言天象。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[],
    )
    assert out.get("pending_action_id") in (None, 0, "")
    assert _count_pending(db, state.turn) == before

    # 毒化 kind 经 soft 归一 → [] → 零写
    out2 = sess.apply_cli_conversation_actions(
        minister, "卿且坐。", "臣谢恩。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "not_a_cluster"},
    )
    assert out2.get("pending_action_id") in (None, 0, "")
    assert _count_pending(db, state.turn) == before


def test_scripted_appointment_stages_exactly_one_office_pending(game, monkeypatch):
    """正向：脚本化任免判词 → 恰一条 office pending（真 apply 入口）。"""
    db, state, content = game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    # 禁止串行抽取，证明只靠 preclassified
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial appointment extractor")))
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "无", "draft_text": "", "target_candidate": "",
    })
    sess = _bind_apply(db, state, content)
    before = _count_pending(db, state.turn)
    scripted = inject_scripted_candidates({
        "kind": "appointment",
        "appoint_action": "任命",
        "name": "测试候选人甲",
        "office": "陕西巡抚",
    })
    assert len(scripted) == 1
    out = sess.apply_cli_conversation_actions(
        minister, "着测试候选人甲为陕西巡抚。", "臣遵旨拟任。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    assert out.get("pending_action_id")
    rows = db.list_pending_actions(int(state.turn), minister_name=minister.name)
    office_rows = [r for r in rows if r["kind"] == "office"]
    assert len(office_rows) == 1
    assert office_rows[0]["action"] == "任命"
    payload = json.loads(office_rows[0]["payload_json"] or "{}")
    assert payload.get("name") == "测试候选人甲"
    assert _count_pending(db, state.turn) == before + 1


def test_scripted_confirmation_does_not_stage_new_pending(game, monkeypatch):
    """confirmation 是应答类：只处置既有 pending，不新 stage。"""
    db, state, content = game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    pid = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister.name, target_id=None,
        payload={"name": "某人", "office": "某职", "appointer": minister.name},
    )
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "应允")
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
    sess = _bind_apply(db, state, content)
    before_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))}
    out = sess.apply_cli_conversation_actions(
        minister, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={int(pid)},
    )
    # 不应新建另一条 pending（应允可能 commit/night_approve 原行）
    after = db.list_pending_actions(int(state.turn))
    new_ids = {int(r["id"]) for r in after} - before_ids
    assert not new_ids
    assert out.get("pending_action_id") in (None, 0, "")


# ── P5 并行：可控 future，回话延迟不改判词；毒化 → [] ───────────────


def test_finish_poisoned_classifier_yields_empty_list_not_none(game):
    db, state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")

    fut: Future = Future()
    fut.set_result({"kind": "not_registered", "appoint_action": "流放"})
    assert sess._finish_cli_action_intent(fut) == []

    fut2: Future = Future()
    fut2.set_exception(RuntimeError("classifier boom"))
    assert sess._finish_cli_action_intent(fut2) == []

    assert sess._finish_cli_action_intent(None) is None

    fut3: Future = Future()
    fut3.set_result([{"kind": "draft"}])
    got = sess._finish_cli_action_intent(fut3)
    assert isinstance(got, list) and len(got) == 1 and got[0]["kind"] == "draft"


def test_parallel_classifier_verdict_independent_of_reply_delay(game, monkeypatch):
    """分类调度与回话并行：判词在回话完成前已定，回话延迟/失败不改写结构化候选。"""
    db, state, content = game
    minister = next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )
    classifier_started = threading.Event()
    allow_classify = threading.Event()
    verdict = [{"kind": "draft"}]
    captured: list = []

    def fake_classify(*a, **k):
        classifier_started.set()
        assert allow_classify.wait(2), "classify should be releasable"
        return list(verdict)

    class FakeAgent:
        def run(self, _msg):
            # 回话前分类器必须已启动（并行）
            assert classifier_started.wait(1), "classifier must start before reply finishes"
            allow_classify.set()
            return SimpleNamespace(content="臣已拟旨如下……", tools=[])

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda character: FakeAgent(),
        build_draft_line=lambda: "无",
    )
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message

    monkeypatch.setattr("ming_sim.session._dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    # 回话后串行抽取不得覆盖：用 preclassified 路径
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨", "draft_text": "伪串行草案应被 preclassified 挡住优先路径",
        "target_candidate": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")

    # 直接测 start/finish 并行契约 + apply 用 finish 结果
    fut = sess._start_cli_action_intent(minister, "拟一道旨赈陕西。")
    assert fut is not None
    # 不放行 classify 时 future 未完成；回话侧可先跑 agent——此处用 finish join
    allow_classify.set()
    candidates = sess._finish_cli_action_intent(fut)
    assert isinstance(candidates, list) and len(candidates) == 1
    assert candidates[0]["kind"] == "draft"
    captured.append(candidates)

    sess_apply = _bind_apply(db, state, content)
    before = _count_pending(db, state.turn)
    out = sess_apply.apply_cli_conversation_actions(
        minister, "拟一道旨赈陕西。", "臣已拟旨如下：着户部发银赈陕西。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=candidates,
    )
    assert out.get("pending_action_id")
    assert _count_pending(db, state.turn) == before + 1
    row = db.list_pending_actions(int(state.turn), minister_name=minister.name)[-1]
    assert row["kind"] == "directive"


# ── 撤回：经 hook stage 的原地修改前像恢复 ───────────────────────────


def _active_minister(db, content):
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("no minister")


def test_in_place_directive_update_via_hook_restored_on_undo(game, monkeypatch):
    """#515 AC：经新挂点/脚本判词 stage 后，原地改候选；撤回本轮恢复前像（ADR 0038）。"""
    db, state, content = game
    m = _active_minister(db, content)
    an.open_night(db, state, location="文华殿", time_of_day="午")

    # 轮 1：经 apply + scripted draft 新建候选
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")
    minister_ch = content.characters[m]
    sess = _bind_apply(db, state, content)

    def _seal_round(chat_id: int, reply: str = "臣遵旨。") -> None:
        uid = db.conn.execute(
            "INSERT INTO chat_messages (minister_name, turn, role, content) "
            "VALUES (?, ?, 'emperor', ?)",
            (m, state.turn, "拟旨。"),
        ).lastrowid
        mid = db.conn.execute(
            "INSERT INTO chat_messages (minister_name, turn, role, content) "
            "VALUES (?, ?, 'minister', ?)",
            (m, state.turn, reply),
        ).lastrowid
        db.conn.commit()
        db.update_chat_turn_messages(
            int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
        )
        db.conn.execute(
            "UPDATE chat_turns SET extract_status='done' WHERE id=?", (int(chat_id),)
        )
        db.conn.commit()

    before1 = db.capture_chat_rollback_snapshot()
    night_id, chat1 = an.attach_chat_turn_to_night(db, state, m)
    out1 = sess.apply_cli_conversation_actions(
        minister_ch, "拟旨赈灾。", "着户部发银三万两赈陕西。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=inject_scripted_candidates({"kind": "draft"}),
    )
    pid = int(out1["pending_action_id"])
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
    ).fetchone()
    original_text = json.loads(row["payload_json"])["text"]
    assert "三万" in original_text or "赈" in original_text
    _seal_round(chat1)
    after1 = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(int(chat1), before1, after1)

    # 轮 2：原地修改候选正文（跨轮更新既有候选）
    before2 = db.capture_chat_rollback_snapshot()
    _nid2, chat2 = an.attach_chat_turn_to_night(db, state, m)
    updated = db.update_directive_candidate(
        pid, payload={"text": "着户部发银五十万两赈陕西（改）。", "actor": m},
    )
    assert updated == pid
    _seal_round(chat2, reply="臣已改拟。")
    after2 = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(int(chat2), before2, after2)

    row_mid = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
    ).fetchone()
    assert "五十万" in json.loads(row_mid["payload_json"])["text"]

    # 撤回轮 2 → 前像恢复原文
    db.undo_chat_turn(int(chat2))
    row_after = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pid,)
    ).fetchone()
    assert row_after is not None
    assert json.loads(row_after["payload_json"])["text"] == original_text
