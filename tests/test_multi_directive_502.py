"""多道圣旨独立成条（issue #502，ADR 0006/0038/0049）。

外部行为契约：一夜之内皇帝分别请大臣拟数道**各自独立**的旨，每道旨自成一条
候选（独立 pending_actions(kind=directive) 行、各自正文），不被并进同一条圣旨。
对现有草案的**补充/修改**仍原地更新那一道候选（不冻结在首句、也不新增行）。

真路：走 `apply_cli_conversation_actions`（CLI/web streaming 共用的会话落地真源），
仅 LLM 边界 canned——生产抽取器 prompt 照跑。
"""

from __future__ import annotations

import json
import types

import pytest

import ming_sim.cli_backend as cb
from ming_sim.session import GameSession
import ming_sim.audience_night as an

_POLICY_FIELDS = {
    "dossier_action_type": "policy",
    "target_kind": "issue",
    "target_id": "test-policy",
}


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
        registry=None, content=None,
    )


def _canned_by_tag(mapping):
    """按生产 `tag=` 分派 canned JSON（不盯 prompt 自由文，#502 L9）。缺省 tag 返回 {}。
    mapping: {tag: dict}；未列 tag 回落安全默认（confirmation/draft/appointment/minister→无）。"""
    _defaults = {
        "confirmation": {"确认": "无"},
        "directive_confirmation": {"决定": "无", "目标编号": []},
        "draft_intent": {"拟旨意图": "无"},
        "appointment": {"任免动作": "无"},
        "minister_actions": {"动作类型": "无"},
        "action_intent": {"动作类型": "无"},
    }

    def _run(prompt, llm_config=None, tag=""):
        obj = mapping.get(tag, _defaults.get(tag, {}))
        if tag == "draft_intent" and obj.get("拟旨意图") == "拟旨":
            obj = {
                "动作类型": "policy",
                "目标类型": "issue",
                "目标ID": "test-policy",
                **obj,
            }
        return (json.dumps(obj, ensure_ascii=False), 1)
    return _run


def _canned(draft_result):
    """拟旨草案路由（by tag）：draft_intent→draft_result，其余安全默认。"""
    return _canned_by_tag({"draft_intent": draft_result})


def _draft_turn(sess, ch, monkeypatch, *, player_message, reply, draft_result):
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned(draft_result))
    return GameSession.apply_cli_conversation_actions(
        sess, ch, player_message=player_message, answer=reply,
        has_directive=False, secret_order_id=None,
        preclassified_intent={"kind": "draft"},
    )


def _pending_directives(db, turn):
    return [p for p in db.list_pending_actions(turn) if p["kind"] == "directive"]


def test_mixed_batch_stages_supported_decree_without_capturing_acting_appointment(
    game, monkeypatch,
):
    """同批暂缓的署理项不应连带吞掉已支持的独立旨稿。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    sess = _fake_session(db, state)
    supported_text = "着户部清查三边粮饷，限三月完报。"
    acting_text = "命洪承畴暂署兵部尚书。"
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "draft_intent": {
            "成品旨稿": [
                {
                    "正文": supported_text,
                    "动作类型": "policy",
                    "目标类型": "issue",
                    "目标ID": "three-borders-pay",
                },
                {
                    "正文": acting_text,
                    "动作类型": "acting_appointment",
                    "目标类型": "office",
                    "目标ID": "兵部尚书",
                },
            ],
        },
    }))

    GameSession.apply_cli_conversation_actions(
        sess, ch,
        player_message="分别拟旨清查三边粮饷，并命洪承畴暂署兵部尚书",
        answer="臣已分别拟妥。",
        has_directive=False,
        secret_order_id=None,
        preclassified_intent=[{"kind": "draft"}, {"kind": "draft"}],
    )

    pending = _pending_directives(db, state.turn)
    assert len(pending) == 1
    payload = json.loads(pending[0]["payload_json"])
    assert payload["text"] == supported_text
    assert payload["dossier_action_type"] == "policy"
    assert acting_text not in payload["text"]


def test_two_new_decrees_stage_as_independent_candidates(game, monkeypatch):
    """一夜拟两道各自独立的旨 → 两条独立 pending directive 候选，各自正文；
    不被并进同一条（AC1「不出现全部内容卡进一道圣旨」）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    sess = _fake_session(db, state)

    text_a = "奉天承运皇帝诏曰，着户部清查三边粮饷，限三月完报，钦此。"
    text_b = "奉天承运皇帝诏曰，着兵部核饷九边军械，限两月呈览，钦此。"

    # 第一道：无现存候选 → 新
    _draft_turn(sess, ch, monkeypatch,
                player_message="拟旨吧", reply=text_a,
                draft_result={"拟旨意图": "拟旨"})
    pend = _pending_directives(db, state.turn)
    assert len(pend) == 1

    # 第二道：皇帝另请一道**新**旨 → 抽取器指向「新」→ 独立第二条候选
    _draft_turn(sess, ch, monkeypatch,
                player_message="另拟一道旨，着兵部核饷", reply=text_b,
                draft_result={"拟旨意图": "拟旨", "目标草案": "新", "合并草案": ""})

    pend = _pending_directives(db, state.turn)
    assert len(pend) == 2, f"两道独立新旨应各自成条，实际 {len(pend)} 条"
    ids = {p["id"] for p in pend}
    assert len(ids) == 2
    texts = [json.loads(p["payload_json"])["text"] for p in pend]
    assert any(text_a in t for t in texts)
    assert any(text_b in t for t in texts)
    # 各自独立：无任何一条把两道正文并进去
    assert not any(text_a in t and text_b in t for t in texts), "两道旨被并进了同一条"


def _stage_two_night_candidates(db, state, name):
    """夜内直接暂存两道独立 directive 候选（确定性，不走 LLM），返回 (id_a, id_b)。"""
    id_a = db.stage_directive_candidate(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "着户部清查三边粮饷，限三月完报。", "actor": name})
    id_b = db.stage_directive_candidate(
        state.turn, name, payload={**_POLICY_FIELDS, "text": "着兵部核饷九边军械，限两月呈览。", "actor": name})
    return id_a, id_b


def _approved_directive_ids(db, night_id):
    return {int(r["id"]) for r in db.list_night_approved_pending(int(night_id), kind="directive")}


def test_verbal_approve_targets_one_of_many(game, monkeypatch):
    """同大臣名下多道并存时「准其中一道」只提交那一道（AC4，提案粒度）：
    被点名那道标 night_approved、另一道仍 pending 未提交。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag(
        {"directive_confirmation": {"决定": "应允", "目标编号": [id_a]}}))

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="户部清查那道旨，准了", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

    approved = _approved_directive_ids(db, nid)
    assert approved == {id_a}, f"只应提交被点名的一道，实际 {approved}"
    # 另一道仍在 pending、未被提交
    still_pending = {p["id"] for p in _pending_directives(db, state.turn)}
    assert id_b in still_pending


def test_verbal_reject_targets_one_others_survive(game, monkeypatch):
    """口头拒绝一道后该候选消失、其余照常留存（AC3）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag(
        {"directive_confirmation": {"决定": "拒绝", "目标编号": [id_a]}}))

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="户部那道不必了，作罢", answer="臣领旨。",
        has_directive=False, secret_order_id=None,
    )

    ids = {p["id"] for p in _pending_directives(db, state.turn)}
    assert id_a not in ids, "被拒的那道应消失"
    assert id_b in ids, "未被拒的那道应照常留存"


def test_ambiguous_command_returns_structured_state_no_silent_default(game, monkeypatch):
    """多道并存时含糊口令（「准了」不指明哪道）→ 结构化含糊态（含候选集）、不静默默认提交
    （AC5）：两道都不标 night_approved，返回体带含糊态供大臣追问。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag(
        {"directive_confirmation": {"决定": "含糊", "目标编号": []}}))

    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准了", answer="请陛下明示是哪一道。",
        has_directive=False, secret_order_id=None,
    )

    # 两道都不被提交（不静默当「不回→默认同意」）
    assert _approved_directive_ids(db, nid) == set()
    # 结构化含糊态含候选集，供大臣当场追问
    amb = out.get("directive_confirmation_ambiguous")
    assert amb is not None, "含糊口令应返回结构化含糊态"
    amb_ids = {int(c["id"]) for c in amb["candidates"]}
    assert amb_ids == {id_a, id_b}
    # 两道仍在 pending，一条也没被误建成第三道（L1 free-fall 回归）
    assert len(_pending_directives(db, state.turn)) == 2


def test_multi_confirm_none_result_does_not_stage_third_decree(game, monkeypatch):
    """L1 回归：≥2 道 directive + 纯准驳口令，若 directive_confirmation 返回「无」，
    也按含糊处置（不 free-fall 到拟旨抽取误建第三道）；仍 2 行、带含糊态。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    # directive_confirmation=无（空指向）；draft_intent 故意判「拟旨」——若 free-fall 就会误建第三道。
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "directive_confirmation": {"决定": "无", "目标编号": []},
        "draft_intent": {"拟旨意图": "拟旨", "目标草案": "新", "合并草案": "误建第三道"},
    }))

    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准了", answer="臣遵旨。",
        has_directive=False, secret_order_id=None,
    )

    assert len(_pending_directives(db, state.turn)) == 2, "纯准驳口令不得误建第三道"
    assert out.get("directive_confirmation_ambiguous") is not None
    assert {p["id"] for p in _pending_directives(db, state.turn)} == {id_a, id_b}


def test_named_clarification_clears_flag_frees_sibling_default(game, monkeypatch):
    """L4：含糊后点名准 A → 清全组待澄清标；A 可提交、B 复位普通 pending（默提路径可默认同意）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    night = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid = int(night["id"])
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    # 第一轮：含糊「准了」→ 两道打待澄清标
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag(
        {"directive_confirmation": {"决定": "含糊", "目标编号": []}}))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准了", answer="请陛下明示。",
        has_directive=False, secret_order_id=None)
    assert _flag(db, id_a) and _flag(db, id_b)

    # 第二轮：点名「准户部那道(A)」→ 清 A、B 的标，A night_approved
    # （外层确认门 LLM 判应允；结构化指认落到 A）
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag({
        "confirmation": {"确认": "应允"},
        "directive_confirmation": {"决定": "应允", "目标编号": [id_a]},
    }))
    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="准户部那道", answer="臣遵旨。",
        has_directive=False, secret_order_id=None)

    assert not _flag(db, id_a) and not _flag(db, id_b), "点名指明后全组清标（L4 兑现 docstring）"
    assert _approved_directive_ids(db, nid) == {id_a}
    # B 复位普通 pending：默提路径（action_ids=None）可默认同意（不再被待澄清永久跳过）
    applied = db.commit_pending_actions(state)
    joined = "".join(str(r["text"] or "") for r in db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=?", (state.turn,)).fetchall())
    assert "兵部核饷" in joined, "被解标的兄弟 B 应可默认同意提交"


def _flag(db, cid):
    row = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (int(cid),)).fetchone()
    if row is None:
        return False
    try:
        return bool(json.loads(row["payload_json"] or "{}").get("_needs_clarification"))
    except (ValueError, TypeError):
        return False


def test_night_promulgated_directives_identifiable_by_night_and_range(game):
    """夜内定案（收夜提交）的旨在账上可辨识为已明发（AC6，公开层）：
    按夜取数各夜明发的旨；密令（私密）不入明发清单（负路）。"""
    db, state, content = game
    name = _active_minister_name(db, content)

    # 第一夜：两道拟旨 + 一道密令（私密），全应允，收夜
    n1 = an.open_night(db, state, location="乾清宫", time_of_day="夜")
    nid1 = int(n1["id"])
    d1 = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "着户部清查粮饷。", "actor": name})
    d2 = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "着兵部核饷军械。", "actor": name})
    so = db.stage_pending_action(
        state.turn, kind="secret_order", action="新建", minister_name=name, target_id=None,
        payload={"title": "密查盐引", "content": "着人密查两淮盐引亏空。", "assignee": name,
                 "tags": [], "deadline_months": 3, "excluded_names": [], "excluded_offices": []})
    db.mark_pending_night_approved([d1, d2, so], night_id=nid1)
    an.close_night(db, state, night_id=nid1, content=content)

    promulgated = db.list_night_promulgated_directives(nid1)
    texts = [str(p["text"] or "") for p in promulgated]
    assert any("户部清查" in t for t in texts)
    assert any("兵部核饷" in t for t in texts)
    # 密令私密：不出现在明发清单里
    assert not any("盐引" in t for t in texts), "密令（私密）不应被辨识为明发"
    # 账上（公开层卷轴）有明发标记
    tags = {t for e in an.list_ledger(db, nid1) for t in e.get("tags") or []}
    assert an.TAG_MINGFA in tags

    # 第二夜（推进一回合）：一道旨，收夜。按区间取数能分辨各夜/各回合明发。
    turn1 = state.turn
    state.turn += 1
    n2 = an.open_night(db, state, location="文华殿", time_of_day="日")
    nid2 = int(n2["id"])
    d3 = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "着工部修葺城防。", "actor": name})
    db.mark_pending_night_approved([d3], night_id=nid2)
    an.close_night(db, state, night_id=nid2, content=content)

    assert {str(p["text"] or "") for p in db.list_night_promulgated_directives(nid2)} \
        and any("工部修葺" in str(p["text"] or "") for p in db.list_night_promulgated_directives(nid2))
    # 第一夜的不混进第二夜
    assert not any("户部清查" in str(p["text"] or "") for p in db.list_night_promulgated_directives(nid2))
    # 按区间（回合区间）取数覆盖两回合共三道
    rng = db.list_promulgated_directives(turn_from=turn1, turn_to=state.turn)
    assert len({p["directive_id"] for p in rng}) == 3


def test_needs_clarification_directive_skipped_by_default_commit(game):
    """含糊待澄清候选不被「不回→默认同意」批量提交（AC5：颁诏时不误提交）；
    对照：未标待澄清的那道照常默认提交入 turn_directives。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    db.flag_directive_needs_clarification(id_a)  # A 含糊待澄清；B 未表态

    applied = db.commit_pending_actions(state)  # 默认批量（action_ids=None）

    committed_ids = {int(a.get("pending_action_id") or a.get("id") or 0) for a in applied}
    # A 被跳过、仍 pending；B 默认提交
    pend_ids = {p["id"] for p in _pending_directives(db, state.turn)}
    assert id_a in pend_ids, "待澄清候选不应被默认提交"
    rows = db.conn.execute(
        "SELECT text FROM turn_directives WHERE turn=?", (state.turn,)).fetchall()
    joined = "".join(str(r["text"] or "") for r in rows)
    assert "兵部核饷" in joined, "未标待澄清的那道应照常默认提交"
    assert "户部清查" not in joined, "待澄清那道不应进 turn_directives"


def test_supplement_targets_named_candidate_others_unchanged(game, monkeypatch):
    """L8/AC2 真实入口改草 tracer：两道并存，点名补 A（canned target=id_a 合并正文）→
    仍 2 行、A 更新、B 不变。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    b_text_before = json.loads(_by_pid(db, id_b)["payload_json"])["text"]
    sess = _fake_session(db, state)

    merged_a = "着户部清查三边粮饷，限三月完报，监察御史随行核查。"
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag(
        {"draft_intent": {"拟旨意图": "拟旨", "目标草案": str(id_a), "合并草案": merged_a}}))

    GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="户部那道再加监察御史随行", answer="臣领旨，加上监察御史。",
        has_directive=False, secret_order_id=None,
    )

    pend = _pending_directives(db, state.turn)
    assert len(pend) == 2, "改草不新增行"
    assert json.loads(_by_pid(db, id_a)["payload_json"])["text"] == merged_a, "A 更新为合并正文"
    assert json.loads(_by_pid(db, id_b)["payload_json"])["text"] == b_text_before, "B 不变"


def test_unnamed_revise_multi_does_not_stage_third(game, monkeypatch):
    """L7/AC2：多道并存 + 改/补目标不明（extract 归一为「含糊」）→ 不静默建第三道、出含糊态追问。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    ch = next(c for c in content.characters.values() if getattr(c, "name", None) == name)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    id_a, id_b = _stage_two_night_candidates(db, state, name)
    sess = _fake_session(db, state)

    # 拟旨意图=拟旨，但目标草案不可解析（非「新」、非有效 id）→ 归一「含糊」
    monkeypatch.setattr(cb, "_run_backend_for_config", _canned_by_tag(
        {"draft_intent": {"拟旨意图": "拟旨", "目标草案": "那一道吧", "合并草案": "改点东西"}}))

    out = GameSession.apply_cli_conversation_actions(
        sess, ch, player_message="那道旨改一下", answer="请陛下明示是哪一道。",
        has_directive=False, secret_order_id=None,
    )

    assert len(_pending_directives(db, state.turn)) == 2, "目标不明不得静默新建第三道"
    assert out.get("directive_confirmation_ambiguous") is not None


def test_update_directive_candidate_preserves_underscore_flags(game):
    """L5：原地改草不抹下划线控制键（_needs_clarification）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")
    cid = db.stage_directive_candidate(state.turn, name, payload={**_POLICY_FIELDS, "text": "旧稿", "actor": name})
    db.flag_directive_needs_clarification(cid)

    db.update_directive_candidate(cid, payload={**_POLICY_FIELDS, "text": "新稿", "actor": name})

    payload = json.loads(_by_pid(db, cid)["payload_json"])
    assert payload["text"] == "新稿", "正文已更新"
    assert payload.get("_needs_clarification") is True, "下划线控制键保留（不被静默抹掉）"


def test_prefix_two_decrees_stage_independently(game):
    """L2：显式前缀「拟旨如下：」连拟两道 → 两条独立候选（不 upsert 压扁前一道）。"""
    db, state, content = game
    name = _active_minister_name(db, content)
    an.open_night(db, state, location="乾清宫", time_of_day="夜")

    id1 = db.stage_explicit_directive(state.turn, name, "着户部清查三边粮饷。")
    id2 = db.stage_explicit_directive(state.turn, name, "着兵部核饷九边军械。")

    assert id1 != id2, "第二道另起独立候选"
    pend = _pending_directives(db, state.turn)
    assert len(pend) == 2, "连拟两道各自成条"
    texts = [json.loads(p["payload_json"])["text"] for p in pend]
    assert any("户部清查" in t for t in texts) and any("兵部核饷" in t for t in texts)
    assert not any("户部清查" in t and "兵部核饷" in t for t in texts), "两道未被并进一条"


def _by_pid(db, pid):
    return db.conn.execute(
        "SELECT id, payload_json FROM pending_actions WHERE id=?", (int(pid),)).fetchone()


def test_nonstream_web_chat_surfaces_ambiguous():
    """R1：非流式 WebGame.chat 组装 payload 时透出结构化含糊态（候选集），与 stream 同 surface。
    临时大臣路径跳过持久化/读心，聚焦 payload 组装是否携带 directive_confirmation_ambiguous。"""
    import threading
    from types import SimpleNamespace
    import web_app
    from ming_sim.session import ChatTurnResult

    name = "王承恩"
    amb = {"candidates": [
        {"id": 11, "summary": "草拟圣旨：着户部清查粮饷"},
        {"id": 12, "summary": "草拟圣旨：着兵部核饷军械"},
    ]}

    class _Sess:
        temporary_characters = {name}
        content = SimpleNamespace(characters={name: SimpleNamespace(name=name)})
        state = SimpleNamespace(turn=1, turn_phase="")
        db = SimpleNamespace()

        def chat(self, minister_name, text, chat_turn_id=0):
            return ChatTurnResult(
                answer="请陛下明示是哪一道。", directive_confirmation_ambiguous=amb)

        def pending_count(self):
            return 0

        def _character(self, n):
            return self.content.characters[n]

    rt = object.__new__(web_app.WebGame)
    rt.session = _Sess()
    rt.chat_history = {name: []}
    rt._runtime_write_gate = lambda: threading.Lock()
    rt._audience_turn_in_flight = lambda n: False
    rt.chat_projection = lambda n: []
    rt.suggestions_for = lambda c: []
    rt.can_undo_last_chat = lambda n: False
    rt.directive_rows = lambda: []
    rt.directive_payload = lambda row: row

    payload = rt.chat(name, "准了")

    assert payload["directive_confirmation_ambiguous"] == amb, "非流式 payload 应携带结构化含糊态"
    assert {c["id"] for c in payload["directive_confirmation_ambiguous"]["candidates"]} == {11, 12}


def test_nonstream_web_chat_no_ambiguous_key_is_none():
    """负路：非含糊轮 payload 的含糊态键为 None（不误置）。"""
    import threading
    from types import SimpleNamespace
    import web_app
    from ming_sim.session import ChatTurnResult

    name = "王承恩"

    class _Sess:
        temporary_characters = {name}
        content = SimpleNamespace(characters={name: SimpleNamespace(name=name)})
        state = SimpleNamespace(turn=1, turn_phase="")
        db = SimpleNamespace()

        def chat(self, minister_name, text, chat_turn_id=0):
            return ChatTurnResult(answer="臣遵旨。")

        def pending_count(self):
            return 0

        def _character(self, n):
            return self.content.characters[n]

    rt = object.__new__(web_app.WebGame)
    rt.session = _Sess()
    rt.chat_history = {name: []}
    rt._runtime_write_gate = lambda: threading.Lock()
    rt._audience_turn_in_flight = lambda n: False
    rt.chat_projection = lambda n: []
    rt.suggestions_for = lambda c: []
    rt.can_undo_last_chat = lambda n: False
    rt.directive_rows = lambda: []
    rt.directive_payload = lambda row: row

    payload = rt.chat(name, "今日无事")
    assert payload["directive_confirmation_ambiguous"] is None


def test_clarification_cue_many_candidates_no_indexerror():
    """回归（coderabbit #1087）：`_ensure_clarification_cue` 的中文序数表只有 9 字（其二…其十），
    第 11 道及以后须回退阿拉伯数字。旧码 `i <= 10` 在第 11 道（i==10）仍取字符串支落索引 [9]
    抛 IndexError。断言 11 道并存时不崩、末道用数字序。"""
    ambiguous = {"candidates": [{"id": i, "summary": f"第{i}道"} for i in range(11)]}
    cue = GameSession._ensure_clarification_cue("", ambiguous)
    assert "其一" in cue and "其十" in cue  # 前十道中文序数
    assert "其10" in cue  # 第 11 道（i==10）回退阿拉伯数字，不越界
