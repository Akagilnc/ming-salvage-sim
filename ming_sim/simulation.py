"""月末推演与打分提取：跑 simulator/extractor agent。L7。"""

from __future__ import annotations

import json
import sqlite3
from typing import Callable, Dict, List, Optional

from agno.agent import Agent

from ming_sim.agents import parse_agent_json, run_agent_stream_text, run_agent_text
from ming_sim.context import historical_anchor_for_month, victory_status
from ming_sim.db import GameDB
from ming_sim.issues import gather_candidate_events, issue_to_payload
from ming_sim.models import GameState
from ming_sim.token_stats import tlog


def _table(rows: List[Dict[str, object]], cols: List[str]) -> Dict[str, object]:
    """array-of-dicts → header + 二维数组。省掉每行重复的 key，体积约为 dict 形式的 1/3。"""
    return {
        "cols": cols,
        "rows": [[r.get(c) for c in cols] for r in rows],
    }


def _auto_table(rows: List[Dict[str, object]]) -> Dict[str, object]:
    """同 _table，但自动取首行 keys。空列表返回空 cols/rows。"""
    if not rows:
        return {"cols": [], "rows": []}
    cols = list(rows[0].keys())
    return _table(rows, cols)




def simulate_season_with_agno(
    agent: Agent,
    state: GameState,
    db: GameDB,
    decree_text: str,
    directives_brief: List[Dict[str, object]],
    previous_narrative: str,
    fixed_flows: Optional[List[Dict[str, object]]] = None,
    deaths_this_turn: Optional[List[Dict[str, str]]] = None,
    debuts_this_turn: Optional[List[Dict[str, str]]] = None,
    on_thinking: Optional[Callable[[str], None]] = None,
    on_text: Optional[Callable[[str], None]] = None,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
) -> str:
    """推演 agent: 全量盘面塞 user payload，无 tool。"""
    active = db.list_active_issues()
    issues_payload = [
        issue_to_payload(row, db.list_recent_issue_advances(int(row["id"]), 1))
        for row in active
    ]
    candidate_events = [
        {
            "id": ev.id,
            "title": ev.title,
            "kind": ev.kind,
            "summary": ev.summary,
            "interests": ev.interests,
            "is_historical": ev.trigger_year > 0,
            "resolve_condition": ev.resolve_condition,
            "fail_condition": ev.fail_condition,
        }
        for ev in gather_candidate_events(state, db)
    ]
    region_rows = [
        dict(r) for r in db.conn.execute(
            "SELECT name,kind,population,public_support,unrest,natural_disaster,"
            "human_disaster,registered_land,hidden_land,tax_per_turn,grain_security,"
            "gentry_resistance,military_pressure,status,"
            "json_extract(fiscal,'$.corruption') as corruption FROM regions ORDER BY id"
        ).fetchall()
    ]
    army_rows = [
        dict(r) for r in db.conn.execute(
            "SELECT name,station,theater,commander,controller,troop_type,manpower,"
            "maintenance_per_turn,supply,morale,training,equipment,arrears,mobility,"
            "loyalty,status FROM armies ORDER BY id"
        ).fetchall()
    ]
    court_roster = [
        dict(r) for r in db.conn.execute(
            "SELECT name,office,office_type,court_role,faction,status FROM characters "
            "WHERE status!='offstage' AND office_type!='后宫' ORDER BY rowid"
        ).fetchall()
    ]
    payload = {
        "year": state.year,
        "period": state.period,
        "decree_text": decree_text,
        "directives": directives_brief,
        "current_state": dict(state.metrics),
        "treasury_brief": db.treasury_report(state),
        "factions_brief": db.faction_report(),
        "classes_brief": db.class_report(),
        "external_powers_brief": db.external_power_report(),
        "active_issues": issues_payload,
        "candidate_events": candidate_events,
        "previous_narrative_tail": previous_narrative[-1500:] if previous_narrative else "",
        "historical_anchor": historical_anchor_for_month(state.year, state.period),
        "victory_status": victory_status(db, state),
        "regions": _auto_table(region_rows),
        "armies": _auto_table(army_rows),
        "buildings": _auto_table(db.building_payload()),
        "court_roster": court_roster,
        "fixed_flows": fixed_flows or [],
        "deaths_this_turn": deaths_this_turn or [],
        "debuts_this_turn": debuts_this_turn or [],
        "relevant_memories": relevant_memories or [],
        "data_note": "regions/armies/buildings 均为 header+二维数组（cols 列名 + rows 数据）。",
    }
    raw = run_agent_stream_text(
        agent,
        json.dumps(payload, ensure_ascii=False, sort_keys=False),
        tag="simulator",
        on_thinking=on_thinking,
        on_text=on_text,
    )
    return raw.strip()


def extract_scores_with_agno(
    agent: Agent,
    db: GameDB,
    state: GameState,
    narrative: str,
    decree_text: str = "",
    sanitizer: Optional[Agent] = None,
    relevant_memories: Optional[List[Dict[str, object]]] = None,
) -> tuple[Dict[str, object], str, str]:
    """结算 agent: 读邸报抽 JSON。"""
    active = db.list_active_issues()
    issues_brief = [
        {
            "issue_id": int(r["id"]),
            "title": r["title"],
            "bar_value": int(r["bar_value"]),
            "inertia": int(r["inertia"]),
            "stage_text": r["stage_text"],
            "cancellable": r["cancellable"],
            "resolve_condition": (r["resolve_condition"] if "resolve_condition" in r.keys() else "") or "(未填)",
            "fail_condition": (r["fail_condition"] if "fail_condition" in r.keys() else "") or "(未填)",
        }
        for r in active
    ]
    region_ids = [r["id"] for r in db.conn.execute("SELECT id FROM regions").fetchall()]
    army_ids = [r["id"] for r in db.conn.execute("SELECT id FROM armies").fetchall()]
    candidate_events = [
        {"id": ev.id, "title": ev.title}
        for ev in gather_candidate_events(state, db)
    ]
    region_rows = [
        dict(r) for r in db.conn.execute(
            "SELECT id,name,kind,population,public_support,unrest,natural_disaster,"
            "human_disaster,registered_land,hidden_land,tax_per_turn,grain_security,"
            "gentry_resistance,military_pressure,status,"
            "json_extract(fiscal,'$.corruption') as corruption FROM regions ORDER BY id"
        ).fetchall()
    ]
    army_rows = [
        dict(r) for r in db.conn.execute(
            "SELECT id,name,station,theater,commander,controller,troop_type,manpower,"
            "maintenance_per_turn,supply,morale,training,equipment,arrears,mobility,"
            "loyalty,status FROM armies ORDER BY id"
        ).fetchall()
    ]
    active_ministers = [
        dict(r) for r in db.conn.execute(
            "SELECT name,office,office_type,court_role,faction FROM characters WHERE status='active' ORDER BY rowid"
        ).fetchall()
    ]
    offstage_ministers = [
        dict(r) for r in db.conn.execute(
            "SELECT name,office,faction,debut_year,debut_month "
            "FROM characters WHERE status='offstage' ORDER BY name"
        ).fetchall()
    ]
    payload = {
        "turn": {"year": state.year, "period": state.period, "turn": state.turn},
        "narrative": narrative,
        "decree_text": decree_text,
        "active_issues": issues_brief,
        "candidate_events": candidate_events,
        "current_state": dict(state.metrics),
        "factions": db.faction_report(),
        "classes": db.class_report(),
        "external_powers": _auto_table(db.external_power_payload()),
        "regions": _auto_table(region_rows),
        "armies": _auto_table(army_rows),
        "buildings": _auto_table(db.building_payload()),
        "active_ministers": _auto_table(active_ministers),
        "offstage_ministers": _auto_table(offstage_ministers),
        "region_ids": region_ids,
        "army_ids": army_ids,
        "class_names": [r["name"] for r in db.conn.execute("SELECT DISTINCT name FROM classes ORDER BY name").fetchall()],
        "external_power_ids": [str(r["id"]) for r in db.conn.execute("SELECT id FROM external_powers").fetchall()],
        "fiscal_config": db.get_fiscal_config(),
        "relevant_memories": relevant_memories or [],
        "_format_note": "regions/armies/buildings/external_powers/active_ministers/offstage_ministers 均为 header+二维数组（cols 列名 + rows 数据）",
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    tlog(f"[extractor] user payload total={len(payload_json)} chars (~{len(payload_json)//1.5:.0f} tok)")
    raw = run_agent_text(agent, payload_json, tag="extractor")
    try:
        return parse_agent_json(raw, "结算抽取"), raw, payload_json
    except Exception as parse_err:
        if sanitizer is None:
            raise
        tlog(f"[extractor] 主输出解析失败：{parse_err}；调 sanitizer 重整")
        cleaned = run_agent_text(sanitizer, raw, tag="sanitizer")
        # 留痕用原始 raw（sanitizer 前），追查时能看到 extractor 真实吐了什么。
        return parse_agent_json(cleaned, "结算抽取（sanitizer）"), raw, payload_json
