"""对话式拟旨意图抽取 + pending 暂存 + last-write-wins（issue #137，ADR 0006）。

行为契约：
- 玩家口头「拟旨吧 / 你拟一道旨」（无显式前缀）→ LLM 判出拟旨意图 → 进 pending_actions
  (kind=directive) 暂存；turn_directives 此刻不动。
- 同一回合同一大臣再次触发拟旨意图（补充/改草） → 同一条 pending 行原地更新（last-write-wins），
  不新增行；确认流仍 3 态（应允/拒绝/不回）。
- 对话应允 / 颁诏时「不回=默认同意」→ commit → turn_directives 建档 status=draft
  （直接进颁诏候选池，无需再经 web UI 准驳；pending 态保留给显式前缀大臣拟旨用）；
  commit_pending_actions 幂等，两路最终落同一状态。
- 显式前缀「拟旨如下：」仍走旧路（add_directive 直接建档 status=pending），不触发此自然语言闸门。
"""

from __future__ import annotations

import json
import types
from unittest.mock import patch

import pytest

import ming_sim.cli_backend as cb
from ming_sim.models import FRONT_HALF_DONE_PHASES, TurnPhase
from ming_sim.session import GameSession


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
        canned={"拟旨意图": "拟旨"},
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


def test_no_draft_pending_when_no_intent(game, monkeypatch):
    """LLM 判出「无」拟旨意图 → 不 stage；闲谈不应触发草案。"""
    db, state, content = game
    _run_conversational_draft(
        db, state, content, monkeypatch,
        player_message="今日天气如何",
        minister_reply="回陛下，今日晴和，宜出行。",
        canned={"拟旨意图": "无"},
    )
    assert db.list_pending_actions(state.turn) == []


def test_explicit_prefix_does_not_trigger_draft_intent(game, monkeypatch):
    """显式「拟旨如下：」走旧路（add_directive 直接建档），不入 pending_actions 自然语言闸门。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    # canned 带拟旨意图，但显式前缀应跳过自然语言检测
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"拟旨意图": "拟旨"}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="拟旨如下：着户部速查三边粮饷",
        answer="奉天承运皇帝诏曰，着户部速查三边粮饷。",
        has_directive=False, secret_order_id=None,
    )
    # 显式路：turn_directives 有 pending 草案，pending_actions 无
    pending_pa = [p for p in db.list_pending_actions(state.turn) if p["kind"] == "directive"]
    assert pending_pa == []


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
                            {"拟旨意图": "拟旨"}, ensure_ascii=False), 1))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="拟旨吧", answer=first_reply,
        has_directive=False, secret_order_id=None)

    pend_after_first = db.list_pending_actions(state.turn)
    assert len(pend_after_first) == 1
    first_id = pend_after_first[0]["id"]
    assert first_reply in json.loads(pend_after_first[0]["payload_json"])["text"]

    # 第二次：皇帝「补充一下」→ 同意图，新草稿
    # 注：LLM 判确认（extraction_confirmation_intent）先被调，返回「无」，然后才进草案检测
    # 两次调用都 canned 成 {"拟旨意图": "拟旨"}（确认判断时会调但结果被丢弃）
    def canned_second(prompt, llm_config=None, tag=""):
        # 确认意图抽取 → 无（别应允/拒绝，只补充草稿）
        if "应允" in prompt or "拒绝" in prompt or "待皇帝定夺" in prompt:
            return (json.dumps({"确认": "无"}, ensure_ascii=False), 1)
        return (json.dumps({"拟旨意图": "拟旨"}, ensure_ascii=False), 1)

    monkeypatch.setattr(cb, "_run_backend_for_config", canned_second)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="再补一条，加上要监察御史同行", answer=second_reply,
        has_directive=False, secret_order_id=None)

    pend_after_second = db.list_pending_actions(state.turn)
    # 仍只有一条（last-write-wins 原地更新）
    assert len(pend_after_second) == 1
    # 行 id 不变（原地更新同一行）
    assert pend_after_second[0]["id"] == first_id
    # 内容更新为最新草稿
    updated_payload = json.loads(pend_after_second[0]["payload_json"])
    assert second_reply in updated_payload["text"]
    assert first_reply not in updated_payload["text"]


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
        payload={"text": draft_text, "actor": name},
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


def test_dialogue_affirm_commits_pending_directive(game, monkeypatch):
    """皇帝应允 → 当场 commit kind=directive → turn_directives 立即建档；暂存清空。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    draft_text = "奉天承运皇帝诏曰，着兵部整饬三边，钦此。"
    db.upsert_pending_directive(state.turn, name,
                                payload={"text": draft_text, "actor": name})
    assert len(db.list_pending_actions(state.turn)) == 1

    # 皇帝应允
    monkeypatch.setattr(cb, "_run_backend_for_config",
                        lambda prompt, llm_config=None, tag="": (json.dumps(
                            {"确认": "应允"}, ensure_ascii=False), 1))
    sess = _fake_session(db, state)
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准，就这么办",
        answer="臣即遵行，拟旨入档。",
        has_directive=False, secret_order_id=None)

    row = db.conn.execute(
        "SELECT text, status FROM turn_directives WHERE turn=? ORDER BY id DESC",
        (state.turn,)).fetchone()
    assert row is not None
    assert row["text"] == draft_text
    assert row["status"] == "draft"
    assert db.list_pending_actions(state.turn) == []


def test_dialogue_reject_drops_pending_directive(game, monkeypatch):
    """皇帝拒绝 → 暂存 kind=directive 被丢；turn_directives 始终不动。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)

    db.upsert_pending_directive(state.turn, name,
                                payload={"text": "草稿文", "actor": name})
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
        payload={"text": draft_text, "actor": name},
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


# ── ⑥ write_decree() 真实入口覆盖（codex r2 finding [high]）─────────────────

def test_write_decree_commits_pending_directive(game, monkeypatch):
    """web「拟诏」按钮路径覆盖（codex r2 finding [high]）：
    玩家口头「拟旨吧」后不显式应允，直接点「拟诏」按钮触发 write_decree()。
    write_decree() 必须先 commit_pending_actions(kind_filter='directive')，
    再 list_directives(status='draft')——否则 drafts 为空，raise "无草案不能拟诏"。

    此测试直接调 GameSession.write_decree()（而非只调 db.commit_pending_actions），
    覆盖 r1 测试照不到的 web 按钮入口。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    draft_text = "奉天承运皇帝诏曰，着兵部整饬三边军务，期三月内完报，钦此。"
    db.upsert_pending_directive(
        state.turn, name,
        payload={"text": draft_text, "actor": name},
    )

    # write_decree 调用前：turn_directives 为空，pending_actions 有一条
    assert db.list_directives(state, statuses=("draft",)) == []
    assert len(db.list_pending_actions(state.turn)) == 1

    # 构造最小 fake session（委派真实 db/state；_refuse_if_settling 直接实现）
    fake_sess = types.SimpleNamespace(
        db=db,
        state=state,
        content=None,
        registry=None,
        llm_config=types.SimpleNamespace(channel="cli"),
        agno_db=None,
        last_decree="",
    )

    def _refuse_if_settling():
        if state.turn_phase in FRONT_HALF_DONE_PHASES:
            raise ValueError("月末结算进行中（恢复态），请先完成结算再改诏稿。")

    def _pending_count():
        return db.count_pending_directives(state)

    fake_sess._refuse_if_settling = _refuse_if_settling
    fake_sess.pending_count = _pending_count

    canned_decree = "奉天承运皇帝诏曰，着兵部整饬三边军务，期三月内完报，钦此。"
    with patch("ming_sim.session.write_decree_with_agno", return_value=canned_decree):
        result = GameSession.write_decree(fake_sess)

    # write_decree 内 commit_pending_actions 已把暂存升级为 draft
    drafts = db.list_directives(state, statuses=("draft",))
    assert len(drafts) == 1
    assert drafts[0]["text"] == draft_text
    assert drafts[0]["status"] == "draft"

    # pending_actions 已清空（标 committed）
    assert db.list_pending_actions(state.turn) == []

    # 返回值是 decree 文本
    assert result == canned_decree


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
        payload={"text": "草稿", "actor": name},
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
        payload={"text": "草稿", "actor": name},
    )
    db.commit_pending_actions(state, kind_filter="directive")

    directive_pending = [
        a for a in db.list_pending_actions(state.turn)
        if a["kind"] == "directive"
    ]
    assert directive_pending == [], "commit 后 pending_directive_count 应为 0"


def test_pending_directive_count_zero_without_any_draft(game):
    """无对话式草案时 pending_directive_count 为 0，
    state_payload 不误触发「拟诏」按钮。"""
    db, state, content = game
    directive_pending = [
        a for a in db.list_pending_actions(state.turn)
        if a["kind"] == "directive"
    ]
    assert directive_pending == []
