"""#656 / ADR 0093 前半：急务分拣＋票拟生成（DECISION 通道＋邸报头版）。

覆盖票面修正案 r1-r3 的 F2（pending_decisions kind 扩列、事务序列、崩溃恢复不重跑、
跨月留存）与 F3（分拣人唯一规则、actor 身份随行落库、原样落库零扫描）。
并发 oracle（五路 barrier）见 test_rescript_fanout_656.py。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import ming_sim.rescript_draft as rescript_mod
from ming_sim.applier import Provenance, RejectedItem, RejectionCollector
from ming_sim.db import GameDB
from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.rescript_draft import (
    generate_rescript_draft,
    select_triage_actor,
    validate_rescript_draft_items,
)

_CANNED = '{"economy_moves": [], "new_armies": [], "new_issues": [], "secret_order_updates": []}'

# #1778 决定 3：生成批次的票拟必带参与名单（ADR 0053 三档，至少一名主办）。
_ROSTER = [{"character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None}]

def _layer_a_opt(label: str = "拟", hint: str = "h", **kw) -> dict:
    """#657 生产层 A option 夹具（validate/generate 路径必用）。"""
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

def test_triage_actor_prefers_first_assistant_over_eunuch_director(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")
    _add_character(db, "测试掌印", "司礼监掌印太监", "阉党", office_type="内廷")
    actor = select_triage_actor(db)
    assert actor == {"name": "测试首辅", "office": "内阁首辅", "faction": "阉党"}

def test_triage_actor_falls_back_to_eunuch_director(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "测试掌印", "司礼监掌印太监", "阉党", office_type="内廷")
    actor = select_triage_actor(db)
    assert actor is not None and actor["name"] == "测试掌印"

def test_triage_actor_negative_yumajian_zhangyin_never_selected(game):
    """r2 裁决 B1 负例：御马监掌印太监与票拟/批红职权无关，不得顶补分拣 actor。"""
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "御马监掌印", "御马监掌印太监", "阉党", office_type="内廷")
    assert select_triage_actor(db) is None

def test_triage_actor_duplicate_hits_deterministic_order(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "B辅臣", "内阁首辅", "东林")
    _add_character(db, "A辅臣", "内阁首辅", "阉党")
    actor = select_triage_actor(db)
    # ORDER BY office_type,office,name（gatekeeper 先例同款确定性序）→ A辅臣 在前
    assert actor is not None and actor["name"] == "A辅臣"

def test_triage_actor_absent_when_both_offices_vacant(game):
    db, _state, _content = game
    _retire_existing_actors(db)
    assert select_triage_actor(db) is None

def test_triage_actor_follows_reappointment(game):
    """F3.2 换人即换立场（可机械断言面）：任免后 actor 事实变更。"""
    db, _state, _content = game
    _retire_existing_actors(db)
    _add_character(db, "首任首辅", "内阁首辅", "东林")
    assert select_triage_actor(db)["name"] == "首任首辅"
    db.conn.execute(
        "UPDATE characters SET status='retired' WHERE name='首任首辅'"
    )
    _add_character(db, "继任首辅", "内阁首辅", "阉党")
    actor = select_triage_actor(db)
    assert actor["name"] == "继任首辅" and actor["faction"] == "阉党"

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

def test_validate_and_persist_preserve_whitespace_verbatim(game):
    """原样不变式（CLAUDE.md P6 / F3.3）：首尾空白逐字段往返零删改——strip 只作判空
    临时值，绝不把 strip 后文本写回落库。"""
    db, state, _content = game
    turn = state.turn
    raw_title = " 陕西告饥  "
    raw_context = "\n秦地赤旱千里，臣愚以为赈济不可缓。\t"
    raw_label_a = " 发帑赈济 "
    raw_hint_a = "\n所安者饥民\n"
    data = {"items": [{
        "title": raw_title, "context": raw_context,
        "options": [
            _layer_a_opt(label=raw_label_a, hint=raw_hint_a),
            _layer_a_opt(label="缓议加派", hint=" 所拂者小农 "),
        ],
    }]}
    drafts = validate_rescript_draft_items(data, set())
    assert len(drafts) == 1  # 首尾空白不构成「非法」，照常通过
    # validator 出口已逐字原样
    assert drafts[0]["title"] == raw_title
    assert drafts[0]["context"] == raw_context
    assert drafts[0]["options"][0]["label"] == raw_label_a
    assert drafts[0]["options"][0]["hint"] == raw_hint_a
    assert drafts[0]["options"][1]["hint"] == " 所拂者小农 "
    assert drafts[0]["options"][0]["draft_capability"]
    # 落库往返仍逐字无损
    db.save_rescript_drafts(turn, drafts)
    row = db.list_rescript_drafts()[0]
    assert row["title"] == raw_title
    assert row["context"] == raw_context
    assert row["options"] == drafts[0]["options"]


def test_generate_ungrounded_region_heals_then_drops_sibling_kept(monkeypatch, tmp_path):
    """#1746：region target 未接地 → heal 耗尽只剔该 option，兄弟保留。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    # 兄弟锚定同批目录 liaodong；坏项 target 游离
    for opt in item["options"]:
        opt["target_id"] = "liaodong"
        opt["region_id"] = "liaodong"
    sibling = dict(item["options"][1])
    item["options"][0]["target_id"] = "ningyuan"
    item["options"][0]["region_id"] = "ningyuan"
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "liaodong", "name": "辽东 / 宁锦", "kind": "边镇"}],
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 1
    assert drafts[0]["options"][0].get("label") == sibling.get("label")


def test_generate_ungrounded_army_heals_then_drops_sibling_kept(monkeypatch, tmp_path):
    """#1746：army target 未接地 → heal 耗尽只剔该 option，兄弟保留。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    sibling = dict(item["options"][1])
    item["options"][0].update({
        "action_type": "military_order",
        "target_kind": "army",
        "target_id": "liaodong",
        "assignee_name": "祖大寿",
        "station": "宁远",
        "deadline_months": 1,
    })
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [{"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"}],
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 1
    assert drafts[0]["options"][0].get("label") == sibling.get("label")


def test_generate_combined_target_and_roster_failures_reported_together_then_land(
    monkeypatch, tmp_path,
):
    """#1804 C：同一 option 同时坏 target_id 与 roster → 首轮补交一次告全两类；

    一次改对两处即落库。短路装回会使首轮只见 target_id（变异验证见本测）。
    """
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    sibling = dict(item["options"][1])
    # 坏项：target 与 roster 同时未接地（region 与 target 同坏，保持 single 组合自洽）
    item["options"][0]["target_id"] = "ningyuan"
    item["options"][0]["region_id"] = "ningyuan"
    bad_roster = [{
        "character_id": "陕西巡抚", "tier": "主办", "role": "", "delegator_id": None,
    }]
    fixed_roster = [{
        "character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None,
    }]
    item["options"][0]["participant_roster"] = bad_roster
    catalog = [
        {"name": "毕自严", "office": "户部尚书"},
        {"name": "崔呈秀", "office": "兵部尚书"},
    ]
    n = {"i": 0}
    prompts: list[str] = []

    def _llm(_a, prompt, tag="", prior_messages=None):
        prompts.append(prompt)
        n["i"] += 1
        if n["i"] == 1:
            return json.dumps({"items": [item]}, ensure_ascii=False)
        # 一次改对两处目录失败；region_id 随 target 回目录内合法值（组合自洽，非本闸）
        return json.dumps({
            "heals": [{
                "heal_id": "0:0",
                "target_id": "shaanxi",
                "region_id": "shaanxi",
                "participant_roster": fixed_roster,
            }],
        }, ensure_ascii=False)

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "character_targets": catalog,
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 2
    fixed = drafts[0]["options"][0]
    assert fixed["target_id"] == "shaanxi"
    assert fixed["participant_roster"][0]["character_id"] == "毕自严"
    assert drafts[0]["options"][1].get("label") == sibling.get("label")
    # 首轮补交请求须同时带出两类失败事实（合并上报，非串行短路）
    assert len(prompts) >= 2
    heal_req = json.loads(prompts[1])
    assert heal_req["kind"] == "rescript_option_field_heal"
    fields = {
        str(f["field"])
        for f in heal_req["failures"][0]["field_failures"]
    }
    assert "target_id" in fields
    assert "participant_roster" in fields

def test_generate_combined_target_roster_partial_heal_reports_remaining(
    monkeypatch, tmp_path,
):
    """#1804 C：首轮同时报两类；只改对一处 → 下轮仍如实报剩余那处。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    sibling = dict(item["options"][1])
    item["options"][0]["target_id"] = "ningyuan"
    item["options"][0]["region_id"] = "ningyuan"
    bad_roster = [{
        "character_id": "陕西巡抚", "tier": "主办", "role": "", "delegator_id": None,
    }]
    fixed_roster = [{
        "character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None,
    }]
    item["options"][0]["participant_roster"] = bad_roster
    catalog = [
        {"name": "毕自严", "office": "户部尚书"},
        {"name": "崔呈秀", "office": "兵部尚书"},
    ]
    n = {"i": 0}
    prompts: list[str] = []

    def _llm(_a, prompt, tag="", prior_messages=None):
        prompts.append(prompt)
        n["i"] += 1
        if n["i"] == 1:
            return json.dumps({"items": [item]}, ensure_ascii=False)
        if n["i"] == 2:
            # 只改对 target（+region 组合自洽），roster 仍坏
            return json.dumps({
                "heals": [{
                    "heal_id": "0:0",
                    "target_id": "shaanxi",
                    "region_id": "shaanxi",
                }],
            }, ensure_ascii=False)
        # 次轮改 roster
        return json.dumps({
            "heals": [{"heal_id": "0:0", "participant_roster": fixed_roster}],
        }, ensure_ascii=False)

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "character_targets": catalog,
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 2
    assert drafts[0]["options"][0]["target_id"] == "shaanxi"
    assert drafts[0]["options"][0]["participant_roster"][0]["character_id"] == "毕自严"
    assert drafts[0]["options"][1].get("label") == sibling.get("label")
    assert len(prompts) >= 3
    first_heal = json.loads(prompts[1])
    first_fields = {
        str(f["field"]) for f in first_heal["failures"][0]["field_failures"]
    }
    assert first_fields >= {"target_id", "participant_roster"}
    second_heal = json.loads(prompts[2])
    second_fields = {
        str(f["field"]) for f in second_heal["failures"][0]["field_failures"]
    }
    assert second_fields == {"participant_roster"}

def test_generate_unknown_roster_character_heals_with_legal_set_then_lands(
    monkeypatch, tmp_path,
):
    """#1804：roster 官职名 → 顶层 participant_roster 失败事实+合法集；照协议部分键补交落库。

    广告协议只认顶层 option 键合并；field 须为 participant_roster（非整点号嵌套键），
    补交体 {"heals":[{"heal_id":"i:o","participant_roster":...}]} 即修复。
    """
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    sibling = dict(item["options"][1])
    bad_roster = [{
        "character_id": "陕西巡抚", "tier": "主办", "role": "", "delegator_id": None,
    }]
    fixed_roster = [{
        "character_id": "毕自严", "tier": "主办", "role": "", "delegator_id": None,
    }]
    item["options"][0]["participant_roster"] = bad_roster
    catalog = [
        {"name": "毕自严", "office": "户部尚书"},
        {"name": "崔呈秀", "office": "兵部尚书"},
    ]
    n = {"i": 0}
    prompts: list[str] = []

    def _llm(_a, prompt, tag="", prior_messages=None):
        prompts.append(prompt)
        n["i"] += 1
        if n["i"] == 1:
            return json.dumps({"items": [item]}, ensure_ascii=False)
        # 照广告协议部分键补交：只回顶层 participant_roster，不整 option 替换
        return json.dumps({
            "heals": [{"heal_id": "0:0", "participant_roster": fixed_roster}],
        }, ensure_ascii=False)

    monkeypatch.setattr(rescript_mod, "run_agent_text", _llm)
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "character_targets": catalog,
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 2
    bad_fixed = drafts[0]["options"][0]
    assert bad_fixed["participant_roster"][0]["character_id"] == "毕自严"
    assert drafts[0]["options"][1].get("label") == sibling.get("label")
    heal_req = json.loads(prompts[1])
    assert heal_req["kind"] == "rescript_option_field_heal"
    facts = {
        str(f["field"]): f
        for f in heal_req["failures"][0]["field_failures"]
    }
    # 顶层键：与 _apply_option_heal 合并路径相容；禁点号嵌套键
    assert "participant_roster" in facts
    assert "participant_roster.character_id" not in facts
    assert "participant_roster.delegator_id" not in facts
    assert facts["participant_roster"]["current"] == bad_roster
    assert set(facts["participant_roster"]["expected"]) == {"毕自严", "崔呈秀"}
    # 部分键补交不得把点号键写进 option 顶层
    assert "participant_roster.character_id" not in bad_fixed
    assert "participant_roster.delegator_id" not in bad_fixed

def test_generate_unknown_delegator_heals_then_drops_sibling_kept(
    monkeypatch, tmp_path,
):
    """#1804：delegator_id 不存在 → heal；耗尽只剔该 option。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    sibling = dict(item["options"][1])
    item["options"][0]["participant_roster"] = [{
        "character_id": "毕自严", "tier": "主办", "role": "",
        "delegator_id": "兵部侍郎",
    }]
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "character_targets": [
            {"name": "毕自严", "office": "户部尚书"},
            {"name": "崔呈秀", "office": "兵部尚书"},
        ],
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 1
    assert drafts[0]["options"][0].get("label") == sibling.get("label")

def test_generate_existing_offcourt_roster_character_lands(monkeypatch, tmp_path):
    """#1804 防回退 #1778：存在但不在朝/无官职 → 合法落库，不得判非法。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    item["options"][0]["participant_roster"] = [{
        "character_id": "离场无职甲", "tier": "主办", "role": "", "delegator_id": None,
    }]
    item["options"][1]["participant_roster"] = [{
        "character_id": "离场无职甲", "tier": "主办", "role": "",
        "delegator_id": "离场无职乙",
    }]
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "character_targets": [
            {"name": "离场无职甲", "office": ""},
            {"name": "离场无职乙", "office": ""},
            {"name": "毕自严", "office": "户部尚书"},
        ],
    }, 1)
    assert drafts is not None and len(drafts) == 1
    assert len(drafts[0]["options"]) == 2
    assert drafts[0]["options"][0]["participant_roster"][0]["character_id"] == "离场无职甲"
    assert drafts[0]["options"][1]["participant_roster"][0]["delegator_id"] == "离场无职乙"

def test_generate_military_order_region_target_heals_then_drops(monkeypatch, tmp_path):
    """#1746 heal-covers-illegal-values-too：军令 target_kind=region 非法 → 补交耗尽只剔该 option。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    sibling = dict(item["options"][1])
    item["options"][0].update({
        "action_type": "military_order",
        "target_kind": "region",
        "target_id": "liaodong",
        "assignee_name": "祖大寿",
        "station": "宁远",
        "deadline_months": 1,
    })
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [
            {"id": "liaodong", "name": "辽东 / 宁锦", "kind": "边镇"},
            {"id": "shaanxi", "name": "陕西", "kind": "腹地"},
        ],
        "army_targets": [{"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"}],
    }, 1)
    assert drafts is not None
    opts = drafts[0]["options"]
    assert len(opts) == 1 and opts[0]["label"] == sibling["label"]

def test_generate_rejects_military_order_empty_assignee(monkeypatch, tmp_path):
    """#1746：可定位 option 缺 assignee_name → 补交耗尽后只剔该 option，兄弟项仍呈。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    item = _legal_item()
    item["options"][0].update({
        "action_type": "military_order",
        "target_kind": "army",
        "target_id": "guanning",
        "locality_scope": "none",
        "region_id": "",
        "transaction_category": "",
        "assignee_name": "",
        "station": "宁远",
        "deadline_months": 1,
    })
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    drafts = generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [{"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"}],
    }, 1)
    assert drafts is not None and len(drafts) == 1
    opts = drafts[0]["options"]
    assert len(opts) == 1
    assert opts[0]["action_type"] == "assignment"
    assert opts[0]["label"] == item["options"][1]["label"]


# ---------------------------------------------------------------------------
# shape 校验＋权威快照绑定（F2.2/F2.3/F2.5）
# ---------------------------------------------------------------------------

def test_validate_items_binds_only_board_issue_ids():
    board = [{"issue_id": 5}, {"issue_id": 7}]
    data = {"items": [
        {"issue_id": 5, "title": "甲", "context": "c", "options": _two_opts("a", "h1", "b", "h2")},
        {"issue_id": 999, "title": "幻觉回显", "context": "c", "options": _two_opts("a", "h1", "b", "h2")},
        {"title": "无回显", "context": "c", "options": _two_opts("a", "h1", "b", "h2")},
    ]}
    drafts = validate_rescript_draft_items(data, {5, 7})
    assert [d.get("event_id") for d in drafts] == ["issue:5", None, None]
    assert drafts[1]["title"] == "幻觉回显"  # 文本原样保留，只不信 id

def _valid_item(i: int) -> dict:
    return {
        "title": f"条目{i}", "context": f"导语{i}",
        "options": _two_opts("甲拟", "所安者饥民", "乙拟", "所拂者小农"),
    }

def test_validate_items_no_count_cap_keeps_all_legal():
    """#1801 ①c：条目数无硬上限——6 条全合法照呈；第 6 条字段非法仍整批 ValueError
    （非 isolate 直调口径；条数本身不再是失败因）。"""
    six_legal = [_valid_item(i) for i in range(6)]
    drafts = validate_rescript_draft_items({"items": six_legal}, set())
    assert len(drafts) == 6
    assert [d["title"] for d in drafts] == [f"条目{i}" for i in range(6)]
    sixth_illegal = [_valid_item(i) for i in range(5)]
    sixth_illegal.append({"title": "缺导语"})
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"items": sixth_illegal}, set())

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
def test_validate_items_missing_required_field_fails_whole_batch(mutate):
    """冻结票面 F2.2/F2.5：title/context/option 内部契约非法＝整批失败（#1801 后项数不再整批）。"""
    good = _valid_item(0)
    bad = _valid_item(1)
    mutate(bad)
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"items": [good, bad]}, set())

def test_validate_items_single_option_is_legal():
    """#1801：单拟合法——条目只给 1 个 option 照常呈上。"""
    item = _valid_item(0)
    item["options"] = [item["options"][0]]
    drafts = validate_rescript_draft_items({"items": [item]}, set())
    assert len(drafts) == 1
    assert len(drafts[0]["options"]) == 1
    assert drafts[0]["title"] == item["title"]

def test_validate_items_many_options_not_gated_or_truncated():
    """#1801：多项不拦——5 个 option 照常呈上、不截断、不报错。"""
    item = _valid_item(0)
    base = item["options"][0]
    item["options"] = [
        {**base, "label": f"拟{i}", "hint": f"h{i}"} for i in range(5)
    ]
    drafts = validate_rescript_draft_items({"items": [item]}, set())
    assert len(drafts) == 1
    assert [o["label"] for o in drafts[0]["options"]] == [f"拟{i}" for i in range(5)]

def test_validate_items_empty_options_drops_item_keeps_siblings(monkeypatch):
    """#1801：0 项按 F2.3 不足照实消失；其它条目仍呈上；日志响亮；不整批判死。"""
    logs: list[str] = []
    monkeypatch.setattr(rescript_mod, "tlog", logs.append)
    good = _valid_item(0)
    empty = _valid_item(1)
    empty["options"] = []
    drafts = validate_rescript_draft_items({"items": [good, empty]}, set())
    assert len(drafts) == 1
    assert drafts[0]["title"] == good["title"]
    assert len(drafts[0]["options"]) == 2
    assert logs, "0 项条目消失须响亮留痕"

def test_validate_items_non_list_options_drops_item_keeps_siblings(monkeypatch):
    """#1801：非 list options 该条目消失；其它条目仍呈上；日志响亮；不整批判死。"""
    logs: list[str] = []
    monkeypatch.setattr(rescript_mod, "tlog", logs.append)
    good = _valid_item(0)
    bad = _valid_item(1)
    bad["options"] = "not-a-list"
    drafts = validate_rescript_draft_items({"items": [good, bad]}, set())
    assert len(drafts) == 1
    assert drafts[0]["title"] == good["title"]
    assert logs, "非 list options 条目消失须响亮留痕"

def test_validate_items_empty_list_is_legal_headless_month():
    """合法 items=[] 仍是「本月确无急务」（F2.3 不凑数）。"""
    assert validate_rescript_draft_items({"items": []}, set()) == []

def test_validate_items_rejects_illegal_top_level():
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"nope": []}, set())
    with pytest.raises(ValueError):
        validate_rescript_draft_items("不是 JSON object", set())

def _legal_item() -> dict:
    return {
        "title": "陕西告饥",
        "context": "秦地赤旱千里。",
        "options": _two_opts("发帑赈济", "所安者饥民", "缓征加赈", "先赈后征"),
    }

def test_validate_items_rejects_unknown_item_field_whole_batch():
    """r2 裁决 B2：item 层多产的未知自由文本字段不得接受后静默省略——整批 shape 错。"""
    item = _legal_item()
    item["extra"] = "模型多写的合法自由文本"
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"items": [item]}, set())

def test_validate_items_rejects_unknown_option_field_whole_batch():
    """非 isolate：option 未知键仍整批 ValueError（generate isolate 时走 heal）。"""
    item = _legal_item()
    item["options"][0]["extra_option"] = "模型多写的合法自由文本"
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"items": [item]}, set())

def test_validate_items_accepts_optional_issue_id_binding_key():
    """issue_id 是唯一豁免的可选绑定键，白名单收窄不得误伤既有绑定路。"""
    item = _legal_item()
    item["issue_id"] = 42
    drafts = validate_rescript_draft_items({"items": [item]}, {42})
    assert drafts[0]["event_id"] == "issue:42"

def test_generate_rescript_draft_degrades_loudly_without_raising(game, monkeypatch, tmp_path):
    """F2.5 响亮降级（r2 B3 收窄后）：typed LLMUnavailable → tlog＋附记，返回 None，不抛。"""
    db, state, _content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))

    def _boom(agent, prompt, tag, **_kwargs):
        raise LLMUnavailable("LLM 不可用")

    monkeypatch.setattr(rescript_mod, "run_agent_text", _boom)
    payload = {"active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {}}
    assert generate_rescript_draft(object(), payload, state.turn) is None
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{state.turn}.json"
    assert note.is_file()
    # 标准 JSON 转义保真：结构化 reason，不锁原文呈现
    assert "LLM 不可用" in json.loads(note.read_text(encoding="utf-8"))["reason"]

def test_generate_rescript_draft_program_error_propagates(game, monkeypatch):
    """r2 裁决 B3 / ADR 0005：程序错不得以「非承重支路」为由吞成降级。
    validator 抛 RuntimeError（代码故障）必须响亮上抛——票拟业务降级 ≠ 代码故障降级。"""
    db, state, _content = game

    def _buggy_validate(data, ids, **_kwargs):
        raise RuntimeError("programmer bug sentinel")

    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda a, p, tag, **_k: "{\"items\": []}",
    )
    monkeypatch.setattr(rescript_mod, "validate_rescript_draft_items", _buggy_validate)
    payload = {
        "active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {},
    }
    with pytest.raises(RuntimeError):
        generate_rescript_draft(object(), payload, state.turn)

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

def test_r3_top_level_unknown_field_rejects_whole_batch():
    """r3-1 顶层 exact-key：多余 summary 等未知顶层键一律整批 ValueError。"""
    data = {
        "items": [{
            "title": "陕西告饥", "context": "秦地赤旱千里。",
            "options": _two_opts("发帑赈济", "所安者饥民", "缓征", "先赈后征"),
        }],
        "summary": "臣请圣裁",
    }
    with pytest.raises(ValueError):
        validate_rescript_draft_items(data, set())

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

def test_r3_strict_parse_degrades_via_generate(game, monkeypatch, tmp_path):
    """r3-2 集成：畸形 JSON 经 generate 降级为无头月而非静默修复。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    payload = {"active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {}}
    # 拼接对象 raw
    raw = '{"items": [{"title": "甲", "context": "c", "options": [{"label": "a", "hint": "h"}, {"label": "b", "hint": "h2"}]}]}{"items": []}'
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda a, p, tag, **_k: raw)
    # 假设 turn 取自 fixture? 用固定值避免依赖
    turn = 99
    assert generate_rescript_draft(object(), payload, turn) is None
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
    assert note.is_file()

def test_r3_lone_surrogate_field_rejects_whole_batch():
    """r3-3 UTF-8 合约：lone surrogate 在 validate 即整批 ValueError，正常中文仍通过。"""
    # lone surrogate \ud800 经 json 逃逸可解但不可 UTF-8 编码
    bad_title = "\ud800"
    data = {
        "items": [{
            "title": bad_title, "context": "秦地赤旱千里。",
            "options": _two_opts("发帑赈济", "所安者饥民", "缓征", "先赈后征"),
        }]
    }
    with pytest.raises(ValueError):
        validate_rescript_draft_items(data, set())
    # 正常中文与约数家产表述仍通过
    good = {
        "items": [{
            "title": "陕西约有三万家产待赈济", "context": "秦地赤旱，百姓约有万户流离。",
            "options": _two_opts("发帑赈济", "所安者饥民", "缓征", "先赈后征"),
        }]
    }
    assert len(validate_rescript_draft_items(good, set())) == 1

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

def test_657_s1_rescript_emitted_set_subset_of_dossier():
    """A12 前置（#1778 后）：只剩 emitted 闭集 ⊂ DOSSIER；七类 routable 已整体取消。"""
    from ming_sim.decree_vocabulary import (
        DOSSIER_ACTION_TYPES,
        RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
    )
    assert RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES <= DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES

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

def test_657_validate_rejects_label_hint_only_options():
    """#657 Class1：旧仅 label/hint 两键输入必须整批失败（无兼容适配层）。"""
    data = {"items": [{
        "title": "陕西告饥", "context": "秦地赤旱。",
        "options": [
            {"label": "发帑赈济", "hint": "所安者饥民"},
            {"label": "缓征", "hint": "先赈后征"},
        ],
    }]}
    with pytest.raises(ValueError):
        validate_rescript_draft_items(data, set())

def test_657_validate_layer_a_roundtrip_capability(game):
    """合法七类 option 整链 validate→persist→读回全字段+capability。"""
    db, state, _content = game
    data = {"items": [{
        "title": "陕西告饥", "context": "秦地赤旱。",
        "options": [
            _layer_a_opt(
                label="发帑赈济", hint="所安者饥民",
                action_type="assignment", transaction_category="督赈",
                deadline_months=2,
            ),
            _layer_a_opt(
                label="赏赉", hint="恩赏",
                action_type="grant_allocation", grant_action="赏赉",
                amount=100, target_kind="character", target_id="杨嗣昌",
                name="杨嗣昌", locality_scope="none", region_id="",
                transaction_category="",
            ),
        ],
    }]}
    drafts = validate_rescript_draft_items(data, set())
    assert len(drafts) == 1
    opts = drafts[0]["options"]
    assert opts[0]["action_type"] == "assignment"
    assert opts[0]["draft_capability"]
    assert opts[1]["action_type"] == "grant_allocation"
    assert opts[1]["grant_action"] == "赏赉"
    assert opts[1]["amount"] == 100
    db.save_rescript_drafts(int(state.turn), drafts)
    row = db.list_rescript_drafts()[0]
    assert row["options"][0]["draft_capability"] == opts[0]["draft_capability"]
    assert row["options"][1]["amount"] == 100

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

def test_1620_validate_army_pay_grant_kind_maps_to_xiexang():
    """真实票拟入口：合法 kind 映射；无 kind 直写协饷与 kind+action 并存整批拒。"""
    # #1624：assignment 须 transaction_category 或点将主办；hold 支用点将满足组合契约
    hold = _layer_a_opt(
        label="暂缓", hint="候报",
        transaction_category="", assignee_name="杨嗣昌",
    )
    drafts = validate_rescript_draft_items(
        {"items": [{
            "title": "关宁欠饷",
            "context": "边军待哺。",
            "options": [
                _army_pay_grant_option(),
                hold,
            ],
        }]},
        set(),
    )
    opt = drafts[0]["options"][0]
    assert opt["grant_action"] == "协饷"
    assert opt["amount"] == 300
    assert opt.get("purpose") == "补饷"
    assert "grant_kind" not in opt

    for bad in (
        _army_pay_grant_option(grant_action="协饷"),  # kind+action 并存
        {k: v for k, v in _army_pay_grant_option(grant_action="协饷").items()
         if k != "grant_kind"},  # 无 kind 直写协饷
    ):
        with pytest.raises(ValueError):
            validate_rescript_draft_items(
                {"items": [{
                    "title": "关宁欠饷",
                    "context": "边军待哺。",
                    "options": [bad, hold],
                }]},
                set(),
            )

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
