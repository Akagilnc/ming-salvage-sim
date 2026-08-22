"""设定加载：把 content/*.json 与 content/prompts/*.md 收进 GameContent。L2。

GameContent.load() 显式调用——模块导入本身不读盘、无副作用。
设定文件是唯一来源（CLAUDE.md），代码不硬编码副本。
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from ming_sim.assets import (
    int_field,
    load_json_asset,
    load_text_asset,
    require_dict,
    require_list,
    str_field,
    string_list,
)
from ming_sim.constants import (
    ARMY_TEXT_FIELDS,
    BUILDING_CATEGORIES,
    BUILDING_OUTPUT_METRICS,
    GATE_AGG_FUNCS,
    GATE_METRIC_KEYS,
    GATE_TABLES,
    CHARACTER_TEXT_FIELDS,
    POWER_TEXT_FIELDS,
    REGION_TEXT_FIELDS,
)

# 文本相等 gate 可比的字段（按表）——runtime _eval_gate_key_str 取 str(row[字段])，
# 文本 cond 配数值字段会得 "50"!=ming 永远 False，故限定为各表 TEXT 字段（#12 cmr r3 codex）。
_GATE_TEXT_FIELDS = {
    "region": set(REGION_TEXT_FIELDS),
    "army": set(ARMY_TEXT_FIELDS),
    "power": set(POWER_TEXT_FIELDS),
    "character": set(CHARACTER_TEXT_FIELDS),
    "event": {"terminal_state", "terminal_reason"},
}
from ming_sim.models import (
    Army,
    Building,
    Character,
    Event,
    Faction,
    OpeningLegacy,
    Power,
    Region,
    SocialClass,
)


# --- 单项加载器（保留原签名，便于复用与单测）---

def load_character_content() -> Tuple[Dict[str, Faction], Dict[str, Character]]:
    data = require_dict(load_json_asset("characters.json"), "characters.json")
    factions: Dict[str, Faction] = {}
    for idx, raw in enumerate(require_list(data.get("factions"), "characters.json.factions"), 1):
        item = require_dict(raw, f"characters.json.factions[{idx}]")
        name = str_field(item, "name", f"characters.json.factions[{idx}]")
        factions[name] = Faction(
            name=name,
            satisfaction=int_field(item, "satisfaction", f"characters.json.factions[{idx}]"),
            leverage=int_field(item, "leverage", f"characters.json.factions[{idx}]"),
            agenda=str_field(item, "agenda", f"characters.json.factions[{idx}]"),
        )

    characters: Dict[str, Character] = {}
    for idx, raw in enumerate(require_list(data.get("characters"), "characters.json.characters"), 1):
        item = require_dict(raw, f"characters.json.characters[{idx}]")
        path = f"characters.json.characters[{idx}]"
        name = str_field(item, "name", f"characters.json.characters[{idx}]")
        character_fields = dict(item)
        character_fields.setdefault("identity", 50)
        identity = int_field(character_fields, "identity", path)
        if not 0 <= identity <= 100:
            raise SystemExit(f"设定字段超出范围：{path}.identity（应为 0–100）")
        seed_guilt_raw = item.get("seed_guilt")
        if seed_guilt_raw is None:
            seed_guilt_raw = {}
        if not isinstance(seed_guilt_raw, dict):
            raise SystemExit(f"{path}.seed_guilt 必须是 JSON 对象。")
        if seed_guilt_raw and set(seed_guilt_raw) != {"crime", "severity"}:
            raise SystemExit(
                f"设定字段结构非法：{path}.seed_guilt（仅允许 crime、severity）"
            )
        seed_guilt_fields = dict(seed_guilt_raw)
        seed_guilt_fields.setdefault("crime", "")
        seed_guilt_fields.setdefault("severity", "无")
        seed_guilt_context = f"characters.json.characters[{idx}].seed_guilt"
        crime_raw = seed_guilt_fields["crime"]
        if not isinstance(crime_raw, str):
            raise SystemExit(f"设定字段应为字符串：{seed_guilt_context}.crime")
        if not crime_raw.strip() and seed_guilt_fields["severity"] != "无":
            raise SystemExit(f"设定字段应为非空字符串：{seed_guilt_context}.crime")
        seed_guilt = {
            "crime": crime_raw.strip(),
            "severity": str_field(seed_guilt_fields, "severity", seed_guilt_context),
        }
        if seed_guilt["severity"] not in {"无", "轻", "中", "重"}:
            raise SystemExit(
                f"characters.json.characters[{idx}].seed_guilt.severity 非法："
                f"{seed_guilt['severity']!r}（仅无/轻/中/重）。"
            )
        if not seed_guilt_raw:
            seed_guilt = {}
        if name in characters:
            raise SystemExit(f"characters.json 不得存在重复人物名：{name}")
        characters[name] = Character(
            name=name,
            office=str_field(item, "office", f"characters.json.characters[{idx}]"),
            office_type=str_field(item, "office_type", f"characters.json.characters[{idx}]"),
            faction=str_field(item, "faction", f"characters.json.characters[{idx}]"),
            aliases=string_list(item.get("aliases", []), f"characters.json.characters[{idx}].aliases"),
            personal_skills=string_list(item.get("personal_skills"), f"characters.json.characters[{idx}].personal_skills"),
            loyalty=int_field(item, "loyalty", f"characters.json.characters[{idx}]"),
            ability=int_field(item, "ability", f"characters.json.characters[{idx}]"),
            integrity=int_field(item, "integrity", f"characters.json.characters[{idx}]"),
            courage=int_field(item, "courage", f"characters.json.characters[{idx}]"),
            style=str_field(item, "style", f"characters.json.characters[{idx}]"),
            power_id=str_field(item, "power_id", f"characters.json.characters[{idx}]"),
            location=str(item.get("location") or "").strip(),
            transit_to=str(item.get("transit_to") or "").strip(),
            birth_year=int(item.get("birth_year") or 0),
            historical_death_year=int(item.get("historical_death_year") or 0),
            historical_death_month=int(item.get("historical_death_month") or 0),
            debut_year=int(item.get("debut_year") or 0),
            debut_month=int(item.get("debut_month") or 0),
            status=str(item.get("status") or "active"),
            status_reason=str(item.get("status_reason") or "").strip(),
            reason_code=str(item.get("reason_code") or "").strip(),
            summary=str(item.get("summary") or ""),
            portrait_id=str(item.get("portrait_id") or ""),
            identity=identity,
            seed_guilt=seed_guilt,
        )

    names_and_aliases_by_faction: Dict[str, Set[str]] = {}
    for character in characters.values():
        for name_or_alias in (character.name, *character.aliases):
            names_and_aliases_by_faction.setdefault(name_or_alias, set()).add(
                character.faction
            )
    cross_faction_names_or_aliases = sorted(
        name_or_alias
        for name_or_alias, factions_for_name_or_alias in names_and_aliases_by_faction.items()
        if len(factions_for_name_or_alias) > 1
    )
    if cross_faction_names_or_aliases:
        raise SystemExit(
            "characters.json 不得存在跨派别人物名或别名："
            + "、".join(cross_faction_names_or_aliases)
        )

    if not factions or not characters:
        raise SystemExit("characters.json 必须至少定义一个派系和一个人物。")
    return factions, characters


def gate_cond_form_error(cond: str) -> str:
    """trigger_gate 比较式形态校验（#12 Q3 fail-loud）。合法→""；非法→错误说明。
    **精确镜像 runtime _gate_passed 两分支**（cmr r1 Claude+codex concur）：
    - 文本比较：(==|!=) + 非纯数字 RHS；或 in=a|b；
    - 数值比较：(>=|<=|>|<|==) + 整数（runtime 数值分支**不含 !=**——故 '!=5' 数值不许，
      否则 load 放行而 runtime 永远 False，ADR 0012 残留 4b②对齐）。"""
    cond = cond.strip()
    sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond)
    if sm and (sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())):
        return ""
    if re.match(r"^(>=|<=|>|<|==)\s*-?\d+$", cond):  # 数值（无 !=，同 runtime）
        return ""
    return f"{cond!r}（应形如 '<=240' / '>=34' 数值，或 '==ming' / '!=houjin' / 'in=a|b' 文本比较）"


def gate_key_form_error(key: str) -> str:
    """trigger_gate key 形态校验（#12 Q3 fail-loud，ADR 0012 残留 4b①）。合法→""；非法→错误说明。
    bare key（无 "."）须是已知 metric；点分 key 首段须是合法表名、结构完整（去末段聚合后 ≥3 段）。
    字段名(列)是否存在由 _eval_gate_key 运行期对 DB schema 兜底（content load 无 DB 不校验列）。"""
    if "." not in key:
        if key not in GATE_METRIC_KEYS:
            return f"未知 metric「{key}」（须 {'/'.join(GATE_METRIC_KEYS)} 之一，或用 表.id.字段 形式）"
        return ""
    parts = key.split(".")
    if parts[0] not in GATE_TABLES:
        return f"未知表「{parts[0]}」（须 {'/'.join(GATE_TABLES)} 之一）"
    if parts[-1] in GATE_AGG_FUNCS:
        parts = parts[:-1]
    if len(parts) < 3:
        return "结构不完整（应形如 表.id.字段[.聚合]）"
    # 拒空段（cmr r1 codex）：空 id / 空字段 / | 列表含空成员 → 静默不达标或 SQL 崩，须 fail-loud
    field = parts[-1]
    id_segment = ".".join(parts[1:-1])
    if not field.strip() or not id_segment.strip():
        return "id 或 字段 为空"
    if any(not m.strip() for m in id_segment.split("|")):
        return "id 列表含空成员（| 分隔）"
    # class.<名>[@<region>] 成员校验（cmr r2/online concur）：类名（@ 前）非空；带 @ 者 region
    # （@ 后）也须非空——空 region 的 @ 是「想写 regional 却漏 region」的 malformed regional gate，
    # runtime 会静默回退 national class 行（应 fail-loud；online codex P2）。national 用无 @ 形式。
    if parts[0] == "class":
        for member in id_segment.split("|"):
            if not member.split("@", 1)[0].strip():
                return "class 名为空（@ 前）"
            if "@" in member and not member.split("@", 1)[1].strip():
                return "class @ 后 region 为空（regional gate 须指定 region；national 用无 @ 形式）"
    if parts[0] == "event" and field != "triggered":
        return "event 数值 gate 仅支持 triggered 字段（形如 event.<event_id>.triggered）；文本 gate 用 terminal_state/terminal_reason"
    return ""


def gate_text_key_form_error(key: str) -> str:
    """文本相等（==/!=非数字）gate 的 key 形态校验（#12 cmr r2 codex）。合法→""；非法→错误说明。
    runtime _eval_gate_key_str 仅支持单 id 的 region/army/power 三段文本字段——故文本 cond 配
    多 id/聚合/class/faction/building/bare-metric key 会 load 放行而 runtime 静默返 None（永不达标）。
    本 PR 首次放行文本 cond 入 load → 须配对校验 key 为文本可求值形态，否则 fail-loud。"""
    parts = key.split(".")
    if len(parts) != 3:
        return "文本相等 gate 的 key 须 表.id.字段 三段（不支持多 id / 聚合 / bare metric）"
    if parts[0] not in _GATE_TEXT_FIELDS:  # 文本可求值表（复用中央 _GATE_TEXT_FIELDS keys，非硬编码）
        return f"文本相等 gate 仅支持 {'/'.join(_GATE_TEXT_FIELDS)} 表，得「{parts[0]}」"
    if "|" in parts[1]:  # _eval_gate_key_str 仅单 id（| 多 id 在段内不增 "." 段数，须单独拒）
        return "文本相等 gate 不支持多 id（| 分隔）"
    if not parts[1].strip() or not parts[2].strip():
        return "id 或 字段 为空"
    if parts[2] not in _GATE_TEXT_FIELDS[parts[0]]:  # 文本 cond 须配文本字段，否则永远 False
        return f"「{parts[2]}」非 {parts[0]} 文本字段（文本相等仅可比 {'/'.join(sorted(_GATE_TEXT_FIELDS[parts[0]]))}）"
    return ""


def gate_cond_is_text(cond: str) -> bool:
    """cond 是否文本比较（==/!= 非数字 RHS，或 in=a|b）——与 runtime _gate_passed 文本分支同判。"""
    sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond.strip())
    return bool(sm and (sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())))


def load_event_content(filename: str = "events.json") -> List[Event]:
    events: List[Event] = []
    for idx, raw in enumerate(require_list(load_json_asset(filename), filename), 1):
        item = require_dict(raw, f"{filename}[{idx}]")
        event_type = str(item.get("event_type") or "situation")
        if event_type not in ("situation", "node", "ending"):
            raise SystemExit(
                f"{filename}[{idx}] event_type 非法：{event_type!r}（仅 situation/node/ending）。"
            )
        trigger_class = str(item.get("trigger_class") or "").strip()
        if trigger_class not in ("", "strategic_foreign"):
            raise SystemExit(
                f"{filename}[{idx}] trigger_class 非法：{trigger_class!r}（仅 strategic_foreign 或空）。"
            )
        if trigger_class == "strategic_foreign" and event_type == "situation":
            raise SystemExit(
                f"{filename}[{idx}] trigger_class=strategic_foreign 仅适用于 node/ending，situation 不可声明。"
            )
        trigger_year = int(item.get("trigger_year") or 0)
        trigger_month = int(item.get("trigger_month") or 0)
        trigger_end_year = int(item.get("trigger_end_year") or 0)
        trigger_end_month = int(item.get("trigger_end_month") or 0)
        if not (0 <= trigger_month <= 12):
            raise SystemExit(f"{filename}[{idx}] trigger_month 必须在 0 到 12 之间。")
        if not (0 <= trigger_end_month <= 12):
            raise SystemExit(f"{filename}[{idx}] trigger_end_month 必须在 0 到 12 之间。")
        open_window_raw = item.get("open_window", False)
        if not isinstance(open_window_raw, bool):
            raise SystemExit(f"{filename}[{idx}] open_window 必须是 JSON boolean。")
        open_window = open_window_raw
        if trigger_year > 0 and trigger_end_year <= 0 and not open_window:
            raise SystemExit(
                f"{filename}[{idx}] 历史锚定事件必须显式声明 trigger_end_year 或 open_window。"
            )
        if trigger_year > 0 and trigger_end_year > 0 and not open_window:
            start = (trigger_year, trigger_month or 1)
            end = (trigger_end_year, trigger_end_month or 12)
            if end < start:
                raise SystemExit(f"{filename}[{idx}] 事件窗口非法：最晚时点早于最早时点。")
        terminal_reason_labels = (
            string_list(item["terminal_reason_labels"], f"{filename}[{idx}].terminal_reason_labels")
            if "terminal_reason_labels" in item else []
        )
        default_terminal_reason = str(item.get("default_terminal_reason") or "").strip()
        if default_terminal_reason and default_terminal_reason not in terminal_reason_labels:
            raise SystemExit(
                f"{filename}[{idx}] default_terminal_reason={default_terminal_reason!r} "
                "不在 terminal_reason_labels 白名单内。"
            )
        gate_raw = item.get("trigger_gate") or {}
        if not isinstance(gate_raw, dict):
            raise SystemExit(f"{filename}[{idx}] trigger_gate 必须是对象（key→比较式）。")
        trigger_gate: Dict[str, str] = {}
        # key 形式见 issues._eval_gate_key：metric 名、region.<id>.<field>、army.<id>.<field>、
        # building.<id>.<field>、power.<id>.<field>、class.<name>[@<region>].<field>，
        # 多 id 用 | 分隔时末段 .<agg>(max/min/avg/sum)。
        # load 校验 key 形态(metric/表名/结构)+比较式形态(数值/文本相等)，fail-loud（#12 Q3）；
        # 字段名(列)是否存在由求值器运行期对 DB schema 兜底（load 无 DB）。
        for mk, mv in gate_raw.items():
            cond = str(mv).strip()
            cond_err = gate_cond_form_error(cond)
            if cond_err:
                raise SystemExit(f"{filename}[{idx}] trigger_gate['{mk}'] 比较式非法：{cond_err}。")
            # 文本相等 cond 须配文本可求值的 key（单 id region/army/power 三段）；否则 runtime
            # 静默永不达标（cmr r2 codex）。数值 cond 走通用 key 形态校验。
            key_err = (gate_text_key_form_error(str(mk)) if gate_cond_is_text(cond)
                       else gate_key_form_error(str(mk)))
            if key_err:
                raise SystemExit(f"{filename}[{idx}] trigger_gate key「{mk}」非法：{key_err}。")
            trigger_gate[str(mk)] = cond
        events.append(
            Event(
                id=str_field(item, "id", f"{filename}[{idx}]"),
                title=str_field(item, "title", f"{filename}[{idx}]"),
                kind=str_field(item, "kind", f"{filename}[{idx}]"),
                summary=str_field(item, "summary", f"{filename}[{idx}]"),
                urgency=int_field(item, "urgency", f"{filename}[{idx}]"),
                severity=int_field(item, "severity", f"{filename}[{idx}]"),
                credibility=int_field(item, "credibility", f"{filename}[{idx}]"),
                interests=string_list(item.get("interests"), f"{filename}[{idx}].interests"),
                audiences=string_list(item.get("audiences"), f"{filename}[{idx}].audiences"),
                resolve_condition=str(item.get("resolve_condition") or ""),
                fail_condition=str(item.get("fail_condition") or ""),
                trigger_year=trigger_year,
                trigger_month=trigger_month,
                trigger_end_year=trigger_end_year,
                trigger_end_month=trigger_end_month,
                open_window=open_window,
                precondition=str(item.get("precondition") or ""),
                event_type=event_type,
                trigger_class=trigger_class,
                category=str(item.get("category") or "").strip(),
                person_core_subjects=(
                    string_list(item["person_core_subjects"], f"{filename}[{idx}].person_core_subjects")
                    if "person_core_subjects" in item else []
                ),
                trigger_gate=trigger_gate,
                auto_trigger=bool(item.get("auto_trigger") or False),
                terminal_reason_labels=terminal_reason_labels,
                default_terminal_reason=default_terminal_reason,
                bar_value=int(item.get("bar_value") or 0),
                bar_good_meaning=str(item.get("bar_good_meaning") or ""),
                bar_bad_meaning=str(item.get("bar_bad_meaning") or ""),
                issue_inertia=int(item.get("inertia") or 0),
                stage_text=str(item.get("stage_text") or ""),
                region_hint=str(item.get("region_hint") or ""),
                issue_tags=string_list(item.get("tags"), f"{filename}[{idx}].tags") if item.get("tags") else [],
                ongoing_effects=dict(item.get("ongoing_effects") or {}),
                effect_on_trigger=dict(item.get("effect_on_trigger") or {}),
                effect_on_resolve=dict(item.get("effect_on_resolve") or {}),
                effect_on_fail=dict(item.get("effect_on_fail") or {}),
            )
        )
    if not events:
        raise SystemExit(f"{filename} 必须至少定义一个事件。")
    return events


def _deep_merge_content_defaults(defaults: Dict[str, object], overrides: Dict[str, object]) -> Dict[str, object]:
    merged = copy.deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_content_defaults(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _normalize_settle_meta_defaults(
    fiscal_raw: Dict[str, object],
    settle_meta_defaults: Dict[str, object],
    ctx: str,
) -> Dict[str, object]:
    fiscal = dict(fiscal_raw)
    settle_raw = fiscal.get("settle")
    if not isinstance(settle_raw, dict):
        return fiscal

    meta_raw = settle_raw.get("_meta", {})
    if meta_raw is None:
        meta_raw = {}
    if not isinstance(meta_raw, dict):
        raise SystemExit(f"{ctx}.fiscal.settle._meta 必须是 JSON 对象。")

    if "_meta_defaults" not in settle_raw:
        if settle_raw.get("_meta") is None and "_meta" in settle_raw:
            settle = dict(settle_raw)
            settle["_meta"] = {}
            fiscal["settle"] = settle
        return fiscal

    default_name = settle_raw.get("_meta_defaults")
    if not isinstance(default_name, str) or not default_name.strip():
        raise SystemExit(f"{ctx}.fiscal.settle._meta_defaults 必须是非空字符串。")
    default_key = default_name.strip()
    if default_key not in settle_meta_defaults:
        raise SystemExit(f"{ctx}.fiscal.settle._meta_defaults 指向未知默认组：{default_name}。")
    defaults_raw = settle_meta_defaults[default_key]
    if not isinstance(defaults_raw, dict):
        raise SystemExit(f"content/regions.json.settle_meta_defaults.{default_key} 必须是 JSON 对象。")

    settle = dict(settle_raw)
    settle["_meta"] = _deep_merge_content_defaults(defaults_raw, meta_raw)
    settle.pop("_meta_defaults", None)
    fiscal["settle"] = settle
    return fiscal


def load_region_content() -> Dict[str, Region]:
    data = require_dict(load_json_asset("regions.json"), "regions.json")
    settle_meta_defaults_raw = data.get("settle_meta_defaults", {})
    settle_meta_defaults = require_dict(settle_meta_defaults_raw, "regions.json.settle_meta_defaults")
    regions: Dict[str, Region] = {}
    for idx, raw in enumerate(require_list(data.get("regions"), "regions.json.regions"), 1):
        item = require_dict(raw, f"regions.json.regions[{idx}]")
        region_id = str_field(item, "id", f"regions.json.regions[{idx}]")
        ctx = f"regions.json.regions[{idx}]"
        fiscal_raw = item.get("fiscal")
        if not isinstance(fiscal_raw, dict):
            raise SystemExit(f"{ctx}.fiscal 必须是 JSON 对象，实际为 {type(fiscal_raw).__name__}。")
        fiscal = _normalize_settle_meta_defaults(fiscal_raw, settle_meta_defaults, ctx)
        regions[region_id] = Region(
            id=region_id,
            name=str_field(item, "name", ctx),
            kind=str_field(item, "kind", ctx),
            population=int_field(item, "population", ctx),
            public_support=int_field(item, "public_support", ctx),
            unrest=int_field(item, "unrest", ctx),
            natural_disaster=str_field(item, "natural_disaster", ctx),
            human_disaster=str_field(item, "human_disaster", ctx),
            registered_land=int_field(item, "registered_land", ctx),
            hidden_land=int_field(item, "hidden_land", ctx),
            tax_per_turn=int_field(item, "tax_per_turn", ctx),
            grain_security=int_field(item, "grain_security", ctx),
            gentry_resistance=int_field(item, "gentry_resistance", ctx),
            military_pressure=int_field(item, "military_pressure", ctx),
            status=str_field(item, "status", ctx),
            controlled_by=str_field(item, "controlled_by", ctx),
            fiscal=fiscal,
            on_restore=dict(item.get("on_restore") or {}),
        )
    if not regions:
        raise SystemExit("regions.json 必须至少定义一个地区。")
    return regions


def load_army_content() -> Dict[str, Army]:
    data = require_dict(load_json_asset("armies.json"), "armies.json")
    armies: Dict[str, Army] = {}
    for idx, raw in enumerate(require_list(data.get("armies"), "armies.json.armies"), 1):
        item = require_dict(raw, f"armies.json.armies[{idx}]")
        army_id = str_field(item, "id", f"armies.json.armies[{idx}]")
        armies[army_id] = Army(
            id=army_id,
            name=str_field(item, "name", f"armies.json.armies[{idx}]"),
            station=str_field(item, "station", f"armies.json.armies[{idx}]"),
            theater=str_field(item, "theater", f"armies.json.armies[{idx}]"),
            commander=str_field(item, "commander", f"armies.json.armies[{idx}]"),
            controller=str_field(item, "controller", f"armies.json.armies[{idx}]"),
            troop_type=str_field(item, "troop_type", f"armies.json.armies[{idx}]"),
            manpower=int_field(item, "manpower", f"armies.json.armies[{idx}]"),
            # #44 每军名义月饷率(两/兵·月,浮点)：应发=ceil(manpower×rate/10000)。armies.json 明军已写
            # 史实值；缺省 0（非明/旧 json 容错，army_needed 对 0 rate 派生 0 应发）。
            # #173：maintenance_per_turn 列已删（月饷由 army_needed 按兵力派生），content 不再解析它。
            salary_rate=float(item.get("salary_rate") or 0.0),
            supply=int_field(item, "supply", f"armies.json.armies[{idx}]"),
            morale=int_field(item, "morale", f"armies.json.armies[{idx}]"),
            training=int_field(item, "training", f"armies.json.armies[{idx}]"),
            equipment=int_field(item, "equipment", f"armies.json.armies[{idx}]"),
            arrears=int_field(item, "arrears", f"armies.json.armies[{idx}]"),
            mobility=int_field(item, "mobility", f"armies.json.armies[{idx}]"),
            loyalty=int_field(item, "loyalty", f"armies.json.armies[{idx}]"),
            # 火器/随军大炮：armies.json 缺省时给基线（火器全军约30%、随军炮0门，符开局玩法设定），
            # json 显式给值则覆盖；clamp 与引擎一致（火器0-100、随军炮0-12）。新档由此贯通——
            # fresh seed 曾不写两列致新档全 0，被 data/probe.db 老档 fixture 掩盖（CMR codexB）。
            firearm_equipment=max(0, min(100, int(item.get("firearm_equipment", 30) or 0))),
            cannon_equipment=max(0, min(12, int(item.get("cannon_equipment", 0) or 0))),
            pay_source_region=str(item.get("pay_source_region") or "").strip(),
            province_pay_share=float(item.get("province_pay_share") or 0.0),
            central_pay_share=float(item.get("central_pay_share") or 0.0),
            province_pay_arrears=float(item.get("province_pay_arrears") or 0.0),
            central_pay_arrears=float(item.get("central_pay_arrears") or 0.0),
            is_tusi=1 if item.get("is_tusi") else 0,
            self_funded_pay=1 if item.get("self_funded_pay") else 0,
            status=str_field(item, "status", f"armies.json.armies[{idx}]"),
            owner_power=str_field(item, "owner_power", f"armies.json.armies[{idx}]"),
        )
    if not armies:
        raise SystemExit("armies.json 必须至少定义一支军队。")
    return armies


def load_building_content() -> Dict[str, Building]:
    data = require_dict(load_json_asset("buildings.json"), "buildings.json")
    buildings: Dict[str, Building] = {}
    for idx, raw in enumerate(require_list(data.get("buildings"), "buildings.json.buildings"), 1):
        item = require_dict(raw, f"buildings.json.buildings[{idx}]")
        ctx = f"buildings.json.buildings[{idx}]"
        building_id = str_field(item, "id", ctx)
        category = str_field(item, "category", ctx)
        if category not in BUILDING_CATEGORIES:
            raise SystemExit(f"{ctx}: category '{category}' 不在白名单 {BUILDING_CATEGORIES}。")
        output_metric = str(item.get("output_metric") or "")
        if output_metric not in BUILDING_OUTPUT_METRICS:
            raise SystemExit(f"{ctx}: output_metric '{output_metric}' 不在白名单 {BUILDING_OUTPUT_METRICS}。")
        buildings[building_id] = Building(
            id=building_id,
            region_id=str_field(item, "region_id", ctx),
            name=str_field(item, "name", ctx),
            category=category,
            level=int_field(item, "level", ctx),
            condition=int_field(item, "condition", ctx),
            maintenance=int_field(item, "maintenance", ctx),
            risk=int_field(item, "risk", ctx),
            output_metric=output_metric,
            output_amount=int_field(item, "output_amount", ctx),
            status=str_field(item, "status", ctx),
        )
    if not buildings:
        raise SystemExit("buildings.json 必须至少定义一座建筑。")
    return buildings


def load_class_content() -> Dict[str, SocialClass]:
    """阶级人口设定。key = "name@region_id"（region_id 为空则 key="name"）。"""
    data = require_dict(load_json_asset("classes.json"), "classes.json")
    classes: Dict[str, SocialClass] = {}
    for idx, raw in enumerate(require_list(data.get("classes"), "classes.json.classes"), 1):
        item = require_dict(raw, f"classes.json.classes[{idx}]")
        name = str_field(item, "name", f"classes.json.classes[{idx}]")
        region_id = str(item.get("region_id") or "").strip()
        key = f"{name}@{region_id}" if region_id else name
        if key in classes:
            raise SystemExit(f"classes.json 重复条目：{key}")
        classes[key] = SocialClass(
            name=name,
            region_id=region_id,
            population=int_field(item, "population", f"classes.json.classes[{idx}]"),
            satisfaction=int_field(item, "satisfaction", f"classes.json.classes[{idx}]"),
            leverage=int_field(item, "leverage", f"classes.json.classes[{idx}]"),
            agenda=str_field(item, "agenda", f"classes.json.classes[{idx}]"),
        )
    if not classes:
        raise SystemExit("classes.json 必须至少定义一个阶级条目。")
    return classes


def load_powers() -> Dict[str, Power]:
    data = load_json_asset("powers.json")
    raw = require_dict(data, "powers.json")
    powers_raw = require_list(raw.get("powers"), "powers.json::powers")
    powers: Dict[str, Power] = {}
    for item in powers_raw:
        entry = require_dict(item, "powers.json::powers[item]")
        pid = str_field(entry, "id", "powers.json::powers[item].id")
        powers[pid] = Power(
            id=pid,
            name=str_field(entry, "name", "powers.json::powers[item].name"),
            kind=str_field(entry, "kind", "powers.json::powers[item].kind"),
            leader=str_field(entry, "leader", "powers.json::powers[item].leader"),
            stance=str_field(entry, "stance", "powers.json::powers[item].stance"),
            leverage=int_field(entry, "leverage", "powers.json::powers[item].leverage"),
            satisfaction=int_field(entry, "satisfaction", "powers.json::powers[item].satisfaction"),
            military_strength=int_field(entry, "military_strength", "powers.json::powers[item].military_strength"),
            cohesion=int_field(entry, "cohesion", "powers.json::powers[item].cohesion"),
            supply=int_field(entry, "supply", "powers.json::powers[item].supply"),
            agenda=str_field(entry, "agenda", "powers.json::powers[item].agenda"),
            status=str_field(entry, "status", "powers.json::powers[item].status"),
            last_action=str(entry.get("last_action") or "尚无新动").strip() or "尚无新动",
            aliases="，".join(string_list(entry.get("aliases", []), "powers.json::powers[item].aliases")),
        )
    return powers


def load_opening_legacies() -> List[OpeningLegacy]:
    """开局负面帝国修正：content/opening_legacies.json。无 fallback，缺字段直接 SystemExit。"""
    raw = require_dict(load_json_asset("opening_legacies.json"), "opening_legacies.json")
    items = require_list(raw.get("legacies"), "opening_legacies.json::legacies")
    out: List[OpeningLegacy] = []
    for idx, item in enumerate(items, 1):
        path = f"opening_legacies.json::legacies[{idx}]"
        entry = require_dict(item, path)
        modifiers = require_dict(entry.get("modifiers"), f"{path}.modifiers")
        clear_gate = require_dict(entry.get("clear_gate"), f"{path}.clear_gate")
        if not clear_gate:
            raise SystemExit(f"{path}.clear_gate 不能为空（开局负面修正必须有程序判定的消除条件）。")
        out.append(OpeningLegacy(
            key=str_field(entry, "key", path),
            name=str_field(entry, "name", path),
            modifiers=modifiers,
            narrative_hint=str_field(entry, "narrative_hint", path),
            clear_gate={str(k): str(v) for k, v in clear_gate.items()},
            clear_narrative=str(entry.get("clear_narrative") or "").strip(),
        ))
    if not out:
        raise SystemExit("opening_legacies.json 必须至少定义一条开局负面修正。")
    return out


def dict_of_string_lists(value: object, path: str) -> Dict[str, List[str]]:
    data = require_dict(value, path)
    return {str(key): string_list(item, f"{path}.{key}") for key, item in data.items()}


def dict_of_strings(value: object, path: str) -> Dict[str, str]:
    data = require_dict(value, path)
    output: Dict[str, str] = {}
    for key, item in data.items():
        if not isinstance(item, str):
            raise SystemExit(f"设定字段应为字符串：{path}.{key}")
        output[str(key)] = item
    return output


def load_skill_content() -> Tuple[
    Dict[str, List[str]],
    Dict[str, Dict[str, object]],
    Dict[str, List[str]],
    Dict[str, List[str]],
    List[str],
    Dict[str, str],
    Dict[str, List[str]],
    Dict[str, str],
    Set[str],
    Dict[str, Dict[str, object]],
    Dict[str, List[str]],
]:
    data = require_dict(load_json_asset("skills.json"), "skills.json")
    office_skills_data = dict_of_string_lists(data.get("office_skills"), "skills.json.office_skills")
    skill_catalog = {
        str(key): require_dict(value, f"skills.json.skill_catalog.{key}")
        for key, value in require_dict(data.get("skill_catalog"), "skills.json.skill_catalog").items()
    }
    office_default_skills = dict_of_string_lists(data.get("office_default_skills"), "skills.json.office_default_skills")
    personal_skill_ids = dict_of_string_lists(data.get("personal_skill_ids"), "skills.json.personal_skill_ids")
    common_skills = string_list(data.get("common_skills"), "skills.json.common_skills")
    skill_descriptions = dict_of_strings(data.get("skill_descriptions"), "skills.json.skill_descriptions")
    grant_keywords = dict_of_string_lists(data.get("grant_keywords"), "skills.json.grant_keywords")
    directive_keywords = dict_of_strings(data.get("directive_keywords"), "skills.json.directive_keywords")
    directive_skill_ids = set(string_list(data.get("directive_skill_ids"), "skills.json.directive_skill_ids"))
    knowledge_domains = dict_of_string_lists(
        data.get("office_knowledge_domains"), "skills.json.office_knowledge_domains"
    )
    allowed_knowledge_domains = {
        "treasury", "military", "regional", "personnel", "construction", "security", "court"
    }
    for office_type, domains in knowledge_domains.items():
        if not domains:
            raise SystemExit(f"skills.json.office_knowledge_domains.{office_type} 不能为空")
        unknown = sorted(set(domains) - allowed_knowledge_domains)
        if unknown:
            raise SystemExit(
                f"skills.json.office_knowledge_domains.{office_type} 含未知知识域：{','.join(unknown)}"
            )

    office_definitions: Dict[str, Dict[str, object]] = {}
    for office_type, raw in require_dict(data.get("office_definitions"), "skills.json.office_definitions").items():
        item = require_dict(raw, f"skills.json.office_definitions.{office_type}")
        skills_ref = str(item.get("skills_ref") or office_type)
        office_definitions[str(office_type)] = {
            "skills": office_skills_data.get(skills_ref, []),
            "tools": string_list(item.get("tools"), f"skills.json.office_definitions.{office_type}.tools"),
            "authority_scope": str_field(item, "authority_scope", f"skills.json.office_definitions.{office_type}"),
            "power": int_field(item, "power", f"skills.json.office_definitions.{office_type}"),
            "responsibility": int_field(item, "responsibility", f"skills.json.office_definitions.{office_type}"),
            "corruption_risk": int_field(item, "corruption_risk", f"skills.json.office_definitions.{office_type}"),
        }

    for skill_id in common_skills:
        if skill_id not in skill_catalog:
            raise SystemExit(f"common_skills 引用了未定义 skill：{skill_id}")
    for mapping_name, mapping in {
        "office_default_skills": office_default_skills,
        "personal_skill_ids": personal_skill_ids,
        "grant_keywords": grant_keywords,
    }.items():
        for key, skill_ids in mapping.items():
            for skill_id in skill_ids:
                if skill_id not in skill_catalog:
                    raise SystemExit(f"{mapping_name}.{key} 引用了未定义 skill：{skill_id}")
    for keyword, skill_id in directive_keywords.items():
        if skill_id not in skill_catalog:
            raise SystemExit(f"directive_keywords.{keyword} 引用了未定义 skill：{skill_id}")

    return (
        office_skills_data,
        skill_catalog,
        office_default_skills,
        personal_skill_ids,
        common_skills,
        skill_descriptions,
        grant_keywords,
        directive_keywords,
        directive_skill_ids,
        office_definitions,
        knowledge_domains,
    )


def load_fiscal_config() -> "List[Dict[str, object]]":
    """财政科目目录（content/fiscal_config.json）。无 fallback，缺字段直接 SystemExit。

    每项必含 key/value/kind/budget_role/note。`budget_role=fixed` 的 base 项额外必含
    account/direction/display（供 flows 生成预算行）。rate 项与 dynamic 项不强制这三字段。
    返回有序 list（保留 JSON 顺序），db.init_fiscal_config 据此 seed。
    """
    raw = require_dict(load_json_asset("fiscal_config.json"), "fiscal_config.json")
    items_raw = require_list(raw.get("items"), "fiscal_config.json.items")
    schema_version = int_field(raw, "schema_version", "fiscal_config.json")
    items: List[Dict[str, object]] = []
    seen: Set[str] = set()
    for idx, entry in enumerate(items_raw):
        path = f"fiscal_config.json.items[{idx}]"
        item = require_dict(entry, path)
        key = str_field(item, "key", path)
        if key in seen:
            raise SystemExit(f"{path}: fiscal key 重复：{key}")
        seen.add(key)
        kind = str_field(item, "kind", path)
        role = str_field(item, "budget_role", path)
        if role not in ("fixed", "dynamic"):
            raise SystemExit(f"{path}: budget_role 必须是 fixed/dynamic，得到 {role}")
        record: Dict[str, object] = {
            "key": key,
            "value": int_field(item, "value", path),
            "kind": kind,
            "budget_role": role,
            "note": str_field(item, "note", path),
            "order": int(item["order"]) if "order" in item else 9999,
        }
        # fixed 的 base 项必须给 account/direction/display；flows 据此生成预算行。
        if role == "fixed" and kind == "base":
            account = str_field(item, "account", path)
            direction = str_field(item, "direction", path)
            if account not in ("国库", "内库"):
                raise SystemExit(f"{path}: account 必须是 国库/内库，得到 {account}")
            if direction not in ("income", "expense"):
                raise SystemExit(f"{path}: direction 必须是 income/expense，得到 {direction}")
            record["account"] = account
            record["direction"] = direction
            record["display"] = str_field(item, "display", path)
        items.append(record)
    return [{"__schema_version": schema_version}, *items]


@dataclass
class GameContent:
    """游戏全部静态设定。GameContent.load() 一次性读盘填充。

    替代原 main.py 的模块级全局量（FACTIONS/CHARACTERS/EVENTS/...），
    根治 `import main` 即读盘的副作用。
    """

    factions: Dict[str, Faction] = field(default_factory=dict)
    characters: Dict[str, Character] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)
    seed_events: List[Event] = field(default_factory=list)
    opening_legacies: List[OpeningLegacy] = field(default_factory=list)
    event_by_id: Dict[str, Event] = field(default_factory=dict)
    regions: Dict[str, Region] = field(default_factory=dict)
    armies: Dict[str, Army] = field(default_factory=dict)
    buildings: Dict[str, Building] = field(default_factory=dict)
    faction_metrics: Tuple[str, ...] = ()
    powers: Dict[str, Power] = field(default_factory=dict)
    classes: Dict[str, SocialClass] = field(default_factory=dict)

    # skill 体系（load_skill_content 十元组）
    office_skills: Dict[str, List[str]] = field(default_factory=dict)
    skill_catalog: Dict[str, Dict[str, object]] = field(default_factory=dict)
    office_default_skills: Dict[str, List[str]] = field(default_factory=dict)
    personal_skill_ids: Dict[str, List[str]] = field(default_factory=dict)
    common_skills: List[str] = field(default_factory=list)
    skill_descriptions: Dict[str, str] = field(default_factory=dict)
    grant_keywords: Dict[str, List[str]] = field(default_factory=dict)
    directive_keywords: Dict[str, str] = field(default_factory=dict)
    directive_skill_ids: Set[str] = field(default_factory=set)
    office_definitions: Dict[str, Dict[str, object]] = field(default_factory=dict)
    office_knowledge_domains: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    skill_tool_templates: Dict[str, str] = field(default_factory=dict)

    # 提示词
    game_world_prompt: str = ""
    minister_agent_prompt: str = ""
    consort_agent_prompt: str = ""

    decree_writer_prompt: str = ""
    season_simulator_prompt: str = ""
    score_extractor_shared_prompt: str = ""
    score_extractor_module_prompts: Dict[str, str] = field(default_factory=dict)
    chapter_memory_prompt: str = ""
    ending_summary_prompt: str = ""
    relation_brew_prompt: str = ""
    faction_brew_prompt: str = ""

    fiscal_items: List[Dict[str, object]] = field(default_factory=list)

    @classmethod
    def load(cls) -> "GameContent":
        factions, characters = load_character_content()
        events = load_event_content("events.json")
        seed_events = load_event_content("seed_events.json")
        opening_legacies = load_opening_legacies()
        regions = load_region_content()
        armies = load_army_content()
        buildings = load_building_content()
        powers = load_powers()
        classes = load_class_content()
        (
            office_skills_data,
            skill_catalog,
            office_default_skills,
            personal_skill_ids,
            common_skills,
            skill_descriptions,
            grant_keywords,
            directive_keywords,
            directive_skill_ids,
            office_definitions,
            office_knowledge_domains,
        ) = load_skill_content()
        missing_knowledge_domains = sorted(
            {
                character.office_type
                for character in characters.values()
                if character.office_type
            }
            - set(office_knowledge_domains)
        )
        if missing_knowledge_domains:
            raise SystemExit(
                "skills.json.office_knowledge_domains 缺少职位映射："
                + ",".join(missing_knowledge_domains)
            )
        return cls(
            factions=factions,
            characters=characters,
            events=events,
            seed_events=seed_events,
            opening_legacies=opening_legacies,
            event_by_id={ev.id: ev for ev in (*events, *seed_events)},
            regions=regions,
            armies=armies,
            buildings=buildings,
            faction_metrics=tuple(factions.keys()),
            powers=powers,
            classes=classes,
            office_skills=office_skills_data,
            skill_catalog=skill_catalog,
            office_default_skills=office_default_skills,
            personal_skill_ids=personal_skill_ids,
            common_skills=common_skills,
            skill_descriptions=skill_descriptions,
            grant_keywords=grant_keywords,
            directive_keywords=directive_keywords,
            directive_skill_ids=directive_skill_ids,
            office_definitions=office_definitions,
            office_knowledge_domains={
                office_type: tuple(domains)
                for office_type, domains in office_knowledge_domains.items()
            },
            fiscal_items=load_fiscal_config(),
            skill_tool_templates=dict_of_strings(load_json_asset("skill_tools.json"), "skill_tools.json"),
            game_world_prompt=load_text_asset("prompts/game_world.md"),
            minister_agent_prompt=load_text_asset("prompts/minister_agent.md"),
            consort_agent_prompt=load_text_asset("prompts/consort_agent.md"),
            decree_writer_prompt=load_text_asset("prompts/decree_writer.md"),
            season_simulator_prompt=load_text_asset("prompts/season_simulator.md"),
            score_extractor_shared_prompt=load_text_asset("prompts/score_extractor_shared.md"),
            score_extractor_module_prompts={
                "internal": load_text_asset("prompts/score_extractor_internal.md"),
                "military_external": load_text_asset("prompts/score_extractor_military_external.md"),
                "issues": load_text_asset("prompts/score_extractor_issues.md"),
                "personnel_secret": load_text_asset("prompts/score_extractor_personnel_secret.md"),
            },
            chapter_memory_prompt=load_text_asset("prompts/chapter_memory.md"),
            ending_summary_prompt=load_text_asset("prompts/ending_summary.md"),
            relation_brew_prompt=load_text_asset("prompts/relation_brew.md"),
            faction_brew_prompt=load_text_asset("prompts/faction_brew.md"),
        )
