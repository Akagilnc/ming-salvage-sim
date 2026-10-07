"""#656 急务 desk／读口契约（phase2 票拟 generate/select 与批量覆写写口已随 F2 退役）。

覆盖 pending_decisions kind 隔离、跨月留存读口、层 A option 形状辅助。
"""
from __future__ import annotations

import json

import pytest

from ming_sim.db import GameDB

# #1778 决定 3：生成批次的票拟必带参与名单（ADR 0053 三档，至少一名主办）。
_ROSTER = [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}]


def _layer_a_opt(label: str = "拟", hint: str = "h", **kw) -> dict:
    """#657 生产层 A option 夹具（层 A option 夹具）。"""
    base = {
        "label": label,
        "hint": hint,
        "action_type": "assignment",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "assignee_name": "",
        "transaction_category": "督赈",
        "participant_roster": [dict(item) for item in _ROSTER],
    }
    base.update(kw)
    return base


def _two_opts(a: str = "甲", ha: str = "h1", b: str = "乙", hb: str = "h2", **kw) -> list:
    return [_layer_a_opt(label=a, hint=ha, **kw), _layer_a_opt(label=b, hint=hb, **kw)]


def _insert_draft_row(
    db,
    turn: int,
    *,
    idx: int,
    title: str,
    context: str = "",
    options: list | None = None,
    event_id: str = "",
    actor_name: str = "",
    actor_office: str = "",
    actor_faction: str = "",
    status: str = "pending",
    revision_round: int = 0,
    prior_options_json: str = "[]",
) -> None:
    """测试夹具：直接落一条 rescript_draft 行（非生产写口，非旧批量覆写算法）。"""
    eid = event_id or f"urgent:{int(turn)}:{int(idx)}"
    db.conn.execute(
        "INSERT INTO pending_decisions\n"
        " (turn, idx, event_id, title, context, options_json, choice_json,\n"
        "  status, kind, actor_name, actor_office, actor_faction,\n"
        "  revision_round, prior_options_json)\n"
        " VALUES (?, ?, ?, ?, ?, ?, '', ?, 'rescript_draft', ?, ?, ?, ?, ?)",
        (
            int(turn),
            int(idx),
            eid,
            title,
            context,
            json.dumps(options or [], ensure_ascii=False),
            status,
            actor_name,
            actor_office,
            actor_faction,
            int(revision_round),
            prior_options_json,
        ),
    )


def test_list_rescript_drafts_projects_planted_rows(game):
    """读口契约：list_rescript_drafts 投影既有 rescript_draft 行字段。"""
    db, state, _content = game
    turn = state.turn
    _insert_draft_row(
        db, turn, idx=0, event_id="issue:42", title="陕西告饥",
        context="秦地赤旱千里，臣愚以为赈济不可缓。",
        options=[{"label": "发帑赈济", "hint": "所安者饥民"}],
        actor_name="测试首辅", actor_office="内阁首辅", actor_faction="阉党",
    )
    _insert_draft_row(
        db, turn, idx=1, title="无局急务",
        options=[{"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}],
    )
    db.conn.commit()
    drafts = db.list_rescript_drafts()
    assert [d["title"] for d in drafts] == ["陕西告饥", "无局急务"]
    first = drafts[0]
    assert first["event_id"] == "issue:42"
    assert first["context"] == "秦地赤旱千里，臣愚以为赈济不可缓。"
    assert first["options"] == [{"label": "发帑赈济", "hint": "所安者饥民"}]
    assert first["status"] == "pending"
    assert first["actor_name"] == "测试首辅"
    assert first["actor_office"] == "内阁首辅"
    assert first["actor_faction"] == "阉党"
    assert drafts[1]["event_id"] == f"urgent:{turn}:1"


def test_save_pending_decisions_keeps_rescript_drafts(game):
    """save_pending_decisions 只清只写 kind='decision'，不连带清除 rescript_draft。"""
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    _insert_draft_row(
        db, turn, idx=1, title="急务", context="待票拟",
        options=[{"label": "甲", "hint": "一"}, {"label": "乙", "hint": "二"}],
        event_id=f"urgent:{turn}:1",
    )
    db.conn.commit()
    draft_before = db.list_rescript_drafts()[0]
    db.save_pending_decisions(turn, [
        {"title": "抉择改一", "context": "c2", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"title": "抉择改二", "context": "c3", "options": [
            {"label": "c", "hint": ""}, {"label": "d", "hint": ""}]},
    ])
    rows = db.list_pending_decisions(turn)
    assert [r["title"] for r in rows] == ["抉择改一", "抉择改二"]
    assert [r["idx"] for r in rows] == [0, 1]
    assert all(r["kind"] == "decision" for r in rows)
    draft_after = db.list_rescript_drafts()[0]
    assert draft_after["idx"] == 2
    for field in ("event_id", "title", "context", "options"):
        assert draft_after[field] == draft_before[field]


def test_restore_roundtrip_at_awaiting_pause_has_no_draft_rows(game, tmp_path):
    """AWAITING 暂停态：仅有 decision 行时 restore 后同形。"""
    db, state, content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])

    path = str(tmp_path / "restore.db")
    db.backup_to(path)
    restored = GameDB(path, content)
    try:
        assert restored.list_rescript_drafts() == []
        rows = restored.list_pending_decisions(turn)
        assert [r["title"] for r in rows] == ["抉择"]
        assert all(r["kind"] == "decision" for r in rows)
    finally:
        restored.close()


def _plant_draft(db, state, title: str) -> None:
    turn = int(state.turn)
    row = db.conn.execute(
        "SELECT COALESCE(MAX(idx) + 1, 0) FROM pending_decisions WHERE turn = ?",
        (turn,),
    ).fetchone()
    idx = int(row[0] or 0)
    _insert_draft_row(
        db, turn, idx=idx, title=title, context="旧导语",
        options=[{"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}],
        actor_name="测试首辅", actor_office="内阁首辅", actor_faction="阉党",
    )
    db.conn.commit()

def test_persist_then_abort_draft_never_enters_hitl_envelope(game):
    """A6+#657：list_pending_decisions 仍只回 decision；批红案头 desk 合并投影含急务。

    #656：decision list 缝不混 draft。
    #657：session.pending_decisions → list_rescript_desk 同页两类；
    仅 decision 行标 decided 时 draft 仍 pending（CAS 按 kind）。
    """
    from ming_sim.session import GameSession

    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    _plant_draft(db, state, "急务")

    rows = db.list_pending_decisions(turn)
    assert [r["kind"] for r in rows] == ["decision"]
    assert [d["title"] for d in db.list_rescript_drafts()] == ["急务"]

    # #657 批红案头：web 投影合并急务 + decision
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    projected = sess.pending_decisions()
    titles = [d["title"] for d in projected]
    assert "急务" in titles and "抉择" in titles

    # 仅 decision 行标 decided——draft 不在 list_pending_decisions 中被误标
    for r in db.list_pending_decisions(turn):
        db.conn.execute(
            "UPDATE pending_decisions SET choice_json=?, status='decided' "
            "WHERE turn=? AND idx=? AND kind='decision'",
            ('{"label":"a"}', turn, r["idx"]),
        )
    db.conn.commit()
    drafts = {d["title"]: d["status"] for d in db.list_rescript_drafts()}
    assert drafts["急务"] == "pending"   # 票拟不被误标 decided

# ---------------------------------------------------------------------------
# PR #1521 r3：三条 shape 拒收负例（顶层未知字段 / 畸形 JSON / lone surrogate）
# ---------------------------------------------------------------------------

def test_r3_strict_parse_control_char_raises_contract_error():
    """r3-2 strict 解析：含非法控制字符的 raw 不做清洗，直解失败抛 LLMContractError。"""
    from ming_sim.rescript_draft import _parse_rescript_json_strict
    from ming_sim.exceptions import LLMContractError
    # 控制字符 \x01 在 JSON 字符串内非法，必须触发 JSONDecodeError→LLMContractError
    raw = '{"items": [{"title": "a\x01b", "context": "c", "options": [{"label": "l1", "hint": "h1"}, {"label": "l2", "hint": "h2"}]}]}'
    with pytest.raises(LLMContractError):
        _parse_rescript_json_strict(raw)

def test_r3_strict_parse_concatenated_objects_raises_contract_error():
    """r3-2 strict 解析：拼接对象不截首块，直解失败抛 LLMContractError。"""
    from ming_sim.rescript_draft import _parse_rescript_json_strict
    from ming_sim.exceptions import LLMContractError
    raw = '{"items": [{"title": "甲", "context": "c", "options": [{"label": "a", "hint": "h1"}, {"label": "b", "hint": "h2"}]}]}{"items": []}'
    with pytest.raises(LLMContractError):
        _parse_rescript_json_strict(raw)

def test_657_s1_option_shape_stamps_draft_capability():
    """层 A option 必填键校验；服务端写 draft_capability。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    raw = {
        "label": "发帑赈济",
        "hint": "所安者饥民",
        "action_type": "assignment",
        "assignee_name": "杨嗣昌",
        "target_kind": "region",
        "target_id": "shaanxi",
        "locality_scope": "single",
        "region_id": "shaanxi",
        "transaction_category": "督赈",
    }
    opt = normalize_rescript_layer_a_option(raw)
    assert opt["draft_capability"]
    assert opt["label"] == "发帑赈济"
    assert opt["action_type"] == "assignment"
    # 缺必填键 → 拒
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({"label": "x", "hint": "y"})
    # #1778：库级全集内的类型（policy 等）照常受理，无七类闭集
    policy_opt = normalize_rescript_layer_a_option({
        **raw,
        "action_type": "policy",
        "target_kind": "policy",
        "target_id": "清丈全国田亩",
        "locality_scope": "national",
        "region_id": "",
    })
    assert policy_opt["action_type"] == "policy"
    assert policy_opt["draft_capability"]
    # 库级全集之外仍 fail-loud（ADR 0040 形状检查）
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({**raw, "action_type": "修仙"})

def _army_pay_grant_option(**extra) -> dict:
    opt = {
        "label": "补发关宁军饷",
        "hint": "边饷急",
        "action_type": "grant_allocation",
        "assignee_name": "",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "grant_kind": "army_pay",
        "amount": 300,
        "account": "国库",
        "purpose": "补饷",
        "participant_roster": [dict(item) for item in _ROSTER],
    }
    opt.update(extra)
    return opt

def test_1620_layer_a_reward_with_army_target_stays_reward():
    """赏赉+army 不因 target_kind 升格协饷。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    opt = normalize_rescript_layer_a_option({
        "label": "赏关宁将士",
        "hint": "恩赏",
        "action_type": "grant_allocation",
        "assignee_name": "",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "grant_action": "赏赉",
        "amount": 50,
        "account": "国库",
    })
    assert opt["grant_action"] == "赏赉"

@pytest.mark.parametrize("extra,drop", [
    pytest.param({"grant_action": "赏赉"}, (), id="conflict-reward"),
    pytest.param({"grant_kind": "other"}, (), id="unknown-kind"),
    pytest.param({"grant_action": "补发军饷"}, ("grant_kind",), id="zh-synonym"),
    # 非 grant 携 grant_kind：不得因 allowed 白名单静默丢键
    pytest.param(
        {"action_type": "assignment", "assignee_name": "杨嗣昌"}, (),
        id="non-grant-kind",
    ),
    # #1503 五字段 admission：缺 purpose/account、非法 target_kind
    pytest.param({"purpose": ""}, (), id="empty-purpose"),
    pytest.param({}, ("purpose",), id="drop-purpose"),
    pytest.param({"account": ""}, (), id="empty-account"),
    pytest.param({}, ("account",), id="drop-account"),
    pytest.param(
        {"target_kind": "region", "target_id": "shaanxi"}, (),
        id="region-target",
    ),
])
def test_1620_layer_a_army_pay_rejects_bad_typed_shape(extra, drop):
    """层 A：五字段缺漏、矛盾 kind、未知 kind、中文同义、非 grant 携 kind 均 fail-loud。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    raw = _army_pay_grant_option(**extra)
    for key in drop:
        raw.pop(key, None)
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option(raw)

def test_1620_internal_canonical_xiexang_renormalizes_without_kind():
    """内部 canonical（无 kind、grant_action=协饷）二次归一仍通；生成旁路另闸。"""
    from ming_sim.rescript_draft import normalize_rescript_layer_a_option

    raw = _army_pay_grant_option(grant_action="协饷")
    raw.pop("grant_kind", None)
    opt = normalize_rescript_layer_a_option(raw)
    assert opt["grant_action"] == "协饷"
    assert opt["purpose"] == "补饷"
    assert opt["account"] == "国库"

def test_657_s1_list_rescript_desk_merges_cross_month_and_decisions(game):
    """desk：旧急务 ORDER BY turn,idx → 本月 decision；decision_key 与新列投影。"""
    db, state, _content = game
    turn = int(state.turn)
    prior = turn - 1 if turn > 0 else 0
    # 跨月急务（prior turn）
    db.conn.execute(
        "INSERT INTO pending_decisions\n"
        " (turn, idx, event_id, title, context, options_json, choice_json,\n"
        "  status, kind, actor_name, actor_office, actor_faction,\n"
        "  revision_round, prior_options_json)\n"
        " VALUES (?, 0, 'urgent:old:0', '旧急务甲', '跨月', ?, '',\n"
        "  'pending', 'rescript_draft', '首辅', '内阁首辅', '东林', 2, ?)",
        (
            prior,
            json.dumps(_two_opts("甲", "h1", "乙", "h2"), ensure_ascii=False),
            json.dumps([[{"label": "旧甲", "hint": "oh"}]], ensure_ascii=False),
        ),
    )
    _insert_draft_row(
        db, turn, idx=0, title="本月急务", context="当月",
        options=_two_opts("丙", "h3", "丁", "h4"),
        actor_name="次辅", actor_office="内阁次辅", actor_faction="阉党",
    )
    db.save_pending_decisions(turn, [{
        "title": "本月抉择",
        "context": "decision",
        "options": _two_opts("准", "", "驳", ""),
        "event_id": "ev-1",
    }])
    # 已 decided 的急务不得入 desk
    db.conn.execute(
        "INSERT INTO pending_decisions\n"
        " (turn, idx, event_id, title, context, options_json, choice_json,\n"
        "  status, kind, revision_round, prior_options_json)\n"
        " VALUES (?, 99, 'urgent:done', '已决急务', '', '[]', '{}',\n"
        "  'decided', 'rescript_draft', 0, '[]')",
        (prior,),
    )
    db.conn.commit()

    desk = db.list_rescript_desk(turn)
    titles = [row["title"] for row in desk]
    assert "已决急务" not in titles
    # 旧急务在前，本月 decision 在急务之后（合并序）
    assert titles[0] == "旧急务甲"
    assert "本月急务" in titles
    assert titles[-1] == "本月抉择" or "本月抉择" in titles
    # 旧急务 → 本月急务 → 本月 decision
    assert titles.index("旧急务甲") < titles.index("本月急务") < titles.index("本月抉择")

    old = next(r for r in desk if r["title"] == "旧急务甲")
    assert old["decision_key"] == f"rescript_draft:{prior}:0"
    assert old["revision_round"] == 2
    assert old["status"] == "pending"
    assert old["actor_name"] == "首辅"
    assert isinstance(old["prior_options_json"], list)
    assert old["choice"] is None or old["choice"] == {} or old["choice"] == ""

    dec = next(r for r in desk if r["title"] == "本月抉择")
    assert dec["decision_key"] == f"decision:{turn}:{dec['idx']}"
    assert dec["kind"] == "decision"

    # list 补列：list_rescript_drafts / list_pending_decisions 带出新列
    drafts = db.list_rescript_drafts()
    hit = next(d for d in drafts if d["title"] == "旧急务甲")
    assert hit["revision_round"] == 2
    assert "prior_options_json" in hit
    decisions = db.list_pending_decisions(turn)
    assert all("revision_round" in d for d in decisions)

    # #656 不变式：save_pending_decisions 不碰 rescript_draft
    db.save_pending_decisions(turn, [{
        "title": "抉择再写", "context": "c", "options": _two_opts("准", "", "驳", ""),
    }])
    assert any(d["title"] == "本月急务" for d in db.list_rescript_drafts())
    assert any(d["title"] == "旧急务甲" for d in db.list_rescript_desk(turn))
