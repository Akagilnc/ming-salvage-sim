"""#568 点策捕获＋指代物化（ADR 0059）。

Seams:
- apply_cli_conversation_actions（preclassified draft + 脚本化 extract_draft_intent）
- draft/directive 成案路消费 dossier_action_type=strategy_selection（零新增 ACTION_CLUSTERS kind）
- 案卷 source_chat_turn_id 绑大臣陈策轮（复用既有填值路径）
- night close → decree_dossiers
- confirmation / EFFECT_ANSWER_EXISTING 既有准驳豁免不回归

不测活 LLM；不建 chips/方案列表表/平行溯源。
"""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 — install catalog
import ming_sim.audience_night as an
import ming_sim.cli_backend as cb
from ming_sim.session import GameSession


# ── archive/越次召对-杨嗣昌.md 相关轮次（脚本化注入）────────────────


# 杨陈盐课/清丈先后（大臣陈策）
_YANG_PRESENT_SALT_SURVEY = (
    "回皇爷。这两刀，盐课易动、清丈难啃，须分先后。"
    "盐课——病在两淮。清丈——不如先择一省试点——畿辅天子脚下好弹压，"
    "或江南隐田最多——以考成法督责地方官。"
)

# 帝先提两线
_EMPEROR_TWO_LINES = "让倪元璐、黄道周两人，分别督办两件事。你觉得何如？"

# 杨陈：两线并进风险 + 分派建议（陈策，含倪黄）
_YANG_PRESENT_DUAL_RISK = (
    "皇爷这一手……大胆。两人分督，火力是足了。只是臣方才说「分先后」，正为这个——"
    "两线齐发，就是同时开罪盐商勋贵与天下士绅。"
    "若论分派：盐课盘账繁细，倪公心思缜密，或更相宜；清丈要硬压士绅，黄公骨鲠震慑，或更压得住。"
    "若皇爷执意并举，臣愿在户部替二公接应钱粮。"
)

# 帝改口点策（北极星 beat5）
_EMPEROR_PICK = "那就让两人先试点清丈，畿辅天子脚下好弹压，后面找机会再两路并进。"

_YANG_ACK = (
    "皇爷圣明，这才是老成走法。两公合力、先试畿辅，火力拧成一股；"
    "天子脚下，士绅再横也得掂量。盐课缓图，待清丈见效再回头动两淮。"
)


def _bind_apply(db, state, content=None):
    s = SimpleNamespace(
        db=db, state=state, registry=None, content=content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    s.apply_cli_conversation_actions = types.MethodType(
        GameSession.apply_cli_conversation_actions, s)
    return s


def _minister(db, content, name="杨嗣昌"):
    ch = content.characters.get(name)
    if ch is not None and db.get_character_status(name)[0] == "active":
        return ch
    return next(
        c for c in content.characters.values()
        if getattr(c, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(c) == "ming"
        and db.get_character_status(c.name)[0] == "active"
        and str(getattr(c, "office", "") or "").strip()
    )


def _silence_serial(monkeypatch):
    monkeypatch.setattr(cb, "extract_minister_actions", lambda *a, **k: {
        "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
        "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
    })
    monkeypatch.setattr(cb, "extract_appointment_action", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial appointment extractor")))
    monkeypatch.setattr(cb, "extract_confirmation_intent", lambda *a, **k: "无")
    monkeypatch.setattr(cb, "classify_cli_action_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call serial classifier")))


def _chat_turn(db, state, night_id, minister_name, user_text, answer, seq):
    uid = db.append_chat_message(minister_name, state.turn, "user", user_text)
    mid = db.append_chat_message(minister_name, state.turn, "minister", answer)
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name,turn,year,period,user_message_id,minister_message_id,"
        "night_id,night_seq,status,extract_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            minister_name, state.turn, state.year, state.period,
            uid, mid, night_id, seq, "active", "done",
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def _inject_yang_strategy_turns(db, state, night_id, minister_name):
    """注入 archive 相关轮次；返回大臣陈策轮 id（两人分督陈策，非帝点策轮）。"""
    _chat_turn(
        db, state, night_id, minister_name,
        "盐课、清丈，怎么动？", _YANG_PRESENT_SALT_SURVEY, 10,
    )
    present_id = _chat_turn(
        db, state, night_id, minister_name,
        _EMPEROR_TWO_LINES, _YANG_PRESENT_DUAL_RISK, 20,
    )
    return present_id


def _script_strategy_extract(monkeypatch, *, draft_text=""):
    """脚本化判词：dossier_action_type=strategy_selection；正文可由物化从上下文展开。"""
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: {
        "draft_action": "拟旨",
        "draft_text": draft_text,
        "dossier_action_type": "strategy_selection",
        "target_kind": "policy",
        "target_id": "land-survey-pilot-jifu",
        "target_candidate": "",
    })


def _payload(row):
    try:
        return json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}


class _EmptyEndorsementAgent:
    """收夜 endorsement-only 批脚本化空结果（本片不测背书，禁活 LLM）。"""

    def run(self, materials):
        return json.dumps({"endorsements": []}, ensure_ascii=False)


def _close_night(db, state, night_id, content):
    return an.close_night(
        db, state, night_id=int(night_id), content=content,
        endorsement_extractor_agent=_EmptyEndorsementAgent(),
    )


# ── 正例 tracer ─────────────────────────────────────────────────────


def test_north_star_beat5_strategy_selection_lands_one_dossier(game, monkeypatch):
    """正例：点策收夜恰 1 案卷；decree_text 含试点清丈/倪黄合力/畿辅；origin=陈策轮。"""
    db, state, content = game
    minister = _minister(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    present_turn_id = _inject_yang_strategy_turns(db, state, nid, minister.name)

    _silence_serial(monkeypatch)
    # 正文留空：逼物化走 ADR 0028 上下文展开，不得只落皇帝原句
    _script_strategy_extract(monkeypatch, draft_text="")

    before_pending = {
        int(r["id"]) for r in db.list_pending_actions(int(state.turn))
    }
    out = sess.apply_cli_conversation_actions(
        minister, _EMPEROR_PICK, _YANG_ACK,
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "draft"}],
    )
    staged_id = int(out.get("pending_action_id") or 0)
    assert staged_id > 0, "点策须 stage 一条 directive 候选"
    assert staged_id not in before_pending

    staged = next(
        r for r in db.list_pending_actions(int(state.turn))
        if int(r["id"]) == staged_id
    )
    sp = _payload(staged)
    assert sp.get("dossier_action_type") == "strategy_selection"
    body = str(sp.get("text") or "")
    assert "试点" in body and "清丈" in body, f"须含试点清丈，实际={body!r}"
    assert "畿辅" in body, f"须含畿辅，实际={body!r}"
    assert ("倪" in body and "黄" in body) or "两公" in body or "合力" in body, (
        f"须从陈策上下文展开倪黄/合力，实际={body!r}"
    )
    assert body.strip() != _EMPEROR_PICK.strip(), "不得仅存皇帝原句无上下文展开"
    # 未选「两线并进」不得另起候选
    new_pending = [
        r for r in db.list_pending_actions(int(state.turn))
        if int(r["id"]) not in before_pending
    ]
    assert len(new_pending) == 1, f"未选路径零额外 pending，实际={len(new_pending)}"

    # 应允 → 收夜成案
    _silence_serial(monkeypatch)
    sess.apply_cli_conversation_actions(
        minister, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={staged_id},
    )
    assert staged_id in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="directive")
    }

    _close_night(db, state, nid, content)
    dossiers = list(db.list_decree_dossiers())
    assert len(dossiers) == 1, f"收夜后恰 1 条案卷，实际={len(dossiers)}"
    d = dossiers[0]
    assert d["action_type"] == "strategy_selection"
    dt = str(d["decree_text"] or "")
    assert "试点" in dt and "清丈" in dt
    assert "畿辅" in dt
    assert ("倪" in dt and "黄" in dt) or "两公" in dt or "合力" in dt
    assert dt.strip() != _EMPEROR_PICK.strip()
    assert int(d["source_chat_turn_id"] or 0) == present_turn_id, (
        f"origin 须绑大臣陈策轮 {present_turn_id}，实际={d['source_chat_turn_id']}"
    )
    # 未选零痕：无第二案卷、无方案列表字段/额外 pending
    assert not db.list_pending_actions(int(state.turn), status="pending")
    assert "strategy_options" not in (d.get("payload") or {})
    assert "unselected" not in json.dumps(d.get("payload") or {}, ensure_ascii=False)


def test_strategy_selection_origin_not_emperor_pick_turn(game, monkeypatch):
    """origin 单向新指旧：source_chat_turn_id 非皇帝点策轮。"""
    db, state, content = game
    minister = _minister(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    present_turn_id = _inject_yang_strategy_turns(db, state, nid, minister.name)
    # 点策轮亦入库（模拟当轮已落 messages），origin 仍须指陈策轮
    pick_turn_id = _chat_turn(
        db, state, nid, minister.name, _EMPEROR_PICK, _YANG_ACK, 30,
    )

    _silence_serial(monkeypatch)
    _script_strategy_extract(monkeypatch, draft_text="")
    out = sess.apply_cli_conversation_actions(
        minister, _EMPEROR_PICK, _YANG_ACK,
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "draft"}],
    )
    staged_id = int(out["pending_action_id"])
    sp = _payload(next(
        r for r in db.list_pending_actions(int(state.turn)) if int(r["id"]) == staged_id
    ))
    origin = int(sp.get("source_chat_turn_id") or 0)
    assert origin == present_turn_id
    assert origin != pick_turn_id


# ── 负向 ────────────────────────────────────────────────────────────


def test_minister_advice_emperor_comment_only_no_dossier(game, monkeypatch):
    """0042 US19：大臣献策＋皇帝仅评论/追问未拍板 → 零案卷、零 pending。"""
    db, state, content = game
    minister = _minister(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _inject_yang_strategy_turns(db, state, nid, minister.name)

    _silence_serial(monkeypatch)
    # 结构化判词落「无」——不跑 draft extract 升格
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("comment-only must not call draft extract")))

    before = list(db.list_pending_actions(int(state.turn)))
    sess.apply_cli_conversation_actions(
        minister,
        "说得有理，容朕再想想。盐课那边阻力究竟有多大？",
        "臣不敢催促，愿备档候旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "none"}],
    )
    after = list(db.list_pending_actions(int(state.turn)))
    assert len(after) == len(before)
    _close_night(db, state, nid, content)
    assert db.list_decree_dossiers() == []


def test_confirmation_answer_existing_not_swallowed_by_strategy_path(game, monkeypatch):
    """裁决类豁免不回归：既有 pending 应允仍走 EFFECT_ANSWER_EXISTING，不误 stage 点策。"""
    db, state, content = game
    minister = _minister(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])

    pid = db.stage_pending_action(
        state.turn, kind="office", action="任命",
        minister_name=minister.name, target_id=None,
        payload={"name": "洪承畴", "office": "陕西巡抚", "appointer": minister.name},
    )
    _silence_serial(monkeypatch)
    monkeypatch.setattr(
        cb, "extract_confirmation_intent",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("must not call serial confirmation extractor")),
    )
    monkeypatch.setattr(cb, "extract_draft_intent", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("confirmation must not fall into draft/strategy extract")))

    before_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))}
    out = sess.apply_cli_conversation_actions(
        minister, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[
            {"kind": "draft"},
            {"kind": "confirmation", "confirmation": "应允"},
        ],
        confirm_target_ids={int(pid)},
    )
    new_ids = {int(r["id"]) for r in db.list_pending_actions(int(state.turn))} - before_ids
    assert not new_ids, "应允不得另 stage 点策/拟旨"
    assert int(pid) in {
        int(r["id"]) for r in db.list_night_approved_pending(nid, kind="office")
    }
    assert out.get("pending_action_id") in (None, 0, "")


def test_unselected_dual_track_leaves_no_structured_residue(game, monkeypatch):
    """未选「盐课与清丈两线并进」：零额外 dossier/pending/方案列表字段。"""
    db, state, content = game
    minister = _minister(db, content)
    sess = _bind_apply(db, state, content)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    _inject_yang_strategy_turns(db, state, nid, minister.name)

    _silence_serial(monkeypatch)
    _script_strategy_extract(monkeypatch, draft_text="")
    out = sess.apply_cli_conversation_actions(
        minister, _EMPEROR_PICK, _YANG_ACK,
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "draft"}],
    )
    staged_id = int(out["pending_action_id"])
    _silence_serial(monkeypatch)
    sess.apply_cli_conversation_actions(
        minister, "准。", "臣遵旨。",
        has_directive=False, secret_order_id=None,
        preclassified_intent=[{"kind": "confirmation", "confirmation": "应允"}],
        confirm_target_ids={staged_id},
    )
    _close_night(db, state, nid, content)

    dossiers = db.list_decree_dossiers()
    assert len(dossiers) == 1
    # 未选路径：无「两线并进」独立案卷；正文可提及缓图盐课，但不得另有 salt+survey 并行案
    dual = [
        d for d in dossiers
        if d["action_type"] != "strategy_selection"
    ]
    assert dual == []
    pending_left = [
        r for r in db.list_pending_actions(int(state.turn))
        if r.get("status") == "pending"
    ]
    assert pending_left == []
    # 无方案列表专用字段
    blob = json.dumps(dossiers[0].get("payload") or {}, ensure_ascii=False)
    for banned in ("strategy_options", "unselected_strategies", "plot_options", "备选方案"):
        assert banned not in blob
