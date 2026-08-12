"""#515 S0：动作分类器扩展挂点 + 识别兜底 + 脚本化判词契约。

Seams:
- ACTION_CLUSTERS 唯一登记（含 materialize_fn / FieldSpec）
- run_materialize_pipeline / session.chat / WebGame.chat+undo_last_chat

不断言 LLM 语义；不另造 undo；不手抄 snapshot 生命周期。
"""

from __future__ import annotations

import json
import threading
import types
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 — install catalog
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    EFFECT_ANSWER_EXISTING,
    EFFECT_MATERIALIZE,
    EFFECT_NOOP,
    ActionCandidateShapeError,
    assert_action_candidate_shape,
    candidates_from_classifier_payload,
    classifier_json_fields_prompt,
    cluster_by_kind,
    materialize_clusters_ordered,
    normalize_intent_candidates,
    normalize_one_candidate,
    primary_intent,
    validate_action_candidate_shape,
)

# 测试本地固定期望（#515 六类）；非生产常量——删 catalog 行仍红，未来新类不改此集。
_EXPECTED_MIGRATED_KINDS = frozenset({
    "none", "confirmation", "secret", "cultivate", "appointment", "draft",
})
from ming_sim.session import GameSession
from web_app import WebGame


# ── 单一挂点 ──────────────────────────────────────────────────────────


def test_required_six_migrated_subset_of_registry():
    """固定六类 ⊆ registered；期望集在测试本地，不读生产 guard 常量。"""
    registered = {c.kind for c in ACTION_CLUSTERS}
    assert _EXPECTED_MIGRATED_KINDS <= registered
    for k in _EXPECTED_MIGRATED_KINDS:
        assert cluster_by_kind(k) is not None


def test_registry_row_carries_handler_and_fields_prompt_from_specs():
    assert cluster_by_kind("none").effect == EFFECT_NOOP
    assert cluster_by_kind("confirmation").effect == EFFECT_ANSWER_EXISTING
    for c in materialize_clusters_ordered():
        assert c.effect == EFFECT_MATERIALIZE
        assert c.materialize_fn is not None
    # prompt 字段来自 FieldSpec，非手写副本
    schema = classifier_json_fields_prompt()
    assert "动作类型" in schema
    assert "确认" in schema and "任免动作" in schema
    assert "密令动作" in schema


def test_registry_rows_generate_shape_contract_matrix():
    # 从 ACTION_CLUSTERS 汇集 FieldSpec（不经公共派生索引 API）
    specs_by_name = {}
    for c in ACTION_CLUSTERS:
        for f in c.fields:
            specs_by_name.setdefault(f.name, f)

    for c in ACTION_CLUSTERS:
        if c.kind == "none":
            assert candidates_from_classifier_payload({"kind": "none"}, soft=True) == []
            continue
        base = {"kind": c.kind}
        for f in c.fields:
            if f.allowed:
                non_none = f.allowed - {"无"}
                base[f.name] = next(iter(non_none)) if non_none else next(iter(f.allowed))
            elif f.as_int:
                base[f.name] = 1
            else:
                base[f.name] = "x"
        got = candidates_from_classifier_payload(base, soft=False)
        assert len(got) == 1 and got[0]["kind"] == c.kind
        for f in c.fields:
            if not f.allowed:
                continue
            bad = dict(base)
            bad[f.name] = "__not_in_enum__"
            with pytest.raises(ActionCandidateShapeError):
                candidates_from_classifier_payload(bad, soft=False)

    # 共享 superset：enum 字段挂在别 kind 上仍 out-of-enum 拒
    enum_specs = [s for s in specs_by_name.values() if s.allowed]
    assert enum_specs, "catalog must expose at least one enum FieldSpec"
    host_kind = next(
        c.kind for c in ACTION_CLUSTERS if c.kind not in ("none",) and c.kind != "confirmation"
    )
    # 分类器会为不适用的共享 enum 字段回空串；空白等同字段缺席，不得毙掉候选。
    for c in ACTION_CLUSTERS:
        if c.kind == "none":
            continue
        for spec in enum_specs:
            for key in (spec.name, spec.zh):
                for blank in ("", " \t\n"):
                    got = candidates_from_classifier_payload(
                        {"kind": c.kind, key: blank}, soft=True,
                    )
                    assert len(got) == 1 and got[0]["kind"] == c.kind
                    assert got[0][spec.name] == spec.default

    for spec in enum_specs:
        payload = {"kind": host_kind, spec.name: "__not_in_enum__"}
        ok, reason = validate_action_candidate_shape(payload)
        assert ok is False and "out of enum" in reason
        with pytest.raises(ActionCandidateShapeError):
            candidates_from_classifier_payload(payload, soft=False)

    # 整数上限取自 FieldSpec.int_hi（非名称特判）
    int_specs = [s for s in specs_by_name.values() if s.as_int and s.int_hi < 10**9]
    assert int_specs, "catalog must expose a clamped int FieldSpec"
    for spec in int_specs:
        over = normalize_one_candidate(
            {"kind": "secret", spec.name: int(spec.int_hi) + 100}, soft=True,
        )
        assert over[spec.name] == int(spec.int_hi)


def test_strict_shape_rejects_unknown_kind_and_out_of_enum_subfield():
    ok, reason = validate_action_candidate_shape({"kind": "treasury"})
    assert ok is False and "unknown" in reason
    with pytest.raises(ActionCandidateShapeError):
        assert_action_candidate_shape({"动作类型": "拨帑"})
    with pytest.raises(ActionCandidateShapeError):
        candidates_from_classifier_payload(
            {"kind": "appointment", "appoint_action": "流放"}, soft=False)


def test_soft_llm_path_degrades_bad_shape_to_empty_list():
    assert candidates_from_classifier_payload({"动作类型": "拨帑"}, soft=True) == []
    assert candidates_from_classifier_payload({"kind": "nope"}, soft=True) == []
    got = candidates_from_classifier_payload({"动作类型": "拟旨"}, soft=True)
    assert len(got) == 1 and got[0]["kind"] == "draft"


def test_normalize_preserves_none_vs_empty_list_semantics():
    assert normalize_intent_candidates(None) is None
    assert normalize_intent_candidates({"kind": "none"}) == []
    assert primary_intent(None) is None
    assert primary_intent([])["kind"] == "none"


# ── apply 真入口 ──────────────────────────────────────────────────────


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
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
    scripted = candidates_from_classifier_payload({
        "kind": "appointment", "appoint_action": "任命", "mode": "ordinary",
        "name": "测试候选人甲", "office": "陕西巡抚",
    }, soft=False)
    out = sess.apply_cli_conversation_actions(
        minister, "中旨直发，着测试候选人甲为陕西巡抚。", "臣遵旨拟任。",
        has_directive=False, secret_order_id=None, preclassified_intent=scripted,
    )
    assert out.get("pending_action_id")
    office_rows = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "office"
    ]
    assert len(office_rows) == 1
    assert office_rows[0]["action"] == "任命"
    payload = json.loads(office_rows[0]["payload_json"] or "{}")
    assert payload.get("name") == "测试候选人甲"
    assert payload.get("office") == "陕西巡抚"
    assert payload.get("mode") == "midzhi"
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
    monkeypatch.setattr(
        cb, "extract_confirmation_intent",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not call serial confirmation extractor")),
    )
    sess = _bind_apply(db, state, content)
    before_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))}
    out = sess.apply_cli_conversation_actions(
        minister, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "draft"}, {"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={int(pid)},
    )
    new_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))} - before_ids
    assert not new_ids
    assert int(pid) not in {
        int(r["id"]) for r in db.list_pending_actions(int(state.turn))
    }
    assert out.get("pending_action_id") in (None, 0, "")


# ── P5：双向 barrier，串行实现必须红 ──────────────────────────────────


def test_finish_poisoned_classifier_yields_empty_list_not_none(game):
    db, state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    fut: Future = Future()
    fut.set_result({"kind": "not_registered"})
    assert sess._finish_cli_action_intent(fut) == []
    assert sess._finish_cli_action_intent(None) is None


def test_non_parallel_cli_chat_materializes_each_top_level_candidate(game, monkeypatch):
    """一句多旨经真实 session.chat 串行 classifier 后逐项暂存。"""
    db, state, content = game
    minister = _active_ch(db, content)
    old_text = "着户部清核旧案。"
    db.stage_directive_candidate(
        state.turn, minister.name, payload={"text": old_text, "actor": minister.name})
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")
    classified = json.dumps([
        {"动作类型": "拟旨", "确认": "", "密令动作": "", "任免动作": ""},
        {"动作类型": "拟旨", "确认": "", "密令动作": "", "任免动作": ""},
        {
            "动作类型": "任免",
            "确认": "",
            "密令动作": "",
            "任免动作": "任命",
            "姓名": "孙传庭",
            "官职": "陕西巡抚",
        },
    ], ensure_ascii=False)
    drafts = [
        {
            "正文": "着户部发帑十万两赈济陕西灾民。",
            "动作类型": "grant_allocation",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "金额": 100000,
            "账户": "国库",
            "执行面": "in_transit",
            "颁布方式": "普通",
        },
        {
            "正文": "着孙传庭巡抚陕西，整饬军政。",
            "动作类型": "assignment",
            "目标类型": "region",
            "目标ID": "shaanxi",
            "承办人": "孙传庭",
            "颁布方式": "普通",
        },
    ]
    calls = []

    def scripted_backend(*_args, **kwargs):
        tag = kwargs.get("tag")
        calls.append(tag)
        if tag == "action_intent":
            return classified, 0
        if tag == "draft_intent":
            return json.dumps({"成品旨稿": drafts}, ensure_ascii=False), 0
        raise AssertionError(f"unexpected backend call: {tag}")

    monkeypatch.setattr(cb, "_run_backend_for_config", scripted_backend)

    class FakeAgent:
        def run(self, _msg):
            return SimpleNamespace(
                content=(
                    "臣拟两道：其一着户部发帑十万两赈济陕西灾民；"
                    "其二着孙传庭巡抚陕西，整饬军政。"
                ),
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
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="agy")
    sess.temporary_characters = {}
    sess._retrieve_memories_for_message = lambda message: message
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)

    sess.chat(
        minister.name,
        "分别拟两道旨：一道发帑赈陕西，一道令孙传庭整饬陕西军政；并任孙传庭为陕西巡抚。",
    )

    rows = db.list_pending_actions(int(state.turn), minister_name=minister.name)
    assert calls == ["action_intent", "draft_intent"]
    assert [row["kind"] for row in rows] == ["directive", "directive", "directive", "office"]
    assert len({int(row["id"]) for row in rows[:3]}) == 3
    payloads = [json.loads(row["payload_json"] or "{}") for row in rows[:3]]
    assert [payload["text"] for payload in payloads] == [
        old_text, drafts[0]["正文"], drafts[1]["正文"],
    ]
    assert payloads[1]["amount"] == 100000
    assert payloads[2]["assignee"] == "孙传庭"


def test_real_chat_bidirectional_barrier_parallel_required(game, monkeypatch):
    """双向 barrier：classifier 进入后等 reply 进入；reply 进入后确认 classifier 在飞。

    若生产先同步跑完 classifier 再回话，reply 永远等不到 classifier_entered → 红。
    """
    db, state, content = game
    minister = _active_ch(db, content)
    classifier_entered = threading.Event()
    reply_entered = threading.Event()
    allow_classify = threading.Event()
    allow_reply = threading.Event()
    calls: list = []

    def fake_classify(*args, **kwargs):
        calls.append("classify")
        classifier_entered.set()
        # 必须等 reply 线程已进入 agent.run，证明重叠
        assert reply_entered.wait(2), "serial classify-before-reply would fail this barrier"
        allow_classify.set()
        return [{"kind": "draft"}]

    class FakeAgent:
        def run(self, _msg):
            reply_entered.set()
            assert classifier_entered.wait(2), "reply started without in-flight classifier"
            # 等 classify 完成（并行 join 前不必；此处只证明重叠后放行）
            assert allow_classify.wait(2)
            allow_reply.set()
            return SimpleNamespace(content="着户部发银赈陕西。", tools=[])

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
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: {
        "appoint_action": "无", "name": "", "office": "",
    })
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨", "draft_text": "【毒化串行】", "target_candidate": "",
    })
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")

    before = _count_pending(db, state.turn)
    result = sess.chat(minister.name, "拟一道旨赈陕西。")
    assert allow_reply.is_set()
    assert calls == ["classify"]
    assert "赈陕西" in (result.answer or "")
    assert result.pending_action_id
    assert _count_pending(db, state.turn) == before + 1
    row = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "directive"
    ][-1]
    text = json.loads(row["payload_json"])["text"]
    assert "赈陕西" in text
    assert "毒化" not in text


@pytest.mark.parametrize(
    "classify_mode",
    ["bad_shape", "raises"],
    ids=["bad_shape_return", "classifier_raises"],
)
def test_real_chat_poisoned_classifier_zero_writes(game, monkeypatch, classify_mode):
    """真实 session.chat：坏 shape 与 classifier 抛异常均保留回话、零 pending。"""
    db, state, content = game
    minister = _active_ch(db, content)

    def fake_classify(*a, **k):
        if classify_mode == "raises":
            raise RuntimeError("classifier boom")
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


# ── 撤回：WebGame.chat + undo_last_chat 生产入口 ─────────────────────


def _wire_web_game(db, state, content, agent, monkeypatch) -> WebGame:
    """真实 WebGame 生命周期方法 + 真 GameSession 分类/apply 路径。"""
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda character: agent,
        build_draft_line=lambda: "无",
        session_ids={},
    )
    sess.llm_config = SimpleNamespace(channel="cli", cli_runner="codex")
    sess.temporary_characters = set()
    sess.previous_summary = ""
    sess.last_decree = ""
    sess.agno_db = None
    sess._retrieve_memories_for_message = lambda message: message
    # bind production methods used by WebGame.chat / undo_last_chat
    for name in (
        "chat", "_start_cli_action_intent", "_finish_cli_action_intent",
        "_confirmation_intent_for_preexisting_pending",
        "_cli_backend_fallback_actions", "apply_cli_conversation_actions",
        "_character", "pending_count", "note_chat_rollback",
        "_audience_prompt_for_message",
        "_stage_appointment_candidate",
        "_merge_staged_new_secret_order_content",
        "_ensure_confirmation_cue",
    ):
        if hasattr(GameSession, name):
            setattr(sess, name, types.MethodType(getattr(GameSession, name), sess))
    # undo 后 registry 重建需要完整 Agno 环境；本 tracer 只验 pending 前像，跳过 registry 重建。
    sess.refresh_runtime_after_chat_rollback = lambda: None
    sess.note_chat_rollback = lambda **kw: None

    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)

    wg = WebGame.__new__(WebGame)
    wg.session = sess
    wg.chat_history = {name: [] for name in content.characters}
    wg._write_gate = threading.Lock()
    wg._drain_cond = threading.Condition()
    wg._pending_writes_count = 0
    wg._draining = False
    wg.favorites = set()
    wg.suggestions_for = lambda _c: []
    # trail helpers no-op (avoid mindreading/extraction noise)
    wg._spawn_pending_write_thread = lambda *a, **k: None
    wg._spawn_extraction_trail = lambda *a, **k: None
    wg._trail_mindreading_after_reply = lambda *a, **k: None
    return wg


class _SyncAgent:
    """非流式 session.chat 用：返回 content/tools 对象（非 generator）。"""

    def __init__(self, content: str):
        self.content = content
        self.tools = []

    def run(self, *_a, **_k):
        return SimpleNamespace(content=self.content, tools=self.tools)


def test_webgame_chat_create_then_undo_removes_candidate(game, monkeypatch):
    db, state, content = game
    minister = _active_ch(db, content)
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: [{"kind": "draft"}])
    _silence_serial(monkeypatch)
    agent = _SyncAgent("着户部发银三万两赈陕西。")
    wg = _wire_web_game(db, state, content, agent, monkeypatch)

    before = _count_pending(db, state.turn)
    payload = wg.chat(minister.name, "拟一道旨赈陕西。")
    assert payload.get("pending_action_id") or any(
        p["kind"] == "directive" for p in db.list_pending_actions(int(state.turn))
    )
    assert _count_pending(db, state.turn) == before + 1
    assert wg.can_undo_last_chat(minister.name)

    wg.undo_last_chat(minister.name)
    assert not any(
        p["kind"] == "directive" for p in db.list_pending_actions(int(state.turn))
    )


def test_webgame_cross_round_update_then_undo_restores_before_image(game, monkeypatch):
    db, state, content = game
    minister = _active_ch(db, content)
    _silence_serial(monkeypatch)
    original = "着户部发银三万两赈陕西。"
    updated = "着户部发银五十万两赈陕西（改）。"
    phase = {"n": 0}

    def fake_classify(*a, **k):
        return [{"kind": "draft"}]

    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)

    class PhaseAgent:
        def run(self, *_a, **_k):
            phase["n"] += 1
            text = original if phase["n"] == 1 else updated
            return SimpleNamespace(content=text, tools=[])

    wg = _wire_web_game(db, state, content, PhaseAgent(), monkeypatch)

    wg.chat(minister.name, "拟一道旨赈陕西。")
    rows = [
        p for p in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if p["kind"] == "directive"
    ]
    assert len(rows) == 1
    pid = int(rows[0]["id"])
    original_text = json.loads(rows[0]["payload_json"])["text"]

    def fake_draft(player_message, reply, **kwargs):
        cands = kwargs.get("existing_candidates") or []
        tid = str(cands[-1]["id"]) if cands else ""
        return {"draft_action": "拟旨", "draft_text": updated, "target_candidate": tid}

    monkeypatch.setattr(cb, "extract_draft_intent", fake_draft)
    wg.chat(minister.name, "把赈银改成五十万两。")
    mid = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,),
        ).fetchone()["payload_json"]
    )["text"]
    assert "五十万" in mid

    wg.undo_last_chat(minister.name)
    restored = json.loads(
        db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?", (pid,),
        ).fetchone()["payload_json"]
    )["text"]
    assert restored == original_text
