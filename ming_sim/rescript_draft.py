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
from ming_sim.constants import TURN_UNIT
from ming_sim.db import GameDB
from ming_sim.error_pack import error_packs_root
from ming_sim.models import GameState, reign_period_label
from ming_sim.token_stats import tlog

MAX_RESCRIPT_DRAFTS = 5


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


_EFFECT_KEYS = (f"当前每{TURN_UNIT}效果", "成功效果", "失败效果")
_ADVANCE_KEY = f"上{TURN_UNIT}推进"


def _strip_bare_quantities(value: object) -> Optional[object]:
    """递归剥离 gameplay 裸量（int/float；bool 是语义标志不剥），保留定性文字与结构。

    0143 输入侧投影：剥净后的空容器一并去掉——票拟输入里只留 ID、纪年与文字事实
    （P4：皇帝无表，票拟官也不看裸数）。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return None
    if isinstance(value, dict):
        cleaned = {
            key: stripped for key, item in value.items()
            if (stripped := _strip_bare_quantities(item)) is not None
        }
        return cleaned or None
    if isinstance(value, list):
        cleaned = [
            stripped for item in value
            if (stripped := _strip_bare_quantities(item)) is not None
        ]
        return cleaned or None
    return value


def _project_issue_qualitatively(issue: object) -> Optional[Dict[str, object]]:
    """单条 issue 的票拟输入侧定性投影（P4 / ADR 0143 唯一通道）。

    剥 gameplay 裸量：`局势走向` inertia、效果 delta、上月推进 delta_bar、待办
    数值进度（months_elapsed/paid_total/remaining 等）；保留契约所需 issue_id 与
    定性文字（状态档位、结案条件、推进叙事）。simulator 共用投影不动——只在票拟
    payload 出口收窄。
    """
    if not isinstance(issue, dict):
        return None
    row = dict(issue)
    row.pop("局势走向", None)
    for key in (*_EFFECT_KEYS, "commitment_progress"):
        if key in row:
            row[key] = _strip_bare_quantities(row[key])
    advance = row.get(_ADVANCE_KEY)
    if isinstance(advance, dict) and "delta_bar" in advance:
        adv = dict(advance)
        adv.pop("delta_bar", None)
        row[_ADVANCE_KEY] = adv
    return row


def build_rescript_draft_payload(
    state: GameState,
    narrative: str,
    simulator_payload: Dict[str, object],
    triage_actor: Dict[str, str],
) -> Dict[str, object]:
    """票拟生成 LLM 步的确定性输入（F1.3：零依赖 extractor 输出，只读盘面投影）。

    active_issues 取 simulator_payload 里已投影的一份再过票拟出口定性投影（0143
    输入侧投影唯一通道，issue_id 是权威绑定快照）；缺失时回空表并留痕（无盘面可
    投影＝无急务可选）。
    """
    raw_issues = simulator_payload.get("active_issues")
    if not isinstance(raw_issues, list):
        tlog("[rescript] simulator_payload 无 active_issues 投影，按空盘面处理。")
        raw_issues = []
    active_issues = [
        projected for projected in
        (_project_issue_qualitatively(issue) for issue in raw_issues)
        if projected is not None
    ]
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
        "target": {"min_items": 3, "max_items": MAX_RESCRIPT_DRAFTS},
    }


def validate_rescript_draft_items(
    data: object,
    board_issue_ids: set[int],
) -> List[Dict[str, object]]:
    """shape 校验（F2.2/F2.5 整批响亮降级的判据面）＋权威快照绑定＋原样不变式（F3.3）。

    - 顶层非法（非 dict / 无 items list）→ raise ValueError（整批降级，本月无头版）；
    - 任一条目必需字段缺失或非法（title/context 非空字符串 / options 非 2-3 项 /
      option.label/hint 非空字符串）→ raise ValueError 整批失败（冻结票面 F2.2/F2.5：
      不得保留合法项形成部分头版，不得把缺失洗成空串）；合法 `items=[]` 仍是
      「本月无急务」；
    - 自由文本零删改（CLAUDE.md P6 / F3.3）：strip 只作判空的临时值，落库一律原文；
    - 超出上限截前 MAX 条（确定性）；
    - event_id 只采信出现在权威盘面里的 issue_id 回指（bind 同款纪律）；其余留给
      落库层合成 `urgent:{turn}:{idx}`。
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("票拟生成输出顶层非法：须为 {\"items\":[...]}")

    def _required_text(item: Dict[str, object], field: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"票拟条目缺必需字段或为空白：{field}")
        return value  # 原样返回，零删改（F3.3）

    drafts: List[Dict[str, object]] = []
    for raw in data["items"]:
        if len(drafts) >= MAX_RESCRIPT_DRAFTS:
            break
        if not isinstance(raw, dict):
            raise ValueError("票拟条目非 object（整批失败，F2.5）")
        title = _required_text(raw, "title")
        context = _required_text(raw, "context")
        raw_opts = raw.get("options")
        if not isinstance(raw_opts, list) or not (2 <= len(raw_opts) <= 3):
            raise ValueError(f"票拟条目 options 非 2-3 项（整批失败，F2.2）：{title!r}")
        options: List[Dict[str, str]] = []
        for opt in raw_opts:
            if not isinstance(opt, dict):
                raise ValueError(f"票拟 option 非 object（整批失败，F2.2）：{title!r}")
            options.append({
                "label": _required_text(opt, "label"),
                "hint": _required_text(opt, "hint"),
            })
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
