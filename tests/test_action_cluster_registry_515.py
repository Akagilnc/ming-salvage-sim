"""#515 S0：动作分类器扩展挂点 + 识别兜底 + 脚本化判词契约基座。

Seams:
- ming_sim.action_clusters（登记表 / shape / effect / materializer 挂接）
- ming_sim.action_materialize.run_materialize_pipeline（真实 consumer 唯一物化入口）
- session.chat / apply_cli_conversation_actions 生产入口
- ADR 0038 undo_chat_turn 经真实轮级前像链

不断言 LLM 语义；不另造 undo 机制。
"""

from __future__ import annotations

import json
import threading
import types
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 — register materializers
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim import audience_night as an
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    EFFECT_ANSWER_EXISTING,
    EFFECT_MATERIALIZE,
    EFFECT_NOOP,
    ActionCandidateShapeError,
    KIND_TO_LABEL,
    LABEL_TO_KIND,
    assert_action_candidate_shape,
    candidates_from_classifier_payload,
    classifier_action_types_prompt,
    cluster_by_kind,
    get_materializer,
    inject_scripted_candidates,
    materialize_clusters_ordered,
    normalize_intent_candidates,
    primary_intent,
    validate_action_candidate_shape,
)
from ming_sim.session import GameSession


# ── 登记表 = 单一扩展挂点（表驱动，不写死六类字面量以外的契约）────────


def test_registry_drives_prompt_enums_effects_and_materializers():
    kinds = {c.kind for c in ACTION_CLUSTERS}
    labels = {c.label_zh for c in ACTION_CLUSTERS}
    # 六类均迁移（从登记动态断言，非平行清单）
    assert kinds == set(KIND_TO_LABEL)
    assert labels == set(LABEL_TO_KIND)
    prompt = classifier_action_types_prompt()
    for c in ACTION_CLUSTERS:
        assert c.label_zh in prompt
        assert LABEL_TO_KIND[c.label_zh] == c.kind
        assert KIND_TO_LABEL[c.kind] == c.label_zh
    # effect 表达 none/confirmation 语义
    assert cluster_by_kind("none").effect == EFFECT_NOOP
    assert cluster_by_kind("confirmation").effect == EFFECT_ANSWER_EXISTING
    for c in materialize_clusters_ordered():
        assert c.effect == EFFECT_MATERIALIZE
        assert get_materializer(c.kind) is not None, f"{c.kind} missing materializer"
    # 子枚举挂在登记行上
    conf = cluster_by_kind("confirmation")
    assert any(f.name == "confirmation" and f.allowed for f in conf.fields)
    appt = cluster_by_kind("appointment")
    assert any(f.name == "appoint_action" and "任命" in (f.allowed or []) for f in appt.fields)


def test_registry_rows_generate_shape_contract_matrix():
    """每个登记 materialize/answer 行至少一条合法 shape；枚举外统一拒。"""
    for c in ACTION_CLUSTERS:
        if c.kind == "none":
            assert candidates_from_classifier_payload({"kind": "none"}, soft=True) == []
            continue
        base = {"kind": c.kind}
        for f in c.fields:
            if f.allowed:
                base[f.name] = next(iter(f.allowed - {"无"})) if (f.allowed - {"无"}) else next(iter(f.allowed))
            elif f.as_int:
                base[f.name] = 1
            else:
                base[f.name] = "x"
        got = inject_scripted_candidates(base)
        assert len(got) == 1 and got[0]["kind"] == c.kind
        # 枚举外
        for f in c.fields:
            if not f.allowed:
                continue
            bad = dict(base)
            bad[f.name] = "__not_in_enum__"
            with pytest.raises(ActionCandidateShapeError):
                inject_scripted_candidates(bad)


# ── typed shape ─────────────────────────────────────────────────────


def test_strict_shape_rejects_unknown_kind_and_out_of_enum_subfield():
    ok, reason = validate_action_candidate_shape({"kind": "treasury"})
    assert ok is False and "unknown" in reason
    with pytest.raises(ActionCandidateShapeError):
        assert_action_candidate_shape({"动作类型": "拨帑"})
    with pytest.raises(ActionCandidateShapeError):
        inject_scripted_candidates({"kind": "appointment", "appoint_action": "流放"})


def test_soft_llm_path_degrades_bad_shape_to_empty_list():
    assert candidates_from_classifier_payload({"动作类型": "拨帑"}, soft=True) == []
    assert candidates_from_classifier_payload({"kind": "nope"}, soft=True) == []
    got = candidates_from_classifier_payload({"动作类型": "拟旨"}, soft=True)
    assert len(got) == 1 and got[0]["kind"] == "draft"
    assert candidates_from_classifier_payload({"动作类型": "无"}, soft=True) == []


def test_normalize_preserves_none_vs_empty_list_semantics():
    assert normalize_intent_candidates(None) is None
    assert normalize_intent_candidates({"kind": "none"}) == []
    assert primary_intent(None) is None
    assert primary_intent([])["kind"] == "none"


# ── 识别兜底：apply 真入口 ───────────────────────────────────────────


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


def _active_ch(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )


def _silence_serial(monkeypatch):
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


def test_unrecognized_scripted_verdict_zero_writes(game, monkeypatch):
    db, state, content = game
    minister = _active_ch(db, content)
    _silence_serial(monkeypatch)
    sess = _bind_apply(db, state, content)
    before = _count_pending(db, state.turn)
    out = sess.apply_cli_conversation_actions(
        minister, "今日天气如何？", "臣不敢妄言天象。",
        has_directive=False, secret_order_id=None, preclassified_intent=[],
    )
    assert out.get("pending_action_id") in (None, 0, "")
    assert _count_pending(db, state.turn) == before
    out2 = sess.apply_cli_conversation_actions(
        minister, "卿且坐。", "臣谢恩。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "not_a_cluster"},
    )
    assert out2.get("pending_action_id") in (None, 0, "")
    assert _count_pending(db, state.turn) == before


def test_scripted_appointment_stages_via_registry_materializer(game, monkeypatch):
    db, state, content = game
    minister = _active_ch(db, content)
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
    out = sess.apply_cli_conversation_actions(
        minister, "着测试候选人甲为陕西巡抚。", "臣遵旨拟任。",
        has_directive=False, secret_order_id=None, preclassified_intent=scripted,
    )
    assert out.get("pending_action_id")
    office_rows = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "office"
    ]
    assert len(office_rows) == 1 and office_rows[0]["action"] == "任命"
    assert json.loads(office_rows[0]["payload_json"]).get("name") == "测试候选人甲"
    assert _count_pending(db, state.turn) == before + 1


def test_scripted_confirmation_answer_existing_no_new_stage(game, monkeypatch):
    db, state, content = game
    minister = _active_ch(db, content)
    pid = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister.name, target_id=None,
        payload={"name": "某人", "office": "某职", "appointer": minister.name},
    )
    _silence_serial(monkeypatch)
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "应允")
    sess = _bind_apply(db, state, content)
    before_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))}
    out = sess.apply_cli_conversation_actions(
        minister, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={int(pid)},
    )
    new_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))} - before_ids
    assert not new_ids
    assert out.get("pending_action_id") in (None, 0, "")


# ── P5：真实 session.chat 入口，回话延迟不改判词 ─────────────────────


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


def test_real_chat_parallel_classifier_stages_draft_despite_reply_delay(game, monkeypatch):
    """真实 session.chat：分类器在 FakeAgent.run 完成前启动；合法 draft 判词落候选。

    Event 控制回话：分类器先起、再放回话；串行抽取毒化文本不得覆盖 preclassified。
    """
    db, state, content = game
    minister = _active_ch(db, content)
    classifier_started = threading.Event()
    allow_reply = threading.Event()
    calls: list = []

    def fake_classify(*args, **kwargs):
        calls.append("classify")
        classifier_started.set()
        # 等回话线程证明并行：回话 run 会 set allow_reply；此处不阻塞死锁——
        # 分类器先返回判词，回话可独立完成。
        return [{"kind": "draft"}]

    class FakeAgent:
        def run(self, _msg):
            assert classifier_started.wait(2), "classifier must start before reply finishes"
            allow_reply.set()
            return SimpleNamespace(
                content="着户部发银赈陕西。",
                tools=[],
            )

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

    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    # 毒化串行：若被误用会 stage 错误正文
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨",
        "draft_text": "【毒化串行草案不应落库】",
        "target_candidate": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")

    before = _count_pending(db, state.turn)
    result = sess.chat(minister.name, "拟一道旨赈陕西。")
    assert allow_reply.is_set()
    assert calls == ["classify"]
    assert "着户部发银赈陕西" in (result.answer or "")
    assert result.pending_action_id
    assert _count_pending(db, state.turn) == before + 1
    row = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "directive"
    ][-1]
    text = json.loads(row["payload_json"])["text"]
    assert "赈陕西" in text
    assert "毒化" not in text


def test_real_chat_poisoned_classifier_zero_writes(game, monkeypatch):
    """毒化分类器 → finish=[] → chat 零 pending 写入。"""
    db, state, content = game
    minister = _active_ch(db, content)

    def fake_classify(*a, **k):
        return {"kind": "not_a_cluster", "appoint_action": "流放"}

    class FakeAgent:
        def run(self, _msg):
            return SimpleNamespace(content="臣惶恐。", tools=[])

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(get=lambda c: FakeAgent(), build_draft_line=lambda: "无")
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    _silence_serial(monkeypatch)
    before = _count_pending(db, state.turn)
    result = sess.chat(minister.name, "卿且坐。")
    assert result.answer == "臣惶恐。"
    assert not result.pending_action_id
    assert _count_pending(db, state.turn) == before


# ── 撤回：真实 chat 入口 stage + 轮级前像 + undo ─────────────────────


def _chat_session(db, state, content, agent, monkeypatch):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(get=lambda c: agent, build_draft_line=lambda: "无")
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    return sess


def _lifecycle_round(db, state, minister_name, *, write_fn):
    """对齐 WebGame 轮窗口：snapshot → attach → writes → seal messages → record diffs。"""
    before = db.capture_chat_rollback_snapshot()
    _night_id, chat_id = an.attach_chat_turn_to_night(db, state, minister_name)
    write_fn(int(chat_id))
    uid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'emperor', ?)",
        (minister_name, state.turn, "拟旨。"),
    ).lastrowid
    mid = db.conn.execute(
        "INSERT INTO chat_messages (minister_name, turn, role, content) "
        "VALUES (?, ?, 'minister', ?)",
        (minister_name, state.turn, "臣遵旨。"),
    ).lastrowid
    db.conn.commit()
    db.update_chat_turn_messages(
        int(chat_id), user_message_id=int(uid), minister_message_id=int(mid),
    )
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done' WHERE id=?", (int(chat_id),)
    )
    db.conn.commit()
    db.record_chat_turn_rollback_diffs(
        int(chat_id), before, db.capture_chat_rollback_snapshot(),
    )
    return int(chat_id)


def test_create_via_chat_then_undo_removes_candidate(game, monkeypatch):
    """创建：真实 chat + 脚本判词 → pending；撤回本轮 → 候选消失。"""
    db, state, content = game
    minister = _active_ch(db, content)
    an.open_night(db, state, location="文华殿", time_of_day="午")
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: [{"kind": "draft"}])
    _silence_serial(monkeypatch)

    class Agent:
        def run(self, _m):
            return SimpleNamespace(content="着户部发银三万两赈陕西。", tools=[])

    sess = _chat_session(db, state, content, Agent(), monkeypatch)

    def _write(_chat_id):
        # 生产 consumer：session.chat（分类器 + apply materialize）
        r = sess.chat(minister.name, "拟一道旨赈陕西。")
        assert r.pending_action_id

    chat_id = _lifecycle_round(db, state, minister.name, write_fn=_write)
    assert any(p["kind"] == "directive" for p in db.list_pending_actions(int(state.turn)))
    db.undo_chat_turn(chat_id)
    assert not any(
        p["kind"] == "directive" for p in db.list_pending_actions(int(state.turn))
    )


def test_cross_round_update_via_chat_then_undo_restores_before_image(game, monkeypatch):
    """跨轮：chat 新建 → 再 chat 原地改草 → 撤回第二轮恢复前像。"""
    db, state, content = game
    minister = _active_ch(db, content)
    an.open_night(db, state, location="文华殿", time_of_day="午")
    _silence_serial(monkeypatch)

    original_reply = "着户部发银三万两赈陕西。"
    updated_reply = "着户部发银五十万两赈陕西（改）。"
    phase = {"n": 0}

    def fake_classify(*a, **k):
        return [{"kind": "draft"}]

    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)

    class Agent:
        def run(self, _m):
            phase["n"] += 1
            text = original_reply if phase["n"] == 1 else updated_reply
            return SimpleNamespace(content=text, tools=[])

    sess = _chat_session(db, state, content, Agent(), monkeypatch)

    # Round 1: create
    def write1(_cid):
        r = sess.chat(minister.name, "拟一道旨赈陕西。")
        assert r.pending_action_id
    chat1 = _lifecycle_round(db, state, minister.name, write_fn=write1)
    rows = [
        p for p in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if p["kind"] == "directive"
    ]
    assert len(rows) == 1
    pid = int(rows[0]["id"])
    original_text = json.loads(rows[0]["payload_json"])["text"]
    assert "三万" in original_text or "赈" in original_text

    # Round 2: in-place update via real apply path (draft + existing candidate → merge/update)
    # extract_draft_intent supplies merged text targeting the existing id
    def fake_draft(player_message, reply, **kwargs):
        cands = kwargs.get("existing_candidates") or []
        tid = str(cands[-1]["id"]) if cands else ""
        return {
            "draft_action": "拟旨",
            "draft_text": updated_reply,
            "target_candidate": tid,
        }

    monkeypatch.setattr(cb, "extract_draft_intent", fake_draft)

    def write2(_cid):
        r = sess.chat(minister.name, "把赈银改成五十万两。")
        assert r.pending_action_id == pid or r.pending_action_id
    chat2 = _lifecycle_round(db, state, minister.name, write_fn=write2)
    mid_text = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,),
        ).fetchone()["payload_json"]
    )["text"]
    assert "五十万" in mid_text

    db.undo_chat_turn(chat2)
    restored = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,),
        ).fetchone()["payload_json"]
    )["text"]
    assert restored == original_text
    # chat1 still valid history; candidate from create round remains
    assert db.conn.execute(
        "SELECT status FROM chat_turns WHERE id=?", (chat1,),
    ).fetchone()["status"] == "active"
