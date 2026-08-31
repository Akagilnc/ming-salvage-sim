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
from ming_sim.constants import TURN_UNIT
from ming_sim.db import GameDB
from ming_sim.decree import _settle_after_narrative, persist_resolve_context
from ming_sim.error_pack import clear_for_resimulation
from ming_sim.exceptions import LLMUnavailable, SettlementAbort
from ming_sim.rescript_draft import (
    build_rescript_draft_payload,
    generate_rescript_draft,
    select_triage_actor,
    validate_rescript_draft_items,
)

_CANNED = '{"economy_moves": [], "new_armies": [], "new_issues": [], "secret_order_updates": []}'


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


def test_payload_projection_excludes_machine_condition_fields():
    """A4 判词：票拟 issue 投影是字段白名单——只携绑定 issue_id 与明确的定性/
    叙事文字；机器契约字段（resolve/fail/stop condition 及中文别名）整体不进票拟
    输入，seed_events 的 public_support >60 / unrest <30 阈值串零穿透；未知字段
    不透传（删除「任意字符串全透传」根因，零字符串扫描/擦洗）。"""
    from ming_sim.models import GameState

    state = GameState.__new__(GameState)
    state.year, state.period, state.turn = 1630, 4, 40
    resolve_cond = ("陕西 public_support（地方民心）>60 且 unrest（动乱值）<30，"
                    "且驻陕官军/边军已能压制叛军即可结案")
    simulator_payload = {"active_issues": [{
        "issue_id": 42, "kind": "situation", "title": "陕西告饥",
        "状态": "流民渐聚", "进度": "未见起色",
        "局势走向": -7, "end_turn": 48,
        "结案条件": resolve_cond,
        "resolve_condition": resolve_cond,
        "fail_condition": "陕西流寇成股（万人以上）攻破州县",
        "stop_condition": "民力已竭",
        f"当前每{TURN_UNIT}效果": {"metrics": {"民心": -1},
            "economy": [{"account": "国库", "delta": -500}]},
        f"上{TURN_UNIT}推进": {"delta_bar": 12, "narrative": "抚臣发帑赈济"},
        "commitment_progress": {"months_elapsed": 3, "paid_total": 150,
                                "remaining_to_goal": "距达标仍有差距"},
        "未知嵌套": {"深层文字": "某处告急", "阈值": "public_support >60"},
    }]}
    payload = build_rescript_draft_payload(state, "邸报正文", simulator_payload,
                                           {"name": "首辅", "office": "内阁首辅", "faction": "阉党"})
    issues = payload["active_issues"]
    assert len(issues) == 1
    issue = issues[0]
    # 白名单内：绑定 id 与定性/叙事文字
    assert issue["issue_id"] == 42                      # 权威绑定快照保留
    assert issue["title"] == "陕西告饥"
    assert issue["状态"] == "流民渐聚"                   # 定性叙事保留
    assert issue["进度"] == "未见起色"                   # 定性档位保留
    # 白名单外字段整体不透传（含机器契约条件与任意未知嵌套）
    for field in ("kind", "局势走向", "end_turn", "结案条件", "resolve_condition",
                  "fail_condition", "stop_condition", f"当前每{TURN_UNIT}效果",
                  f"上{TURN_UNIT}推进", "commitment_progress", "未知嵌套"):
        assert field not in issue, field
    # 机械负向判据：seed_events 阈值串零穿透整个 payload（含邸报正文之外的一切 slot）
    serialized = json.dumps(payload, ensure_ascii=False)
    assert ">60" not in serialized
    assert "<30" not in serialized
    assert "万人以上" not in serialized
    # 纪年契约字段照旧
    assert payload["turn"]["year"] == 1630 and payload["turn"]["reign_period_label"]


def test_payload_projects_consumable_region_targets_from_real_monthly_board(game):
    """系统票拟看到同批盘面的合法 region id，而非从地名臆造目标。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, _content = game
    simulator_payload = build_simulator_payload(state, db, "", "")
    payload = build_rescript_draft_payload(
        state, "邸报", simulator_payload,
        {"name": "首辅", "office": "内阁首辅", "faction": "阉党"},
    )

    targets = {row["id"]: row for row in payload["region_targets"]}
    assert targets["liaodong"] == {
        "id": "liaodong", "name": "辽东 / 宁锦", "kind": "边镇",
    }
    assert "ningyuan" not in targets

    bad = dict(simulator_payload)
    for table in (
        {"cols": ["id", "name", "kind"], "rows": [["liaodong"]]},
        {"cols": ["id", "name", "kind"], "rows": [["", "辽东", "边镇"]]},
        {"cols": ["id", "name", "kind"], "rows": [[123, "辽东", "边镇"]]},
        {"cols": ["id", "name", "kind"], "rows": [["liaodong", ["辽东"], "边镇"]]},
        {"cols": ["id", "name", "kind"], "rows": ["abc"]},
    ):
        bad["regions"] = table
        with pytest.raises(ValueError):
            build_rescript_draft_payload(
                state, "邸报", bad,
                {"name": "首辅", "office": "内阁首辅", "faction": "阉党"},
            )


def test_generate_rejects_region_id_outside_same_batch_catalog(monkeypatch):
    item = _legal_item()
    item["options"][0]["target_id"] = "ningyuan"
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    assert generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "liaodong", "name": "辽东 / 宁锦", "kind": "边镇"}],
    }, 1) is None


def test_payload_projects_consumable_army_targets_from_real_monthly_board(game):
    """系统票拟看到同批盘面的合法 army id，而非把省 id 当军."""
    from ming_sim.action_materialize import GRANT_ACTIONS
    from ming_sim.simulation import build_simulator_payload

    db, state, _content = game
    simulator_payload = build_simulator_payload(state, db, "", "")
    enemy_ids = {
        "manchu_banners_main",
        "han_liaoren_corps",
        "mongol_chahar_host",
        "korean_border_army",
        "bandit_wangjiayin",
    }
    army_board = simulator_payload["armies"]
    id_index = army_board["cols"].index("id")
    assert enemy_ids <= {row[id_index] for row in army_board["rows"]}

    payload = build_rescript_draft_payload(
        state, "邸报", simulator_payload,
        {"name": "首辅", "office": "内阁首辅", "faction": "阉党"},
    )

    targets = {row["id"]: row for row in payload["army_targets"]}
    assert targets["guanning"]["id"] == "guanning"
    assert targets["guanning"]["name"]
    assert "liaodong" not in targets
    assert enemy_ids.isdisjoint(targets)
    # #1620：grant_action 闭集与 Layer-A GRANT_ACTIONS 同源投影
    assert payload["grant_actions"] == sorted(GRANT_ACTIONS - {"无"})


def test_generate_rejects_army_id_outside_same_batch_catalog(monkeypatch):
    item = _legal_item()
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
    assert generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [{"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"}],
    }, 1) is None


def test_generate_rejects_military_order_with_region_target(monkeypatch):
    item = _legal_item()
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
    assert generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [
            {"id": "liaodong", "name": "辽东 / 宁锦", "kind": "边镇"},
            {"id": "shaanxi", "name": "陕西", "kind": "腹地"},
        ],
        "army_targets": [{"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"}],
    }, 1) is None


def test_generate_rejects_military_order_empty_assignee(monkeypatch):
    item = _legal_item()
    item["options"][0].update({
        "action_type": "military_order",
        "target_kind": "army",
        "target_id": "guanning",
        "assignee_name": "",
        "station": "宁远",
        "deadline_months": 1,
    })
    monkeypatch.setattr(
        rescript_mod, "run_agent_text",
        lambda *a, **k: json.dumps({"items": [item]}, ensure_ascii=False),
    )
    assert generate_rescript_draft(object(), {
        "active_issues": [],
        "region_targets": [{"id": "shaanxi", "name": "陕西", "kind": "腹地"}],
        "army_targets": [{"id": "guanning", "name": "关宁军 / 宁锦防线", "station": "辽东 / 宁远锦州"}],
    }, 1) is None


def test_payload_projection_without_active_issues_degrades_to_empty():
    from ming_sim.models import GameState

    state = GameState.__new__(GameState)
    state.year, state.period, state.turn = 1630, 4, 40
    payload = build_rescript_draft_payload(state, "邸报", {},
                                           {"name": "首辅", "office": "内阁首辅", "faction": "阉党"})
    assert payload["active_issues"] == []


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


def test_validate_items_over_limit_fails_whole_batch():
    """A1 判词：处理条目前校验 items 总数——超 5 条即 ValueError 整批失败，
    零截断零保留（不 slice、不静默丢弃后项）。6 条全合法与第 6 条非法同判。"""
    six_legal = [_valid_item(i) for i in range(6)]
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"items": six_legal}, set())
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
    lambda item: item.update(options=[item["options"][0]]),          # 只 1 项
    lambda item: item.update(options=item["options"] * 2),           # 4 项
    lambda item: item["options"].__setitem__(0, {"label": "a"}),      # hint 缺失
    lambda item: item["options"].__setitem__(0, {"label": "", "hint": "h"}),
    lambda item: item["options"].__setitem__(0, {"hint": "h"}),       # label 缺失
])
def test_validate_items_missing_required_field_fails_whole_batch(mutate):
    """冻结票面 F2.2/F2.5：任一必需字段缺失/非法＝整批失败，不保留合法项成部分头版。"""
    good = _valid_item(0)
    bad = _valid_item(1)
    mutate(bad)
    with pytest.raises(ValueError):
        validate_rescript_draft_items({"items": [good, bad]}, set())


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
    with pytest.raises(ValueError, match="未知字段"):
        validate_rescript_draft_items({"items": [item]}, set())


def test_validate_items_rejects_unknown_option_field_whole_batch():
    """r2 裁决 B2：option 层未知字段同样不得静默省略——整批 shape 错。"""
    item = _legal_item()
    item["options"][0]["extra_option"] = "模型多写的合法自由文本"
    with pytest.raises(ValueError, match="未知字段"):
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

    def _boom(agent, prompt, tag):
        raise LLMUnavailable("LLM 不可用")

    monkeypatch.setattr(rescript_mod, "run_agent_text", _boom)
    payload = {"active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {}}
    assert generate_rescript_draft(object(), payload, state.turn) is None
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{state.turn}.json"
    assert note.is_file()
    assert "LLM 不可用" in note.read_text(encoding="utf-8")


def test_generate_rescript_draft_program_error_propagates(game, monkeypatch):
    """r2 裁决 B3 / ADR 0005：程序错不得以「非承重支路」为由吞成降级。
    validator 抛 RuntimeError（代码故障）必须响亮上抛——票拟业务降级 ≠ 代码故障降级。"""
    db, state, _content = game

    def _buggy_validate(data, ids):
        raise RuntimeError("programmer bug sentinel")

    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda a, p, tag: "{\"items\": []}")
    monkeypatch.setattr(rescript_mod, "validate_rescript_draft_items", _buggy_validate)
    payload = {
        "active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {},
    }
    with pytest.raises(RuntimeError, match="programmer bug sentinel"):
        generate_rescript_draft(object(), payload, state.turn)


# ---------------------------------------------------------------------------
# 集成：_settle_after_narrative 落库序列（F2.5）＋原样落库（F3.3）
# ---------------------------------------------------------------------------

def _stub_settle_agents(monkeypatch) -> None:
    import ming_sim.decree as decree_mod
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_rescript_draft_agent", lambda *a, **k: object())


def test_settlement_persists_drafts_verbatim_and_survives_clear(game, monkeypatch):
    """急务随结算落库：自由文本原样（零改写零裁剪）；phase2 清除后跨月留存；
    全量邸报正文不被裁剪。"""
    import ming_sim.decree as decree_mod
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    turn = state.turn
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    memorial = "臣体仁谨奏：秦地赤旱千里，流民渐起，伏乞圣裁。"
    draft_raw = json.dumps({"items": [{
        "issue_id": 42, "title": "陕西告饥",
        "context": memorial,
        "options": _two_opts("发帑赈济", "所安者饥民", "缓议加派", "所拂者小农"),
    }]}, ensure_ascii=False)

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return draft_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    narrative = "本月邸报全文……（全量正文，一字不减）"
    _settle_after_narrative(
        state, db, None, None,
        decree_text="减赋诏", narrative=narrative,
        simulator_payload={
            "active_issues": [{"issue_id": 42, "title": "陕西告饥"}],
            "regions": {"cols": ["id", "name", "kind"],
                        "rows": [["shaanxi", "陕西", "布政司"]]},
            "transit_semantics": [],
        },
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )

    drafts = db.list_rescript_drafts()
    assert len(drafts) == 1
    row = drafts[0]
    # 原样落库（F3.3）：自由文本逐字保留，无任何改写/裁剪/模板化
    assert row["context"] == memorial
    assert row["title"] == "陕西告饥"
    assert [o["label"] for o in row["options"]] == ["发帑赈济", "缓议加派"]
    assert all(o.get("draft_capability") for o in row["options"])
    assert all(o.get("action_type") == "assignment" for o in row["options"])
    assert row["event_id"] == "issue:42"
    assert row["status"] == "pending"
    # actor 身份随行落库（F3.2）
    assert row["actor_name"] == "测试首辅"
    assert row["actor_office"] == "内阁首辅"
    assert row["actor_faction"] == "阉党"
    # phase2 已跑完（clear 已按 kind 过滤）→ decision 行清、draft 行跨月留存
    # （A6 后 draft 不经 list_pending_decisions 读，直接验表）
    rows = db.conn.execute(
        "SELECT kind FROM pending_decisions WHERE turn=?", (turn,)
    ).fetchall()
    assert [r["kind"] for r in rows] == ["rescript_draft"]
    assert db.get_resolve_context(turn) is None
    # 全量邸报不被裁剪：turn_extractions.narrative 原文照存（落库前文仍用原始 narrative）
    row = db.conn.execute(
        "SELECT narrative FROM turn_extractions WHERE turn=?", (turn,)
    ).fetchone()
    assert row is not None and row["narrative"] == narrative


def test_extractor_abort_rolls_back_drafts(game, monkeypatch, tmp_path):
    """F2.5：extractor 响亮中止 ⇒ 票拟一并回滚不落、重试重生成。"""
    import ming_sim.decree as decree_mod
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    draft_raw = json.dumps({"items": [{
        "title": "陕西告饥", "context": "秦地赤旱千里。",
        "options": _two_opts("发帑赈济", "所安者饥民", "缓议加派", "所拂者小农"),
    }]}, ensure_ascii=False)

    def _fake_run(agent, prompt, tag):
        if tag.startswith("extractor/"):
            raise RuntimeError("extractor boom")
        return draft_raw

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    with pytest.raises(SettlementAbort):
        _settle_after_narrative(
            state, db, None, None,
            decree_text="诏", narrative="邸报",
            simulator_payload={"active_issues": [], "transit_semantics": []},
            relevant_memories=[], secret_orders={},
            before_turn=state.turn, _emit=lambda *a: None, content=content,
        )
    assert db.list_rescript_drafts() == []
    assert db.get_resolve_context(state.turn) is None


def test_draft_degrade_does_not_abort_settlement(game, monkeypatch, tmp_path):
    """F2.5：票拟步形状校验失败＝响亮降级，本月无头版，结算照常完成。"""
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return "这不是 JSON"
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    turn = state.turn
    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={"active_issues": [], "transit_semantics": []},
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )
    assert db.list_rescript_drafts() == []  # 本月无头版
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
    assert note.is_file()
    assert state.turn == turn + 1  # 结算本体完成、回合照常推进


def test_mixed_batch_shape_failure_degrades_whole_month(game, monkeypatch, tmp_path):
    """冻结票面 F2.2/F2.5：一合法＋一缺必需字段的混合批次＝整月响亮降级——零行落库、
    降级附记在、结算不中止（不得保留合法项形成部分头版，不得把缺失洗成空串）。"""
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    draft_raw = json.dumps({"items": [
        {"issue_id": 42, "title": "陕西告饥",
         "context": "秦地赤旱千里，赈济不可缓。",
         "options": _two_opts("发帑赈济", "所安者饥民", "缓议加派", "所拂者小农")},
        {"title": "辽饷告匮", "options": [   # 缺 context 必需字段 → 整批非法
            {"label": "折发宗禄", "hint": "所拂者宗藩"},
            {"label": "加派小农", "hint": "所拂者小农"}]},
    ]}, ensure_ascii=False)

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return draft_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    turn = state.turn
    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={
            "active_issues": [{"issue_id": 42, "title": "陕西告饥"}],
            "regions": {"cols": ["id", "name", "kind"],
                        "rows": [["shaanxi", "陕西", "布政司"]]},
            "transit_semantics": [],
        },
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )
    assert db.list_rescript_drafts() == []   # 零行落库：不保留合法项成部分头版
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
    assert note.is_file()                    # 降级附记在
    assert "context" in note.read_text(encoding="utf-8")
    assert state.turn == turn + 1            # 结算不中止、回合照常推进


def test_over_limit_legal_batch_degrades_whole_month_zero_rows(game, monkeypatch, tmp_path):
    """A1 回归（6 条全合法）：超限＝整月响亮降级——零行落库、降级附记在、结算不中止
    （不截断保留前五条成部分头版）。"""
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    draft_raw = json.dumps({"items": [
        {"issue_id": 42, "title": f"条目{i}", "context": f"导语{i}，赈济不可缓。",
         "options": _two_opts("发帑赈济", "所安者饥民", "缓议加派", "所拂者小农")}
        for i in range(6)  # 6 条全合法，仍超上限 → 整批失败
    ]}, ensure_ascii=False)

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return draft_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    turn = state.turn
    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={"active_issues": [{"issue_id": 42, "title": "陕西告饥"}], "transit_semantics": []},
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )
    assert db.list_rescript_drafts() == []   # 零行落库：第六条不再被静默截丢
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
    assert note.is_file()                    # 降级附记在（响亮而非静默）
    assert "超上限" in note.read_text(encoding="utf-8")
    assert state.turn == turn + 1            # 结算不中止、回合照常推进


def test_sixth_item_illegal_degrades_whole_month_zero_rows(game, monkeypatch, tmp_path):
    """A1 回归（第 6 条非法）：前 5 条合法也不保留——整月降级零行落库。"""
    import ming_sim.rescript_draft as rescript_draft
    import ming_sim.simulation as simulation

    db, state, content = game
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    _stub_settle_agents(monkeypatch)
    _retire_existing_actors(db)
    _add_character(db, "测试首辅", "内阁首辅", "阉党")

    items = [{"issue_id": 42, "title": f"条目{i}", "context": f"导语{i}。",
              "options": _two_opts("甲拟", "所安者饥民", "乙拟", "所拂者小农")}
             for i in range(5)]
    items.append({"title": "缺导语第六条"})  # 第 6 条非法
    draft_raw = json.dumps({"items": items}, ensure_ascii=False)

    def _fake_run(agent, prompt, tag):
        if tag == "rescript-draft":
            return draft_raw
        return _CANNED

    monkeypatch.setattr(simulation, "run_agent_text", _fake_run)
    monkeypatch.setattr(rescript_draft, "run_agent_text", _fake_run)

    turn = state.turn
    _settle_after_narrative(
        state, db, None, None,
        decree_text="诏", narrative="邸报",
        simulator_payload={"active_issues": [{"issue_id": 42, "title": "陕西告饥"}], "transit_semantics": []},
        relevant_memories=[], secret_orders={},
        before_turn=turn, _emit=lambda *a: None, content=content,
    )
    assert db.list_rescript_drafts() == []   # 零行落库：前五条合法项不成部分头版
    note = tmp_path / "error_packs" / "rescript_draft_degraded" / f"turn{turn}.json"
    assert note.is_file()
    assert state.turn == turn + 1


# ---------------------------------------------------------------------------
# F1.3/F2.5 崩溃恢复：不重跑票拟步（持久层读回）＋restore 往返无损
# ---------------------------------------------------------------------------

def test_ready_context_recovery_reads_drafts_back_without_rerun(game, monkeypatch):
    """崩溃恢复（ready 重放）不重跑票拟：票拟行已在持久层，重放路零票拟 LLM 调用。"""
    import ming_sim.decree as decree_mod

    db, state, content = game
    turn = state.turn
    persist_resolve_context(
        db, turn, {},
        decree_text="诏", narrative="邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=[{"title": "急务", "context": "导语", "options": [
            {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}],
            "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
        }],
    )
    assert db.get_resolve_context(turn) is not None

    calls: list[str] = []

    def _forbidden_draft_run(agent, prompt, tag):
        calls.append(tag)
        raise AssertionError("恢复重放不得重跑票拟生成步")

    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "record_chapter_memory", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_ending_summary_agent", lambda *a, **k: None)
    monkeypatch.setattr(rescript_mod, "run_agent_text", _forbidden_draft_run)
    monkeypatch.setattr(
        decree_mod, "extract_scores_by_modules_with_agno",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("重放不得重跑 extractor")),
    )

    result = decree_mod.resolve_decisions_phase2(
        state, db, None, None, content=content,
    )
    assert isinstance(result, str)  # 重放路返回结算报告
    assert calls == []
    # 重放完成（clear 只清 decision 行）→ 票拟行无损留存
    drafts = db.list_rescript_drafts()
    assert len(drafts) == 1 and drafts[0]["title"] == "急务"


def test_restore_roundtrip_preserves_draft_rows_field_by_field(game):
    """F2.5 restore 断言（结算中存档点）：ready context＋票拟已落，restore 后逐字段无损。"""
    db, state, content = game
    turn = state.turn
    persist_resolve_context(
        db, turn, {},
        decree_text="诏", narrative="邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=[{
            "event_id": "issue:7", "title": "辽饷告匮",
            "context": "九边欠饷数月，饥溃可待。",
            "options": _two_opts("折发宗禄", "所拂者宗藩", "加派小农", "所拂者小农"),
            "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
        }],
    )
    before = db.list_rescript_drafts()
    assert len(before) == 1

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db.backup_to(path)
        restored = GameDB(path, content)
        try:
            after = restored.list_rescript_drafts()
        finally:
            restored.close()
    finally:
        os.remove(path)
        if os.path.exists(f"{path}_agno.db"):
            os.remove(f"{path}_agno.db")

    assert after == before


def test_restore_roundtrip_at_awaiting_pause_has_no_draft_rows(game):
    """F2.5 restore 断言（AWAITING 暂停态存档点）：phase1 暂停时尚无票拟行，restore 后同形。"""
    db, state, content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])

    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db.backup_to(path)
        restored = GameDB(path, content)
        try:
            assert restored.list_rescript_drafts() == []
            rows = restored.list_pending_decisions(turn)
            assert [r["title"] for r in rows] == ["抉择"]
            assert all(r["kind"] == "decision" for r in rows)
        finally:
            restored.close()
    finally:
        os.remove(path)
        if os.path.exists(f"{path}_agno.db"):
            os.remove(f"{path}_agno.db")


# ---------------------------------------------------------------------------
# A2 重模拟作废：陈旧票拟与 ready context 降级同生死
# ---------------------------------------------------------------------------

def _ready_with_drafts(db, state, drafts):
    persist_resolve_context(
        db, state.turn, {},
        decree_text="诏", narrative="邸报",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=drafts,
    )


def _draft_rows(title: str) -> list:
    return [{"title": title, "context": "旧导语", "options": [
        {"label": "甲", "hint": ""}, {"label": "乙", "hint": ""}],
        "actor_name": "测试首辅", "actor_office": "内阁首辅", "actor_faction": "阉党",
    }]


def test_resimulation_clear_invalidates_stale_drafts(game):
    """A2 判词：ready→clear 作废动作清该 turn 陈旧票拟行；phase1 context 与
    decision 行保留。重跑结果为空列表时不得残留旧票拟冒充新头版。"""
    db, state, content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    _ready_with_drafts(db, state, _draft_rows("陈旧急务"))
    assert [d["title"] for d in db.list_rescript_drafts()] == ["陈旧急务"]

    clear_for_resimulation(db, turn)

    # 陈旧票拟行已清；decision 行不动；phase1 context 降级保留（非删行）
    assert db.list_rescript_drafts() == []
    rows = db.list_pending_decisions(turn)
    assert [r["title"] for r in rows] == ["抉择"]
    ctx = db.get_resolve_context(turn)
    assert ctx is not None and ctx.get("extracted") is None

    # 重跑结果为空列表（本月确无急务）→ 零残留
    persist_resolve_context(
        db, turn, {}, decree_text="诏", narrative="邸报新",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=[],
    )
    assert db.list_rescript_drafts() == []


def test_resimulation_clear_degraded_rerun_leaves_no_stale_drafts(game):
    """A2 回归（降级 None）：重跑票拟步降级返回 None 时，旧票拟不得存活。"""
    db, state, _content = game
    turn = state.turn
    _ready_with_drafts(db, state, _draft_rows("陈旧急务"))
    clear_for_resimulation(db, turn)
    # 重跑降级：persist 不携 rescript_drafts（None）
    persist_resolve_context(
        db, turn, {}, decree_text="诏", narrative="邸报新",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
    )
    assert db.get_resolve_context(turn) is not None
    assert db.list_rescript_drafts() == []   # 无头版，而非旧版冒充


def test_resimulation_clear_atomic_on_downgrade_write_failure(game, monkeypatch):
    """A2-r4 判词（故障注入）：作废动作单事务——context 降级写失败时，draft 删除、
    rejection 作废标记与 ready 降级一并回滚；不得留下「ready 真源仍在、配套票拟
    已删」的半作废状态。decision 行不受影响。"""
    db, state, _content = game
    turn = state.turn
    db.save_pending_decisions(turn, [
        {"title": "抉择", "context": "c", "options": [
            {"label": "a", "hint": ""}, {"label": "b", "hint": ""}]},
    ])
    _ready_with_drafts(db, state, _draft_rows("陈旧急务"))
    # 预置一条该 turn 的拒收记录，验证作废标记同样随事务回滚。
    collector = RejectionCollector(attempt=1)
    collector.record("issues", RejectedItem(
        item={"issue_id": "i1"}, reason="幻觉 id",
        category="hallucinated_id", source=Provenance.system_simulation,
    ), turn)
    collector.flush_to_db(db)
    db.conn.commit()

    def _boom(*_args, **_kwargs):
        raise RuntimeError("注入：降级写失败")

    monkeypatch.setattr(db, "save_resolve_context", _boom)
    with pytest.raises(RuntimeError, match="注入：降级写失败"):
        clear_for_resimulation(db, turn)

    # 全回滚：draft 仍在、rejection 未被作废、ctx 仍 ready、decision 行不动。
    assert [d["title"] for d in db.list_rescript_drafts()] == ["陈旧急务"]
    row = db.conn.execute(
        "SELECT resimulation_invalidated FROM rejection_reports WHERE turn=?", (turn,)
    ).fetchone()
    assert row is not None and row[0] == 0
    ctx = db.get_resolve_context(turn)
    assert ctx is not None and ctx.get("extracted") is not None
    assert [r["title"] for r in db.list_pending_decisions(turn)] == ["抉择"]

    # 注入解除后重跑成功路径：三路陈旧清零语义照常成立。
    monkeypatch.undo()
    clear_for_resimulation(db, turn)
    assert db.list_rescript_drafts() == []
    ctx = db.get_resolve_context(turn)
    assert ctx is not None and ctx.get("extracted") is None


def test_resimulation_clear_new_results_fully_replace_old_drafts(game):
    """A2 回归（新列表）：重跑产出新票拟时只有新行，旧行零残留。"""
    db, state, _content = game
    turn = state.turn
    _ready_with_drafts(db, state, _draft_rows("陈旧急务"))
    clear_for_resimulation(db, turn)
    persist_resolve_context(
        db, turn, {}, decree_text="诏", narrative="邸报新",
        simulator_payload={}, secret_orders=[], relevant_memories=[],
        rescript_drafts=_draft_rows("新急务"),
    )
    assert [d["title"] for d in db.list_rescript_drafts()] == ["新急务"]


# ---------------------------------------------------------------------------
# A6 HITL envelope 单缝：persist-then-abort 后票拟不进亲裁/刷新/submit 消费面
# ---------------------------------------------------------------------------

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
    # persist-then-abort 形状：ready ctx＋decision 与 draft 同回合并存

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
    with pytest.raises(ValueError, match="未知字段"):
        validate_rescript_draft_items(data, set())


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


def test_r3_strict_parse_degrades_via_generate(game, monkeypatch, tmp_path):
    """r3-2 集成：畸形 JSON 经 generate 降级为无头月而非静默修复。"""
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path))
    payload = {"active_issues": [], "gazette": "邸报", "triage_actor": {}, "turn": {}}
    # 拼接对象 raw
    raw = '{"items": [{"title": "甲", "context": "c", "options": [{"label": "a", "hint": "h"}, {"label": "b", "hint": "h2"}]}]}{"items": []}'
    monkeypatch.setattr(rescript_mod, "run_agent_text", lambda a, p, tag: raw)
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
    with pytest.raises(ValueError, match="不可编码字符"):
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


def test_657_s1_rescript_closed_sets_subset_of_dossier(game):
    """A12 前置：双闭集 ⊂ DOSSIER_ACTION_TYPES，且 DOSSIER 不是七值。"""
    from ming_sim.decree_vocabulary import (
        DOSSIER_ACTION_TYPES,
        RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
        RESCRIPT_ROUTABLE_ACTION_TYPES,
    )
    assert RESCRIPT_ROUTABLE_ACTION_TYPES <= DOSSIER_ACTION_TYPES
    assert RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES <= DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES
    assert "dismiss_assignment" not in RESCRIPT_ROUTABLE_ACTION_TYPES
    assert len(DOSSIER_ACTION_TYPES) > len(RESCRIPT_ROUTABLE_ACTION_TYPES)
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
    with pytest.raises(ValueError):
        normalize_rescript_layer_a_option({
            **raw, "action_type": "policy",  # 非七类 routable
        })


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
