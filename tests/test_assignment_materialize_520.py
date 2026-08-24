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


def _ctx(db, character, candidates, turn, *, message, reply, recent_context=""):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message=message,
        reply=reply,
        message_text=message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
        recent_context=recent_context,
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
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )


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
    """#520 r4：recent_context 空时案卷正文须同时保留皇帝任务描述与大臣领命回话。

    真实物化接缝：run_materialize_pipeline → pending payload text。
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
    body = str(pending.get("text") or "")
    assert player in body, f"须保留皇帝本轮原话，got={body!r}"
    assert reply in body, f"须保留大臣领命回话，got={body!r}"


def test_assignment_title_and_body_keep_current_turn_anchor(game):
    """缺 title 不得吃前轮 body 头；当轮短句不得被前文子串吞掉。"""
    db, state, content = game
    actor = _active_ming(db, content)
    # 前轮长文含当轮短句子串「三事」
    recent = (
        "皇帝：核钱粮、整宗藩、护内帑，卿有何策？\n"
        "大臣：臣请分三事：一核钱粮，二整宗藩，三护内帑。"
    )
    player = "三事"  # 短句，是前文「分三事」的子串
    reply = "臣遵旨分办。请陛下定夺准驳。"
    payload = {
        "kind": "assignment",
        "title": "",  # 分类器未给 title
        "target_id": "",
        "commitment_kind": "无",
    }
    candidates = candidates_from_classifier_payload(payload, soft=False)
    ctx = _ctx(
        db, actor.name, candidates, state.turn,
        message=player, reply=reply, recent_context=recent,
    )
    run_materialize_pipeline(ctx)
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    title = str(pending.get("title") or "")
    body = str(pending.get("text") or "")
    # 标题来源=当轮，不得取前轮「核钱粮、整宗藩…」头 40
    assert not title.startswith("皇帝：核钱粮")
    assert "核钱粮、整宗藩" not in title
    assert player in title or title == player
    # 正文须显式含当轮短句，不得因 substring 被吞
    assert f"皇帝：{player}" in body or body.strip().endswith(player)
    assert "核钱粮" in body  # 上下文链仍在


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


def test_ordinary_assignment_without_commitment_lands(game):
    """无验收承诺的普通交办可落；stop_condition 空、无 until_stop marker。"""
    db, state, content = game
    actor = _active_ming(db, content)
    before = len(_active_initiatives(db))
    ctx = _stage_assignment(
        db, state.turn, title="核钱粮", target_id="he-qianliang",
        assignee=actor.name, commitment_kind="无",
        message="这核钱粮的事你办。",
    )
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?",
        (ctx.out["pending_action_id"],),
    ).fetchone()["payload_json"])
    assert pending.get("commitment_kind") in (None, "", "无")
    assert not pending.get("stop_condition")

    dossier = _close_night_dossier(db, state, content, ctx.out["pending_action_id"])
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    issues = _active_initiatives(db)
    assert len(issues) == before + 1
    row = next(r for r in issues if "核钱粮" in str(r["title"]))
    assert row["commitment_kind"] in ("", None)
    assert not str(row["stop_condition"] or "").strip()
    assert row["origin_ref"] == f"dossier:{dossier['id']}"


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
    """beat 6：前轮三事经真实分类入口 → 逐事扇出三独立交办候选；案卷 text 取上下文链。"""
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
    titles = {p.get("title") or p.get("target_id") for _, p in staged}
    assert {"核钱粮", "整宗藩", "护内帑"} <= titles or {
        "he-qianliang", "zheng-zongfan", "hu-neitang",
    } <= {p.get("target_id") for _, p in staged}
    assert len({pid for pid, _ in staged}) == 3
    # 案卷 text 须含最近相关上下文，不得仅本轮一句
    for _, payload in staged:
        body = str(payload.get("text") or "")
        assert "核钱粮" in body
        assert recent.splitlines()[0] in body or "核钱粮、整宗藩、护内帑" in body


def test_beat8_reinforce_updates_existing_and_adds_fourth(game, monkeypatch):
    """beat 8：真实分类入口重申三事更新既有 + 追加欠饷=第4候选，不重复建。"""
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
    assert "加紧" in str(staged[first_ids[0]].get("title") or staged[first_ids[0]].get("text") or "")
    fourth = [pid for pid in staged if pid not in first_ids]
    assert len(fourth) == 1
    assert staged[fourth[0]].get("target_id") == "jiubian-arrears"
    # 强化后正文仍走最近相关上下文链
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
    for _, payload in staged:
        assert "核钱粮" in str(payload.get("text") or "")

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
    wg._spawn_extraction_trail = lambda *a, **k: None
    wg._trail_mindreading_after_reply = lambda *a, **k: None
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
