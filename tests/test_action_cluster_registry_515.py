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
from tests.dossier_test_helpers import create_test_secret_order


# ── 单一挂点 ──────────────────────────────────────────────────────────


def test_required_six_migrated_subset_of_registry():
    """固定六类 ⊆ registered；期望集在测试本地，不读生产 guard 常量。"""
    registered = {c.kind for c in ACTION_CLUSTERS}
    assert _EXPECTED_MIGRATED_KINDS <= registered
    for k in _EXPECTED_MIGRATED_KINDS:
        assert cluster_by_kind(k) is not None


def test_registry_row_carries_handler_and_effect():
    assert cluster_by_kind("none").effect == EFFECT_NOOP
    assert cluster_by_kind("confirmation").effect == EFFECT_ANSWER_EXISTING
    for c in materialize_clusters_ordered():
        assert c.effect == EFFECT_MATERIALIZE
        assert c.materialize_fn is not None


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


# ── #516：问/令查分界（扩 #515 表驱动正反例 + 结构化判词契约）──────────


@pytest.mark.parametrize(
    ("utterance", "raw_payload", "expect_kinds", "expect_secret_action", "expect_order_id"),
    [
        # 北极星 + 含密查/查访字样的疑问 → 分类无
        ("陕西巡抚可有？", {"动作类型": "无"}, [], None, 0),
        ("可有人密查陕西军饷？", {"动作类型": "无"}, [], None, 0),
        ("着人查访陕西军情如何？", {"动作类型": "无"}, [], None, 0),
        # 含命令词但整体为问 → 仍无
        ("命东厂密查其家产的是谁？", {"动作类型": "无"}, [], None, 0),
        # 另案祈使令查 → secret 新建
        (
            "你去查他家产",
            {"动作类型": "密令动作", "密令动作": "新建"},
            ["secret"],
            "新建",
            0,
        ),
        (
            "着东厂密查其家产",
            {"动作类型": "密令动作", "密令动作": "新建"},
            ["secret"],
            "新建",
            0,
        ),
        # 指向现有密令的补充 → 更新原令（#516 r3）
        (
            "再去查他在苏州的田产",
            {
                "动作类型": "密令动作",
                "密令动作": "更新",
                "目标密令编号": 6,
                "新标题": "查其家产",
                "新内容": "再去查他在苏州的田产",
            },
            ["secret"],
            "更新",
            6,
        ),
        # #1509：确认=修改携带 typed 新内容与目标编号，须原样过缝（并入真实分类入口）
        (
            "朕要修改密令正文为只查饷银去向，不查动向",
            {
                "动作类型": "确认",
                "确认": "修改",
                "新内容": "只查饷银去向，不查动向",
                "目标编号": [6],
            },
            ["confirmation"],
            None,
            0,
        ),
    ],
    ids=[
        "north_star_pure_ask",
        "ask_with_micha",
        "ask_with_chafang",
        "ask_with_command_words",
        "imperative_go_check_new",
        "imperative_micha_new",
        "supplement_existing_update",
        "confirmation_modify_carries_new_content_and_target_ids",
    ],
)
def test_classify_soft_path_ask_vs_order_payload_matrix(
    monkeypatch, utterance, raw_payload, expect_kinds,
    expect_secret_action, expect_order_id,
):
    """#515 soft 归一：问/令查表驱动 payload → kind 列表（LLM 语义 externally scripted）。"""

    def _scripted(prompt, llm_config=None, tag=""):
        assert tag == "action_intent"
        return (json.dumps(raw_payload, ensure_ascii=False), 0)

    monkeypatch.setattr(cb, "_run_backend_for_config", _scripted)
    active = None
    if expect_secret_action == "更新":
        active = [{"id": expect_order_id, "title": "查其家产", "content": "密查家产"}]
    got = cb.classify_cli_action_intent(utterance, active_orders=active)
    assert [c["kind"] for c in got] == expect_kinds
    if expect_secret_action is not None:
        assert got[0]["secret_action"] == expect_secret_action
        assert int(got[0].get("order_id") or 0) == int(expect_order_id)
    if raw_payload.get("确认") == "修改":
        assert got[0]["confirmation"] == "修改"
        assert got[0]["new_content"] == raw_payload["新内容"]
        assert got[0]["target_ids"] == raw_payload["目标编号"]


@pytest.mark.parametrize(
    ("utterance", "scripted", "expect_action", "seed_existing"),
    [
        ("陕西巡抚可有？", [], None, False),
        ("可有人密查陕西军饷？", [], None, False),
        ("着人查访陕西军情如何？", [], None, False),
        ("命东厂密查其家产的是谁？", [], None, False),
        (
            "你去查他家产",
            [{"kind": "secret", "secret_action": "新建"}],
            "新建",
            False,
        ),
        (
            "着东厂密查其家产",
            [{"kind": "secret", "secret_action": "新建"}],
            "新建",
            False,
        ),
        # 已有相关密令时补充 → 更新原令，不得另建
        (
            "再去查他在苏州的田产",
            [{
                "kind": "secret",
                "secret_action": "更新",
                "order_id": 0,  # filled at runtime
                "new_title": "查其家产",
                "new_content": "再去查他在苏州的田产",
            }],
            "更新",
            True,
        ),
    ],
    ids=[
        "stage_north_star_zero",
        "stage_ask_micha_zero",
        "stage_ask_chafang_zero",
        "stage_ask_command_words_zero",
        "stage_imperative_go_check_new",
        "stage_imperative_micha_new",
        "stage_supplement_existing_update",
    ],
)
def test_scripted_ask_vs_order_staging_matrix(
    game, monkeypatch, utterance, scripted, expect_action, seed_existing,
):
    """脚本化判词经真实 apply：纯问零 staging；另案新建；现有令补充→更新。"""
    db, state, content = game
    minister = _active_ch(db, content)
    _silence_serial(monkeypatch)
    monkeypatch.setattr(
        cb, "_extract_secret_order",
        lambda *a, **k: {
            "title": "查家产",
            "content": utterance,
            "assignee": minister.name,
            "tags": [],
            "deadline_months": 0,
            "excluded_names": [],
            "excluded_offices": [],
            "dossier_links": [],
            "covert_task": {
                "kind": "清丈", "axes": ["实务事功"], "direction": 1,
                "delivery": {"unit": "万亩", "target_units": 1.0, "effect_sign": 1, "region": "henan", "field": "registered_land", "target": "421"},
            },
        },
    )
    oid = 0
    if seed_existing:
        oid = create_test_secret_order(db,
            state, minister.name, "查其家产", "密查家产", [],
        )
        for cand in scripted:
            if cand.get("secret_action") == "更新":
                cand["order_id"] = oid
    sess = _bind_apply(db, state, content)
    before = _count_pending(db, state.turn)
    out = sess.apply_cli_conversation_actions(
        minister, utterance, "臣领旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    secret_rows = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "secret_order"
    ]
    if expect_action is None:
        assert out.get("pending_action_id") in (None, 0, "")
        assert secret_rows == []
        assert _count_pending(db, state.turn) == before
        return
    assert out.get("pending_action_id")
    assert len(secret_rows) == 1
    assert secret_rows[0]["action"] == expect_action
    assert _count_pending(db, state.turn) == before + 1
    if expect_action == "更新":
        assert int(secret_rows[0]["target_id"] or 0) == int(oid)
        # 不得因补充而另建一条新建暂存
        assert not any(r["action"] == "新建" for r in secret_rows)


# ── P5：双向 barrier，串行实现必须红 ──────────────────────────────────

# #516 问/令查样本：并入 P5 真实 session.chat barrier/poison 矩阵（不经 preclassified_intent）
_P5_ASK_VS_ORDER_UTTERANCES = (
    "陕西巡抚可有？",
    "可有人密查陕西军饷？",
    "着人查访陕西军情如何？",
    "命东厂密查其家产的是谁？",
    "你去查他家产",
    "着东厂密查其家产",
)
_P5_ASK_VS_ORDER_BARRIER_CASES = (
    # utterance, classify_result, reply, expect_secret_stage, expect_directive_stage
    ("拟一道旨赈陕西。", [{"kind": "draft"}], "着户部发银赈陕西。", False, True),
    ("陕西巡抚可有？", [], "臣回奏：容臣查明再报。", False, False),
    ("可有人密查陕西军饷？", [], "臣回奏：容臣查明再报。", False, False),
    ("着人查访陕西军情如何？", [], "臣回奏：容臣查明再报。", False, False),
    ("命东厂密查其家产的是谁？", [], "臣回奏：容臣查明再报。", False, False),
    (
        "你去查他家产",
        [{"kind": "secret", "secret_action": "新建"}],
        "臣领旨密查。",
        True,
        False,
    ),
    (
        "着东厂密查其家产",
        [{"kind": "secret", "secret_action": "新建"}],
        "臣领旨密查。",
        True,
        False,
    ),
)
_P5_ASK_VS_ORDER_BARRIER_IDS = (
    "draft_parallel",
    "north_star_pure_ask",
    "ask_with_micha",
    "ask_with_chafang",
    "ask_with_command_words",
    "imperative_go_check",
    "imperative_micha",
)
_P5_POISON_UTTERANCES = ("卿且坐。",) + _P5_ASK_VS_ORDER_UTTERANCES
_P5_POISON_UTTERANCE_IDS = (
    "neutral",
    "north_star_pure_ask",
    "ask_with_micha",
    "ask_with_chafang",
    "ask_with_command_words",
    "imperative_go_check",
    "imperative_micha",
)


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


def test_cli_chat_materializes_each_top_level_candidate(game, monkeypatch):
    """一句多旨经真实 session.chat classifier 后逐项暂存（任意 CLI runner 并发分类）。"""
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


@pytest.mark.parametrize(
    ("utterance", "classify_result", "reply", "expect_secret_stage", "expect_directive_stage"),
    _P5_ASK_VS_ORDER_BARRIER_CASES,
    ids=_P5_ASK_VS_ORDER_BARRIER_IDS,
)
def test_real_chat_bidirectional_barrier_parallel_required(
    game, monkeypatch, utterance, classify_result, reply,
    expect_secret_stage, expect_directive_stage,
):
    """双向 barrier：classifier 进入后等 reply 进入；reply 进入后确认 classifier 在飞。

    若生产先同步跑完 classifier 再回话，reply 永远等不到 classifier_entered → 红。
    #516：纯问/含命令词疑问/祈使令查样本并入真实 session.chat，不经 preclassified_intent。
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
        return list(classify_result)

    class FakeAgent:
        def run(self, _msg):
            reply_entered.set()
            assert classifier_entered.wait(2), "reply started without in-flight classifier"
            # 等 classify 完成（并行 join 前不必；此处只证明重叠后放行）
            assert allow_classify.wait(2)
            allow_reply.set()
            return SimpleNamespace(content=reply, tools=[])

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
    monkeypatch.setattr(
        cb, "_extract_secret_order",
        lambda *a, **k: {
            "title": "查家产",
            "content": utterance,
            "assignee": minister.name,
            "tags": [],
            "deadline_months": 0,
            "excluded_names": [],
            "excluded_offices": [],
            "dossier_links": [],
            "covert_task": {
                "kind": "清丈", "axes": ["实务事功"], "direction": 1,
                "delivery": {"unit": "万亩", "target_units": 1.0, "effect_sign": 1, "region": "henan", "field": "registered_land", "target": "421"},
            },
        },
    )

    before = _count_pending(db, state.turn)
    result = sess.chat(minister.name, utterance)
    assert allow_reply.is_set()
    assert calls == ["classify"]
    # Pending state is structured; the model's reply must remain byte-for-byte intact.
    assert result.answer == reply

    secret_rows = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "secret_order" and r["action"] == "新建"
    ]
    directive_rows = [
        r for r in db.list_pending_actions(int(state.turn), minister_name=minister.name)
        if r["kind"] == "directive"
    ]
    if expect_directive_stage:
        assert result.pending_action_id
        assert _count_pending(db, state.turn) == before + 1
        assert len(directive_rows) == 1
        text = json.loads(directive_rows[-1]["payload_json"])["text"]
        assert "赈陕西" in text
        assert "毒化" not in text
        assert secret_rows == []
    elif expect_secret_stage:
        assert result.pending_action_id
        assert _count_pending(db, state.turn) == before + 1
        assert len(secret_rows) == 1
        assert directive_rows == []
    else:
        assert result.answer == reply
        assert not result.pending_action_id
        assert _count_pending(db, state.turn) == before
        assert secret_rows == []
        assert directive_rows == []


@pytest.mark.parametrize(
    "utterance",
    _P5_POISON_UTTERANCES,
    ids=_P5_POISON_UTTERANCE_IDS,
)
@pytest.mark.parametrize(
    "classify_mode",
    ["bad_shape", "raises"],
    ids=["bad_shape_return", "classifier_raises"],
)
def test_real_chat_poisoned_classifier_zero_writes(
    game, monkeypatch, classify_mode, utterance,
):
    """真实 session.chat：坏 shape 与 classifier 抛异常均保留回话、零 pending。

    #516：问/令查样本同走并发分类毒化路，不经 preclassified_intent。
    """
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
    result = sess.chat(minister.name, utterance)
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
        "admit_audience", "consume_audience_admission", "can_summon",
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
    from ming_sim.session_write_queue import SessionWriteQueue
    wg._write_queue = SessionWriteQueue()
    wg._write_gate = wg._write_queue.write_gate
    wg._runtime_write_queue = lambda: wg._write_queue  # type: ignore
    wg._mark_pending_write = lambda key=None: wg._write_queue.claim(key=key or ("pending",))  # type: ignore
    wg._complete_pending_write = lambda ticket=None: wg._write_queue.complete(ticket)  # type: ignore
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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
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
