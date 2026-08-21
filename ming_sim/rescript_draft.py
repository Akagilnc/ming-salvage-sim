"""急务分拣＋票拟生成（#656 / ADR 0093 前半）：DECISION 待核议通道的邸报头版。

分拣人唯一规则（票面 F3.1，纯确定性读取现有 office/faction、不新增中立排序器）：
  1. 主分拣人＝内阁首辅（active 明臣 office LIKE '%首辅%'）；
  2. 缺位顶补＝司礼监掌印（office LIKE '%掌印%'）；
  3. 多行命中按 gatekeeper 先例 ORDER BY office_type,office,name 取第一；
  4. 双双缺位＝本月无分拣、无头版（全量邸报照旧可读）；
  5. 首辅与掌印同时在位时首辅分拣、掌印不参与。

产文保护（票面 F3.3 / ADR 0142/0143）：LLM 自由文本**原样落库**——本模块对输出只做
shape 校验（顶层合法／必需字段在），零 regex、零词表、零裁剪、零改写、零奏疏模板；
奏疏体零数值只在输入侧以正向措辞落实（prompt＋定性盘面投影）。

载体（票面 F2）：复用既有 pending_decisions 表，kind='rescript_draft' 行；只投影既有
issue 盘面事实，不新建 issue。event_id 绑定走 bind_decisions_to_candidate_events 同款
纪律——权威快照（喂给 LLM 的 issue 盘面投影）为准，不信 LLM 回显；无对应 issue 的
急务用确定性合成 id `urgent:{turn}:{idx}`。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ming_sim.agents import parse_agent_json, run_agent_text
from ming_sim.db import GameDB
from ming_sim.error_pack import error_packs_root
from ming_sim.models import GameState, reign_period_label
from ming_sim.token_stats import tlog

RESCRIPT_DRAFT_KIND = "rescript_draft"
MAX_RESRIPT_DRAFTS = 5


def select_triage_actor(db: GameDB) -> Optional[Dict[str, str]]:
    """F3.1 唯一分拣人选择规则：首辅优先、掌印顶补、重复命中取第一、双双缺位回 None。"""
    for office_pattern in ("%首辅%", "%掌印%"):
        row = db.conn.execute(
            "SELECT name,office,faction FROM characters "
            "WHERE status='active' AND power_id='ming' AND office LIKE ? "
            "ORDER BY office_type,office,name LIMIT 1",
            (office_pattern,),
        ).fetchone()
        if row is not None:
            return {
                "name": str(row["name"]),
                "office": str(row["office"]),
                "faction": str(row["faction"] or ""),
            }
    return None


def build_rescript_draft_payload(
    state: GameState,
    db: GameDB,
    narrative: str,
    simulator_payload: Dict[str, object],
    triage_actor: Dict[str, str],
) -> Dict[str, object]:
    """票拟生成 LLM 步的确定性输入（F1.3：零依赖 extractor 输出，只读盘面投影）。

    active_issues 复用 simulator_payload 里已做定性投影的同一份（0143 输入侧投影唯一
    通道，issue_id 是权威绑定快照）；缺失时回空表并留痕（无盘面可投影＝无急务可选）。
    """
    del db
    active_issues = simulator_payload.get("active_issues")
    if not isinstance(active_issues, list):
        tlog("[rescript] simulator_payload 无 active_issues 投影，按空盘面处理。")
        active_issues = []
    return {
        "turn": {
            "year": state.year,
            "period": state.period,
            "turn": state.turn,
            "reign_period_label": reign_period_label(state.year, state.period),
        },
        "gazette": narrative,
        "triage_actor": dict(triage_actor),
        "active_issues": active_issues,
        "target": {"min_items": 3, "max_items": MAX_RESRIPT_DRAFTS},
    }


def validate_rescript_draft_items(
    data: object,
    board_issue_ids: set[int],
) -> List[Dict[str, object]]:
    """shape 校验（F2.5 响亮降级的判据面）＋权威快照绑定。

    - 顶层非法（非 dict / 无 items list）→ raise ValueError（整批降级，本月无头版）；
    - 单条缺必需字段（title 空 / options 非 2-3 项或 label 空）→ 丢弃该条并 tlog 留痕，
      不静默吞；存活 0 条与「本月确无急务」同形（合法的无头版，不凑数 F2.3）；
    - 超出上限截前 MAX 条（确定性）；
    - event_id 只采信出现在权威盘面里的 issue_id 回指（bind 同款纪律）；其余留给
      落库层合成 `urgent:{turn}:{idx}`。
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("票拟生成输出顶层非法：须为 {\"items\":[...]}")
    drafts: List[Dict[str, object]] = []
    for raw in data["items"]:
        if len(drafts) >= MAX_RESRIPT_DRAFTS:
            break
        if not isinstance(raw, dict):
            tlog("[rescript] 票拟条目非 object，丢弃该条。")
            continue
        title = str(raw.get("title") or "").strip()
        context = str(raw.get("context") or "").strip()
        raw_opts = raw.get("options")
        options: List[Dict[str, str]] = []
        if isinstance(raw_opts, list):
            for opt in raw_opts:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label") or "").strip()
                if not label:
                    continue
                options.append({"label": label, "hint": str(opt.get("hint") or "").strip()})
        if not title or not (2 <= len(options) <= 3):
            tlog(f"[rescript] 票拟条目缺必需字段（title 空或 options 非 2-3 项），丢弃：{title!r}")
            continue
        draft: Dict[str, object] = {"title": title, "context": context, "options": options}
        # 权威快照为准：只认喂给 LLM 的 issue 盘面里真实存在的 issue_id（不信回显）。
        issue_id = raw.get("issue_id")
        if isinstance(issue_id, bool):
            issue_id = None
        elif isinstance(issue_id, int):
            pass
        elif isinstance(issue_id, str) and issue_id.strip().lstrip("-").isdigit():
            issue_id = int(issue_id.strip())
        else:
            issue_id = None
        if issue_id is not None and issue_id in board_issue_ids:
            draft["event_id"] = f"issue:{issue_id}"
        drafts.append(draft)
    return drafts


def _board_issue_ids(active_issues: object) -> set[int]:
    ids: set[int] = set()
    if isinstance(active_issues, list):
        for item in active_issues:
            if isinstance(item, dict) and isinstance(item.get("issue_id"), int) \
                    and not isinstance(item.get("issue_id"), bool):
                ids.add(int(item["issue_id"]))
    return ids


def _write_degraded_note(turn: int, reason: str) -> None:
    """响亮降级的 error pack 附记：诊断目录留 JSON 注记（不写整包热备——结算未中止）。"""
    try:
        root = error_packs_root() / "rescript_draft_degraded"
        root.mkdir(parents=True, exist_ok=True)
        note = {
            "turn": int(turn),
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        (root / f"turn{int(turn)}.json").write_text(
            json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:  # noqa: BLE001 — 附记是诊断旁路，任何异常不得拖垮结算
        tlog(f"[rescript] 降级附记写盘失败：{exc}")


def generate_rescript_draft(
    agent: Any,
    payload: Dict[str, object],
    turn: int,
) -> Optional[List[Dict[str, object]]]:
    """phase2 第五路：跑一次票拟生成 LLM 调用并校验 shape。

    响亮降级契约（F2.5）：任何失败（LLM 异常 / 输出非法）→ tlog 留痕＋诊断目录附记，
    返回 None，本月视作无头版；**绝不抛**——结算本体零依赖票拟，中止会把非承重并行
    支路耦合进关键路。
    """
    try:
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
        tlog(f"[rescript] user payload total={len(payload_json)} chars (~{len(payload_json)//1.5:.0f} tok)")
        raw = run_agent_text(agent, payload_json, tag="rescript-draft")
        data = parse_agent_json(raw, "急务票拟生成")
        drafts = validate_rescript_draft_items(data, _board_issue_ids(payload.get("active_issues")))
        tlog(f"[rescript] 票拟生成 {len(drafts)} 条。")
        return drafts
    except Exception as exc:  # noqa: BLE001 — 响亮降级（F2.5），不中止结算
        tlog(f"[rescript] 票拟生成失败，本月视作无头版：{exc}")
        _write_degraded_note(turn, str(exc))
        return None
