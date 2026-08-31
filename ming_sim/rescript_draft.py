"""急务分拣＋票拟生成（#656 / ADR 0093 前半）：DECISION 待核议通道的邸报头版。

分拣人唯一规则（票面 F3.1，纯确定性读取现有 office/faction、不新增中立排序器）：
  1. 主分拣人＝内阁首辅（active 明臣 office LIKE '%首辅%'）；
  2. 缺位顶补＝司礼监掌印（office LIKE '%司礼监掌印%'；r2 裁决 B1：`%掌印%`
     会误吞御马监掌印等无关衙门掌印，角色破面——收窄为司礼监掌印）；
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
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import APIConnectionError, APIStatusError, APITimeoutError

from ming_sim.agents import run_agent_text
from ming_sim.assets import strip_json_fence
from ming_sim.llm_model import llm_unavailable_from_error
from ming_sim.db import GameDB
from ming_sim.decree_vocabulary import (
    RESCRIPT_ROUTABLE_ACTION_TYPES,
    TARGET_KINDS,
    _DRAFT_CAPABILITY_KEYS,
    derive_draft_capability,
)
from ming_sim.error_pack import error_packs_root
from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.models import GameState, reign_period_label
from ming_sim.token_stats import tlog

MAX_RESCRIPT_DRAFTS = 5

# #657 C.3 层 A option 必填键（缺一 shape 失败）；draft_capability 由服务端派生写入。
_LAYER_A_REQUIRED_KEYS = (
    "label", "hint", "action_type", "target_kind", "target_id", "locality_scope",
)
_LAYER_A_PRESENT_KEYS = (
    "assignee_name", "region_id", "transaction_category",
)
_LOCALITY_SCOPES = frozenset({"national", "single", "none"})
_LOCALITY_ALIASES = {
    "全国": "national", "全域": "national",
    "单地": "single", "一地": "single",
    "无": "none", "无属地": "none",
}


# 层 A 允许键 = C.3 必填/须在 + C.4 闭集 + draft_capability（服务端覆盖，LLM 自带不准）
_LAYER_A_ALLOWED_KEYS = frozenset(
    list(_LAYER_A_REQUIRED_KEYS)
    + list(_LAYER_A_PRESENT_KEYS)
    + [key for key, _default in _DRAFT_CAPABILITY_KEYS]
    + ["draft_capability"]
)


def normalize_stop_condition(raw: object) -> str:
    """stop_condition 唯一保真缝（C.6）：仅 str 原文；None/空白→""；dict/list/其它→ValueError。

    供层 A normalize / choice 规范化 / mapper 共用——禁止平行拷贝。
    非空不 strip 落库（strip 只可在 until_stop 判空临时用）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        if not raw.strip():
            return ""
        return raw
    raise ValueError(
        f"stop_condition 须为 str（C.6），拒 {type(raw).__name__}"
    )


def normalize_rescript_layer_a_option(raw: object) -> Dict[str, object]:
    """#657 层 A option shape 校验 + 服务端写 draft_capability（生产票拟/改票单真源）。

    自由文本（label/hint 等）strip 只作判空临时值，落库原文；
    draft_capability 一律服务端重算覆盖，禁止 LLM 自带为准。
    """
    if not isinstance(raw, dict):
        raise ValueError("票拟 option 非 object（层 A shape）")
    unknown = set(raw) - _LAYER_A_ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"票拟 option 含未知字段（整批 shape 错，F2.5/F3.3）：{sorted(unknown)}"
        )
    out: Dict[str, object] = {}
    for key in _LAYER_A_REQUIRED_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not str(value).strip():
            raise ValueError(f"票拟 option 缺层 A 必填键或为空白：{key}")
        out[key] = str(value)  # 原文；strip 仅判空
    action_type = str(out["action_type"]).strip()
    if action_type not in RESCRIPT_ROUTABLE_ACTION_TYPES:
        raise ValueError(f"票拟 option.action_type 非七类 routable：{action_type!r}")
    out["action_type"] = action_type
    target_kind = str(out["target_kind"]).strip()
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"票拟 option.target_kind 非法：{target_kind!r}")
    out["target_kind"] = target_kind
    scope_raw = str(out["locality_scope"]).strip()
    scope = _LOCALITY_ALIASES.get(scope_raw, scope_raw)
    if scope not in _LOCALITY_SCOPES:
        raise ValueError(f"票拟 option.locality_scope 非法：{scope_raw!r}")
    out["locality_scope"] = scope
    # C.3：三键必须在且为 str（可 ""）；禁缺键补全 / None→"" / str(value) 洗值
    for key in _LAYER_A_PRESENT_KEYS:
        if key not in raw:
            raise ValueError(f"票拟 option 缺层 A 须在键：{key}")
        value = raw[key]
        if not isinstance(value, str):
            raise ValueError(
                f"票拟 option.{key} 须为 str（可空串），拒 {type(value).__name__}"
            )
        out[key] = value
    # 其余 capability 闭集字段透传（有则规范化，无则由 derive 填默认）
    for key, _default in (
        ("name", ""), ("title", ""), ("commitment_kind", ""),
        ("station", ""), ("office", ""),
        ("grant_action", ""), ("account", ""), ("purpose", ""), ("cadence", ""),
        ("execution_surface", ""), ("appoint_action", ""),
        ("appointment_tenure", ""), ("punish_action", ""),
        ("privilege", ""), ("summon_target", ""),
    ):
        if key in raw and raw[key] is not None:
            out[key] = str(raw[key])
    if "stop_condition" in raw and raw["stop_condition"] is not None:
        out["stop_condition"] = normalize_stop_condition(raw["stop_condition"])
    # #1620：grant amount 不走通用 int()——由 require_grant_allocation_shape 独掌
    # （strict_int 拒 bool/float）；非 grant 整数字段维持既有 int()。
    int_keys = ("end_turn", "deadline_months", "due_turn")
    if action_type != "grant_allocation":
        int_keys = (*int_keys, "amount")
    for key in int_keys:
        if key in raw and raw[key] is not None and raw[key] != "":
            try:
                out[key] = int(raw[key])  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"票拟 option.{key} 非法：{raw[key]!r}") from exc
    # #1620：grant 金额/account 走 require_grant_allocation_shape 唯一权威（与 mapper 同缝），
    # 禁残缺 option 上桌；空 account 不回写默认，免 draft_capability 漂移；
    # 非空 account 回写 shape 返回的 canonical（太仓→国库），与显式国库同 capability。
    # amount 传 raw 原值；用返回值写 out["amount"]（honorific 无则不写）。
    if action_type == "grant_allocation":
        from ming_sim.action_materialize import require_grant_allocation_shape

        input_account = str(out.get("account") or "").strip()
        shaped = require_grant_allocation_shape(
            grant_action=out.get("grant_action"),
            amount=raw.get("amount") if "amount" in raw else None,
            account=out.get("account"),
        )
        if "amount" in shaped:
            out["amount"] = shaped["amount"]
        if input_account:
            out["account"] = shaped["account"]
    out["draft_capability"] = derive_draft_capability(out)
    return out


def select_triage_actor(db: GameDB) -> Optional[Dict[str, str]]:
    """F3.1 唯一分拣人选择规则：首辅优先、司礼监掌印顶补、重复命中取第一、双双缺位回 None。

    r2 裁决 B1（票面 F3.1「司礼监掌印」明文＋P3 角色保真）：兜底不得用宽模式
    `%掌印%`——御马监掌印太监与票拟/批红职权无关，不得成为分拣 actor。
    """
    for office_pattern in ("%首辅%", "%司礼监掌印%"):
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


_TOP_ALLOWED_KEYS = frozenset({"items"})
_ITEM_ALLOWED_KEYS = frozenset({"title", "context", "options", "issue_id"})


def _assert_utf8(s: str, field: str) -> None:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as exc:  # noqa: BLE001
        raise ValueError(
            f"票拟字段含 SQLite 不可编码字符（整批 shape 错，F2.5）：{field} {exc}"
        ) from exc


def _parse_rescript_json_strict(raw: str) -> Dict[str, Any]:
    # r4 P1：围栏外 prose 必须走整批 shape 降级——容忍恰好覆盖全响应的单层围栏，
    # 围栏外任何非空白字符 → LLMContractError 整批降级；不得改 strip_json_fence 全局语义。
    match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if match:
        before = raw[: match.start()]
        after = raw[match.end() :]
        if before.strip() or after.strip():
            raise LLMContractError(
                f"急务票拟生成 输出含围栏外文字（整批 shape 错，F2.5）：围栏外含 prose，按票面应走整批降级\n原始输出：{raw[:800]}"
            )
        text = match.group(1).strip()
    else:
        text = raw.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMContractError(
            f"急务票拟生成 输出不是合法 JSON：{exc}\n原始输出：{raw[:800]}"
        ) from exc
    if not isinstance(data, dict):
        raise LLMContractError(
            f"急务票拟生成 输出不是合法 JSON：顶层必须是 JSON object\n原始输出：{raw[:800]}"
        )
    return data

_RESCRIPT_ISSUE_TEXT_FIELDS = ("title", "状态", "进度", "待办未解进度")


def _project_issue_qualitatively(issue: object) -> Optional[Dict[str, object]]:
    """单条 issue 的票拟输入侧定性投影（P4 / ADR 0142/0143 唯一通道）。

    字段白名单收窄（#656 A4 判词边界）：只携绑定所需 issue_id 与明确的定性/叙事
    文字字段；resolve_condition/fail_condition/stop_condition（含「结案条件」「失败
    条件」别名）等机器契约字段一律不进票拟输入——机器阈值串（如 seed_events 的
    public_support >60 / unrest <30）随所属字段整体消失，不做任何字符串内扫描/
    解析/替换。白名单外的未知字段（含任意嵌套结构）不透传——删除「任意字符串全
    透传」的根因。simulator 共用投影不动——只在票拟 payload 出口收窄。
    """
    if not isinstance(issue, dict):
        return None
    row: Dict[str, object] = {}
    if "issue_id" in issue:
        row["issue_id"] = issue["issue_id"]
    for field in _RESCRIPT_ISSUE_TEXT_FIELDS:
        value = issue.get(field)
        if isinstance(value, str) and value.strip():
            row[field] = value
    return row or None


def _project_region_targets(table: object) -> List[Dict[str, str]]:
    """Project the simulator's canonical typed region table into the target catalog."""
    return _project_board_targets(
        table,
        fields=("id", "name", "kind"),
        required=("id", "name", "kind"),
        label="region",
    )


def _project_army_targets(table: object) -> List[Dict[str, str]]:
    """Project Ming-controlled armies from the simulator's full army board."""
    armies = _project_board_targets(
        table,
        fields=("id", "name", "station", "owner_power"),
        required=("id", "name", "owner_power"),
        label="army",
    )
    return [
        {field: army[field] for field in ("id", "name", "station")}
        for army in armies
        if army["owner_power"] == "ming"
    ]


def _project_board_targets(
    table: object,
    *,
    fields: tuple[str, ...],
    required: tuple[str, ...],
    label: str,
) -> List[Dict[str, str]]:
    if table is None:
        return []
    try:
        cols = table["cols"]  # type: ignore[index]
        rows = table["rows"]  # type: ignore[index]
        indexes = {field: cols.index(field) for field in fields}
        targets = []
        for row in rows:
            if not isinstance(row, list):
                raise ValueError(f"canonical {label} target row 非 list：{row!r}")
            target = {}
            for field, index in indexes.items():
                value = row[index]
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"canonical {label} target {field} 非字符串：{value!r}"
                    )
                target[field] = (value or "").strip()
            targets.append(target)
        if any(not target[field] for target in targets for field in required):
            raise ValueError(f"canonical {label} target 含空 {'/'.join(required)}")
        return targets
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"canonical {label} target table 畸形") from exc


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
    # #1620：grant_action 闭集与 Layer-A GRANT_ACTIONS 同源，注入生成契约禁同义动作名。
    from ming_sim.action_materialize import GRANT_ACTIONS

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
        "region_targets": _project_region_targets(simulator_payload.get("regions")),
        "army_targets": _project_army_targets(simulator_payload.get("armies")),
        "grant_actions": sorted(GRANT_ACTIONS - {"无"}),
        "target": {"min_items": 3, "max_items": MAX_RESCRIPT_DRAFTS},
    }


def validate_rescript_draft_items(
    data: object,
    board_issue_ids: set[int],
) -> List[Dict[str, object]]:
    """shape 校验（F2.2/F2.5 整批响亮降级的判据面）＋权威快照绑定＋原样不变式（F3.3）。

    - 顶层非法（非 dict / 无 items list）→ raise ValueError（整批降级，本月无头版）；
    - 任一条目必需字段缺失或非法（title/context 非空字符串 / options 非 2-3 项 /
      option 须过层 A 单真源 normalize）→ raise ValueError 整批失败（F2.2/F2.5：
      不得保留合法项形成部分头版，不得把缺失洗成空串）；合法 `items=[]` 仍是
      「本月无急务」；
    - 自由文本零删改（CLAUDE.md P6 / F3.3）：strip 只作判空的临时值，落库一律原文；
    - option 经 normalize_rescript_layer_a_option：C.3 必填 + C.4 闭集；
      draft_capability 服务端重算；未知键响亮失败（不再接受仅 label/hint 两键）；
    - 处理条目前先校验 items 总数：超过 MAX_RESCRIPT_DRAFTS 即 raise ValueError
      整批响亮降级（#656 A1：不截断、不静默丢弃后项、不保留前五条，F2.5）；
    - item 层白名单外未知字段 → raise ValueError 整批失败（r2 B2）；
      issue_id 是唯一豁免的可选绑定键；
    - event_id 只采信出现在权威盘面里的 issue_id 回指（bind 同款纪律）；其余留给
      落库层合成 `urgent:{turn}:{idx}`。
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("票拟生成输出顶层非法：须为 {\"items\":[...]}")
    unknown_top = set(data) - _TOP_ALLOWED_KEYS
    if unknown_top:
        raise ValueError(
            f"票拟顶层含未知字段（整批 shape 错，F2.5/F3.3）：{sorted(unknown_top)}"
        )
    items = data["items"]
    if len(items) > MAX_RESCRIPT_DRAFTS:
        raise ValueError(
            f"票拟条目超上限：{len(items)} 条 > {MAX_RESCRIPT_DRAFTS}（整批失败，F2.5）"
        )

    def _required_text(item: Dict[str, object], field: str) -> str:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"票拟条目缺必需字段或为空白：{field}")
        _assert_utf8(value, field)
        return value  # 原样返回，零删改（F3.3）

    drafts: List[Dict[str, object]] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("票拟条目非 object（整批失败，F2.5）")
        unknown = set(raw) - _ITEM_ALLOWED_KEYS
        if unknown:
            raise ValueError(
                f"票拟条目含未知字段（整批 shape 错，F2.5/F3.3 零删改不静默省略）：{sorted(unknown)}"
            )
        title = _required_text(raw, "title")
        context = _required_text(raw, "context")
        raw_opts = raw.get("options")
        if not isinstance(raw_opts, list) or not (2 <= len(raw_opts) <= 3):
            raise ValueError(f"票拟条目 options 非 2-3 项（整批失败，F2.2）：{title!r}")
        options: List[Dict[str, object]] = []
        for opt in raw_opts:
            if not isinstance(opt, dict):
                raise ValueError(f"票拟 option 非 object（整批失败，F2.2）：{title!r}")
            # 层 A 单真源：完整 option + 服务端 draft_capability
            try:
                normalized_opt = normalize_rescript_layer_a_option(opt)
            except ValueError as exc:
                raise ValueError(
                    f"票拟 option 层 A shape 失败（整批失败，F2.2/F2.5）：{title!r} {exc}"
                ) from exc
            # 自由文本 UTF-8 可编码性（label/hint 原文）
            _assert_utf8(str(normalized_opt.get("label") or ""), "label")
            _assert_utf8(str(normalized_opt.get("hint") or ""), "hint")
            options.append(normalized_opt)
        # options_json 序列化前再校验 ensure_ascii=False 场景的可编码性
        try:
            json.dumps(options, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError as exc:  # noqa: BLE001
            raise ValueError(
                f"票拟字段含 SQLite 不可编码字符（整批 shape 错，F2.5）：options {exc}"
            ) from exc
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


def _assert_region_targets_grounded(
    drafts: List[Dict[str, object]], region_target_ids: set[str]
) -> None:
    for draft in drafts:
        for option in draft["options"]:  # type: ignore[union-attr]
            if option["target_kind"] == "region" \
                    and option["target_id"] not in region_target_ids:
                raise ValueError(
                    f"票拟 option.target_id 不在同批 region_targets：{option['target_id']!r}"
                )


def _assert_army_targets_grounded(
    drafts: List[Dict[str, object]], army_target_ids: set[str]
) -> None:
    for draft in drafts:
        for option in draft["options"]:  # type: ignore[union-attr]
            if option["action_type"] == "military_order" \
                    and option["target_kind"] != "army":
                raise ValueError("票拟 military_order 的 target_kind 须为 army")
            if option["target_kind"] == "army" \
                    and option["target_id"] not in army_target_ids:
                raise ValueError(
                    f"票拟 option.target_id 不在同批 army_targets：{option['target_id']!r}"
                )
            if option["action_type"] == "military_order" \
                    and not str(option.get("assignee_name") or "").strip():
                raise ValueError("票拟 military_order 缺 assignee_name")


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
    """phase2 fan-out 第 N+1 路（N=同池 extractor 模块数）：跑一次票拟生成 LLM 调用并校验 shape。

    响亮降级契约（F2.5）按错误归属拆缝（r2 裁决 B3 / ADR 0005 / relation_brew 同款
    先例）：业务降级面只收声明类型——LLM 调用缝只收 typed LLMUnavailable；解析/shape
    校验缝只收 LLMContractError/ValueError。命中即 tlog 留痕＋诊断目录附记，返回 None，
    本月视作无头版。程序错（RuntimeError/KeyError/TypeError 等）**响亮上抛**——票拟
    业务降级 ≠ 代码故障降级，不再以「非承重支路」为由吞程序错误。
    """
    # payload 序列化是纯程序逻辑：其错误属代码侧错（ADR 0005），不在降级面内，响亮上抛。
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    tlog(f"[rescript] user payload total={len(payload_json)} chars (~{len(payload_json)//1.5:.0f} tok)")

    def _degrade(exc: Exception) -> None:
        tlog(f"[rescript] 票拟生成失败，本月视作无头版：{exc}")
        _write_degraded_note(turn, str(exc))

    try:
        raw = run_agent_text(agent, payload_json, tag="rescript-draft")
    except (APITimeoutError, APIConnectionError, APIStatusError) as error:  # 窄捕 provider 已知故障→译 typed（照抄 decree.py:1991 Z3 缝）
        _degrade(llm_unavailable_from_error(error, "急务票拟生成"))
        return None
    except LLMUnavailable as exc:  # LLM 调用缝：只收 typed 声明，程序错上抛
        _degrade(exc)
        return None
    try:
        data = _parse_rescript_json_strict(raw)
        region_targets = payload.get("region_targets")
        region_target_ids = {
            str(row["id"]) for row in region_targets
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        } if isinstance(region_targets, list) else set()
        army_targets = payload.get("army_targets")
        army_target_ids = {
            str(row["id"]) for row in army_targets
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        } if isinstance(army_targets, list) else set()
        drafts = validate_rescript_draft_items(
            data, _board_issue_ids(payload.get("active_issues"))
        )
        _assert_region_targets_grounded(drafts, region_target_ids)
        _assert_army_targets_grounded(drafts, army_target_ids)
    except (LLMContractError, ValueError) as exc:  # 解析/shape 缝：只收契约违约
        _degrade(exc)
        return None
    tlog(f"[rescript] 票拟生成 {len(drafts)} 条。")
    return drafts
