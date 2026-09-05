"""#520 交办·责成：军令状→候选→收夜案卷→0055 判后 initiative。

Seams:
- ACTION_CLUSTERS assignment 行 + materialize_fn
- run_materialize_pipeline / apply_cli_conversation_actions
- commit_pending_actions（收夜落案卷，不成 initiative）
- apply_dossier_verdicts（0055 顺颁才落 initiative）
- 既有 initiative 校验/cap、ADR 0038 撤回前像
"""

from __future__ import annotations

import json
import threading
import types
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
import ming_sim.cli_backend as cb
import ming_sim.session as session_mod
from ming_sim.action_clusters import (
    ACTION_CLUSTERS,
    candidates_from_classifier_payload,
    cluster_by_kind,
)
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from ming_sim.decree import reload_state_from_db
from ming_sim.session import GameSession
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict
from web_app import WebGame


def _ctx(db, character, candidates, turn, *, message, reply, recent_context="", chat_turn_id=0):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
        recent_context=recent_context,
        chat_turn_id=int(chat_turn_id or 0),
    )


def _seed_prior_three_matters(db, minister_name, turn):
    """前轮对话埋三事，供 ADR 0028 最近相关上下文取链。"""
    db.append_chat_message(
        minister_name, turn, "user",
        "核钱粮、整宗藩、护内帑，卿有何策？",
    )
    db.append_chat_message(
        minister_name, turn, "minister",
        "臣请分三事：一核钱粮，二整宗藩，三护内帑。",
    )


def _classify_assignment_via_real_entry(
    monkeypatch, *,
    message,
    recent_context="",
    pending_summaries=None,
    scripted_payload,
):
    """走真实 classify_cli_action_intent 入口；仅 mock LLM backend，禁预造 payload 旁路。"""

    def _scripted(prompt, llm_config=None, tag=""):
        assert tag == "action_intent"
        assert message in prompt
        assert "【最近相关召对】" in prompt
        if (recent_context or "").strip():
            # 跨轮指代须能看见前轮事项正文
            assert "核钱粮" in prompt and "整宗藩" in prompt and "护内帑" in prompt
        return (json.dumps(scripted_payload, ensure_ascii=False), 0)

    monkeypatch.setattr(cb, "_run_backend_for_config", _scripted)
    return cb.classify_cli_action_intent(
        message,
        pending_summaries=pending_summaries or [],
        recent_context=recent_context,
    )


def _active_ming(db, content, *, exclude=""):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
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
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial classifier")))


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    return s


def _stage_assignment(
    db, turn, *, title, target_id=None, assignee=None,
    commitment_kind="无", stop_condition="", end_turn=0,
    ongoing_effects="", message=None, reply=None, target_candidate="",
    actor=None,
):
    actor = actor or db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = {
        "kind": "assignment",
        "title": title,
        "target_id": target_id or title,
        "assignee": assignee or actor,
        "commitment_kind": commitment_kind,
    }
    if stop_condition:
        payload["stop_condition"] = stop_condition
    if end_turn:
        payload["end_turn"] = end_turn
    if ongoing_effects:
        payload["ongoing_effects"] = ongoing_effects
    if target_candidate:
        payload["target_candidate"] = target_candidate
    candidate = candidates_from_classifier_payload(payload, soft=False)
    spoken = message or f"着{payload['assignee']}办{title}。"
    ctx = _ctx(
        db, actor, candidate, turn,
        message=spoken,
        reply=reply or f"臣请奉行：{title}。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    return ctx


def _close_night_dossier(db, state, content, pending_id):
    """单元接缝：单条 pending → 案卷（commit_pending_actions）。

    #1565 验收1/2 不得以此 helper 冒充召对收夜全链；验收测走 open_night/
    mark_pending_night_approved/close_night 与 list_active_issues。
    """
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


class _EmptyEndorsementAgent:
    """收夜 endorsement 批空结果（本片不测背书，禁活 LLM；同 strategy_selection_568）。"""

    def run(self, _materials):
        return json.dumps({"endorsements": []}, ensure_ascii=False)


class _CannedStoryExtractor:
    """#501 叙事抽取离线边界：空 facts，经生产 trail 标 extract done（同 web_audience_night_498）。"""

    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


def _close_night_approved_directives(db, state, content, night_id, pending_ids):
    """收夜真源：应允白名单 → audience_night.close_night。

    extract 清待补由 WebGame.chat 生产 trail（canned extractor）完成，本 helper 不 SQL 改 extract_status。
    """
    import ming_sim.audience_night as an
    ids = [int(p) for p in pending_ids]
    n = db.mark_pending_night_approved(ids, night_id=int(night_id))
    assert n == len(ids), f"应允未全中 night={night_id} ids={ids} marked={n}"
    result = an.close_night(
        db, state, night_id=int(night_id), content=content,
        endorsement_extractor_agent=_EmptyEndorsementAgent(),
    )
    assert result.get("closed") is True or result.get("already") is True
    return result


def _assignment_pendings(db, turn, *, minister_name=None):
    rows = []
    for row in db.list_pending_actions(int(turn), minister_name=minister_name):
        if row.get("kind") != "directive" or row.get("status") != "pending":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "assignment":
            continue
        rows.append((int(row["id"]), payload))
    return rows


def _active_initiatives(db):
    return list(db.conn.execute(
        "SELECT * FROM issues WHERE kind='initiative' AND status='active' ORDER BY id"
    ).fetchall())


# ── catalog 挂点 ──────────────────────────────────────────────────────


def test_assignment_cluster_registered_with_materialize_fn():
    cluster = cluster_by_kind("assignment")
    assert cluster is not None
    assert cluster.label_zh == "交办·责成"
    assert cluster.materialize_fn is not None
    names = {f.name for f in cluster.fields}
    assert "commitment_kind" in names
    assert "stop_condition" in names
    assert "target_candidate" in names
    # #520 r2：owner=当前召对大臣；assignee 分类字段无改派用途，已删
    assert "assignee" not in names


# ── #520 r2：owner 单一来源 / 无民心夹带 / 相对期限 / 当轮锚 ──────────


def test_assignment_owner_is_audience_minister_not_classifier_assignee(game):
    """软分类器 assignee/name 不得覆盖 owner；owner=当前召对大臣。"""
    db, state, content = game
    actor = _active_ming(db, content)
    other = _active_ming(db, content, exclude=actor.name)
    assert other.name != actor.name

    payload = {
        "kind": "assignment",
        "title": "核钱粮",
        "target_id": "he-qianliang",
        "assignee": other.name,  # 分类器误填他人
        "name": other.name,
        "commitment_kind": "无",
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message=f"这核钱粮的事你办。",
        reply="臣请奉行。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    owner = pending.get("assignee_id") or pending.get("assignee")
    assert owner == actor.name
    assert owner != other.name

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["executor_id"] == actor.name


def test_assignment_verdict_does_not_inject_public_support_plus_one(game):
    """#520 只授权捕获落库；判后不得夹带统一民心+1（兑现归 #476）。"""
    db, state, content = game
    actor = _active_ming(db, content)
    ctx = _stage_assignment(
        db, state.turn, title="核钱粮", target_id="he-qianliang",
        assignee=actor.name,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    row = next(
        r for r in _active_initiatives(db)
        if r["origin_ref"] == f"dossier:{dossier['id']}"
    )
    effect = json.loads(row["effect_on_resolve"] or "{}") if row["effect_on_resolve"] else {}
    metrics = effect.get("metrics") or {}
    assert metrics.get("民心") in (None, 0), f"不得夹带民心默认：{effect!r}"


def test_relative_deadline_months_becomes_absolute_end_turn(game):
    """交办接缝：相对期限月数 → 绝对 end_turn=turn+N；stop_condition 可校验 dict 原样落。"""
    db, state, content = game
    actor = _active_ming(db, content)
    stop = {"army.guanning.arrears": "<=0"}
    ongoing = {
        "economy": [{
            "account": "国库", "delta": -10, "category": "补饷",
            "reason": "每月补边饷", "purpose": "补饷",
        }],
    }
    # 分类器给相对月数（或把 end_turn 填成相对 N）；接缝换算绝对回合
    payload = {
        "kind": "assignment",
        "title": "解决九边欠饷",
        "target_id": "jiubian-arrears",
        "commitment_kind": "until_stop",
        "deadline_months": 3,
        "end_turn": 3,  # 相对三月；不得被当成绝对第 3 回合
        "stop_condition": json.dumps(stop, ensure_ascii=False),
        "ongoing_effects": json.dumps(ongoing, ensure_ascii=False),
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message="连续三个月补齐边饷，并保证不会再欠。",
        reply="臣请立军令状。请陛下定夺准驳。",
    )
    run_materialize_pipeline(ctx)
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    assert pending["end_turn"] == state.turn + 3
    assert pending["end_turn"] > state.turn
    assert pending["stop_condition"] == stop

    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    row = next(
        r for r in _active_initiatives(db)
        if r["origin_ref"] == f"dossier:{dossier['id']}"
    )
    assert int(row["end_turn"]) == state.turn + 3
    assert json.loads(row["stop_condition"]) == stop


def test_classify_prompt_carries_turn_and_stop_condition_contract(monkeypatch, game):
    """分类入口须获当前 turn 与 GATE_TABLES 可寻址契约，使承诺能落到合法 shape。"""
    db, state, content = game
    captured = {}

    def _scripted(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        assert tag == "action_intent"
        return (json.dumps({"kind": "none"}, ensure_ascii=False), 0)

    monkeypatch.setattr(cb, "_run_backend_for_config", _scripted)
    cb.classify_cli_action_intent(
        "连续三个月补齐边饷。",
        recent_context="",
        current_turn=int(state.turn),
    )
    prompt = captured["prompt"]
    assert f"当前回合={int(state.turn)}" in prompt or f"当前回合：{int(state.turn)}" in prompt
    assert "region" in prompt and "army" in prompt and "character" in prompt
    assert "stop_condition" in prompt or "停止条件" in prompt


def test_classify_prompt_stop_condition_example_is_single_layer_json(monkeypatch, game):
    """#520 r4：停止条件示例须为单层合法 JSON；核验最终 prompt 字节，禁双花括号。"""
    db, state, content = game
    captured = {}

    def _scripted(prompt, llm_config=None, tag=""):
        captured["prompt"] = prompt
        assert tag == "action_intent"
        return (json.dumps({"kind": "none"}, ensure_ascii=False), 0)

    monkeypatch.setattr(cb, "_run_backend_for_config", _scripted)
    cb.classify_cli_action_intent(
        "连续三个月补齐边饷，并保证不会再欠。",
        recent_context="",
        current_turn=int(state.turn),
    )
    prompt = captured["prompt"]
    # 最终 prompt 字节：示例为单层 dict JSON，不得残留 {{ / }}
    assert '{{"army.guanning.arrears":"<=0"}}' not in prompt
    assert '{"army.guanning.arrears":"<=0"}' in prompt
    # 示例片段本身须是可解析的单层 dict JSON
    marker = '{"army.guanning.arrears":"<=0"}'
    assert json.loads(marker) == {"army.guanning.arrears": "<=0"}
    assert marker in prompt


def test_assignment_empty_recent_context_keeps_emperor_and_minister_in_body(game):
    """#520 r4 / #1565：recent_context 空时案卷正文须同时保留皇帝任务描述与大臣领命回话。

    题名=分类 title；正文唯一真源=payload.text（上下文链），不写平行 body。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    player = "朕要你解决九边欠饷，并保证——不会再欠。"
    reply = "臣请立军令状：边饷按月补齐，直至关宁无欠。请陛下定夺准驳。"
    payload = {
        "kind": "assignment",
        "title": "解决九边欠饷",
        "target_id": "jiubian-arrears",
        "commitment_kind": "until_stop",
        "stop_condition": json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False),
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message=player, reply=reply, recent_context="",  # 首轮无历史
    )
    run_materialize_pipeline(ctx)
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending.get("title") == "解决九边欠饷"
    body = str(pending.get("text") or "")
    assert player in body, f"须保留皇帝本轮原话，got={body!r}"
    assert reply in body, f"须保留大臣领命回话，got={body!r}"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_assignment_title_structured_anchor_not_emperor_prose(game, monkeypatch):
    """#1565 B：缺锚恢复全链 typed 证据（WebGame.chat 真实入口，不旁路 materialize）。

    chat 缺锚 → validation 失败零 pending → 同会话补正 target_id 重拟 →
    close_night 成案 → 盖玺 initiative。正文不锁散文。
    """
    import ming_sim.audience_night as an

    db, state, content = game
    actor = _active_ming(db, content)
    player = (
        "户部亏空日甚，太仓入不敷出。卿可据实奏对，并拟一道旨："
        "清核太仓出纳、暂缓非急工役、优发边饷要紧处，限半月回报。"
    )
    reply = "臣遵旨分办。请陛下定夺准驳。"
    before_initiatives = len(_active_initiatives(db))
    phase = {"n": 0}

    def fake_classify(*_a, **_k):
        phase["n"] += 1
        if phase["n"] == 1:
            return candidates_from_classifier_payload({
                "kind": "assignment", "title": "", "target_id": "",
                "commitment_kind": "无",
            }, soft=False)
        return candidates_from_classifier_payload({
            "kind": "assignment", "title": "", "target_id": "清核太仓",
            "commitment_kind": "无",
        }, soft=False)

    # validation recovery 报告走 compose；禁活 backend
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda _p, _c=None, *, tag="": ("臣请陛下明示交办题名后重拟。", 1),
    )
    _silence_serial(monkeypatch)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    wg = _wire_web_game(db, state, content, _SyncAgent(reply), monkeypatch)

    # ① 缺锚：WebGame.chat → 零 pending，validation 留因
    out1 = wg.chat(actor.name, player)
    assert not out1.get("pending_action_id")
    failure = out1.get("decree_validation_failure") or {}
    assert "title" in set(failure.get("failed_fields") or [])
    assert failure.get("report")
    assert not _assignment_pendings(db, state.turn, minister_name=actor.name)

    # ② 补正/重拟：同会话再 chat，结构化 target_id 锚 → 合法 pending
    out2 = wg.chat(actor.name, player)
    pending_id = int(out2.get("pending_action_id") or 0)
    assert pending_id > 0
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (pending_id,),
    ).fetchone()["payload_json"])
    assert pending.get("title") == "清核太仓"
    assert str(pending.get("text") or "").strip()
    chat_turn_id = int(pending.get("source_chat_turn_id") or 0)
    assert chat_turn_id > 0

    # ③ 收夜成案 → 盖玺 → initiative
    night = an.get_open_night(db)
    assert night is not None
    _close_night_approved_directives(db, state, content, int(night["id"]), [pending_id])
    dossier = next(
        d for d in db.list_decree_dossiers()
        if int(d["pending_action_id"] or 0) == pending_id
    )
    assert int(dossier.get("source_chat_turn_id") or 0) == chat_turn_id
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert len(_active_initiatives(db)) == before_initiatives + 1
    issue = next(
        r for r in _active_initiatives(db)
        if r["origin_ref"] == f"dossier:{dossier['id']}"
    )
    assert issue["origin_kind"] == "decree"
    assert issue["title"] == "清核太仓"
    assert str(issue["stage_text"] or "").strip()


# ── AC：军令状 → 案卷 → 判后 initiative ──────────────────────────────


def test_military_order_assignment_lands_initiative_only_after_verdict(game):
    """军令状：暂存→收夜案卷（无 initiative）→顺颁后 initiative(owner+stop_condition)。"""
    db, state, content = game
    actor = _active_ming(db, content)
    stop = json.dumps({"army.guanning.arrears": "<=0"}, ensure_ascii=False)
    ongoing = json.dumps(
        {"economy": [{
            "account": "国库", "delta": -10, "category": "补饷",
            "reason": "每月补边饷", "purpose": "补饷",
        }]},
        ensure_ascii=False,
    )

    before = len(_active_initiatives(db))
    ctx = _stage_assignment(
        db, state.turn,
        title="解决九边欠饷",
        target_id="jiubian-arrears",
        assignee=actor.name,
        commitment_kind="until_stop",
        stop_condition=stop,
        ongoing_effects=ongoing,
        message="朕要你解决九边欠饷，并保证——不会再欠。",
        reply="臣请立军令状：边饷按月补齐，直至关宁无欠。请陛下定夺准驳。",
    )
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["dossier_action_type"] == "assignment"
    assert pending["commitment_kind"] == "until_stop"
    assert pending.get("assignee_id") == actor.name or pending.get("assignee") == actor.name
    assert len(_active_initiatives(db)) == before, "物化前不得创建 initiative"

    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "assignment"
    assert dossier["status"] == "proposed"
    assert dossier["executor_id"] == actor.name
    assert len(_active_initiatives(db)) == before, "收夜只落案卷，initiative 按 0055 下沉"

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    issues = _active_initiatives(db)
    assert len(issues) == before + 1
    row = next(r for r in issues if "欠饷" in str(r["title"]))
    assert row["kind"] == "initiative"
    assert row["commitment_kind"] == "until_stop"
    assert row["origin_ref"] == f"dossier:{dossier['id']}"
    assert json.loads(row["stop_condition"]) == {"army.guanning.arrears": "<=0"}
    participants = json.loads(row["participants"])
    assert actor.name in participants
    roster = json.loads(row["participant_roster"])
    assert any(
        p.get("character_id") == actor.name and p.get("tier") == "主办"
        for p in roster
    )
    assert db.get_decree_dossier(dossier["id"])["status"] == "executing"


def test_assignment_rejected_verdict_creates_no_initiative(game):
    """打回：案卷在、initiative 零落。"""
    db, state, content = game
    actor = _active_ming(db, content)
    before = len(_active_initiatives(db))
    ctx = _stage_assignment(
        db, state.turn, title="清丈田亩", target_id="qingzhang",
        assignee=actor.name,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(state, [_rejected_verdict(dossier["id"])], content=content)
    assert len(_active_initiatives(db)) == before


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_ordinary_assignment_without_commitment_lands(game, monkeypatch):
    """无验收承诺的普通交办可落；stop_condition 空、无 until_stop marker。

    #1565 验收2：WebGame.chat 真实召对持久完成 → 应允收夜 close_night → 盖玺
    → issue_payloads（/api/game/state 同源）读回；typed 回指
    source_chat_turn_id / pending_id / directive_id / dossier_id / origin。
    分类 stub 只证明下游传递，不证明真实 LLM 题名/正文语义。
    """
    import ming_sim.audience_night as an

    db, state, content = game
    actor = _active_ming(db, content)
    message = "这核钱粮的事你办。"
    reply = "臣请奉行：核钱粮。请陛下定夺准驳。"
    before_issue_ids = {int(r["id"]) for r in db.list_active_issues()}
    before_initiatives = len(_active_initiatives(db))

    def fake_classify(*_a, **_k):
        return candidates_from_classifier_payload({
            "kind": "assignment",
            "title": "核钱粮",
            "target_id": "he-qianliang",
            "assignee": actor.name,
            "commitment_kind": "无",
        }, soft=False)

    # 串行抽取静默后覆盖 classify（_silence_serial 会把 classify 设成断言抛错）
    _silence_serial(monkeypatch)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    wg = _wire_web_game(db, state, content, _SyncAgent(reply), monkeypatch)

    # 真实 WebGame.chat 召对持久完成（产 chat_turn / pending，非手造 SQL）
    payload = wg.chat(actor.name, message)
    pending_id = int(payload.get("pending_action_id") or 0)
    assert pending_id > 0
    pending_row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()
    pending = json.loads(pending_row["payload_json"])
    assert pending.get("title") == "核钱粮"
    assert str(pending.get("text") or "").strip()
    chat_turn_id = int(pending.get("source_chat_turn_id") or 0)
    assert chat_turn_id > 0
    assert pending.get("commitment_kind") in (None, "", "无")
    assert not pending.get("stop_condition")
    # chat_turn 由生产 chat 路径写入
    ct = db.conn.execute(
        "SELECT id, status FROM chat_turns WHERE id=?", (chat_turn_id,),
    ).fetchone()
    assert ct is not None

    night = an.get_open_night(db)
    assert night is not None
    nid = int(night["id"])
    _close_night_approved_directives(db, state, content, nid, [pending_id])
    pending_after = db.conn.execute(
        "SELECT status, committed_directive_id FROM pending_actions WHERE id=?",
        (pending_id,),
    ).fetchone()
    assert pending_after["status"] == "committed"
    directive_id = int(pending_after["committed_directive_id"] or 0)
    assert directive_id > 0
    dossier = next(
        d for d in db.list_decree_dossiers()
        if int(d["pending_action_id"] or 0) == pending_id
    )
    assert int(dossier.get("directive_id") or 0) == directive_id
    assert int(dossier.get("source_chat_turn_id") or 0) == chat_turn_id
    d_payload = json.loads(dossier["payload_json"] or "{}")
    assert d_payload.get("title") == "核钱粮"

    # 盖玺（0055 顺颁 seam；完整 settle LLM 不在本测）
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    issues = _active_initiatives(db)
    assert len(issues) == before_initiatives + 1
    row = next(r for r in issues if r["origin_ref"] == f"dossier:{dossier['id']}")
    assert row["origin_kind"] == "decree"
    assert row["title"] == "核钱粮"
    assert row["stage_text"] == d_payload.get("text")
    assert row["commitment_kind"] in ("", None)

    # GET issues 同源：WebGame.issue_payloads（/api/game/state 的 issues 槽）
    api_issues = wg.issue_payloads()
    api_ids = {int(i["id"]) for i in api_issues}
    assert int(row["id"]) in api_ids
    assert before_issue_ids <= api_ids

    # 恢复读回
    reload_state_from_db(db, state, content=content)
    restored = db.get_decree_dossier(dossier["id"])
    assert int(restored.get("source_chat_turn_id") or 0) == chat_turn_id
    assert int(restored.get("pending_action_id") or 0) == pending_id
    assert int(restored.get("directive_id") or 0) == directive_id
    restored_issue = db.find_active_issue_by_origin("decree", f"dossier:{dossier['id']}")
    assert restored_issue is not None
    assert restored_issue["title"] == "核钱粮"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_pure_inquiry_stages_zero_mechanical_matters(game, monkeypatch):
    """#1565 验收1：基线 → WebGame.chat 纯问事持久完成 → 收夜退出 → issue_payloads 零新增
    + 同链离殿交办正对照。

    分类经 classify_cli_action_intent 挂点（stub kind=none）；stub 不证明真实 LLM 语义。
    """
    import ming_sim.audience_night as an

    db, state, content = game
    actor = _active_ming(db, content)
    before_issue_ids = {int(r["id"]) for r in db.list_active_issues()}
    before_pending = len(db.list_pending_actions(state.turn))
    before_dossiers = len(db.list_decree_dossiers())
    before_initiatives = len(_active_initiatives(db))

    phase = {"n": 0}

    def fake_classify(*_a, **_k):
        phase["n"] += 1
        if phase["n"] == 1:
            return []  # kind=none → 空候选
        return candidates_from_classifier_payload({
            "kind": "assignment",
            "title": "核钱粮",
            "target_id": "he-qianliang",
            "assignee": actor.name,
            "commitment_kind": "无",
        }, soft=False)

    _silence_serial(monkeypatch)
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    q_reply = "臣以为当先清核太仓出纳，再议缓急。"
    a_reply = "臣请奉行：核钱粮。请陛下定夺准驳。"
    agent_phase = {"n": 0}

    class _PhaseAgent:
        def run(self, *_a, **_k):
            agent_phase["n"] += 1
            text = q_reply if agent_phase["n"] == 1 else a_reply
            return SimpleNamespace(content=text, tools=[])

    wg = _wire_web_game(db, state, content, _PhaseAgent(), monkeypatch)

    # 纯问事：WebGame.chat 真实入口
    out = wg.chat(actor.name, "户部亏空日甚，卿以为如何？")
    assert not out.get("pending_action_id")
    assert len(db.list_pending_actions(state.turn)) == before_pending

    night = an.get_open_night(db)
    assert night is not None
    nid = int(night["id"])
    closed = an.close_night(
        db, state, night_id=nid, content=content,
        endorsement_extractor_agent=_EmptyEndorsementAgent(),
    )
    assert closed.get("closed") is True or closed.get("already") is True
    # GET issues 同源读面零新增
    api_ids = {int(i["id"]) for i in wg.issue_payloads()}
    assert api_ids == before_issue_ids
    assert len(db.list_decree_dossiers()) == before_dossiers
    assert len(_active_initiatives(db)) == before_initiatives

    # 正对照：同链离殿交办 → 应允收夜 → 盖玺 → issues 新增
    assign_out = wg.chat(actor.name, "这核钱粮的事你办。")
    pid = int(assign_out.get("pending_action_id") or 0)
    assert pid > 0
    night2 = an.get_open_night(db)
    assert night2 is not None
    _close_night_approved_directives(db, state, content, int(night2["id"]), [pid])
    dossier = next(
        d for d in db.list_decree_dossiers()
        if int(d["pending_action_id"] or 0) == pid
    )
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    after_ids = {int(i["id"]) for i in wg.issue_payloads()}
    assert len(after_ids - before_issue_ids) >= 1
    assert any(
        r["origin_ref"] == f"dossier:{dossier['id']}"
        for r in _active_initiatives(db)
    )


def test_old_assignment_dossier_decree_text_carries_to_stage_text_not_title(game):
    """#1565：旧/公开成案只有 decree_text 时正文承接到 stage_text；不得回填为题名。"""
    db, state, content = game
    actor = _active_ming(db, content)
    before = len(_active_initiatives(db))
    decree_body = "属地差务@shaanxi：清核仓廪、整饬驿递。"
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text=decree_body,
        target_kind="issue",
        target_id="errand-shaanxi",
        executor_kind="character",
        executor_id=actor.name,
        payload={
            "dossier_action_type": "assignment",
            "target_kind": "issue",
            "target_id": "errand-shaanxi",
            "assignee_id": actor.name,
            # 无 title / text：模拟旧入口
        },
        status="proposed",
    )
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier_id, "decision": "promulgated"}],
        content=content,
    )
    issues = _active_initiatives(db)
    assert len(issues) == before + 1
    row = next(r for r in issues if r["origin_ref"] == f"dossier:{dossier_id}")
    # 题名=结构化 target_id；正文=decree_text 承接（不回填题名）
    assert row["title"] == "errand-shaanxi"
    assert row["stage_text"] == decree_body


def test_old_assignment_missing_title_and_target_keeps_dossier_fails_execution(game):
    """#1565 B：真缺锚旧案——保留案卷与正文，execution failed+closed，零 initiative。

    closed 无出边：同案卷不可 reopen。恢复入口=新拟 assignment（见
    test_assignment_title_structured_anchor_not_emperor_prose 全链），不在此冒充可恢复。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    before = len(_active_initiatives(db))
    before_ids = {int(r["id"]) for r in _active_initiatives(db)}
    decree_body = "清核太仓出纳、暂缓非急工役。"
    # 行级 target_id 仅满足建档 schema；payload 故意无 title/target_id（真缺锚）。
    dossier_id = db.create_decree_dossier(
        state,
        action_type="assignment",
        decree_text=decree_body,
        target_kind="issue",
        target_id="schema-row-only",
        executor_kind="character",
        executor_id=actor.name,
        payload={
            "dossier_action_type": "assignment",
            "target_kind": "issue",
            "target_id": "",
            "text": decree_body,
            "assignee_id": actor.name,
            # 无 title：真缺结构化锚
        },
        status="proposed",
    )
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier_id, "decision": "promulgated"}],
        content=content,
    )
    assert len(_active_initiatives(db)) == before
    assert not any(
        r["origin_ref"] == f"dossier:{dossier_id}" for r in _active_initiatives(db)
    )
    row = db.conn.execute(
        "SELECT execution_outcome, status, decree_text, payload_json "
        "FROM decree_dossiers WHERE id=?",
        (dossier_id,),
    ).fetchone()
    assert row["execution_outcome"] == "failed"
    assert row["status"] == "closed"  # 既裁生命周期：failed+close，无出边
    # 案卷与正文保留；零新增 initiative（typed 身份，不锁生成题名措辞）
    assert row["decree_text"] == decree_body
    payload = json.loads(row["payload_json"] or "{}")
    assert payload.get("text") == decree_body
    after_ids = {int(r["id"]) for r in _active_initiatives(db)}
    assert after_ids == before_ids


def test_stop_condition_only_without_marker_still_rejected(game):
    """防回归毒样本：stop_condition-only 缺 marker 经真实 assignment 全管线被拒。

    不得在 stage 丢掉毒字段后当普通交办落地；既有 initiative 校验负责拒收。
    禁止以直接调用 apply_score_extraction 代替本管线验收。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    before = len(_active_initiatives(db))
    stop = {"army.guanning.arrears": "<=0"}
    ctx = _stage_assignment(
        db, state.turn,
        title="缺 marker 毒样本",
        target_id="poison-stop-only",
        assignee=actor.name,
        commitment_kind="无",  # 缺 until_stop marker
        stop_condition=json.dumps(stop, ensure_ascii=False),
        message="边饷不得再欠，卿去办。",
        reply="臣遵旨。请陛下定夺准驳。",
    )
    pending_id = ctx.out["pending_action_id"]
    assert pending_id, "毒样本须能进入交办暂存，不得在入口被平行校验挡掉"
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    # 形状保留：毒字段不得在 stage 被洗掉
    assert pending.get("stop_condition") == stop
    assert pending.get("commitment_kind") not in ("until_stop",)

    dossier = _close_night_dossier(db, state, content, pending_id)
    d_payload = json.loads(str(dossier.get("payload_json") or "{}"))
    assert d_payload.get("stop_condition") == stop

    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    # 不得当普通交办落地 initiative
    assert len(_active_initiatives(db)) == before
    assert not any(
        r["origin_ref"] == f"dossier:{dossier['id']}"
        for r in _active_initiatives(db)
    )
    row = db.conn.execute(
        "SELECT execution_outcome, execution_note, status FROM decree_dossiers WHERE id=?",
        (dossier["id"],),
    ).fetchone()
    blob = " ".join(str(row[k] or "") for k in row.keys())
    assert row["execution_outcome"] == "failed"
    assert "commitment_kind" in blob


# ── 附录 A beat 6/8/10（真实分类/上下文入口，禁预造 payload 旁路）──


def test_beat6_three_matters_fan_out_three_independent_candidates(game, monkeypatch):
    """beat 6：前轮三事经真实分类入口 → 逐事扇出三独立交办候选。

    #1565：题名=分类 title；正文=_assignment_dossier_text 上下文链（recent+皇帝/大臣句）。
    #1744 权威多独立交办行为证明（原 515 two_independent_assignments chat 平行样板已并入本测）。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    _seed_prior_three_matters(db, actor.name, state.turn)

    message = "三件事都说得好。朕欲让你负责这三件事。"
    reply = "臣请分办核钱粮、整宗藩、护内帑三事，请陛下定夺准驳。"
    recent = session_mod._recent_audience_context_for_secret_order(
        db, actor.name, state.turn, message,
    )
    assert "核钱粮" in recent and "整宗藩" in recent and "护内帑" in recent

    matters = [
        ("核钱粮", "he-qianliang"),
        ("整宗藩", "zheng-zongfan"),
        ("护内帑", "hu-neitang"),
    ]
    candidates = _classify_assignment_via_real_entry(
        monkeypatch,
        message=message,
        recent_context=recent,
        scripted_payload=[
            {
                "kind": "assignment",
                "title": title,
                "target_id": tid,
                "assignee": actor.name,
                "commitment_kind": "无",
            }
            for title, tid in matters
        ],
    )
    assert len(candidates) == 3
    assert {c.get("kind") for c in candidates} == {"assignment"}

    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message=message, reply=reply, recent_context=recent,
    )
    run_materialize_pipeline(ctx)

    staged = _assignment_pendings(db, state.turn, minister_name=actor.name)
    assert len(staged) == 3
    titles = {p.get("title") for _, p in staged}
    assert titles == {"核钱粮", "整宗藩", "护内帑"}
    assert len({pid for pid, _ in staged}) == 3
    # 案卷 text 须含最近相关上下文，不得仅本轮一句
    for _, payload in staged:
        body = str(payload.get("text") or "")
        assert "核钱粮" in body
        assert recent.splitlines()[0] in body or "核钱粮、整宗藩、护内帑" in body


def test_beat8_reinforce_updates_existing_and_adds_fourth(game, monkeypatch):
    """beat 8：真实分类入口重申三事更新既有 + 追加欠饷=第4候选，不重复建。

    无 draft 的跨轮续办权威证明；draft 共存/顺序边界见 515 draft_plus_digit_target_candidate。
    """
    db, state, content = game
    actor = _active_ming(db, content)
    _seed_prior_three_matters(db, actor.name, state.turn)

    # 先经真实分类入口落三独立候选
    first_message = "三件事都说得好。朕欲让你负责这三件事。"
    first_recent = session_mod._recent_audience_context_for_secret_order(
        db, actor.name, state.turn, first_message,
    )
    first_candidates = _classify_assignment_via_real_entry(
        monkeypatch,
        message=first_message,
        recent_context=first_recent,
        scripted_payload=[
            {
                "kind": "assignment",
                "title": title,
                "target_id": tid,
                "assignee": actor.name,
                "commitment_kind": "无",
            }
            for title, tid in (
                ("核钱粮", "he-qianliang"),
                ("整宗藩", "zheng-zongfan"),
                ("护内帑", "hu-neitang"),
            )
        ],
    )
    run_materialize_pipeline(_ctx(
        db, actor.name, first_candidates, state.turn,
        message=first_message,
        reply="臣请分办三事，请陛下定夺准驳。",
        recent_context=first_recent,
    ))
    first_rows = _assignment_pendings(db, state.turn, minister_name=actor.name)
    assert len(first_rows) == 3
    first_ids = [pid for pid, _ in first_rows]
    # 记入对话，供下一轮最近相关上下文
    db.append_chat_message(actor.name, state.turn, "user", first_message)
    db.append_chat_message(
        actor.name, state.turn, "minister", "臣请分办三事，请陛下定夺准驳。",
    )

    reinforce_message = "徐徐图之……这三件事你都办。另加一件欠饷。"
    reinforce_reply = "臣遵旨：三事加紧，并补九边欠饷。"
    recent = session_mod._recent_audience_context_for_secret_order(
        db, actor.name, state.turn, reinforce_message,
    )
    pending_summaries = [
        f"#{pid} 交办「{(p.get('title') or p.get('target_id') or '')}」"
        for pid, p in first_rows
    ]
    reinforced = _classify_assignment_via_real_entry(
        monkeypatch,
        message=reinforce_message,
        recent_context=recent,
        pending_summaries=pending_summaries,
        scripted_payload=[
            {
                "kind": "assignment",
                "title": "核钱粮（加紧）",
                "target_id": "he-qianliang",
                "assignee": actor.name,
                "target_candidate": str(first_ids[0]),
                "commitment_kind": "无",
            },
            {
                "kind": "assignment",
                "title": "整宗藩（加紧）",
                "target_id": "zheng-zongfan",
                "assignee": actor.name,
                "target_candidate": str(first_ids[1]),
                "commitment_kind": "无",
            },
            {
                "kind": "assignment",
                "title": "护内帑（加紧）",
                "target_id": "hu-neitang",
                "assignee": actor.name,
                "target_candidate": str(first_ids[2]),
                "commitment_kind": "无",
            },
            {
                "kind": "assignment",
                "title": "补九边欠饷",
                "target_id": "jiubian-arrears",
                "assignee": actor.name,
                "commitment_kind": "无",
            },
        ],
    )
    assert len(reinforced) == 4
    run_materialize_pipeline(_ctx(
        db, actor.name, reinforced, state.turn,
        message=reinforce_message, reply=reinforce_reply, recent_context=recent,
    ))

    staged = dict(_assignment_pendings(db, state.turn, minister_name=actor.name))
    assert set(first_ids).issubset(set(staged))
    assert len(staged) == 4
    assert staged[first_ids[0]].get("title") == "核钱粮（加紧）"
    fourth = [pid for pid in staged if pid not in first_ids]
    assert len(fourth) == 1
    assert staged[fourth[0]].get("target_id") == "jiubian-arrears"
    assert staged[fourth[0]].get("title") == "补九边欠饷"
    # 强化后正文仍走最近相关上下文链（含前轮事项）
    assert "核钱粮" in str(staged[first_ids[0]].get("text") or "")

    dossiers = [
        _close_night_dossier(db, state, content, pid) for pid in staged
    ]
    db.apply_dossier_verdicts(state, [
        {"dossier_id": d["id"], "decision": "promulgated"} for d in dossiers
    ], content=content)
    batch_origins = {f"dossier:{d['id']}" for d in dossiers}
    landed = [r for r in _active_initiatives(db) if r["origin_ref"] in batch_origins]
    assert len(landed) == 4


def test_beat10_accept_three_lands_three_independent_initiatives(game, monkeypatch):
    """beat 10：真实分类入口「三事全允」→ 扇 3 独立 initiative，owner/origin_ref 落全。"""
    db, state, content = game
    actor = _active_ming(db, content)
    sess = _bind_apply(db, state, content)
    _seed_prior_three_matters(db, actor.name, state.turn)

    message = "三事全允。"
    reply = "臣请分办三事，请陛下定夺准驳。"
    recent = session_mod._recent_audience_context_for_secret_order(
        db, actor.name, state.turn, message,
    )
    # 先走真实分类入口，再 silence 串行抽取（apply 只消费已分类候选）
    scripted = _classify_assignment_via_real_entry(
        monkeypatch,
        message=message,
        recent_context=recent,
        scripted_payload=[
            {
                "kind": "assignment",
                "title": title,
                "target_id": tid,
                "assignee": actor.name,
                "commitment_kind": "无",
            }
            for title, tid in (
                ("核钱粮", "he-qianliang"),
                ("整宗藩", "zheng-zongfan"),
                ("护内帑", "hu-neitang"),
            )
        ],
    )
    _silence_serial(monkeypatch)
    # apply 入口消费真实分类结果；materialize 仍取同一 recent_context 链
    monkeypatch.setattr(
        session_mod, "_recent_audience_context_for_secret_order",
        lambda *a, **k: recent,
    )
    out = sess.apply_cli_conversation_actions(
        actor, message, reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent=scripted,
    )
    staged = _assignment_pendings(db, state.turn, minister_name=actor.name)
    assert len(staged) == 3
    ids = [pid for pid, _ in staged]
    titles = {str(payload.get("title") or "") for _, payload in staged}
    assert titles == {"核钱粮", "整宗藩", "护内帑"}
    for _, payload in staged:
        body = str(payload.get("text") or "")
        assert "核钱粮" in body

    # 应允三道
    sess.apply_cli_conversation_actions(
        actor, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids=set(ids),
    )

    dossiers = []
    for pid in ids:
        dossiers.append(_close_night_dossier(db, state, content, pid))
    db.apply_dossier_verdicts(state, [
        {"dossier_id": d["id"], "decision": "promulgated"} for d in dossiers
    ], content=content)

    batch_origins = {f"dossier:{d['id']}" for d in dossiers}
    landed = [r for r in _active_initiatives(db) if r["origin_ref"] in batch_origins]
    assert len(landed) == 3
    for row in landed:
        assert row["origin_ref"].startswith("dossier:")
        roster = json.loads(row["participant_roster"] or "[]")
        assert any(
            p.get("character_id") == actor.name and p.get("tier") == "主办"
            for p in roster
        )


# ── cap 逐项 ──────────────────────────────────────────────────────────


def test_cap15_per_item_reject_overflow_lands_rest(game):
    """撞 cap=15：超出项拒+戏内回禀朝廷分身乏术，可落项照落。"""
    db, state, content = game
    actor = _active_ming(db, content)
    for idx in range(14):
        db.insert_issue(
            state, kind="initiative", title=f"既有国策{idx}",
            origin_kind="decree",
            effect_on_resolve={"metrics": {"民心": 1}},
        )
    assert db.count_active_initiatives() == 14

    d_ids = []
    for title, tid in (("可落交办", "can-land"), ("超出交办", "overflow")):
        ctx = _stage_assignment(
            db, state.turn, title=title, target_id=tid, assignee=actor.name,
        )
        d_ids.append(_close_night_dossier(db, state, content, ctx.out["pending_action_id"])["id"])

    db.apply_dossier_verdicts(state, [
        {"dossier_id": d_ids[0], "decision": "promulgated"},
        {"dossier_id": d_ids[1], "decision": "promulgated"},
    ], content=content)

    assert db.count_active_initiatives() == 15
    landed = [
        r for r in _active_initiatives(db)
        if r["origin_ref"] == f"dossier:{d_ids[0]}"
    ]
    assert len(landed) == 1
    overflow = db.get_decree_dossier(d_ids[1])
    # 超出项不得创建 initiative；执行失败留痕含戏内回禀
    assert not any(r["origin_ref"] == f"dossier:{d_ids[1]}" for r in _active_initiatives(db))
    exec_note = str(overflow.get("execution_note") or overflow.get("status") or "")
    # 失败关闭或 note 含分身乏术
    row = db.conn.execute(
        "SELECT execution_outcome, execution_note, status FROM decree_dossiers WHERE id=?",
        (d_ids[1],),
    ).fetchone()
    blob = " ".join(str(row[k] or "") for k in row.keys())
    assert "分身乏术" in blob or "朝廷分身乏术" in blob


# ── 0038 跨轮强化撤回前像 ────────────────────────────────────────────


def _wire_web_game(db, state, content, agent, monkeypatch) -> WebGame:
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
    wg._spawn_pending_write_thread = lambda *a, **k: None
    wg._trail_mindreading_after_reply = lambda *a, **k: None

    # 生产 trail 同步跑：canned 空 facts → extract_status=done（禁 SQL 旁路清待补）
    from ming_sim.audience_extraction import trail_extraction_after_reply

    def _spawn_extraction_trail(minister_name, answer_text, chat_turn_id):
        if not chat_turn_id:
            return None
        trail_extraction_after_reply(
            db=db,
            minister_name=minister_name,
            minister_reply=str(answer_text or ""),
            chat_turn_id=int(chat_turn_id),
            llm_config=sess.llm_config,
            write_gate=wg._write_gate,
            extractor_agent=_CannedStoryExtractor(),
        )
        return None

    wg._spawn_extraction_trail = _spawn_extraction_trail
    return wg


class _SyncAgent:
    def __init__(self, content: str):
        self.content = content
        self.tools = []

    def run(self, *_a, **_k):
        return SimpleNamespace(content=self.content, tools=self.tools)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_cross_round_assignment_update_undo_restores_before_image(game, monkeypatch):
    """跨轮强化更新既有候选后，撤回本轮恢复前像（ADR 0038）。"""
    db, state, content = game
    minister = _active_ming(db, content)
    _silence_serial(monkeypatch)

    original_title = "核钱粮"
    updated_title = "核钱粮（加紧催办）"
    phase = {"n": 0}
    staged_id = {"id": 0}

    def fake_classify(*_a, **_k):
        phase["n"] += 1
        if phase["n"] == 1:
            return candidates_from_classifier_payload({
                "kind": "assignment",
                "title": original_title,
                "target_id": "he-qianliang",
                "assignee": minister.name,
                "commitment_kind": "无",
            }, soft=False)
        return candidates_from_classifier_payload({
            "kind": "assignment",
            "title": updated_title,
            "target_id": "he-qianliang",
            "assignee": minister.name,
            "commitment_kind": "无",
            "target_candidate": str(staged_id["id"]),
        }, soft=False)

    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)
    wg = _wire_web_game(
        db, state, content, _SyncAgent("臣请办核钱粮。"), monkeypatch,
    )

    wg.chat(minister.name, "核钱粮的事你办。")
    rows = _assignment_pendings(db, state.turn, minister_name=minister.name)
    assert len(rows) == 1
    staged_id["id"] = rows[0][0]
    original_payload = dict(rows[0][1])

    wg.chat(minister.name, "这核钱粮你加紧办。")
    mid = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (staged_id["id"],),
    ).fetchone()["payload_json"])
    assert "加紧" in str(mid.get("title") or mid.get("text") or "")

    assert wg.can_undo_last_chat(minister.name)
    wg.undo_last_chat(minister.name)
    restored = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (staged_id["id"],),
    ).fetchone()["payload_json"])
    assert restored.get("title") == original_payload.get("title")
    assert "加紧" not in str(restored.get("title") or "")


def test_assignment_restore_from_db_only_is_lossless(game):
    """P1：restore 只读 DB 能接续 initiative 与案卷。"""
    db, state, content = game
    actor = _active_ming(db, content)
    ctx = _stage_assignment(
        db, state.turn, title="修历", target_id="xiu-li", assignee=actor.name,
    )
    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    issue = next(
        r for r in _active_initiatives(db)
        if r["origin_ref"] == f"dossier:{dossier['id']}"
    )
    reload_state_from_db(db, state, content=content)
    restored_issue = db.conn.execute(
        "SELECT * FROM issues WHERE id=?", (issue["id"],),
    ).fetchone()
    assert restored_issue is not None
    assert restored_issue["status"] == "active"
    assert db.get_decree_dossier(dossier["id"])["action_type"] == "assignment"
