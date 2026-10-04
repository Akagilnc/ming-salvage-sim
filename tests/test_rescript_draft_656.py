"""#656 急务票面写口／desk 契约（phase2 票拟 generate/select 已随 F2 退役）。

覆盖 pending_decisions kind 扩列、票拟行覆写与跨月留存、层 A option 形状辅助。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
from ming_sim.db import GameDB


_CANNED = '{"economy_moves": [], "new_armies": [], "new_issues": [], "secret_order_updates": []}'

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

def _retire_existing_actors(db) -> None:
    db.conn.execute(
        "UPDATE characters SET status='retired' WHERE status='active' AND power_id='ming' "
        "AND (office LIKE '%首辅%' OR office LIKE '%掌印%')"
    )

def _add_character(db, name: str, office: str, faction: str, office_type: str = "内阁") -> None:
    template = db.conn.execute("SELECT * FROM characters LIMIT 1").fetchone()
    columns = [r[1] for r in db.conn.execute("PRAGMA table_info(characters)").fetchall()]
    values = [template[c] for c in columns]
    values[columns.index("name")] = name
    values[columns.index("office")] = office
    values[columns.index("office_type")] = office_type
    values[columns.index("faction")] = faction
    values[columns.index("status")] = "active"
    values[columns.index("power_id")] = "ming"
    db.conn.execute(
        f"INSERT INTO characters ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        values,
    )
    db.conn.commit()

# ---------------------------------------------------------------------------
# F3.1 分拣人唯一规则
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# F2.1/F2.2 载体与字段映射
# ---------------------------------------------------------------------------

def test_save_and_list_rescript_drafts_roundtrip(game):
    db, state, _content = game
    turn = state.turn
    db.save_rescript_drafts(turn, [
        {
            "event_id": "issue:42",
            "title": "陕西告饥",
            "context": "秦地赤旱千里，臣愚以为赈济不可缓。",
            "options": [{"label": "发帑赈济", "hint": "所安者饥民"}],
            "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
        },
        {"title": "无局急务", "context": "", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""},
        ]},
    ])
    drafts = db.list_rescript_drafts()
    assert [d["title"] for d in drafts] == ["陕西告饥", "无局急务"]
    first = drafts[0]
    assert first["event_id"] == "issue:42"          # 权威 issue 回指原样保留
    assert first["context"] == "秦地赤旱千里，臣愚以为赈济不可缓。"
    assert first["options"] == [{"label": "发帑赈济", "hint": "所安者饥民"}]
    assert first["status"] == "pending"
    assert first["actor_name"] == "测试首辅"
    assert first["actor_office"] == "内阁首辅"
    assert first["actor_faction"] == "阉党"
    second = drafts[1]
    # 无对应 issue 的急务＝确定性合成 id urgent:{turn}:{idx}
    assert second["event_id"] == f"urgent:{turn}:1"

def test_rescript_draft_idx_continues_after_decision_rows(game):
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择一", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"title": "抉择二", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    db.save_rescript_drafts(turn, [
        {"title": "急务", "context": "", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
    ])
    rows = db.list_pending_decisions(turn)
    # A6 后 HITL 缝只回 decision 行；draft 续编经 list_rescript_drafts 验证
    assert [r["idx"] for r in rows] == [0, 1]
    assert all(r["kind"] == "decision" for r in rows)
    drafts = db.list_rescript_drafts()
    assert [d["idx"] for d in drafts] == [2]  # 与 decision 行共占 (turn, idx) 主键续编

def test_clear_pending_decisions_keeps_rescript_drafts(game):
    """F2.4 定音点：phase2 清除只清 decision 行；rescript_draft 跨月留存。"""
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    db.save_rescript_drafts(turn, [
        {"title": "急务", "context": "", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
    ])
    db.clear_pending_decisions(turn)
    # decision 行清；draft 行仍在案头（跨月留存）。A6 后 draft 不经
    # list_pending_decisions 读，直接验表。
    rows = db.conn.execute(
        "SELECT kind FROM pending_decisions WHERE turn=?", (turn,)
    ).fetchall()
    assert [r["kind"] for r in rows] == ["rescript_draft"]
    assert [d["title"] for d in db.list_rescript_drafts()] == ["急务"]

def test_save_pending_decisions_keeps_rescript_drafts(game):
    """判修 C2（run 01a02d20）：save_pending_decisions 与 clear/save_rescript_drafts
    同款按 kind 收窄——decision 盘面覆写只清只写 kind='decision'。
    生产危险路：phase1 落 decision → phase2 落票拟 → 同回合重结算再覆
    decision 盘面，旧写者不得连带清除 rescript_draft 行（F2/A6 不变式闭合）。"""
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    db.save_rescript_drafts(turn, [
        {"title": "急务", "context": "待票拟", "options": [
            {"label": "甲", "hint": "一"}, {"label": "乙", "hint": "二"}]},
    ])
    draft_before = db.list_rescript_drafts()[0]
    db.save_pending_decisions(turn, [
        {"title": "抉择改一", "context": "c2", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"title": "抉择改二", "context": "c3", "options": [
            {"label": "c", "hint": ""}, {"label": "d", "hint": ""}]},
    ])
    # decision 由一条增长为两条时仍完整覆写；draft 行重排但身份和内容不变。
    rows = db.list_pending_decisions(turn)
    assert [r["title"] for r in rows] == ["抉择改一", "抉择改二"]
    assert [r["idx"] for r in rows] == [0, 1]
    assert all(r["kind"] == "decision" for r in rows)
    draft_after = db.list_rescript_drafts()[0]
    assert draft_after["idx"] == 2
    for field in ("event_id", "title", "context", "options"):
        assert draft_after[field] == draft_before[field]

def test_save_rescript_drafts_overwrites_not_duplicates(game):
    db, state, _content = game
    turn = state.turn
    for _ in range(2):
        db.save_rescript_drafts(turn, [
            {"title": "急务", "context": "", "options": [
                {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
        ])
    assert len(db.list_rescript_drafts()) == 1

def test_repeated_overwrite_keeps_stable_synthetic_ids(game):
    """A3 判词：先删后算 idx——相同 decision 盘面重复覆写得到相同 idx 与
    `urgent:{turn}:{idx}` 合成身份，不随被删旧行漂移；无 UUID/映射账。"""
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择一", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
        {"title": "抉择二", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])

    def _drafts(title_a: str, title_b: str) -> list:
        return [
            {"title": title_a, "context": "导语甲", "options": [
                {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
            {"title": title_b, "context": "导语乙", "options": [
                {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}]},
        ]

    db.save_rescript_drafts(turn, _drafts("急务甲", "急务乙"))
    first = db.list_rescript_drafts()
    assert [d["event_id"] for d in first] == [f"urgent:{turn}:2", f"urgent:{turn}:3"]
    # 同盘面覆写：行被替换、合成身份不变
    db.save_rescript_drafts(turn, _drafts("改拟甲", "改拟乙"))
    second = db.list_rescript_drafts()
    assert [d["title"] for d in second] == ["改拟甲", "改拟乙"]  # 确证替换发生
    assert [d["event_id"] for d in second] == [f"urgent:{turn}:2", f"urgent:{turn}:3"]
    # decision 行 idx 不受影响
    decisions = db.list_pending_decisions(turn)
    assert [d["idx"] for d in decisions] == [0, 1]

# ---------------------------------------------------------------------------
# F3.3 原样不变式＋P4 输入侧定性投影＋prompt 正向措辞（机械验收）
# ---------------------------------------------------------------------------

def test_prompt_zero_numeric_instruction_is_positive_qualitative():
    """P4 落 prompt 用正向表述，不写「不要显示数值」式负向句；其余承载事实/F2.3/
    结构化契约的合法约束不得借机删除。"""
    prompt = (Path(__file__).resolve().parents[1] / "content" / "prompts" / "rescript_draft.md") \
        .read_text(encoding="utf-8")
    assert "不要出现任何数字数值" not in prompt
    assert "不要显示" not in prompt
    assert "定性说法" in prompt            # 正向定性措辞在
    assert "不得虚构" in prompt            # 事实约束保留
    assert "不许凑数" in prompt            # F2.3 约束保留
    assert "只输出一个 JSON object" in prompt  # 结构化契约保留

# ---------------------------------------------------------------------------
# shape 校验＋权威快照绑定（F2.2/F2.3/F2.5）
# ---------------------------------------------------------------------------

def _valid_item(i: int) -> dict:
    return {
        "title": f"条目{i}", "context": f"导语{i}",
        "options": _two_opts("甲拟", "所安者饥民", "乙拟", "所拂者小农"),
    }

@pytest.mark.parametrize("mutate", [
    lambda item: item.update(title=""),
    lambda item: item.update(title="   "),
    lambda item: item.pop("title"),
    lambda item: item.update(context=""),
    lambda item: item.pop("context"),
    lambda item: item["options"].__setitem__(0, {"label": "a"}),      # hint 缺失
    lambda item: item["options"].__setitem__(0, {"label": "", "hint": "h"}),
    lambda item: item["options"].__setitem__(0, {"hint": "h"}),       # label 缺失
])

def _legal_item() -> dict:
    return {
        "title": "陕西告饥",
        "context": "秦地赤旱千里。",
        "options": _two_opts("发帑赈济", "所安者饥民", "缓征加赈", "先赈后征"),
    }

# ---------------------------------------------------------------------------
# F1.3/F2.5 崩溃恢复：不重跑票拟步（持久层读回）＋restore 往返无损
# ---------------------------------------------------------------------------

def test_restore_roundtrip_at_awaiting_pause_has_no_draft_rows(game, tmp_path):
    """F2.5 restore 断言（AWAITING 暂停态存档点）：phase1 暂停时尚无票拟行，restore 后同形。"""
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

# ---------------------------------------------------------------------------
# 票拟与本月上下文同存（#1846 已删 ready 降级）
# ---------------------------------------------------------------------------

def _ready_with_drafts(db, state, drafts):
    if drafts:
        db.save_rescript_drafts(state.turn, drafts)

def _draft_rows(title: str) -> list:
    return [{"title": title, "context": "旧导语", "options": [
        {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}],
        "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
    }]

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
    _ready_with_drafts(db, state, _draft_rows("急务"))
    # 本月上下文 + decision 与 draft 同回合并存

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
    with pytest.raises(LLMContractError, match="不是合法 JSON"):
        _parse_rescript_json_strict(raw)

def test_r3_strict_parse_concatenated_objects_raises_contract_error():
    """r3-2 strict 解析：拼接对象不截首块，直解失败抛 LLMContractError。"""
    from ming_sim.rescript_draft import _parse_rescript_json_strict
    from ming_sim.exceptions import LLMContractError
    raw = '{"items": [{"title": "甲", "context": "c", "options": [{"label": "a", "hint": "h1"}, {"label": "b", "hint": "h2"}]}]}{"items": []}'
    with pytest.raises(LLMContractError, match="不是合法 JSON"):
        _parse_rescript_json_strict(raw)

# ---------------------------------------------------------------------------
# #657 片1：行事实与案头（schema + 词表 + desk 读）
# ---------------------------------------------------------------------------

def _pending_columns(db) -> set[str]:
    return {r[1] for r in db.conn.execute("PRAGMA table_info(pending_decisions)").fetchall()}

def _ledger_columns(db) -> set[str]:
    return {r[1] for r in db.conn.execute("PRAGMA table_info(story_ledger_entries)").fetchall()}

def test_657_s1_schema_columns_and_no_banned_fields(game):
    """片1：revision_round/prior_options_json/origin_ref 列存在；无 consumed_epoch/rescript_origin。"""
    db, _state, _content = game
    pending_cols = _pending_columns(db)
    assert "revision_round" in pending_cols
    assert "prior_options_json" in pending_cols
    assert "consumed_epoch" not in pending_cols
    ledger_cols = _ledger_columns(db)
    assert "origin_ref" in ledger_cols
    dossier_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(decree_dossiers)").fetchall()}
    assert "rescript_origin" not in dossier_cols
    # partial UNIQUE on non-empty origin_ref
    idx_sql = [
        str(r[0]) for r in db.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_ledger_origin_ref'"
        ).fetchall()
    ]
    assert idx_sql and "origin_ref" in idx_sql[0] and "origin_ref != ''" in idx_sql[0].replace('"', "")

def test_657_s1_rescript_emitted_set_subset_of_dossier(game):
    """A12 前置（#1778 后）：只剩 emitted 闭集 ⊂ DOSSIER；七类 routable 已整体取消。"""
    import ming_sim.decree_vocabulary as dv
    from ming_sim.decree_vocabulary import (
        DOSSIER_ACTION_TYPES,
        RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
    )
    assert RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES <= DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES
    assert not hasattr(dv, "RESCRIPT_ROUTABLE_ACTION_TYPES")
    assert not hasattr(dv, "NATIONAL_FANOUT_ACTION_TYPES")
    _ = game  # fixture keeps DB init path green

def test_657_s1_derive_draft_capability_stable_and_sensitive():
    """capability：同字段稳定；闭集任一有效差改变键。"""
    from ming_sim.decree_vocabulary import derive_draft_capability

    base = {
        "action_type": "assignment",
        "label": "发帑赈济",
        "hint": "所安者饥民",
        "assignee_name": "杨嗣昌",
        "target_kind": "region",
        "target_id": "shaanxi",
        "transaction_category": "督赈",
        "locality_scope": "single",
        "region_id": "shaanxi",
    }
    a = derive_draft_capability(base)
    b = derive_draft_capability(dict(base))
    assert isinstance(a, str) and a == b and len(a) >= 16
    # 扰动 label
    changed = dict(base)
    changed["label"] = "缓征"
    assert derive_draft_capability(changed) != a
    # 扰动 assignee
    changed2 = dict(base)
    changed2["assignee_name"] = "洪承畴"
    assert derive_draft_capability(changed2) != a
    # 缺键按默认参与派生，不因插入空串而变
    with_default = dict(base)
    with_default["summon_target"] = ""
    assert derive_draft_capability(with_default) == a

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
    db.save_rescript_drafts(turn, [{
        "title": "本月急务",
        "context": "当月",
        "options": _two_opts("丙", "h3", "丁", "h4"),
        "actor_name": "次辅", "actor_office": "内阁次辅", "actor_faction": "阉党",
    }])
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

    # #656 不变式：clear/save decision 不碰 rescript_draft
    db.clear_pending_decisions(turn)
    assert any(d["title"] == "本月急务" for d in db.list_rescript_drafts())
    assert any(d["title"] == "旧急务甲" for d in db.list_rescript_desk(turn))
