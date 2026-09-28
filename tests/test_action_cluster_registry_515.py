"""#515 S0：动作字段目录 + 识别兜底 + 脚本化判词契约。

Seams:
- ACTION_CLUSTERS 字段目录 / WebGame.chat+undo_last_chat

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
import ming_sim.session as session_mod
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    ActionCandidateShapeError,
    assert_action_candidate_shape,
    candidates_from_classifier_payload,
    cluster_by_kind,
    normalize_intent_candidates,
    normalize_one_candidate,
    primary_intent,
    validate_action_candidate_shape,
)

# 测试本地固定期望（#515 六类）；非生产常量——删 catalog 行仍红，未来新类不改此集。
from tests.conftest import offline_empty_audience_translate, stub_audience_translate, stub_scene_agent

_EXPECTED_MIGRATED_KINDS = frozenset({
    "none", "confirmation", "secret", "cultivate", "appointment", "draft",
})
from ming_sim.session import GameSession
from web_app import WebGame


# ── 字段目录 ──────────────────────────────────────────────────────────


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

    # 可选正整数：as_int + default None + int_lo>=1 为结构化契约；raw 直达，不经 generic clamp
    opt_pos = [
        s for s in specs_by_name.values()
        if s.as_int and s.default is None and int(s.int_lo) >= 1
    ]
    assert opt_pos, "catalog must expose optional positive-int FieldSpec"
    for spec in opt_pos:
        # 同一 catalog 真源：nullable / JSON integer / positive lower bound
        assert spec.default is None
        assert spec.as_int is True
        assert int(spec.int_lo) >= 1
        host = next(
            c.kind for c in ACTION_CLUSTERS
            if any(f.name == spec.name for f in c.fields)
        )
        absent = normalize_one_candidate({"kind": host}, soft=True)
        assert absent[spec.name] is None
        kept = normalize_one_candidate({"kind": host, spec.name: 7}, soft=True)
        assert kept[spec.name] == 7
        # numeric string 原样过缝；拒绝权在既有严格 parser/stage 边界
        raw_str = normalize_one_candidate({"kind": host, spec.name: "12"}, soft=True)
        assert raw_str[spec.name] == "12"


def test_money_units_and_season_option_contract_project_from_catalog():
    """同名金额各守所属 action 单位；season option 不另立字段表。"""
    from ming_sim.action_clusters import (
        season_option_fields, validate_season_option,
    )

    grant = next(c for c in ACTION_CLUSTERS if c.kind == "grant_allocation")
    punishment = next(c for c in ACTION_CLUSTERS if c.kind == "punishment")
    assert next(f for f in grant.fields if f.name == "amount").quantity_unit == "万两"
    assert next(f for f in punishment.fields if f.name == "amount").quantity_unit == "两"
    assert season_option_fields("grant_allocation") == (
        "action_type", "grant_action", "target_id", "target_kind", "amount",
        "account", "purpose", "cadence",
    )
    valid = {
        "action_type": "grant_allocation", "grant_action": "协饷",
        "target_id": "guanning", "target_kind": "army", "amount": 1,
        "account": "内库", "purpose": "补饷", "cadence": "一次性",
    }
    assert validate_season_option(
        {**valid, "action_type": " grant_allocation "}
    ) == "grant_allocation"
    with pytest.raises(ValueError):
        validate_season_option({**valid, "target_kind": "character"})
    with pytest.raises(ValueError):
        validate_season_option({**valid, "action_type": "grant_allocaton"})
    for key in season_option_fields("grant_allocation")[1:]:
        with pytest.raises(ValueError):
            validate_season_option({k: v for k, v in valid.items() if k != key})
    for key, bad in (("account", "太仓银"), ("target_id", ""),
                     ("target_id", "   "), ("amount", None),
                     ("amount", "1"), ("amount", True), ("amount", 0)):
        with pytest.raises(ValueError):
            validate_season_option({**valid, key: bad})


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


def _count_pending(db, turn) -> int:
    return len(db.list_pending_actions(int(turn)))


def _active_ch(db, content):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫",)
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
    )


# ── 撤回：WebGame.chat + undo_last_chat 生产入口 ─────────────────────


def _wire_web_game(db, state, content, agent, monkeypatch, *, translate_fn=None) -> WebGame:
    """真实 WebGame 生命周期方法 + 真 GameSession scene_chat / 转译路径。"""
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = SimpleNamespace(
        get=lambda character, **_kw: agent,
        session_ids={},
    )
    sess.llm_config = SimpleNamespace(
        channel="cli", cli_runner="codex", base_url="", model="test", api_key="",
    )
    sess.previous_summary = ""
    sess.last_decree = ""
    sess.agno_db = None
    sess._beat_generator = None
    # 大臣级 Web 入口恢复 start_chat_turn_scene；离线 registry 禁 None 崩。
    from tests.conftest import _OfflineSceneRegistry
    sess._scene_registry = _OfflineSceneRegistry()
    sess._retrieve_memories_for_message = lambda message: message
    stub_audience_translate(monkeypatch, translate_fn)
    # bind production methods used by WebGame.chat / undo_last_chat / scene_chat
    for name in (
        "chat", "scene_chat", "_apply_scene_turn_translation",
        "start_chat_turn_scene", "join_chat_turn_scene",
        "persist_chat_turn_scene", "abandon_chat_turn_scene",
        "schedule_pending_scene_translation",
        "_character", "pending_count", "note_chat_rollback",
        "admit_audience", "consume_audience_admission", "can_summon",
        "_recognize_audience_command_verdict",
        "close_night_after_chat_if_needed",
    ):
        if hasattr(GameSession, name):
            setattr(sess, name, types.MethodType(getattr(GameSession, name), sess))
    # undo 后 registry 重建需要完整 Agno 环境；本 tracer 只验 pending 前像，跳过 registry 重建。
    sess.refresh_runtime_after_chat_rollback = lambda: None
    sess.note_chat_rollback = lambda **kw: None
    monkeypatch.setattr(session_mod, "_dump_llm_messages", lambda *a, **k: None)
    # scene_chat 用 create_scene_agent；挡真实 LLM，回放 agent 正文。
    class _SceneShim:
        def run(self, *_a, **_k):
            out = agent.run() if hasattr(agent, "run") else SimpleNamespace(content=getattr(agent, "content", ""), tools=[])
            return out
    monkeypatch.setattr(session_mod, "create_scene_agent", lambda *a, **k: _SceneShim())
    import ming_sim.materials as materials_mod
    monkeypatch.setattr(
        materials_mod, "prepare_scene_materials",
        lambda *a, **k: SimpleNamespace(opening="", materials_dir="."),
    )
    # session.scene_chat 从 ming_sim.materials 名绑定导入；同步补 session 模块属性。
    monkeypatch.setattr(
        session_mod, "prepare_scene_materials",
        lambda *a, **k: SimpleNamespace(opening="", materials_dir="."),
        raising=False,
    )

    wg = WebGame.__new__(WebGame)
    wg.session = sess
    # db/state/content 是 WebGame 从 session 投影的 property，不直写。
    wg.chat_history = {name: [] for name in content.characters}
    from ming_sim.session_write_queue import SessionWriteQueue
    wg._write_queue = SessionWriteQueue()
    wg._write_gate = wg._write_queue.write_gate
    # 与生产同形：session 与 WebGame 共用 queue gate，转译与 chat atomic 同闸。
    sess._write_gate = wg._write_gate
    sess._write_queue = wg._write_queue
    wg._runtime_write_queue = lambda: wg._write_queue  # type: ignore
    wg._runtime_write_gate = lambda: wg._write_gate  # type: ignore
    wg._ticketed_write_gate = lambda ticket=None: wg._write_gate  # type: ignore
    wg._mark_pending_write = lambda key=None: wg._write_queue.claim(key=key or ("pending",))  # type: ignore
    wg._complete_pending_write = lambda ticket=None: wg._write_queue.complete(ticket)  # type: ignore
    wg.favorites = set()
    wg.suggestions_for = lambda _c: []
    # Keep unrelated background trails quiet.
    wg._spawn_pending_write_thread = lambda *a, **k: None
    wg._trail_highlight_judge_after_reply = lambda *a, **k: []
    return wg


class _SyncAgent:
    """非流式 session.chat 用：返回 content/tools 对象（非 generator）。"""

    def __init__(self, content: str):
        self.content = content
        self.tools = []

    def run(self, *_a, **_k):
        return SimpleNamespace(content=self.content, tools=self.tools)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_webgame_chat_create_then_undo_removes_candidate(game, monkeypatch):
    db, state, content = game
    minister = _active_ch(db, content)
    draft_text = "着户部发银三万两赈陕西。"
    agent = _SyncAgent(draft_text)

    def translate_fn(prompt, llm_config):
        return {**offline_empty_audience_translate(prompt, llm_config), "commissions": [{"text": draft_text}]}

    wg = _wire_web_game(db, state, content, agent, monkeypatch, translate_fn=translate_fn)

    before = _count_pending(db, state.turn)
    payload = wg.chat(minister.name, "拟一道旨赈陕西。")
    wg._runtime_write_queue().barrier(lambda: None)
    assert payload.get("answer")
    assert any(
        p["kind"] == "directive" for p in db.list_pending_actions(int(state.turn))
    ), db.list_pending_actions(int(state.turn))
    assert _count_pending(db, state.turn) == before + 1
    assert wg.can_undo_last_chat(minister.name)

    wg.undo_last_chat(minister.name)
    assert not any(
        p["kind"] == "directive" for p in db.list_pending_actions(int(state.turn))
    )


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_webgame_cross_round_update_then_undo_restores_before_image(game, monkeypatch):
    """scene_chat + 转译：第二轮新交办后撤回，第一轮 pending 前像必须仍在（ADR 0038）。"""
    db, state, content = game
    minister = _active_ch(db, content)
    original = "着户部发银三万两赈陕西。"
    updated = "着户部发银五十万两赈陕西（改）。"
    phase = {"n": 0}

    class PhaseAgent:
        def run(self, *_a, **_k):
            phase["n"] += 1
            text = original if phase["n"] == 1 else updated
            return SimpleNamespace(content=text, tools=[])

    def translate_fn(prompt, llm_config):
        # 每轮各声明一条新交办（不改写既有行），使撤回第二轮只逆转第二轮产物。
        if "【本轮皇帝】把赈银改成五十万两" in prompt or "五十万两" in prompt and "改成" in prompt:
            return {**offline_empty_audience_translate(prompt, llm_config), "commissions": [{"text": updated}]}
        return {**offline_empty_audience_translate(prompt, llm_config), "commissions": [{"text": original}]}

    wg = _wire_web_game(
        db, state, content, PhaseAgent(), monkeypatch, translate_fn=translate_fn,
    )

    wg.chat(minister.name, "拟一道旨赈陕西。")
    wg._runtime_write_queue().barrier(lambda: None)
    rows = [
        p for p in db.list_pending_actions(int(state.turn))
        if p["kind"] == "directive" and p.get("status") == "pending"
    ]
    assert len(rows) == 1, rows
    pid = int(rows[0]["id"])
    original_text = json.loads(rows[0]["payload_json"])["text"]
    assert original_text == original

    wg.chat(minister.name, "把赈银改成五十万两。")
    wg._runtime_write_queue().barrier(lambda: None)
    after = [
        p for p in db.list_pending_actions(int(state.turn))
        if p["kind"] == "directive" and p.get("status") == "pending"
    ]
    assert len(after) == 2, after
    assert any(int(p["id"]) == pid for p in after)

    wg.undo_last_chat(minister.name)
    # ADR 0038：撤第二轮须留下第一轮前像——pid 行必须仍 pending 且正文不变。
    restored_row = db.conn.execute(
        "SELECT payload_json, status FROM pending_actions WHERE id=?",
        (pid,),
    ).fetchone()
    assert restored_row is not None, "第一轮 pending 被误删"
    assert str(restored_row["status"] or "") == "pending"
    restored = json.loads(restored_row["payload_json"])["text"]
    assert restored == original_text
    # 第二轮产物须随撤回消失
    remaining = [
        p for p in db.list_pending_actions(int(state.turn))
        if p["kind"] == "directive" and p.get("status") == "pending"
    ]
    assert len(remaining) == 1
    assert int(remaining[0]["id"]) == pid


def test_undo_restored_approved_decree_restarts_forecast_for_new_version(game, monkeypatch):
    """撤回恢复旧批稿后，以新版本身份重新暂存预推。"""
    from ming_sim.declaration_dispatch import pending_action_decree_ref, stage_declaration
    from ming_sim.session_write_queue import get_session_write_queue
    import ming_sim.audience_night as audience_night
    import ming_sim.decree as decree_mod
    import ming_sim.decree_forecast as forecast_mod
    import ming_sim.month_translate as month_translate

    db, state, content = game
    minister = _active_ch(db, content)
    night = audience_night.open_night(db, state)
    pending_id = db.stage_pending_action(
        state.turn, kind="directive", action="拟旨", minister_name=minister.name,
        payload={
            "dossier_action_type": "policy", "target_kind": "issue",
            "target_id": "test-policy", "text": "着户部清核辽饷。",
            "actor": minister.name, "mode": "ordinary",
        },
    )
    db.mark_pending_night_approved([pending_id], night_id=int(night["id"]))
    old_ref = pending_action_decree_ref(pending_id, 1)
    stage_declaration(db, decree_ref=old_ref, declaration={"commissions": []}, turn=state.turn)

    chat_turn_id = db.create_chat_turn(
        state, minister.name, "undo-approved-decree", 0, night_id=int(night["id"]),
    )
    db.update_chat_turn_messages(
        chat_turn_id,
        db.append_chat_message(minister.name, state.turn, "user", "改拟旨。"),
        db.append_chat_message(minister.name, state.turn, "minister", "臣遵旨。"),
    )
    before = db.capture_chat_rollback_snapshot()
    db.update_directive_candidate(pending_id, {
        "dossier_action_type": "policy", "target_kind": "issue",
        "target_id": "test-policy", "text": "着户部重核辽饷。", "actor": minister.name,
    })
    db.record_chat_turn_rollback_diffs(
        chat_turn_id, before, db.capture_chat_rollback_snapshot(),
    )

    def judge(_agent, prompt, **_kwargs):
        dossier_id = json.loads(prompt)["dossiers"][0]["id"]
        return json.dumps({
            "verdicts": [{"dossier_id": dossier_id, "decision": "promulgated"}],
        })

    monkeypatch.setattr(decree_mod, "run_agent_text", judge)
    monkeypatch.setattr(
        forecast_mod.agents, "run_agent_text",
        lambda *_a, **_k: "预推叙述" + "<<DECISION>>{}<<END>>" + "问后叙述",
    )
    monkeypatch.setattr(
        month_translate, "run_declaration_translate_prompt",
        lambda *_a, **_k: {"commissions": []},
    )
    wg = _wire_web_game(db, state, content, _SyncAgent("无关回话。"), monkeypatch)
    from ming_sim.models import LLMConfig
    wg.session.llm_config = LLMConfig(
        api_key="test", base_url="https://example.invalid/v1", model="test-model",
    )

    wg.undo_last_chat(minister.name)
    assert get_session_write_queue(wg.session).wait_idle(timeout_s=5)

    restored = db.conn.execute(
        "SELECT version,night_approved FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    assert (int(restored["version"]), int(restored["night_approved"])) == (3, 1)
    assert db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?", (old_ref,),
    ).fetchone()["status"] == "discarded"
    new_ref = pending_action_decree_ref(pending_id, 3)
    assert db.conn.execute(
        "SELECT status FROM staged_declarations WHERE decree_ref=?", (new_ref,),
    ).fetchone()["status"] == "staged"


# ── #1744：分类粒度 / draft 共存边界 → chat → HTTP 可见 ──
# 独有契约（本区）：
# - one_intent_probe_raw_chat_to_pending_api：冻结 probe-shaped raw 经 classify 入口归一
#   + WebGame.chat + GET /api/pending_actions 恰一 ordinary（运输契约，非 live LLM）
# - draft_plus_independent_titleless_assignment：空 title ≠ 意图身份（删门反向）
# - draft_plus_digit_target_candidate_updates：batch 含 draft 时 digit 续办仍原地更新，
#   且 draft/assignment 两种候选顺序均成立（相对 520 beat8 的独有：draft 共存边界）
# - draft_xiexang_promoted_plus_independent_titleless：draft 协饷改写 kind 后，
#   *独立* titleless assignment 仍成条（≠ 线上 T2 同旨阴影；同旨案形仅回执一次性探针）
# 多独立交办权威行为证明在 test_assignment_materialize_520.beat6（本区不再平行造样）。

_EMPEROR_1744 = (
    "户部亏空日甚，太仓入不敷出。卿可据实奏对，并拟一道旨："
    "清核太仓出纳、暂缓非急工役、优发边饷要紧处，限半月回报。"
)
# 确定性运输夹具用短 reply；一次性闭环证据用冻结全文回奏（见回执 artifacts）。
_REPLY_1744 = (
    "臣毕自严叩见皇上。太仓亏空非一日之患。\n\n"
    "**拟旨：**\n\n奉天承运皇帝诏曰：着户部会同太仓清核出纳，"
    "非急工役暂行缓办，辽东边饷优先筹拨。限半月具奏。钦此。"
)
@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_one_scene_commission_stages_one_directive(game, monkeypatch):
    """Web 殿上 chat 经 scene_chat 转译落一条交办候选。"""
    db, state, content = game
    minister = _active_ch(db, content)

    def translate_fn(prompt, llm_config):
        return {"scene_facts": [{"body": _REPLY_1744, "role": "scene", "person_names": []}],
                "commissions": [{"text": _REPLY_1744}], "promises": []}

    wg = _wire_web_game(
        db, state, content, _SyncAgent(_REPLY_1744), monkeypatch,
        translate_fn=translate_fn,
    )
    before = {
        int(r["id"])
        for r in db.list_pending_actions(int(state.turn))
    }
    wg.chat(minister.name, _EMPEROR_1744)
    wg._runtime_write_queue().barrier(lambda: None)
    all_new = [
        r for r in db.list_pending_actions(int(state.turn))
        if int(r["id"]) not in before and r.get("kind") == "directive"
    ]
    assert len(all_new) == 1, all_new
    payload = json.loads(all_new[0].get("payload_json") or "{}")
    assert _REPLY_1744 in str(payload.get("text") or "")


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_scene_chat_translation_can_stage_multiple_commissions(game, monkeypatch):
    """#1842：Web scene_chat 转译一次可落多条 commission → pending 可见（替代旧分类器 batch 网测）。"""
    db, state, content = game
    minister = _active_ch(db, content)

    def translate_fn(prompt, llm_config):
        return {
            **offline_empty_audience_translate(prompt, llm_config),
            "commissions": [
                {"text": "着清核太仓出纳"},
                {"text": "着陕西巡抚督办赈灾"},
            ],
            "promises": [],
        }

    wg = _wire_web_game(
        db, state, content,
        _SyncAgent("臣请清核太仓，并请陕西巡抚督办赈灾。"),
        monkeypatch,
        translate_fn=translate_fn,
    )
    before = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))}
    wg.chat(minister.name, "清核太仓，另着陕西巡抚督办赈灾。")
    wg._runtime_write_queue().barrier(lambda: None)
    new_dirs = [
        r for r in db.list_pending_actions(int(state.turn))
        if int(r["id"]) not in before and r.get("kind") == "directive" and r.get("status") == "pending"
    ]
    assert len(new_dirs) == 2, new_dirs
    texts = [json.loads(r["payload_json"]).get("text", "") for r in new_dirs]
    assert any("太仓" in t for t in texts)
    assert any("陕西" in t for t in texts)
