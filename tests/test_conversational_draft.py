"""对话式拟旨意图抽取 + pending 暂存 + last-write-wins（issue #137，ADR 0006）。

行为契约：
- 玩家口头「拟旨吧 / 你拟一道旨」（无显式前缀）→ LLM 判出拟旨意图 → 进 pending_actions
  (kind=directive) 暂存；turn_directives 此刻不动。
- 同一回合同一大臣再次触发拟旨意图（补充/改草） → 同一条 pending 行原地更新（last-write-wins），
  不新增行；确认流仍 3 态（应允/拒绝/不回）。
    - 对话应允 → commit → turn_directives 建档 status=pending，仍经既有准/驳界面；
      颁诏时「不回=默认同意」→ commit → turn_directives 建档 status=draft。
- 显式前缀「拟旨如下：」与自然语言拟旨共用同一 pending_actions 闸门。
"""

from __future__ import annotations

import json
import sqlite3
import types

import pytest

import ming_sim.cli_backend as cb
from ming_sim.models import TurnPhase
from ming_sim.session import GameSession
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}


@pytest.fixture(autouse=True)
def _restore_content(content):
    snap = {name: (ch.office, ch.status, ch.office_type, ch.faction)
            for name, ch in content.characters.items()}
    original_keys = set(content.characters.keys())
    yield
    for k in list(content.characters.keys()):
        if k not in original_keys:
            del content.characters[k]
    for name, (office, status, office_type, faction) in snap.items():
        ch = content.characters.get(name)
        if ch is not None:
            ch.office, ch.status, ch.office_type, ch.faction = office, status, office_type, faction


def _active_minister_name(db, content) -> str:
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(getattr(ch, "name", name))[0] == "active":
            return getattr(ch, "name", name)
    raise AssertionError("找不到 active 的大明大臣")


def _fake_session(db, state):
    return types.SimpleNamespace(
        db=db, state=state,
        llm_config=types.SimpleNamespace(channel="cli"),
        registry=None,
    )


def _run_conversational_draft(db, state, content, monkeypatch, *,
                               player_message: str, minister_reply: str,
                               canned: dict):
    """口头拟旨召对：不带显式前缀，让 LLM 返回 canned 意图。"""
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(canned, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message=player_message, answer=minister_reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent=(
            {"kind": "draft"}
            if canned.get("拟旨意图") == "拟旨"
            else {"kind": "none"}
        ),
    )
    return name, out


# ── ① 对话式拟旨触发草案进 pending ────────────────────────────────────────

def test_conversational_draft_intent_stages_pending(game, monkeypatch):
    """口头「拟旨吧」→ LLM 抽出拟旨意图 → kind=directive pending 暂存；
    turn_directives 此刻一行也没有（颁诏/应允前不动）。"""
    db, state, content = game
    name, out = _run_conversational_draft(
        db, state, content, monkeypatch,
        player_message="拟旨吧",
        minister_reply="奉天承运皇帝诏曰，特谕户部清查三边粮饷，限期三月内完报，钦此。",
        canned={"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"},
    )

    # pending_actions 里有一条 kind=directive
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1
    pa = pend[0]
    assert pa["kind"] == "directive"
    assert pa["action"] == "拟旨"
    assert pa["minister_name"] == name
    payload = json.loads(pa["payload_json"])
    assert "奉天承运" in payload["text"]  # 大臣回话即草稿

    # turn_directives 此时一行也没有
    directives = db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)).fetchone()[0]
    assert directives == 0


def test_new_conversational_draft_ignores_conflicting_player_prose_mode(game, monkeypatch):
    db, state, content = game
    _run_conversational_draft(
        db, state, content, monkeypatch,
        player_message="中旨直发，拟一道清查辽饷的旨。",
        minister_reply="着户部清查辽饷。",
        canned={
            "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
            "目标ID": "liao-pay", "颁布方式": "普通",
        },
    )
    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["mode"] == "ordinary"


def test_no_draft_pending_when_no_intent(read_game, monkeypatch):
    """LLM 判出「无」拟旨意图 → 不 stage；闲谈不应触发草案。"""
    db, state, content = read_game
    _run_conversational_draft(
        db, state, content, monkeypatch,
        player_message="今日天气如何",
        minister_reply="回陛下，今日晴和，宜出行。",
        canned={"拟旨意图": "无"},
    )
    assert db.list_pending_actions(state.turn) == []


def test_explicit_prefix_stages_same_pending_directive_as_natural_language(game, monkeypatch):
    """#412：显式「拟旨如下：」也先进 pending_actions，不能直接写 turn_directives 特例路径。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    # canned 带拟旨意图，但显式前缀仍应跳过后置 LLM 检测，使用大臣回话作为润色草案。
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {
                                "拟旨意图": "拟旨",
                                "动作类型": "policy",
                                "目标类型": "issue",
                                "目标ID": "liao-pay-audit",
                            }, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="拟旨如下：着户部速查三边粮饷",
        answer="奉天承运皇帝诏曰，着户部速查三边粮饷。",
        has_directive=False, secret_order_id=None,
    )

    # 显式路与自然语言路同形：只暂存 pending_actions，尚未写 turn_directives。
    pending_pa = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert len(pending_pa) == 1
    payload = json.loads(pending_pa[0]["payload_json"])
    assert payload["text"] == "奉天承运皇帝诏曰，着户部速查三边粮饷。"
    assert payload["actor"] == name
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("typed_mode", "expected"),
    [("midzhi", "midzhi"), ("ordinary", "ordinary"), (None, "ordinary")],
)
def test_explicit_prefix_uses_typed_classifier_mode_not_player_prose(
    game, monkeypatch, typed_mode, expected,
):
    """#1731 类A：前缀入口 mode 只吃分类器 typed；玩家散文「中旨直发」不入槽。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    draft_text = "着户部清核辽饷，限期完报。"
    monkeypatch.setattr(
        cb, "resolve_minister_actions",
        lambda *_a, **_k: {"decree_text": draft_text, "secret_order": None},
    )
    # materialize 对显式前缀早退；禁串行抽取旁路。
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no serial extractor")),
    )
    intent = {"kind": "draft"}
    if typed_mode is not None:
        intent["mode"] = typed_mode
    sess = _fake_session(db, state)
    out = GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="拟旨如下：中旨直发，着户部清核辽饷。",
        answer=draft_text,
        has_directive=False, secret_order_id=None,
        preclassified_intent=intent,
    )
    assert out.get("pending_action_id")
    pending = next(
        p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"
    )
    payload = json.loads(pending["payload_json"])
    assert payload["mode"] == expected
    assert payload["text"] == draft_text

    if expected == "midzhi":
        db.commit_pending_actions(state, kind_filter="directive")
        db.ensure_dossiers_for_draft_directives(state)
        dossiers = db.list_decree_dossiers()
        assert len(dossiers) == 1
        assert dossiers[0]["mode"] == "midzhi"


# ── ② pending 原地更新 last-write-wins ───────────────────────────────────

def test_pending_directive_last_write_wins(game, monkeypatch):
    """同一回合同一大臣再次触发拟旨意图 → 同一 pending 行原地更新（不新增行）。
    pending_actions 仍只有一条，payload.text 更新为最新草稿。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    first_reply = "第一版草稿：着户部速查三边粮饷，三月内完报。"
    second_reply = "修订版：着户部及兵部联合清查三边粮饷军械，限两月完报，结果呈览。"

    sess = _fake_session(db, state)

    # 第一次：触发拟旨意图
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="拟旨吧", answer=first_reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"})

    pend_after_first = db.list_pending_actions(state.turn)
    assert len(pend_after_first) == 1
    first_id = pend_after_first[0]["id"]
    assert first_reply in json.loads(pend_after_first[0]["payload_json"])["text"]

    # 第二次：皇帝「补充一下」→ LLM 返回合并后新草稿。
    # 注：LLM 判确认（extraction_confirmation_intent）先被调，返回「无」，然后才进草案检测
    # 两次调用都 canned 成 {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}（确认判断时会调但结果被丢弃）
    def canned_second(prompt, llm_config=None, tag=""):
        # 确认意图抽取 → 无（别应允/拒绝，只补充草稿）
        if "应允" in prompt or "拒绝" in prompt or "待皇帝定夺" in prompt:
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        return (json.dumps(
                {
                    "拟旨意图": "拟旨", "合并草案": second_reply,
                    "动作类型": "policy",
                    "目标类型": "issue",
                    "目标ID": "liao-pay-audit",
                },
            ensure_ascii=False,
        ), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", canned_second)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="再补一条，加上要监察御史同行", answer=second_reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"})

    pend_after_second = db.list_pending_actions(state.turn)
    # 仍只有一条（last-write-wins 原地更新）
    assert len(pend_after_second) == 1
    # 行 id 不变（原地更新同一行）
    assert pend_after_second[0]["id"] == first_id
    # 内容更新为最新草稿
    updated_payload = json.loads(pend_after_second[0]["payload_json"])
    assert second_reply in updated_payload["text"]
    assert first_reply not in updated_payload["text"]


@pytest.mark.parametrize("landing, player_message, expected_mode", [
    ("pending_upsert", "再补一条。", "midzhi"),
    ("pending_candidate", "再补一条。", "midzhi"),
    ("committed", "再补一条。", "midzhi"),
    ("committed", "普通", "ordinary"),
    # Full natural-language ordinary declaration must beat durable midzhi.
    ("pending_upsert", "这道改按普通程序颁布，准了", "ordinary"),
    ("pending_candidate", "这道改按普通程序颁布，准了", "ordinary"),
    ("committed", "这道改按普通程序颁布，准了", "ordinary"),
])
@pytest.mark.parametrize("supplement", ["omitted", "empty", "append"])
def test_real_conversation_draft_supplement_preserves_and_appends_roster(
    game, monkeypatch, landing, supplement, player_message, expected_mode,
):
    db, state, content = game
    names = [
        row["name"] for row in db.conn.execute(
            "SELECT name FROM characters WHERE status='active' AND power_id='ming' ORDER BY name LIMIT 3"
        ).fetchall()
    ]
    assert len(names) == 3
    minister, existing, added = names
    character = next(ch for ch in content.characters.values() if ch.name == minister)
    initial = [{"character_id": existing, "tier": "主办", "role": "总理"}]
    payload = {
        **_POLICY_FIELDS, "text": "初稿", "actor": minister, "mode": "midzhi",
        "participant_roster": initial,
    }
    target = ""
    if landing == "committed":
        db.add_directive(
            state, None, "初稿", "大臣拟旨", actor=minister, status="draft",
            dossier_payload=payload,
        )
    else:
        candidate_id = db.upsert_pending_directive(state.turn, minister, payload=payload)
        if landing == "pending_candidate":
            target = str(candidate_id)

    extracted = {
        "draft_action": "拟旨", "draft_text": "补充后的草稿",
        **_POLICY_FIELDS,
        "target_candidate": target,
        "mode": None if player_message == "再补一条。" else "ordinary",
    }
    if supplement == "empty":
        extracted["participant_roster"] = []
    elif supplement == "append":
        extracted["participant_roster"] = [
            initial[0], {"character_id": added, "tier": "协办", "role": "核账"},
        ]
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *args, **kwargs: dict(extracted))

    GameSession.apply_cli_conversation_actions(
        types.SimpleNamespace(
            db=db, state=state, content=content, registry=None,
            llm_config=types.SimpleNamespace(channel="cli"),
        ),
        character, player_message=player_message, answer="臣已补妥。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )

    if landing == "committed":
        row = db.list_directives(state, statuses=("draft",))[-1]
        stored_payload = json.loads(row["dossier_payload_json"])
    else:
        stored_payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    stored = stored_payload["participant_roster"]
    assert stored_payload["mode"] == expected_mode
    expected = ([{**initial[0], "delegator_id": None}, {
        "character_id": added, "tier": "协办", "role": "核账", "delegator_id": None,
    }] if supplement == "append" else initial)
    assert stored == expected


# ── ③ commit 时在 turn_directives 建档 ───────────────────────────────────

def test_pending_directive_commit_creates_turn_directive(game):
    """commit_pending_actions 把 kind=directive 暂存落进 turn_directives(status=draft)；
    暂存标 committed，不留 pending。
    status=draft（而非 pending）使其直接进颁诏候选池，无需再经 web UI 准驳。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    draft_text = "奉天承运皇帝诏曰，着户部清查三边粮饷，钦此。"
    # 直接 stage（不走 LLM），测 commit 侧
    db.upsert_pending_directive(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": draft_text, "actor": name},
    )

    assert len(db.list_pending_actions(state.turn)) == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)).fetchone()[0] == 0

    applied = db.commit_pending_actions(state)

    # turn_directives 建档，status=draft（直接进颁诏候选池）
    row = db.conn.execute(
        "SELECT text, status, actor FROM turn_directives WHERE turn=? ORDER BY id DESC",
        (state.turn,)).fetchone()
    assert row is not None
    assert row["text"] == draft_text
    assert row["status"] == "draft"
    assert row["actor"] == name

    # pending_actions 标 committed，不留 pending
    assert db.list_pending_actions(state.turn) == []
    assert any(a["kind"] == "directive" for a in applied)
    other = sqlite3.connect(db.path)
    try:
        persisted = other.execute(
            "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
            (state.turn,),
        ).fetchone()[0]
    finally:
        other.close()
    assert persisted == 1


def test_pending_directive_commit_failure_is_savepoint_isolated_marks_failed(game, monkeypatch):
    """#654 路1：directive 成案异常经 SAVEPOINT 隔离——不冒泡崩外层 atomic、无 directive 残行、pending=failed。"""
    from ming_sim.applier import atomic

    db, state, content = game
    name = _active_minister_name(db, content)
    db.upsert_pending_directive(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "外层事务回滚草稿", "actor": name},
    )
    original_apply = db._apply_pending_action

    def _boom_after_draft(
        state_arg, pa, payload, *, content=None, registry=None,
        rejection_collector=None,
    ):
        assert original_apply(
            state_arg, pa, payload, content=content, registry=registry,
            rejection_collector=rejection_collector,
        ) is True
        raise RuntimeError("directive commit boom")

    monkeypatch.setattr(db, "_apply_pending_action", _boom_after_draft)

    with atomic(db):
        db.commit_pending_actions(state, kind_filter="directive")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)).fetchone()[0] == 0
    row = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE turn=?",
        (state.turn,),
    ).fetchone()
    assert row["status"] == "failed"
    assert int(row["committed_directive_id"] or 0) == 0


def test_dialogue_affirm_commits_pending_directive_to_later_ui(game, monkeypatch):
    """#412：只有 directive 暂存时，皇帝应允应接收为拟旨候选，但仍保留后续准/驳界面。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    draft_text = "奉天承运皇帝诏曰，着兵部整饬三边，钦此。"
    did = db.upsert_pending_directive(state.turn, name,
                                      payload={**_POLICY_FIELDS, "text": draft_text, "actor": name})
    assert len(db.list_pending_actions(state.turn)) == 1

    # 皇帝「应允」：directive 暂存转入 turn_directives.pending，而不是 draft。
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准，就这么办",
        answer="臣即遵行，拟旨入档。",
        has_directive=False, secret_order_id=None)

    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE turn=?",
        (state.turn,)).fetchone()
    assert row is not None
    assert row["text"] == draft_text
    assert row["status"] == "pending"
    assert db.list_pending_actions(state.turn) == []


def test_dialogue_reject_drops_pending_directive(game, monkeypatch):
    """#412：只有 directive 暂存时，皇帝拒绝须删除它，避免颁诏默认同意。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    did = db.upsert_pending_directive(state.turn, name,
                                      payload={**_POLICY_FIELDS, "text": "草稿文", "actor": name})
    assert len(db.list_pending_actions(state.turn)) == 1

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "拒绝"}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="罢了，不必拟旨",
        answer="臣遵旨，撤回草稿。",
        has_directive=False, secret_order_id=None)

    assert db.list_pending_actions(state.turn) == []
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)).fetchone()[0] == 0


def test_explicit_secret_order_prefix_stages_pending_candidate(game, monkeypatch):
    """#413：显式「密令如下：」也必须先进召对确认闸门，不能在大臣回话前后直接落成密令。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    def _secret_extract(prompt, llm_config=None, tag=""):
        return (json.dumps({
            "标题": "密查辽饷",
            "内容": "查辽东军饷有无侵冒，并封存兵部辽饷册。",
            "承办人": name,
            "期限月数": 3,
            "差务": "核发辽饷",
            "价值轴": ["实务事功"],
            "方向": 1,
            "交付单位": "万两",
            "交付目标": 1, "效果符号": 1,
            "钱粮用途": "辽饷",
            "钱粮类别": "军饷",
            "钱粮账户": "国库",
            "标签": ["辽东", "军饷"],
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _secret_extract)
    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="密令如下：查辽东军饷有无侵冒，三月内回奏",
        answer="臣领密旨，先封存兵部辽饷册，再密访关宁诸将。",
        has_directive=False, secret_order_id=None,
    )

    assert out["secret_order_id"] in (None, 0)
    assert out["pending_action_id"]
    assert db.list_secret_orders() == []
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["kind"] == "secret_order"
    assert pending[0]["action"] == "新建"
    payload = json.loads(pending[0]["payload_json"])
    assert payload["title"] == "密查辽饷"
    assert "封存兵部辽饷册" in payload["content"]


def test_natural_language_secret_order_stages_pending_candidate(game, monkeypatch):
    """#513：真实 chat 入口只按结构化判词暂存新密令候选。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    def _extractors(prompt, llm_config=None, tag=""):
        if tag == "secret_extract":
            return (json.dumps({
                "标题": "暗查关宁",
                "内容": "暗查关宁诸将虚冒兵额，并密访粮道账册。",
                "承办人": name,
                "期限月数": 2,
                "差务": "查虚冒兵额",
                "价值轴": ["实务事功"],
                "方向": 1,
                "交付目标": 1, "效果符号": 1,
                "调查对象": name,
                "标签": ["关宁", "兵额"],
            }, ensure_ascii=False), 1)
        return (json.dumps({"任免动作": "无", "拟旨意图": "无"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _extractors)

    class Agent:
        def run(self, _message):
            return types.SimpleNamespace(
                content="臣领密旨，可先密访粮道账册，再核诸将营册，请陛下定夺。",
                tools=[],
            )

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = types.SimpleNamespace(get=lambda _character: Agent())
    sess.llm_config = types.SimpleNamespace(channel="cli")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    scripted = [{"kind": "secret", "secret_action": "新建"}]
    sess._start_cli_action_intent = lambda *_args, **_kwargs: scripted
    sess._finish_cli_action_intent = lambda future: future

    result = GameSession.chat(
        sess, name, "你替朕下一道密令，暗查关宁诸将虚冒兵额，两月内回奏。")

    assert result.secret_order_id in (None, 0)
    assert result.pending_action_id
    assert db.list_secret_orders() == []
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1
    assert pending[0]["kind"] == "secret_order"
    assert pending[0]["action"] == "新建"
    payload = json.loads(pending[0]["payload_json"])
    assert payload["title"] == "暗查关宁"
    assert "粮道账册" in payload["content"]


def test_secret_order_status_query_does_not_stage_new_hidden_order(game, monkeypatch):
    """问现有密令进展/状态不是新下密令，不能生成隐藏的新密令候选。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    create_test_secret_order(db, state, name, "暗查辽饷", "密查辽饷侵冒。", [], deadline_months=0)
    calls = []

    def _extractors(prompt, llm_config=None, tag=""):
        calls.append(tag)
        if tag == "secret_extract":
            return (json.dumps({
                "标题": "误建进展查询",
                "内容": "给朕查一下密令进展。",
                "承办人": name,
                "期限月数": 0,
                "差务": "清丈",
                "价值轴": ["实务事功"],
                "方向": 1,
                "交付单位": "万亩",
                "交付目标": 1, "效果符号": 1,
                "标签": [],
            }, ensure_ascii=False), 1)
        return (json.dumps({
            "动作类型": "无",
            "确认": "无",
            "密令动作": "无",
            "目标密令编号": 0,
            "拟旨意图": "无",
            "任免动作": "无",
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _extractors)

    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="给朕查一下密令进展。",
        answer="臣查得密令仍在暗访账册，尚未办结。",
        has_directive=False, secret_order_id=None,
    )

    assert out.get("pending_action_id") in (None, 0)
    assert db.list_pending_actions(state.turn) == []


def test_secret_order_progress_query_does_not_stage_new_hidden_order(read_game, monkeypatch):
    """“这道密令查到哪了”是查询进展，不是新下密令。"""
    db, state, content = read_game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(
        cb,
        "_run_backend_for_config",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("progress query must not extract new secret order")),
    )

    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="这道密令查到哪了？",
        answer="臣尚在追查。",
        has_directive=False,
        secret_order_id=None,
    )

    assert not out.get("pending_action_id")
    assert db.list_pending_actions(state.turn) == []


def test_secret_order_chaban_query_does_not_stage_new_hidden_order(read_game, monkeypatch):
    """“这道密令查办得如何”是查询，不是新建密令。"""
    db, state, content = read_game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(
        cb,
        "_run_backend_for_config",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("query must not extract new secret order")),
    )

    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="这道密令查办得如何？",
        answer="臣仍在查办。",
        has_directive=False,
        secret_order_id=None,
    )

    assert not out.get("pending_action_id")
    assert db.list_pending_actions(state.turn) == []


def test_new_secret_order_with_existing_order_stages_only_new_candidate(game, monkeypatch):
    """已有 active 密令时，另下一道密令不能同轮再把旧密令也 stage 一次更新。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    oid = create_test_secret_order(db, state, name, "旧令", "旧令内容。", [], deadline_months=0)

    def _extractors(prompt, llm_config=None, tag=""):
        if tag == "secret_extract":
            return (json.dumps({
                "标题": "新查粮道",
                "内容": "另下一道密令暗查粮道。",
                "承办人": name,
                "期限月数": 2,
                "差务": "核发辽饷",
                "价值轴": ["实务事功"],
                "方向": 1,
                "交付单位": "万两",
                "交付目标": 1, "效果符号": 1,
                "钱粮用途": "辽饷",
                "钱粮类别": "军饷",
                "钱粮账户": "国库",
                "标签": [],
            }, ensure_ascii=False), 1)
        return (json.dumps({
            "动作类型": "密令动作",
            "密令动作": "更新",
            "目标密令编号": oid,
            "新标题": "误改旧令",
            "新内容": "误改旧令内容",
            "期限月数": 0,
            "确认": "无",
            "拟旨意图": "无",
            "任免动作": "无",
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _extractors)

    out = GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="你替朕下一道密令，暗查粮道，两月内回奏。",
        answer="臣领旨，请陛下定夺。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "secret", "secret_action": "新建"},
    )

    assert out["pending_action_id"]
    pending = db.list_pending_actions(state.turn)
    assert [(p["kind"], p["action"], p["target_id"]) for p in pending] == [
        ("secret_order", "新建", None)
    ]


def test_dialogue_reject_drops_pending_new_secret_order(game, monkeypatch):
    """#413：皇帝拒绝待确认的新密令时，只删除暂存候选，不得稍后落成密令。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查关宁",
            "content": "暗查关宁诸将虚冒兵额。",
            "assignee": name,
            "tags": ["关宁"],
            "deadline_months": 2,
        },
    )

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "拒绝"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="罢了，不必下这道密令",
        answer="臣遵旨，撤去此令。",
        has_directive=False, secret_order_id=None,
    )

    assert db.list_pending_actions(state.turn) == []
    db.commit_pending_actions(state)
    assert db.list_secret_orders() == []


def test_dialogue_affirm_commits_pending_new_secret_order(game, monkeypatch):
    """#413：皇帝在召对里应允新密令后，密令无后续准驳界面，应立即正式落库。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={
            "title": "暗查关宁",
            "content": "暗查关宁诸将虚冒兵额。",
            "assignee": name,
            "tags": ["关宁"],
            "deadline_months": 2,
            "covert_task": TYPED_COVERT_TASK,
        },
    )

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="准，就照此密行",
        answer="臣即领密旨。",
        has_directive=False, secret_order_id=None,
    )

    assert db.list_pending_actions(state.turn) == []
    orders = db.list_secret_orders()
    assert len(orders) == 1
    assert orders[0]["title"] == "暗查关宁"
    assert orders[0]["content"] == "暗查关宁诸将虚冒兵额。"
    assert orders[0]["minister_name"] == name


# ── ⑤ "不回=颁诏默认同意"真实入口覆盖（ADR 0006 bugfix）────────────────────

def test_no_reply_path_directive_reachable_by_list_directives(game):
    """「不回」路径（不显式应允/拒绝，直接颁诏）：
    commit_pending_actions(kind_filter='directive') 把暂存提交为 draft，
    list_directives(status='draft') 能拾取 → resolve_turn 的"至少一条草案"守门不触发。
    这是 codex r1 finding [high] 的回归测试，覆盖颁诏前的 auto-commit 逻辑。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    draft_text = "奉天承运皇帝诏曰，着户部速清三边粮饷，钦此。"
    db.upsert_pending_directive(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": draft_text, "actor": name},
    )

    # 颁诏前 list_directives 返回空（暂存还在 pending_actions）
    assert db.list_directives(state, statuses=("draft",)) == []

    # 模拟 resolve_turn 的 auto-commit 步骤：kind_filter='directive'
    db.commit_pending_actions(state, kind_filter="directive")

    # 提交后 list_directives 能拾取 → "至少一条草案才能颁诏"守门不触发
    drafts = db.list_directives(state, statuses=("draft",))
    assert len(drafts) == 1
    assert drafts[0]["text"] == draft_text
    assert drafts[0]["status"] == "draft"

    # pending_count（计 turn_directives.status='pending'）仍为 0 → pending_count 守门不触发
    assert db.count_pending_directives(state) == 0


# ── ⑥ write_decree() 是 preview，不 default-commit（#498 finding3 / ADR 0006·0038）──
#
# 旧行为「write_decree() 先 commit_pending_actions 把未表态 pending 升为 draft」违背
# ADR 0006（0038 修订）：未表态 pending 只在**颁诏/过回合 checkpoint** 默认同意，拟诏
# （preview）不得改 pending status。故删除原 test_write_decree_commits_pending_directive
# （它锁的正是被拆除的违宪行为）；新契约「拟诏不动 pending、无 draft 响亮拒绝」由
# tests/test_audience_night_498.py::test_write_decree_leaves_unacted_pending_unchanged 覆盖。


# ── ⑦ state_payload 暴露 pending_directive_count（codex r3 finding [high]）────
#
# 对话式「拟旨吧」触发 pending_actions kind=directive 后，前端 EdictModal 的「拟诏」
# 按钮的 disabled 条件依赖 state.pending_directive_count > 0 来启用——若该字段没有
# 从 state_payload 正确下发，Web UI 的「不回=默认同意」路径就彻底断路。
# 本组测试验证 db 端的计数源（list_pending_actions filtered by kind）行为正确，
# 是 web_app.py state_payload 的 pending_directive_count 计算逻辑的单元锚。

def test_pending_directive_count_nonzero_after_conversational_draft(game):
    """对话式草案暂存后，过滤 kind=directive 的 list_pending_actions 计数 > 0。
    这是 state_payload 计算 pending_directive_count 的直接数据源。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    db.upsert_pending_directive(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "草稿", "actor": name},
    )

    directive_pending = [
        a for a in db.list_pending_actions(state.turn)
        if a["kind"] == "directive"
    ]
    assert len(directive_pending) == 1, "state_payload 的 pending_directive_count 应为 1"


def test_pending_directive_count_zero_after_commit(game):
    """commit 后 kind=directive 暂存清空，state_payload.pending_directive_count 应变回 0，
    前端「拟诏」按钮依赖 draftDirectives.length（commit 落进 turn_directives）决定可用。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    db.upsert_pending_directive(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "草稿", "actor": name},
    )
    db.commit_pending_actions(state, kind_filter="directive")

    directive_pending = [
        a for a in db.list_pending_actions(state.turn)
        if a["kind"] == "directive"
    ]
    assert directive_pending == [], "commit 后 pending_directive_count 应为 0"


def test_pending_directive_count_zero_without_any_draft(read_game):
    """无对话式草案时 pending_directive_count 为 0，
    state_payload 不误触发「拟诏」按钮。"""
    db, state, content = read_game
    directive_pending = [
        a for a in db.list_pending_actions(state.turn)
        if a["kind"] == "directive"
    ]
    assert directive_pending == []


# ── ⑧ codex r5 F1 — 「补充」须进拟旨抽取契约（has_pending_draft 路径） ──────────

def test_extract_draft_intent_prompt_includes_supplement_hint_when_has_pending(monkeypatch):
    """has_pending_draft=True 时，extract_draft_intent 送给 LLM 的 prompt 包含「补充」提示，
    使「再补一条」之类的玩家话语被 LLM 正确归为拟旨意图（codex r5 F1）。"""
    prompts_seen = []

    def _capture(prompt, llm_config=None, tag=""):
        prompts_seen.append(prompt)
        return (json.dumps({"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}, ensure_ascii=False), 1)

    import ming_sim.cli_backend as cb_mod
    monkeypatch.setattr(cb_mod, "_run_backend_for_config", _capture)

    result = cb.extract_draft_intent(
        "再补一条，加上监察御史同行",
        "好的，臣即补充。",
        has_pending_draft=True,
    )
    assert result["draft_action"] == "拟旨"
    assert prompts_seen, "应调用 LLM"
    prompt = prompts_seen[0]
    assert "补充" in prompt, "prompt 应包含「补充」提示，以引导 LLM 正确判补充意图"


def test_extract_draft_intent_supplement_schema_keeps_valid_json_comma(monkeypatch):
    """补充模式的 JSON 示例要在「拟旨意图」后保留逗号；
    否则「合并草案」紧跟上一字段会诱导模型输出坏 JSON。"""
    prompts_seen = []

    def _capture(prompt, llm_config=None, tag=""):
        prompts_seen.append(prompt)
        return (json.dumps(
            {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy", "合并草案": "合并后的完整草案"},
            ensure_ascii=False,
        ), 1)

    import ming_sim.cli_backend as cb_mod
    monkeypatch.setattr(cb_mod, "_run_backend_for_config", _capture)

    cb.extract_draft_intent(
        "再补一条",
        "臣遵旨补入。",
        has_pending_draft=True,
        existing_draft_text="原始草案：清查粮饷。",
    )

    assert prompts_seen
    prompt = prompts_seen[0]
    assert '"拟旨意图": "无|拟旨",' in prompt
    assert '"拟旨意图": "无|拟旨"  // 皇帝' not in prompt


def test_extract_draft_intent_coerces_non_string_existing_draft_text(monkeypatch):
    """防御性兜底：existing_draft_text 若被传入非字符串，也不能在 .strip() 处崩；
    空合并草案时 draft_text 回落为 str(coerced)（#1185：不盯 prompt 中文标签）。"""

    def _capture(prompt, llm_config=None, tag=""):
        # empty 合并草案 → extract falls back to coerced existing_draft_text
        return (json.dumps(
            {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy", "合并草案": ""},
            ensure_ascii=False,
        ), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)

    result = cb.extract_draft_intent(
        "再补一条",
        "臣遵旨补入。",
        has_pending_draft=True,
        existing_draft_text=123,
    )

    assert result["draft_action"] == "拟旨"
    assert result["draft_text"] == "123"


def test_extract_draft_intent_no_supplement_hint_when_no_pending(monkeypatch):
    """has_pending_draft=False（默认）时，prompt 不含补充提示（保持原行为不变）。"""
    prompts_seen = []

    def _capture(prompt, llm_config=None, tag=""):
        prompts_seen.append(prompt)
        return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)

    import ming_sim.cli_backend as cb_mod
    monkeypatch.setattr(cb_mod, "_run_backend_for_config", _capture)

    cb.extract_draft_intent("今天天气不错", "是啊。", has_pending_draft=False)
    assert prompts_seen
    assert "本回合已有草案暂存" not in prompts_seen[0], "无 pending draft 时不应注入补充提示"


def test_last_write_wins_uses_has_pending_draft_flag(game, monkeypatch):
    """second-round 补充调用走 apply_cli_conversation_actions：
    已有 pending directive 时应以 has_pending_draft=True 调 extract_draft_intent
    （#1185：委派 spy 咬公共 kwargs，不盯 prompt 中文）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    # 先 stage 一条 pending directive
    db.upsert_pending_directive(state.turn, name,
                                payload={**_POLICY_FIELDS, "text": "第一版草稿", "actor": name})

    def _capture(prompt, llm_config=None, tag=""):
        # 确认意图=无；拟旨意图=拟旨 + 合并草案（LWW 写回）
        if "待皇帝定夺" in prompt or "应允" in prompt:
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        return (json.dumps({
            "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
            "目标ID": "test-policy", "合并草案": "第一版草稿，加上监察御史随行",
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)

    fed: list[dict] = []
    real_extract = cb.extract_draft_intent

    def _spy_extract(*args, **kwargs):
        fed.append({
            "has_pending_draft": kwargs.get("has_pending_draft"),
            "existing_draft_text": kwargs.get("existing_draft_text"),
        })
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(cb, "extract_draft_intent", _spy_extract)
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="再补一条，加上监察御史同行",
        answer="好的，加上监察御史随行。",
        has_directive=False, secret_order_id=None,
    )

    assert fed, "应调用 extract_draft_intent"
    assert fed[0]["has_pending_draft"] is True
    assert fed[0]["existing_draft_text"] == "第一版草稿"
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1
    assert json.loads(pend[0]["payload_json"])["text"] == "第一版草稿，加上监察御史随行"


def test_draft_request_with_appointment_content_stages_directive_and_office(game, monkeypatch):
    """#1380：拟旨含任免内容须 directive+office 双 stage（「诏出人不动」病反例）。

    旧名 stages_directive_not_office 编码的是 #1380 拍定要改的旧行为
    （任免只埋草案、不 stage office → 颁诏后人不落职）。法源 #1380 / QA-C P0。
    P5：appointment 走结构化 multi candidates，禁串行 extract_appointment_action。
    """
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    def _capture(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            raise AssertionError(
                "#1380 P5: structured multi appointment must not call serial extractor"
            )
        if tag == "draft_intent":
            return (json.dumps({"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="帮我拟一道旨，授史可法为兵部尚书。",
        answer="奉天承运皇帝诏曰，授史可法为兵部尚书，总理部务，钦此。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[
            {"kind": "draft"},
            {
                "kind": "appointment",
                "appoint_action": "任命",
                "name": "史可法",
                "office": "兵部尚书",
            },
        ],
    )

    pending = db.list_pending_actions(state.turn)
    kinds = sorted(p["kind"] for p in pending)
    assert kinds == ["directive", "office"], (
        f"#1380 拟旨含任免须 directive+office，实际={kinds}"
    )
    directive = next(p for p in pending if p["kind"] == "directive")
    office = next(p for p in pending if p["kind"] == "office")
    assert "史可法" in json.loads(directive["payload_json"])["text"]
    assert json.loads(office["payload_json"]).get("name") == "史可法"


def test_api_channel_multi_draft_appointment_not_dropped_by_draft_bias(
    game, monkeypatch,
):
    """#1502：API 通道 multi draft+appointment 不得因拟旨偏置省略 office。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    def _capture(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            raise AssertionError(
                "#1502 multi structured appointment must not call serial extractor"
            )
        if tag == "draft_intent":
            return (json.dumps({
                "拟旨意图": "拟旨",
                "动作类型": "special_decree",
                "目标类型": "character",
                "目标ID": "史可法",
            }, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    sess = types.SimpleNamespace(
        db=db, state=state,
        llm_config=types.SimpleNamespace(channel="api"),
        registry=None,
    )
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="帮我拟一道旨，授史可法为兵部尚书。",
        answer="奉天承运皇帝诏曰，授史可法为兵部尚书，钦此。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[
            {"kind": "draft"},
            {
                "kind": "appointment",
                "appoint_action": "任命",
                "name": "史可法",
                "office": "兵部尚书",
            },
        ],
    )
    pending = db.list_pending_actions(state.turn)
    kinds = sorted(p["kind"] for p in pending)
    assert "directive" in kinds and "office" in kinds, (
        f"#1502 API multi 须 draft+appointment 并存，实际={kinds}"
    )
    office = next(p for p in pending if p["kind"] == "office")
    assert json.loads(office["payload_json"]).get("name") == "史可法"


def test_structured_verdict_alone_routes_natural_language_action(game, monkeypatch):
    """#513：散文关键词不得覆盖结构化判词；只有判词决定候选暂存。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    monkeypatch.setattr(
        cb,
        "_run_backend_for_config",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("structured verdict must not be overridden by prose scanners")
        ),
    )

    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="朕方才只是引一句旧话：下密令拟旨；现命史可法署理兵部。",
        answer="臣领命，请陛下定夺。",
        has_directive=False, secret_order_id=None,
        preclassified_intent={
            "kind": "appointment",
            "appoint_action": "任命",
            "name": "史可法",
            "office": "兵部尚书",
        },
    )

    pending = db.list_pending_actions(state.turn)
    assert [p["kind"] for p in pending] == ["office"]
    assert json.loads(pending[0]["payload_json"])["name"] == "史可法"


def test_none_player_message_does_not_crash_draft_probe(read_game, monkeypatch):
    """系统生成/空消息路径可能传 player_message=None；拟旨关键词探针必须兜底为无请求。"""
    db, state, content = read_game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    def _none_actions(prompt, llm_config=None, tag=""):
        if tag == "appointment":
            return (json.dumps({"任免动作": "无"}, ensure_ascii=False), 1)
        if tag == "draft_intent":
            return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)
        return ("{}", 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _none_actions)
    sess = _fake_session(db, state)

    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message=None,
        answer="臣谨奏，今日并无可拟之旨。",
        has_directive=False, secret_order_id=None,
    )

    assert db.list_pending_actions(state.turn) == []


def test_discard_pending_directives_does_not_commit_outer_transaction(game):
    """discard_pending_directives 只做删除，不拥有 commit；
    外层事务若回滚，被丢弃的 directive pending 必须恢复。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    db.upsert_pending_directive(state.turn, name,
                                payload={**_POLICY_FIELDS, "text": "可回滚草稿", "actor": name})
    assert len(db.list_pending_actions(state.turn)) == 1

    db.conn.execute("BEGIN")
    try:
        deleted = db.discard_pending_directives(state.turn)
        assert deleted == 1
        assert db.list_pending_actions(state.turn) == []
    finally:
        db.conn.rollback()

    rows = db.list_pending_actions(state.turn)
    assert len(rows) == 1
    assert rows[0]["kind"] == "directive"


# ── ⑩ codex r6 F1 — 补充轮增量合并而非回话覆盖 ──────────────────────────────

def test_supplement_stores_merged_draft_not_raw_reply(game, monkeypatch):
    """补充轮产生的 pending directive payload 应为 LLM 合并后的草案，
    不能是大臣的确认回话（「好的，加上…」）覆盖原草案（codex r6 F1）。

    LLM 返回 {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy", "合并草案": "<merged>"} 时，
    payload["text"] 应等于 merged，而非 minister_reply（确认语）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    original_text = "原始草稿：着户部清查三边粮饷，限三月完报。"
    confirmation_reply = "好的，臣即补入，着监察御史随行。"
    merged_draft = "合并草稿：着户部清查三边粮饷，监察御史随行，限三月完报。"

    db.upsert_pending_directive(state.turn, name,
                                payload={**_POLICY_FIELDS, "text": original_text, "actor": name})

    def _capture(prompt, llm_config=None, tag=""):
        if tag == "draft_intent":
            return (json.dumps(
                {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy", "合并草案": merged_draft}, ensure_ascii=False), 1)
        # 确认意图：无（不提前 commit/drop）
        return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="再补一条，监察御史随行",
        answer=confirmation_reply,
        has_directive=False, secret_order_id=None,
    )

    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1, "仍应只有一条 pending directive（last-write-wins）"
    payload = json.loads(pend[0]["payload_json"])
    assert payload["text"] == merged_draft, (
        f"补充轮应存 LLM 合并草案，实际得到: {payload['text']!r}"
    )
    assert confirmation_reply not in payload["text"], (
        "payload 不能是大臣确认回话（会丢失原草案）"
    )
    assert original_text not in payload["text"], (
        "payload 应是合并后的完整草案，不是原始草案"
    )


# ── ⑪ codex r6 F2 — undo_chat_turn 也回滚 write_decree 产生的 draft ──────────

def test_undo_chat_turn_removes_write_decree_draft(game):
    """stage 对话式草案 → write_decree() 提前 commit 成 draft → undo_chat_turn()：
    撤回后 pending_actions 被删、turn_directives draft 也必须被删（codex r6 F2）。

    turn_directives 行由 write_decree() 产生，时序晚于快照故不在 rollback_items；
    undo 须显式按 (turn, actor) 删除对应 draft，否则撤回后草案仍可颁诏。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    ctid = db.create_chat_turn(state, name, "sess-undo-draft-r6", 0)
    before = db.capture_chat_rollback_snapshot()
    db.upsert_pending_directive(
        state.turn, name,
        payload={**_POLICY_FIELDS, "text": "草案文本（将被撤回）", "actor": name},
    )
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ctid, before, after)

    # 模拟 write_decree() 把 pending directive commit 成 turn_directives draft
    db.commit_pending_actions(state, kind_filter="directive")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0] == 1, "write_decree 应已建 draft 行"

    # 撤回召对
    db.undo_chat_turn(ctid)

    # pending_actions 被删（正常回滚）
    assert db.list_pending_actions(state.turn) == [], "撤回后 pending_actions 应为空"

    # turn_directives draft 也必须被删（codex r6 F2 修复）
    remaining = db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0]
    assert remaining == 0, (
        f"undo 后 turn_directives draft 应被删，但仍有 {remaining} 行"
    )


# ── ⑫ extract_draft_intent 降级分支（issue #137 覆盖补缺）──────────────────────

def test_supplement_mode_falls_back_to_existing_draft_when_merged_empty(monkeypatch):
    """补充模式（has_pending_draft + existing_draft_text）拟旨，但 LLM 未填「合并草案」：
    draft_text 应保留 existing_draft_text，避免用确认回话覆盖旧草案。"""
    def _canned(prompt, llm_config=None, tag=""):
        # 拟旨意图=拟旨，但故意不带「合并草案」字段
        return (json.dumps({"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned)
    result = cb.extract_draft_intent(
        "再补一条，加上监察御史同行",
        "臣即补入，着监察御史随行督查。",
        has_pending_draft=True,
        existing_draft_text="原始草稿：着户部清查三边粮饷。",
    )
    assert result["draft_action"] == "拟旨"
    assert result["draft_text"] == "原始草稿：着户部清查三边粮饷。"
    assert "臣即补入" not in result["draft_text"]


def test_supplement_mode_prefers_merged_when_present(monkeypatch):
    """对照组：补充模式 LLM 填了「合并草案」时，draft_text 取合并草案而非大臣回话。
    锚定 719-722 分支两侧（merged 非空走 merged）。"""
    def _canned(prompt, llm_config=None, tag=""):
        return (json.dumps(
            {"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy", "合并草案": "合并：着户部及监察御史同查三边粮饷。"},
            ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned)
    result = cb.extract_draft_intent(
        "加上监察御史", "好的，臣即补入。",
        has_pending_draft=True,
        existing_draft_text="原始草稿：着户部清查三边粮饷。",
    )
    assert result["draft_text"] == "合并：着户部及监察御史同查三边粮饷。"
    assert "好的，臣即补入" not in result["draft_text"]


def test_extract_draft_intent_backend_exception_degrades_to_none(monkeypatch):
    """_run_backend_for_config 抛异常 → _log 兜底、raw 保持空串 → 归一为「无」、空草稿
    （cli_backend.py:714-715 异常路径 + 723-724 默认 draft_text）。"""
    def _boom(prompt, llm_config=None, tag=""):
        raise RuntimeError("backend down")

    logged = []
    monkeypatch.setattr(cb, "_run_backend_for_config", _boom)
    monkeypatch.setattr(cb, "_log", lambda msg: logged.append(msg))

    result = cb.extract_draft_intent("拟旨吧", "奉天承运皇帝诏曰，特谕户部清查。")
    # 异常 → raw 空 → obj 空 → 拟旨意图归一为「无」（不触发草案 stage）
    assert result["draft_action"] == "无"
    assert result["draft_text"] == ""
    # _log 被调用记录失败
    assert any("拟旨意图抽取失败" in m for m in logged)


def test_extract_draft_intent_non_object_json_degrades_to_none(monkeypatch):
    """LLM 若返回合法但非对象的 JSON（如数组），也不能在 .get() 处崩；
    应按无拟旨意图降级。"""
    def _array_payload(prompt, llm_config=None, tag=""):
        return (json.dumps(["拟旨"], ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _array_payload)

    result = cb.extract_draft_intent("拟旨吧", "臣遵旨。")

    assert result == {"draft_action": "无", "draft_text": "", "target_candidate": ""}


def test_extract_draft_intent_dirty_action_normalized_to_none(monkeypatch):
    """LLM 返回非 {无,拟旨} 的脏「拟旨意图」值 → 归一为「无」（cli_backend.py:718）。
    脏动作不得误触发草案 stage。"""
    def _dirty(prompt, llm_config=None, tag=""):
        return (json.dumps({"拟旨意图": "也许吧"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _dirty)
    result = cb.extract_draft_intent("拟旨吧", "臣遵旨。")
    assert result["draft_action"] == "无"
    assert result["draft_text"] == ""


def test_extract_draft_intent_no_intent_returns_empty_draft_text(monkeypatch):
    """LLM 明确判「无」时，draft_text 必须为空串而不是大臣回话。
    调用方当前也看 draft_action，但 helper 契约写的是无意图→空草稿。"""
    def _no_intent(prompt, llm_config=None, tag=""):
        return (json.dumps({"拟旨意图": "无"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _no_intent)
    result = cb.extract_draft_intent("今日只是问策。", "臣以为当暂缓。")
    assert result == {"draft_action": "无", "draft_text": "", "target_candidate": ""}


# ── ⑬ session.py 补充模式 existing_draft_text 提取的 JSON 兜底（894-899）─────────

def test_supplement_existing_draft_text_swallows_malformed_payload_json(game, monkeypatch):
    """补充轮提取 existing_draft_text 时，pending directive 的 payload_json 是坏 JSON：
    json.loads 抛 → except 兜底为空串；extract_draft_intent 仍被调用（#1185：spy kwargs）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    pid = db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "原始草稿", "actor": name})
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        ("{这不是合法JSON", int(pid)))
    db.conn.commit()

    def _capture(prompt, llm_config=None, tag=""):
        if "待皇帝定夺" in prompt or "应允" in prompt:
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        return (json.dumps({"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    fed: list[dict] = []
    real_extract = cb.extract_draft_intent

    def _spy_extract(*args, **kwargs):
        fed.append({
            "has_pending_draft": kwargs.get("has_pending_draft"),
            "existing_draft_text": kwargs.get("existing_draft_text"),
        })
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(cb, "extract_draft_intent", _spy_extract)
    sess = _fake_session(db, state)
    with pytest.raises(ValueError):
        GameSession.apply_cli_conversation_actions(
            sess, ch, player_message="再补一条", answer="新草稿：着户部及兵部同查。",
            has_directive=False, secret_order_id=None,
        )

    assert fed, "坏 JSON 不得阻断 extract_draft_intent"
    assert fed[0]["has_pending_draft"] is True
    assert fed[0]["existing_draft_text"] == ""
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1
    assert pend[0]["id"] == pid
    assert pend[0]["payload_json"] == "{这不是合法JSON"


@pytest.mark.parametrize("payload_json", ["null", "[1, 2, 3]"])
def test_supplement_existing_draft_text_ignores_non_object_payload_json(
    game, monkeypatch, payload_json
):
    """补充轮 pending directive 的 payload_json 若是合法 JSON 但非 object：
    兜底为空草案文本；extract 仍收到 has_pending_draft + empty existing（#1185 spy）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    pid = db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "原始草稿", "actor": name})
    db.conn.execute(
        "UPDATE pending_actions SET payload_json=? WHERE id=?",
        (payload_json, int(pid)))
    db.conn.commit()

    def _capture(prompt, llm_config=None, tag=""):
        if "待皇帝定夺" in prompt or "应允" in prompt:
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        return (json.dumps({"拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue", "目标ID": "test-policy"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    fed: list[dict] = []
    real_extract = cb.extract_draft_intent

    def _spy_extract(*args, **kwargs):
        fed.append({
            "has_pending_draft": kwargs.get("has_pending_draft"),
            "existing_draft_text": kwargs.get("existing_draft_text"),
        })
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(cb, "extract_draft_intent", _spy_extract)
    sess = _fake_session(db, state)

    with pytest.raises(ValueError):
        GameSession.apply_cli_conversation_actions(
            sess, ch, player_message="再补一条", answer="新草稿：着户部及兵部同查。",
            has_directive=False, secret_order_id=None,
        )

    assert fed and fed[0]["has_pending_draft"] is True
    assert fed[0]["existing_draft_text"] == ""
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1
    assert pend[0]["id"] == pid
    assert pend[0]["payload_json"] == payload_json


def test_supplement_existing_draft_text_accepts_preparsed_payload_json(game, monkeypatch):
    """测试/替身可能把 payload_json 预解析为 dict；补充模式应直接读取 text 喂给 extract。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "原始草稿：清查粮饷。", "actor": name})

    original_list_pending_actions = db.list_pending_actions

    def _list_with_preparsed_payload(*args, **kwargs):
        rows = original_list_pending_actions(*args, **kwargs)
        out = []
        for row in rows:
            row = dict(row)
            if row["kind"] == "directive":
                row["payload_json"] = {"text": "原始草稿：清查粮饷。", "actor": name}
            out.append(row)
        return out

    monkeypatch.setattr(db, "list_pending_actions", _list_with_preparsed_payload)

    def _capture(prompt, llm_config=None, tag=""):
        if "待皇帝定夺" in prompt or "应允" in prompt:
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        return (json.dumps({
            "拟旨意图": "拟旨", "动作类型": "policy", "目标类型": "issue",
            "目标ID": "test-policy", "合并草案": "合并草稿",
        }, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    fed: list[dict] = []
    real_extract = cb.extract_draft_intent

    def _spy_extract(*args, **kwargs):
        fed.append({
            "has_pending_draft": kwargs.get("has_pending_draft"),
            "existing_draft_text": kwargs.get("existing_draft_text"),
        })
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(cb, "extract_draft_intent", _spy_extract)
    sess = _fake_session(db, state)

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="再补一条", answer="加上监察御史同行。",
        has_directive=False, secret_order_id=None,
    )

    assert fed and fed[0]["has_pending_draft"] is True
    assert fed[0]["existing_draft_text"] == "原始草稿：清查粮饷。"
    # read through the real list (not the preparsed stub)
    monkeypatch.setattr(db, "list_pending_actions", original_list_pending_actions)
    pend = db.list_pending_actions(state.turn)
    assert len(pend) == 1
    payload = pend[0]["payload_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["text"] == "合并草稿"


# ── ⑭ db.py _apply_pending_action directive 落库降级分支（5824-5826）────────────

def test_commit_directive_with_empty_text_returns_false_no_archive(game):
    """kind=directive 暂存 payload.text 为空串 → 落库返回 False、不建 turn_directives 行
    （db.py:5825-5826），pending 行被标 failed（不留 pending）。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    # 直接 stage 一条 text 为空的 directive（绕开 upsert 的语义）
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨",
        minister_name=name, target_id=None,
        payload={**_POLICY_FIELDS, "text": "   ", "actor": name})

    assert len(db.list_pending_actions(state.turn)) == 1

    applied = db.commit_pending_actions(state, kind_filter="directive")

    # 空 text → 不建档
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)).fetchone()[0] == 0
    # 未进 applied（落库 False）
    assert not any(a["kind"] == "directive" for a in applied)
    # pending 行不再 pending（标 failed）
    assert db.list_pending_actions(state.turn) == []
    failed = db.conn.execute(
        "SELECT COUNT(*) FROM pending_actions WHERE turn=? AND status='failed'",
        (state.turn,)).fetchone()[0]
    assert failed == 1


def test_commit_pending_actions_rejects_conflicting_kind_filters(game):
    """kind_filter 与 kind_filter_exclude 互斥；同时传入是调用方错误，必须响亮拒绝。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案：清查钱粮", "actor": name})

    with pytest.raises(ValueError, match="kind_filter.*kind_filter_exclude"):
        db.commit_pending_actions(
            state, kind_filter="directive", kind_filter_exclude="secret_order")


def test_commit_directive_actor_falls_back_to_minister_name(game):
    """payload 无 actor 字段 → actor 回退到 pa['minister_name']（db.py:5824）。
    turn_directives.actor 应等于 stage 时的 minister_name。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    draft_text = "奉天承运皇帝诏曰，着户部清查三边粮饷，钦此。"
    # payload 故意不带 actor 键
    db.stage_pending_action(
        state.turn, kind="directive", action="拟旨",
        minister_name=name, target_id=None,
        payload={**_POLICY_FIELDS, "text": draft_text})

    db.commit_pending_actions(state, kind_filter="directive")

    row = db.conn.execute(
        "SELECT text, status, actor FROM turn_directives WHERE turn=? ORDER BY id DESC",
        (state.turn,)).fetchone()
    assert row is not None
    assert row["text"] == draft_text
    assert row["status"] == "draft"
    # actor 回退到 minister_name
    assert row["actor"] == name


def test_commit_directive_rolls_back_draft_when_bookkeeping_update_fails(game):
    """directive commit 要么同时完成 draft insert + committed_directive_id + status，
    要么全部不落。用触发器模拟 committed_directive_id 回填失败，不能留下 orphan draft。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案：清查三边粮饷", "actor": name})
    db.conn.execute(
        """
        CREATE TEMP TRIGGER fail_committed_directive_id
        BEFORE UPDATE OF committed_directive_id ON pending_actions
        WHEN NEW.committed_directive_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'simulated committed_directive_id failure');
        END;
        """
    )
    db.conn.commit()

    # #654 路1：回填失败经 SAVEPOINT 吞没 → failed，不留 orphan draft
    db.commit_pending_actions(state, kind_filter="directive")

    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=?", (state.turn,)
    ).fetchone()[0] == 0
    status = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE turn=?",
        (state.turn,),
    ).fetchone()
    assert status["status"] == "failed"
    assert int(status["committed_directive_id"] or 0) == 0


# ── ⑮ BUG 1 — 召对确认闸门必须放过 kind=directive ───────────────────────────

def test_confirm_gate_does_not_sweep_conversational_directive(game, monkeypatch):
    """BUG 1（CRITICAL）：对话式拟旨（kind=directive）暂存后，同一大臣的后一轮若被判为
    「应允/拒绝」（针对另一条非 directive 暂存，或 LLM 误判任意话语），不得波及 directive。

    召对确认闸门的应允/拒绝语义只属于召对期暂存（密令/任免/调教）——拟旨的接受/搁置是
    颁诏期语义（不回=默认同意）。故 directive 必须存活：应允不得提前 commit 成 draft，
    拒绝不得静默删除玩家草案。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    # 同一大臣：一条对话式拟旨 + 一条非 directive 暂存（office 任免，确认闸门的真正对象）
    did = db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案：着户部清查三边粮饷。", "actor": name})
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=name, target_id=None,
        payload={"name": "某新臣", "office": "兵部主事", "appointer": name})
    assert len(db.list_pending_actions(state.turn)) == 2

    # 后一轮被判「应允」（语义针对 office 暂存）：directive 必须存活、不被提前 commit
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准了", answer="臣遵旨。",
        has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    surviving = [p for p in pend if p["kind"] == "directive"]
    assert len(surviving) == 1, "应允轮不得提前 commit 对话式拟旨"
    assert surviving[0]["id"] == did
    # directive 未被提前落进 turn_directives（颁诏期才落）
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0] == 0, "应允轮不得提前建 draft"


def test_confirm_reject_does_not_delete_conversational_directive(game, monkeypatch):
    """BUG 1（CRITICAL）拒绝侧：后一轮被判「拒绝」时，drop_pending_actions_for_minister
    不得连带删掉玩家的对话式拟旨草案。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    did = db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案：着兵部整饬三边。", "actor": name})
    db.stage_pending_action(
        state.turn, kind="office", action="任命", minister_name=name, target_id=None,
        payload={"name": "某新臣", "office": "兵部主事", "appointer": name})

    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "拒绝"}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="不必了", answer="臣遵旨，撤回。",
        has_directive=False, secret_order_id=None)

    pend = db.list_pending_actions(state.turn)
    surviving = [p for p in pend if p["kind"] == "directive"]
    assert len(surviving) == 1, "拒绝轮不得删除玩家的对话式拟旨草案"
    assert surviving[0]["id"] == did


def test_targeted_directive_rejection_does_not_drop_secret_order(game, monkeypatch):
    """同一大臣同时有密令候选和拟旨时，点名“圣旨作罢”只应丢拟旨。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    directive_id = db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案：清查三边粮饷。", "actor": name})
    secret_id = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "暗查辽饷", "content": "密查辽饷侵冒。", "assignee": name})

    # 确认判读只许结构化 LLM 枚举（ADR 0028）；stub 拒绝，禁词表快路。
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda prompt, llm_config=None, tag="": (
            json.dumps({"确认": "拒绝"}, ensure_ascii=False), 1),
    )
    GameSession.apply_cli_conversation_actions(
        _fake_session(db, state), ch,
        player_message="那道圣旨作罢。",
        answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

    pending = db.list_pending_actions(state.turn)
    assert [p["id"] for p in pending] == [secret_id]
    assert not any(p["id"] == directive_id for p in pending)


# ── ⑯ BUG 2 — write_decree 的 pending_count 守门须早于 commit ─────────────────

def test_write_decree_rejects_before_committing_conversational_directive(game):
    """BUG 2（CRITICAL）：存在未核定的显式 pending directive（pending_count>0）时，
    write_decree 必须在 commit 对话式拟旨【之前】响亮拒绝，不得先把对话草案落成 draft
    再 raise——否则被拒的调用仍留下副作用、无回滚。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    # 显式 pending directive（待准/驳）→ pending_count>0
    db.add_directive(state, None, "显式拟旨：着户部议屯田。", "大臣拟旨",
                     actor=name, notes="显式", status="pending")
    assert db.count_pending_directives(state) > 0
    # 同时有一条对话式拟旨暂存
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "对话草案：着兵部整饬。", "actor": name})

    fake_sess = types.SimpleNamespace(
        db=db, state=state, content=None, registry=None,
        llm_config=types.SimpleNamespace(channel="cli"),
        agno_db=None, last_decree="")
    fake_sess._refuse_if_settling = lambda: None
    fake_sess.pending_count = lambda: db.count_pending_directives(state)

    with pytest.raises(ValueError):
        GameSession.write_decree(fake_sess)

    # 关键：对话式拟旨未被提前 commit —— 仍是 pending、未生成 draft
    pend = db.list_pending_actions(state.turn)
    assert any(p["kind"] == "directive" for p in pend), "被拒时对话式拟旨不得已被 commit"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0] == 0, "被拒时不得已落下 draft 副作用"


# ── ⑰ BUG 3 — undo_chat_turn 只删本轮自己产生的 draft ────────────────────────

def test_undo_chat_turn_preserves_unrelated_same_actor_draft(game):
    """BUG 3（data-loss）：撤回一轮对话式召对，不得连带删掉同一 actor、同回合的【无关】
    draft（如本回合早些时候经显式准驳确认的 directive draft）。

    旧实现按 (turn, actor, status='draft') 删，会过度删除；修复后须只删本 undo 自己 commit
    产生的那条 draft。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    # 先有一条无关的同 actor draft（模拟早先显式准驳后落的 draft）
    unrelated_id = db.add_directive(
        state, None, "无关草案：着工部修河。", "大臣拟旨",
        actor=name, notes="早先确认", status="draft")

    # 一轮对话式召对：stage 对话草案 → 快照 → write_decree 式 commit 成 draft
    ctid = db.create_chat_turn(state, name, "sess-undo-scope", 0)
    before = db.capture_chat_rollback_snapshot()
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "对话草案（将被撤回）。", "actor": name})
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ctid, before, after)
    db.commit_pending_actions(state, kind_filter="directive")

    # 此刻两条 draft
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0] == 2

    db.undo_chat_turn(ctid)

    # 无关 draft 必须存活
    surviving = db.conn.execute(
        "SELECT id FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchall()
    surviving_ids = {int(r["id"]) for r in surviving}
    assert unrelated_id in surviving_ids, "撤回对话召对不得删掉无关的同 actor draft"
    assert len(surviving_ids) == 1, "只应剩无关 draft（本轮自产 draft 被回滚）"


def test_undo_supplement_turn_removes_committed_draft(game):
    """BUG（data-integrity）：补充轮（第 2 次拟旨）走 UPDATE → restore_row 路径，
    其后 write_decree() commit 出 draft。撤回该补充轮时，旧实现只从 delete_inserted_row
    诊断单收 committed_directive_id，漏掉 restore_row 这条，导致 orphan draft 残留 +
    复活的 pending 行再次 commit 出含被撤回文本的 draft → 颁诏污染。

    时序（web 每条聊天消息各为一个 chat turn）：
      turn1：首拟「v1」→ INSERT pending（delete_inserted_row）
      turn2：补充「v2」→ UPDATE 同一 pending 行（restore_row，before=v1/after=v2）
      write_decree：commit pending → turn_directives draft（text=v2）+ pending.committed_directive_id
      undo turn2（全局最后一轮）→ 应删 orphan draft、复活 pending 回 v1
    撤回后：本 actor/turn 的 draft 必须为 0；再 commit 不得产出含 v2 的 draft。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    # turn1：首拟 v1（INSERT pending）—— 在快照外建立 pending 行
    ct1 = db.create_chat_turn(state, name, "sess-suppl-1", 0)
    before1 = db.capture_chat_rollback_snapshot()
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案 v1", "actor": name})
    after1 = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ct1, before1, after1)

    # turn2：补充 v2（UPDATE 同一 pending 行 → restore_row diff）
    ct2 = db.create_chat_turn(state, name, "sess-suppl-2", 0)
    before2 = db.capture_chat_rollback_snapshot()
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案 v2（将被撤回）", "actor": name})
    after2 = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ct2, before2, after2)

    # write_decree() 提前 commit：pending → turn_directives draft（text=v2）
    db.commit_pending_actions(state, kind_filter="directive")
    assert db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0] == 1, "write_decree 应已建 draft 行"

    # 撤回补充轮（turn2 是全局最后一轮 active）
    db.undo_chat_turn(ct2)

    # orphan committed draft 必须被删（修复点）
    remaining = db.conn.execute(
        "SELECT COUNT(*) FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchone()[0]
    assert remaining == 0, (
        f"撤回补充轮后 turn_directives draft 应被删，但仍有 {remaining} 行（orphan）"
    )

    # 复活的 pending 行须回到 v1（restore_row 还原），且不带残留 committed_directive_id
    pending = db.list_pending_actions(state.turn)
    assert len(pending) == 1, "撤回补充轮应复活 v1 的 pending 行"
    payload = json.loads(pending[0]["payload_json"])
    assert payload["text"] == "草案 v1", "复活的 pending 应是补充前的 v1"

    # 再次 commit（模拟下一次拟诏）不得产出含被撤回 v2 文本的 draft
    db.commit_pending_actions(state, kind_filter="directive")
    drafts = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=? AND status='draft'",
        (state.turn,)).fetchall()
    texts = [str(r["text"]) for r in drafts]
    assert all("v2" not in t for t in texts), (
        f"再次拟诏不得含被撤回的 v2 文本，但得到 {texts}"
    )


# ── 陈旧诏书不得颁发（P1：生成稿与 draft 状态不同步）─────────────────────────

def _decree_session(db, state, content):
    """轻量 GameSession（__new__ 跳过重型 init）供拟诏/颁诏流程用。"""
    from ming_sim.session import GameSession
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = None
    sess.agno_db = None
    sess.last_decree = ""
    sess.last_report = ""
    sess.deaths_this_turn = []
    sess.debuts_this_turn = []
    return sess


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_stale_decree_not_issued_when_new_draft_created_after_generation(game, monkeypatch):
    """P1-1：拟诏（write_decree 产生稿）后，玩家又新建一条对话式草案（新 draft）。
    resolve_turn 时，陈旧的 last_decree 仅覆盖旧 draft——必须强制重生成、纳入新 draft，
    不许把新 draft 标记为已颁却不进诏书正文。

    断言：颁诏用的 decree 文本必须由新 draft 集重新生成（含新草案），而非沿用旧稿。"""
    import ming_sim.session as session_mod

    db, state, content = game
    name = _active_minister_name(db, content)
    sess = _decree_session(db, state, content)
    from ming_sim.models import TurnPhase
    state.turn_phase = TurnPhase.SUMMONING.value

    # 草案 A：先 stage + write_decree（生成稿只覆盖 A）
    db.upsert_pending_directive(state.turn, name, payload={
        "text": "草案A：清查粮饷", "actor": name,
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "grain-audit",
    })

    gen_calls = []

    def fake_write(llm_config, agno_db, st, directives, db=None):
        ids = sorted(int(d["id"]) for d in directives)
        gen_calls.append(ids)
        texts = "；".join(str(d["text"]) for d in directives)
        return f"诏书[{texts}]"

    monkeypatch.setattr(session_mod, "write_decree_with_agno", fake_write)

    # 草案 A 经应允/默认同意提交为 draft（write_decree 现只 preview、不 default-commit，#498 finding3）
    db.commit_pending_actions(state, kind_filter="directive")
    decree_v1 = sess.write_decree()
    assert "草案A" in decree_v1
    assert "草案B" not in decree_v1  # 此刻还没 B

    # 玩家回到对话，新建草案 B（新 pending directive，未纳入已生成的 decree_v1）
    db.upsert_pending_directive(state.turn, name + "·乙", payload={
        "text": "草案B：调将镇辽", "actor": name,
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "liaodong-defense",
    })

    # 颁诏：必须重生成，纳入 B，不能沿用只含 A 的陈旧稿
    captured = {}

    def fake_resolve(st, gdb, agno, llm, directives, decree_text, **kw):
        captured["decree_text"] = decree_text
        captured["directive_texts"] = [str(d["text"]) for d in directives]
        from ming_sim.session import ResolveResult
        return ResolveResult(awaiting=False, report="ok")

    monkeypatch.setattr(session_mod, "resolve_directives", fake_resolve)

    sess.resolve_turn()

    assert "草案B" in captured["decree_text"], (
        f"颁诏诏书正文必须纳入颁诏前新建的草案B，但得到：{captured['decree_text']!r}"
    )
    assert any("草案B" in t for t in captured["directive_texts"]), "新 draft B 须进 directives"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_supplied_decree_not_used_after_pending_directive_auto_commit(game, monkeypatch):
    """resolve_turn(decree=...) 外部传入旧诏书时，若本次调用先 auto-commit 了口头草案，
    传入文本不包含新 draft；必须重拟/重取当前 draft 集，不能把未入正文的 draft 标 issued。"""
    import ming_sim.session as session_mod

    db, state, content = game
    name = _active_minister_name(db, content)
    sess = _decree_session(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value

    db.upsert_pending_directive(state.turn, name, payload={
        "text": "口头草案：调辽饷三万。", "actor": name,
        "dossier_action_type": "policy",
        "target_kind": "issue", "target_id": "liaodong-pay",
    })

    def fake_write(llm_config, agno_db, st, directives, db=None):
        texts = "；".join(str(d["text"]) for d in directives)
        return f"重拟诏书[{texts}]"

    captured = {}

    def fake_resolve(st, gdb, agno, llm, directives, decree_text, **kw):
        captured["decree_text"] = decree_text
        captured["directive_texts"] = [str(d["text"]) for d in directives]
        from ming_sim.session import ResolveResult
        return ResolveResult(awaiting=False, report="ok")

    monkeypatch.setattr(session_mod, "write_decree_with_agno", fake_write)
    monkeypatch.setattr(session_mod, "resolve_directives", fake_resolve)

    sess.resolve_turn(decree="外部旧诏书：只含旧稿。")

    assert "口头草案" in captured["decree_text"], (
        f"auto-commit 的口头草案必须进入本次诏书正文，但得到：{captured['decree_text']!r}"
    )
    assert any("口头草案" in t for t in captured["directive_texts"])


def test_undo_clears_generated_decree_when_committed_draft_deleted(game, monkeypatch):
    """P1-2：write_decree() commit 了对话草案后撤回该召对（删了 committed draft），
    生成的诏书正文（last_decree）含被撤回的指令——必须随之清空，不能再原样颁出。

    undo_chat_turn 报告删了哪些 committed draft；session 据此让生成稿失效。"""
    import ming_sim.session as session_mod
    from ming_sim.models import TurnPhase

    db, state, content = game
    name = _active_minister_name(db, content)
    sess = _decree_session(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value

    # 一个召对内 stage 对话草案
    ctid = db.create_chat_turn(state, name, "sess-undo-decree", 0)
    before = db.capture_chat_rollback_snapshot()
    db.upsert_pending_directive(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "草案X：将被撤回的指令", "actor": name})
    after = db.capture_chat_rollback_snapshot()
    db.record_chat_turn_rollback_diffs(ctid, before, after)

    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda llm, agno, st, directives, db=None:
            "诏书：" + "；".join(str(d["text"]) for d in directives))

    # 应允/默认同意把召对内暂存提交为 committed draft（write_decree 现只 preview，#498 finding3）；
    # 提交在 rollback diff 记录之后发生，故 undo 仍能循 committed_directive_id 删除该 draft。
    db.commit_pending_actions(state, kind_filter="directive")
    decree = sess.write_decree()
    assert "草案X" in sess.last_decree and "草案X" in decree

    # 撤回该召对：undo_chat_turn 删 committed draft 并报告之；session 失效生成稿。
    undone = db.undo_chat_turn(ctid)
    deleted = undone.get("deleted_committed_draft_ids") or []
    assert deleted, "undo_chat_turn 应报告删除了 committed draft id"
    sess.note_chat_rollback(deleted_committed_draft_ids=deleted)

    assert not (sess.last_decree or "").strip(), (
        f"撤回 committed draft 后生成的诏书正文必须被清空，但仍有：{sess.last_decree!r}"
    )


def test_normal_undo_keeps_valid_decree(read_game, monkeypatch):
    """P1-2 反面：普通撤回（没删 committed draft）不得无谓清空一份有效生成稿。"""
    db, state, content = read_game
    name = _active_minister_name(db, content)
    sess = _decree_session(db, state, content)
    sess.last_decree = "诏书：保留有效稿"

    # 没有 committed draft 被删
    sess.note_chat_rollback(deleted_committed_draft_ids=[])
    assert sess.last_decree == "诏书：保留有效稿", "普通撤回不得清掉有效诏书稿"


def test_extract_draft_intent_no_skips_invalid_action_type(monkeypatch):
    """#654 H：拟旨意图=无 + 非法动作类型 → 空稿不抛。"""
    import ming_sim.cli_backend as cb

    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: ('{"拟旨意图":"无","动作类型":"not_a_real_action"}', None),
    )
    result = cb.extract_draft_intent("今日只是问策。", "臣以为当暂缓。")
    assert result == {"draft_action": "无", "draft_text": "", "target_candidate": ""}


def test_extract_draft_intent_yes_still_validates_action_type(monkeypatch):
    """#654 H：拟旨意图=拟旨 + 非法类型仍 ValueError。"""
    import ming_sim.cli_backend as cb

    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda *a, **k: ('{"拟旨意图":"拟旨","动作类型":"not_a_real_action","目标类型":"policy","目标ID":"x"}', None),
    )
    with pytest.raises(ValueError, match="动作类型"):
        cb.extract_draft_intent("拟旨吧", "臣遵旨草诏。")


def test_multi_draft_prompt_separates_military_order_and_entries(monkeypatch):
    """#654/#653：多旨示例 military_order 不焊 entries；entries 仅 pay_order 说明保留。"""
    import ming_sim.cli_backend as cb

    captured = []

    def _capture(prompt, *a, **k):
        captured.append(prompt)
        return ('{"成品旨稿":[]}', None)

    monkeypatch.setattr(cb, "_run_backend_for_config", _capture)
    cb.extract_draft_intent("拟两道", "臣拟。", draft_count=2)
    assert len(captured) == 1
    prompt = captured[0]
    assert "military_order" in prompt
    assert '"目标类型":"army"' in prompt
    assert "施行范围" in prompt
    assert "entries 仅 pay_order_override" in prompt
    assert "due_priority_军饷@shaanxi" in prompt
    # 示例 JSON（entries 说明行之前）不得出现 entries 键；军令与偿还序分列
    before_guide = prompt.split("entries 仅 pay_order_override", 1)[0]
    assert "military_order" in before_guide
    assert "entries" not in before_guide
