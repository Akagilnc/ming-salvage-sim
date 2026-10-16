"""Draft-intent domain: extract, roster heal, admission resubmit.

#1902 T4：从 cli_backend（传输层）迁出的现役共享领域能力。消费者（session / issues /
declaration_dispatch / action_materialize / tests）直接引用本模块；传输层不得再拥有
这些编排。LLM 调用经 cli_backend 的 runner 入口，属领域→传输依赖。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Mapping, Optional

from ming_sim.participant_roster import (
    UnknownParticipantRefError,
    is_non_person_participant_name as _is_non_person_participant_name,
)
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    apply_assembled_to_payload,
    assemble_structured_decree,
    combination_correction_feedback,
    expand_combo_failed_fields,
    structured_decree_prompt_contract,
    validate_structured_decree_combination,
)
from ming_sim.decree_vocabulary import DIRECTIVE_ACTION_TYPES

# #529：draft 抽取不产 acting_appointment；#1902 T4 常量归领域核，不经传输层。
DRAFT_ACTION_TYPES = DIRECTIVE_ACTION_TYPES - {"acting_appointment"}

logger = logging.getLogger(__name__)

# Domain → transport：直接引用既有传输真源（#1902 J4）；禁为 monkeypatch 另造间接层。
import ming_sim.cli_backend as _cli_backend


def _directive_mode(value: object) -> Optional[str]:
    """Normalize the extractor's typed mode value, never player prose."""
    return {
        "中旨直发": "midzhi",
        "midzhi": "midzhi",
        "普通": "ordinary",
        "ordinary": "ordinary",
    }.get(str(value or "").strip())


def resolve_directive_mode(
    extracted: object = None, existing: object = None,
) -> str:
    """Resolve the typed LLM decision, preserving an existing candidate on edits."""
    for value in (extracted, existing):
        mode = _directive_mode(value)
        if mode is not None:
            return mode
    return "ordinary"


def _draft_intent_character_roster_facts(content: Any) -> str:
    """#1428：把 content.characters 的 name+aliases 编成抽取接地事实块。

    接地=结构化事实注入（ADR 0142）；不在此做散文截断修复/子串归一。
    参与人 character_id 须填规范名；别名仅作识别线索，输出仍归规范名。
    资格与可召面同口径：_is_summonable_court_minister（身份归一∧非宗藩∧非未仕；#1317 r2）。
    无 db 时用 content 静态 power_id（#125 live 翻转不扩）。身份归一另由 _find_existing_minister
    吃（含未仕/宗藩别名）；事实块只供可召朝臣接地，不倾倒待铨诸生。
    """
    characters = getattr(content, "characters", None) if content is not None else None
    if not characters:
        return ""
    from ming_sim.session import _is_summonable_court_minister

    lines: List[str] = []
    for key, ch in characters.items():
        if not _is_summonable_court_minister(ch):
            continue
        name = str(getattr(ch, "name", None) or key or "").strip()
        if not name:
            continue
        aliases = [
            str(a).strip()
            for a in (getattr(ch, "aliases", None) or [])
            if str(a).strip() and str(a).strip() != name
        ]
        if aliases:
            lines.append(f"{name}（别名：{'、'.join(aliases)}）")
        else:
            lines.append(name)
    if not lines:
        return ""
    return (
        "【在册人物规范名+别名】参与人 character_id 必须从此表规范名选取；"
        "见到别名须归一为对应规范名；不得截短、不得自造未列之名。\n"
        + "\n".join(lines)
        + "\n"
    )


def _draft_intent_army_grounding_facts(content: Any) -> str:
    """#1774：把军队身份别名（matching.army_identity_aliases 单源）编成抽取接地事实块。

    与 _draft_intent_character_roster_facts / _pay_order_grounding_facts 同族：
    结构化事实注入（ADR 0142），机面 canonical id 供料合法（ADR 0143）。
    抽取器据此把皇帝的自然说法（「解赴关宁军前」）归一到 @guanning，
    协饷写缝仍走既有 canonical_army_id_exact 精确等值——本块不放宽解析、
    不新增模糊匹配/子串升格，也不把驻地/战区/将领混进身份别名（matching 同规）。
    """
    armies = getattr(content, "armies", None) if content is not None else None
    if not armies:
        return ""
    from ming_sim.matching import army_identity_aliases

    lines: List[str] = []
    for key, army in armies.items():
        army_id = str(getattr(army, "id", None) or key or "").strip()
        if not army_id:
            continue
        name = str(getattr(army, "name", None) or army_id).strip()
        aliases = [
            alias for alias in army_identity_aliases(army)
            if alias not in (army_id, name)
        ]
        head = f"{name}（别名：{'、'.join(aliases)}）" if aliases else name
        lines.append(f"{head}=@{army_id}")
    if not lines:
        return ""
    return (
        "【军队接地事实】协饷旨意的「目标」只填下列 canonical id"
        "（形如 @guanning）；皇帝行文中的军名、别名、军前/所部等说法，"
        "按语义归到所属军的 canonical id；表中无对应之军才留空。\n"
        + "\n".join(lines)
        + "\n"
    )


# #1274 QA V-1：参与人校验失败有界纠错重试（owner 2026-08-20 三连拍板）。
# 宪法：查无此人不告诉皇帝、底下人偷偷划掉=篡改圣旨，绝对禁止。
# 自愈只许修 LLM 自己的抄写错（修完仍是皇帝说的那个人）；真不在册→戏内回禀。
# 1–2 次；happy path 零额外调用。只在 UnknownParticipantRefError 结构化路上触发。
# #1902 T2：禁从 str(exc) 词面正则判故障（ADR 0142 / 锚定宪法）。
DRAFT_PARTICIPANT_HEAL_RETRIES = 2


def _normalize_unknown_participant_names(
    names: Optional[List[str]] = None,
) -> List[str]:
    cleaned: List[str] = []
    for raw in names or []:
        name = str(raw or "").strip()
        if name and name not in cleaned:
            cleaned.append(name)
    return cleaned


def unknown_participant_fact(names: Optional[List[str]] = None) -> str:
    """查无此人事实串唯一真源（escalate.fact 与 compose 共用）。"""
    cleaned = _normalize_unknown_participant_names(names)
    shown = "、".join(cleaned) if cleaned else "其人"
    return (
        f"朝中名册查无「{shown}」此人；"
        f"不得擅自将其从参与人中除去或另换他人；"
        f"须回禀陛下，乞陛下明示该如何处置。"
    )


class UnknownParticipantEscalate(Exception):
    """真不在册：自愈耗尽后须戏内回禀，禁除名照落 / 禁静默 409 术语怼玩家。"""

    def __init__(self, names: Optional[List[str]] = None):
        self.names = _normalize_unknown_participant_names(names)
        self.fact = unknown_participant_fact(self.names)
        super().__init__(self.fact)


def is_unknown_participant_ref_error(exc: BaseException) -> bool:
    """名册引用结构化故障——可回喂 LLM 纠错；只认类型，不咬呈现词面。"""
    return isinstance(exc, UnknownParticipantRefError)


def _invalid_participant_names_from_error(exc: BaseException) -> List[str]:
    if isinstance(exc, UnknownParticipantRefError):
        return list(exc.names)
    return []


def _person_ids_from_extract_result(result: Dict[str, Any]) -> List[str]:
    """单旨抽取结果中的人物键（character_id + delegator_id/delegator，保序去重）。

    除名闸 prior/new 同键空间：委派人与主办/协办同属人物参与侧，漏收会把
    「毕自」→「毕自严」的委派人自愈误判 removal_only，或丢合法委派人不触发
    lost_prior_valid。raw `delegator` 与 `delegator_id` 同收（与 normalize 接缝一致）。
    #1902 R1：批抽 drafts 形状已无生产产出，只读顶层 roster。
    """
    ids: List[str] = []

    def _absorb(roster: Any) -> None:
        if not isinstance(roster, list):
            return
        for item in roster:
            if not isinstance(item, dict):
                continue
            for key in ("character_id", "delegator_id", "delegator"):
                cid = str(item.get(key) or "").strip()
                if cid and cid not in ids:
                    ids.append(cid)

    if "participant_roster" in result:
        _absorb(result.get("participant_roster"))
    return ids


def _known_person_canon(raw: Any, *, db: Any, content: Any) -> Optional[str]:
    """名册内人物 → 规范名；不在册 / 非人 → None。

    与校验缝同口径（_find_existing_minister），禁把生名当合法 prior。
    """
    from ming_sim.session import _find_existing_minister

    cid = str(raw or "").strip()
    if not cid or _is_non_person_participant_name(cid):
        return None
    if content is None or db is None:
        return None
    found = _find_existing_minister(content, cid, db)
    key = str(found or "").strip()
    return key or None


def _roster_dict_entries(roster: Any) -> List[Dict[str, Any]]:
    if not isinstance(roster, list):
        return []
    return [dict(item) for item in roster if isinstance(item, dict)]


def _entry_person_fields(entry: Dict[str, Any]) -> List[tuple[str, str]]:
    """(field, raw_id) for character_id + delegator；保序。"""
    fields: List[tuple[str, str]] = []
    cid = str(entry.get("character_id") or "").strip()
    if cid:
        fields.append(("character_id", cid))
    did = str(
        entry.get("delegator_id") or entry.get("delegator") or ""
    ).strip()
    if did:
        fields.append(("delegator_id", did))
    return fields


def _is_failed_person_slot(raw: Any, *, db: Any, content: Any) -> bool:
    """人物失败槽？normalize 同口径：空/机构/泛称不算；在册人物不算；其余未知人物算。"""
    cid = str(raw or "").strip()
    if not cid or _is_non_person_participant_name(cid):
        return False
    return _known_person_canon(cid, db=db, content=content) is None


def _count_failed_person_slots_in_roster(
    roster: Any, *, db: Any, content: Any,
) -> int:
    n = 0
    for entry in _roster_dict_entries(roster):
        for _field, raw in _entry_person_fields(entry):
            if _is_failed_person_slot(raw, db=db, content=content):
                n += 1
    return n


def _count_failed_person_slots(
    result: Dict[str, Any], *, db: Any, content: Any,
) -> int:
    """首抽单旨结果的人物失败槽数（顶层 roster；机构/泛称排除）。"""
    if "participant_roster" not in result:
        return 0
    return _count_failed_person_slots_in_roster(
        result.get("participant_roster"), db=db, content=content,
    )


def _collect_corr_person_ids(roster: Any, *, db: Any, content: Any) -> List[str]:
    """纠错轮 roster 人物规范名（保序，可重复）。"""
    out: List[str] = []
    for entry in _roster_dict_entries(roster):
        for _field, raw in _entry_person_fields(entry):
            known = _known_person_canon(raw, db=db, content=content)
            if known:
                out.append(known)
    return out


def _patch_roster_slots_one_to_one(
    baseline_roster: Any,
    correction_roster: Any,
    *,
    db: Any,
    content: Any,
) -> Optional[List[Any]]:
    """可证明一一对应的结构化槽级修补；对应不明 → None（调用方 escalate）。

    #1902 J1：同人证明只认结构化名册校验／模型交付的规范名，不扫正文子串或前缀。
    - baseline 形状/顺序/tier/role 冻结
    - 同下标对应：合法槽必须仍是同一人；失败槽取同位置纠错名（须在册）
    - 禁聚合候选池按序回填（增人/重排可静默换人）
    - 纠错轮新人（在册且非 prior）计数须与失败槽数相等，否则不明
    - 多失败槽（含 validator 首错即停只报一个）→ 不明
    - 不把自由正文姓名/别名/前缀子串当身份准入（#1834 F46）
    """
    base_entries = _roster_dict_entries(baseline_roster)
    corr_entries = _roster_dict_entries(correction_roster)
    if not base_entries:
        return []
    # corr 短于 baseline：仅当被截去的尾槽全是机构/空才可（人物槽缺失 → 不明）
    if len(corr_entries) < len(base_entries):
        for entry in base_entries[len(corr_entries):]:
            for _field, raw in _entry_person_fields(entry):
                cid = str(raw or "").strip()
                if cid and not _is_non_person_participant_name(cid):
                    return None

    prior_valid: set[str] = set()
    failed_slots: List[tuple[int, str]] = []  # (entry_idx, field)
    for idx, entry in enumerate(base_entries):
        for field, raw in _entry_person_fields(entry):
            # 机构/泛称：normalize 会丢，不入失败槽、不入 prior_valid
            if not str(raw or "").strip() or _is_non_person_participant_name(raw):
                continue
            known = _known_person_canon(raw, db=db, content=content)
            if known is None:
                failed_slots.append((idx, field))
            else:
                prior_valid.add(known)

    # 本 roster 多未知 → 对应不明（全局闸应已拦；此处保本地不变量）
    if len(failed_slots) > 1:
        return None
    if not failed_slots:
        return [dict(e) for e in base_entries]

    # 纠错轮全部在册人物中的「新人」；非 prior 的在册 id 计入新人数，须与失败槽数相等
    corr_all_ids = _collect_corr_person_ids(corr_entries, db=db, content=content)
    structured_newcomers: List[str] = []
    seen_new: set[str] = set()
    for pid in corr_all_ids:
        if pid in prior_valid or pid in seen_new:
            continue
        seen_new.add(pid)
        structured_newcomers.append(pid)
    if len(structured_newcomers) != len(failed_slots):
        return None

    out: List[Any] = []
    for idx, base_entry in enumerate(base_entries):
        corr_entry = corr_entries[idx] if idx < len(corr_entries) else {}
        entry = dict(base_entry)
        for field, raw in _entry_person_fields(base_entry):
            # 机构/泛称槽：保首抽原值，交 normalize 滤除；不参与同人对应
            if not str(raw or "").strip() or _is_non_person_participant_name(raw):
                continue
            base_known = _known_person_canon(raw, db=db, content=content)
            corr_raw = str(
                corr_entry.get(field)
                or (corr_entry.get("delegator") if field == "delegator_id" else "")
                or ""
            ).strip()
            corr_known = _known_person_canon(corr_raw, db=db, content=content)
            if base_known is None:
                # 失败槽：同位置必须是唯一结构化新人（模型交付 + 名册校验）
                if corr_known is None or corr_known not in seen_new:
                    return None
                entry[field] = corr_known
                if field == "delegator_id":
                    entry.pop("delegator", None)
            else:
                # 合法槽：同位置必须仍是同一人（重排 → 不明）
                if corr_known != base_known:
                    return None
                entry[field] = base_known
                if field == "delegator_id":
                    entry.pop("delegator", None)
        out.append(entry)
    # 尾部增人（corr 更长）一律丢弃，不落库、不进池
    return out


def _backfill_healed_participant_refs(
    baseline: Dict[str, Any],
    correction: Dict[str, Any],
    *,
    db: Any,
    content: Any,
) -> Optional[Dict[str, Any]]:
    """首抽权威快照 + 纠错轮一一对应槽级修补；对应不明 → None。

    非参与人字段一律保首抽；纠错轮增人/重排/改档不落库。
    失败槽不变式：顶层 roster 人物失败槽须恰好为 1
    （机构/泛称按 normalize 口径排除）；≠1 → None；唯一失败槽同下标修补。
    #1902 R1：批抽 drafts 合并已无生产消费者，删。
    #1902 J1：不读 player_message／失败槽原文做身份证明。
    """
    # 全局闸：复用 _count_failed_person_slots（禁第三套扫描器）
    if _count_failed_person_slots(baseline, db=db, content=content) != 1:
        return None
    out = dict(baseline)
    base_roster = baseline.get("participant_roster")
    if isinstance(base_roster, list):
        patched = _patch_roster_slots_one_to_one(
            base_roster,
            correction.get("participant_roster"),
            db=db,
            content=content,
        )
        if patched is None:
            return None
        out["participant_roster"] = normalize_draft_person_roster(
            patched, db=db, content=content,
        )
    return out


def build_participant_correction_feedback(
    exc: BaseException, *, roster_facts: str = "",
) -> str:
    """正向纠错指令（P7）：无效名 + 名册事实；只许改正抄写，禁除名/另换。"""
    names = _invalid_participant_names_from_error(exc)
    name_part = "、".join(names) if names else "（见校验）"
    block = (
        f"【纠错】名册无此人：{name_part}。"
        f"请改正为名册中陛下所指之人的正确规范名（须仍是同一人）；"
        f"不得擅自除去或另换他人。\n"
    )
    # Roster facts grounding haul: preserve raw when non-empty (#1834 F21).
    raw_facts = "" if roster_facts is None else str(roster_facts)
    facts = raw_facts if raw_facts.strip() else ""
    if facts:
        block += facts if facts.endswith("\n") else facts + "\n"
    return block


def _canon_person_id_key(raw: Any, *, db: Any, content: Any) -> Optional[str]:
    """单 id：非人滤除 + _canonical_minister_key → 熟键；与 roster 归一同口径。"""
    from ming_sim.session import _canonical_minister_key

    cid = str(raw or "").strip()
    if not cid or _is_non_person_participant_name(cid):
        return None
    canon = str(_canonical_minister_key(content, cid, db) or "").strip()
    return canon or None


def _canon_person_id_keys(
    ids: Any, *, db: Any, content: Any,
) -> List[str]:
    """生 character_id 列表 → 熟键（非人滤 + canon），保序去重。

    除名闸 prior 侧与 validated 必须同走此接缝，禁平行第三套 id 语义。
    """
    out: List[str] = []
    for raw in ids or []:
        canon = _canon_person_id_key(raw, db=db, content=content)
        if canon and canon not in out:
            out.append(canon)
    return out


def normalize_draft_person_roster(
    roster: Any, *, db: Any, content: Any,
    validate_delegations: bool = True,
) -> List[Dict[str, object]]:
    """人物参与人：normalize → 非人滤除 → canon → ADR 0053 校验。

    capture 与召对 materialize 共用；校验失败 raise ValueError（参与人物不存在…）。
    validate_delegations=False：调用方将与既有名单合并后再验委派链（#1897 E1）。
    """
    from ming_sim.action_materialize import DecreeMaterializationValidationError
    if not isinstance(roster, list):
        raise DecreeMaterializationValidationError(
            "参与人须为对象列表",
            failed_fields=("participant_roster",),
            category="invalid_participant_roster",
        )

    try:
        canonical_roster = db._normalize_participant_roster(
            roster, strict_structured=True,
        )
    except ValueError as exc:
        raise DecreeMaterializationValidationError(
            str(exc), failed_fields=("participant_roster",),
        ) from exc
    person_roster: List[Dict[str, object]] = []
    for item in canonical_roster:
        entry = dict(item)
        # canon / DB 读：故障上抛，不转产物
        cid = _canon_person_id_key(entry.get("character_id"), db=db, content=content)
        if not cid:
            continue
        entry["character_id"] = cid
        delegator_raw = str(entry.get("delegator_id") or "").strip()
        if delegator_raw:
            delegator = _canon_person_id_key(
                delegator_raw, db=db, content=content,
            )
            entry["delegator_id"] = delegator  # None if 非人
        person_roster.append(entry)
    db._validate_participant_roster_references(person_roster)
    # 委派链与成案/追加同一权威；声明面 as_declaration → 领域拒收（#1897 E1）。
    if validate_delegations:
        db._validate_dossier_delegations(person_roster, as_declaration=True)
    return person_roster


def _apply_validated_roster_to_extract_result(
    result: Dict[str, Any], *, db: Any, content: Any,
) -> Dict[str, Any]:
    """对单旨结果的 participant_roster 做 normalize+validate（就地拷贝）。"""
    out = dict(result)
    if "participant_roster" in out and out.get("participant_roster") is not None:
        out["participant_roster"] = normalize_draft_person_roster(
            out.get("participant_roster"), db=db, content=content,
        )
    return out


def _pay_order_grounding_facts(content: Any, db: Any = None) -> str:
    """把既有 canonical 地区/科目词表与结算时点直接教授抽取器；不建立第二映射。

    #1769：欠科目词表进输入侧结构契约（ADR0143/P6）；不在引擎侧改写 LLM 输出。
    科目闭集唯一真源 = pay_order.DUE_SUBJECTS / ARREARS_SUBJECTS。
    """
    from ming_sim.pay_order import (
        ARREARS_SUBJECTS,
        DEFAULT_DUE_PRIORITY,
        DUE_SUBJECTS,
    )

    regions = getattr(content, "regions", None) if content is not None else None
    lines = []
    for key, region in (regions or {}).items():
        rid = str(getattr(region, "id", None) or key or "").strip()
        name = str(getattr(region, "name", None) or "").strip()
        if rid and name:
            lines.append(f"{name}=@{rid}")
    timing = ""
    if db is not None:
        # 整段 game_state 时点读为持久缝：fetch/解码任一失败→代码故障（F39）。
        try:
            state = db.reign.row(1, fields="turn, year, period", table="game_state")
            if state is not None:
                timing = (
                    f"当前结算时点：turn={int(state['turn'])}，"
                    f"{int(state['year'])}年{int(state['period'])}月。\n"
                )
        except (TypeError, ValueError) as exc:
            raise RuntimeError("game_state 时点持久读失败") from exc
    head = "【pay_order_override 接地事实】"
    if lines:
        head += "地区只能直接使用下列 canonical id，禁别名/自造：\n" + "、".join(lines) + "\n"
    else:
        head += "\n"
    due_set = "/".join(DUE_SUBJECTS)
    arrears_set = "/".join(ARREARS_SUBJECTS)
    default_due = (
        "/".join(DEFAULT_DUE_PRIORITY)
        + "=" + "/".join(str(DEFAULT_DUE_PRIORITY[s]) for s in DEFAULT_DUE_PRIORITY)
    )
    return (
        head + timing
        + f"due_priority 科目∈{due_set}；"
          f"arrears_priority 欠科目∈{arrears_set}；"
          f"due_haircut_bp 科目∈{due_set}。\n"
        + f"priority 数字越小越先；默认{default_due}，"
          "并列按该默认次序稳定排列。相对期限只填 duration_months=N，"
          "不要自行计算 until_turn；该动作 entries 必须非空。\n"
    )


def _ground_relative_pay_order_deadlines(result: Dict[str, Any], db: Any) -> Dict[str, Any]:
    """在既有抽取适配缝把结构化相对月数落成 active-through 绝对 turn。"""
    try:
        row = db.reign.row(1, fields="turn", table="game_state")
        if row is None:
            return result
        current_turn = int(row["turn"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("game_state.turn 持久读失败") from exc
    if result.get("dossier_action_type") != "pay_order_override":
        return result
    for entry in result.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if "duration_months" in entry:
            duration = entry.pop("duration_months")
            if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
                raise ValueError(f"override 相对期限 duration_months 须为正整数：{duration!r}")
            entry["until_turn"] = current_turn + duration - 1
        elif "until_turn" in entry and (
            isinstance(entry["until_turn"], bool)
            or not isinstance(entry["until_turn"], int)
            or entry["until_turn"] < current_turn
        ):
            raise ValueError(f"override until_turn 已过期或无效：{entry['until_turn']!r}")
    return result


def _finalize_extract_with_combo(
    result: Dict[str, Any],
    *,
    needs_combo: bool = False,
) -> Dict[str, Any]:
    """单旨结果建成后做组合校验；失败携带 partial + typed 可修字段边界。

    needs_combo 为调用方局部布尔，不写入结果字典。
    #1902 R1：批抽 draft_combo_flags 路径已无生产消费者，删。
    """
    if needs_combo:
        try:
            validate_structured_decree_combination(result)
        except StructuredDecreeCombinationError as exc:
            raise StructuredDecreeCombinationError(
                str(exc),
                partial_result=dict(result),
                failed_fields=exc.failed_fields,
            ) from exc
    return result


def _apply_failed_fields_from_correction(
    target: Dict[str, Any],
    corrected: Mapping[str, Any],
    failed_fields: object,
) -> None:
    """只把 failed_fields 边界内结构键从纠错轮写入 target（就地）。"""
    for key in expand_combo_failed_fields(failed_fields):
        if key in corrected:
            target[key] = corrected[key]
        else:
            target.pop(key, None)


def _merge_combo_correction_preserving_roster(
    baseline: Dict[str, Any],
    corrected: Dict[str, Any],
    *,
    failed_fields: Optional[frozenset] = None,
) -> Dict[str, Any]:
    """组合纠错成功：仅采纳 typed 失败字段，保留首抽 participant_roster。

    未失败的动作/目标/承办/类别与旨文、名册一律保留首抽；不另建第二 retry。
    #1902 R1：批抽 draft_failures / drafts 合并已无生产消费者，删。
    """
    out = dict(baseline)
    top_fields = frozenset(failed_fields or ())
    if top_fields:
        _apply_failed_fields_from_correction(out, corrected, top_fields)
    if "participant_roster" in baseline:
        out["participant_roster"] = baseline["participant_roster"]
    return out


def _revalidate_merged_combo_result(
    result: Dict[str, Any],
    *,
    failed_fields: Optional[frozenset] = None,
) -> None:
    """合并失败字段后重走共同组合校验；仍败则 typed 上抛。"""
    if failed_fields:
        try:
            validate_structured_decree_combination(result)
        except StructuredDecreeCombinationError as exc:
            raise StructuredDecreeCombinationError(
                str(exc),
                partial_result=dict(result),
                failed_fields=exc.failed_fields,
            ) from exc


def _affair_declaration_from_draft_obj(obj: Mapping[str, Any]) -> Dict[str, Any]:
    """Typed 拆旨声明（new|existing）；缺席不猜。本阶段不消费了结。"""
    from ming_sim.entities.affair import ATTACH_BIRTH, declaration_from_payload
    declaration = declaration_from_payload(obj, allowed=ATTACH_BIRTH)
    return {} if declaration is None else {"affair_declaration": dict(declaration)}


def _stamp_split_birth_key(declaration: Mapping[str, Any]) -> Dict[str, Any]:
    """One extract shares one durable new identity; do not infer from name/origin."""
    body = dict(declaration)
    if body.get("attach") != "new" or str(body.get("birth_key") or "").strip():
        return body
    from uuid import uuid4
    body["birth_key"] = f"split:{uuid4().hex}"
    return body


def _draft_intent_open_affair_facts(db: Any) -> str:
    """Structured open-affair list so existing.affair_id is chosen from input, not guessed."""
    if db is None:
        return ""
    store = getattr(db, "affairs", None)
    list_open = getattr(store, "list_open", None)
    if not callable(list_open):
        return ""
    rows = list_open()
    if not rows:
        return ""
    lines = [
        json.dumps(
            {"id": int(row.id), "name": row.name, "origin": row.origin},
            ensure_ascii=False,
        )
        for row in rows
    ]
    return (
        "【已开事务】existing 的 affair_id 必须取自下列对象的 id，不得自造。\n"
        + "\n".join(lines)
        + "\n"
    )


def extract_draft_intent_with_roster_heal(
    player_message: Optional[str],
    minister_reply: str,
    llm_config: Any = None,
    *,
    db: Any = None,
    content: Any = None,
    heal_retries: int = DRAFT_PARTICIPANT_HEAL_RETRIES,
    initial_correction: str = "",
) -> Dict[str, Any]:
    """extract → 共同契约组合校验 + 名册校验；失败有界纠错重抽（P5 只走失败路）。

    #1624：组合校验失败只回喂结构契约，不改写自由文本旨文；不得各入口另造 heal。
    组合纠错复用 baseline_result：只更新该次不变式 failed_fields 边界内字段，
    保留首抽 participant_roster 与未失败结构，再走既有名册校验
    （禁合法甲→合法乙、未失败动作/目标/类别静默漂移）。
    自愈只许抄写纠错（修完仍是皇帝所指之人）。真不在册 / 擅自除名 →
    raise UnknownParticipantEscalate（调用方戏内回禀，不落草案）。
    db/content 缺一则只抽不校验名册（与旧 extract 同）；组合校验在 extract 内已做。
    LLM 在纠错路上挂死 → 原样上抛。
    initial_correction（#1769）：成案拒收补交时把失败事实与原产物作为首轮回喂。
    #1902 R1：批抽 draft_failures / drafts 承接已无生产消费者，删。
    """
    retries = max(0, int(heal_retries))
    correction = str(initial_correction or "")
    pending_unknown: List[str] = []
    prior_ids_at_fail: List[str] = []
    # 首抽权威快照：首次校验失败后冻结，后续失败不得覆写 baseline/闸基线。
    baseline_result: Optional[Dict[str, Any]] = None
    baseline_from_combo = False
    baseline_failed_fields: frozenset = frozenset()

    for attempt in range(retries + 1):
        # llm_config 关键字传：别族 fake_draft(msg, reply, **kw) 形仍合法，
        # 不得因 heal 多塞第 3 位置参把旧 mock 签名整族打爆。
        try:
            result = extract_draft_intent(
                player_message,
                minister_reply,
                llm_config=llm_config,
                content=content,
                pay_order_facts=_pay_order_grounding_facts(content, db),
                correction_feedback=correction,
                db=db,
            )
        except StructuredDecreeCombinationError as exc:
            # 共同契约组合失败：typed 有界重试；首败冻结 partial + 可修字段边界。
            # 纠错轮整包仍可能因未失败字段漂移而组合失败——此时只取 partial 中
            # 原失败边界字段合并回首抽，再共同校验（不把漂移整包当成功结果）。
            partial = getattr(exc, "partial_result", None)
            if baseline_result is None and isinstance(partial, dict):
                baseline_result = dict(partial)
                baseline_from_combo = True
                baseline_failed_fields = frozenset(getattr(exc, "failed_fields", None) or ())
                if attempt >= retries:
                    raise
                correction = combination_correction_feedback(exc)
                _cli_backend._log(f"拟旨结构组合纠错重试 {attempt + 1}/{retries}: {exc}")
                continue
            if (
                baseline_from_combo
                and baseline_result is not None
                and isinstance(partial, dict)
            ):
                result = _merge_combo_correction_preserving_roster(
                    baseline_result,
                    partial,
                    failed_fields=baseline_failed_fields,
                )
                try:
                    _revalidate_merged_combo_result(
                        result,
                        failed_fields=baseline_failed_fields,
                    )
                except StructuredDecreeCombinationError as merged_exc:
                    if attempt >= retries:
                        raise StructuredDecreeCombinationError(
                            str(merged_exc),
                            partial_result=dict(result),
                            failed_fields=merged_exc.failed_fields,
                        ) from merged_exc
                    correction = combination_correction_feedback(merged_exc)
                    _cli_backend._log(
                        f"拟旨结构组合纠错重试 {attempt + 1}/{retries}: {merged_exc}"
                    )
                    continue
                baseline_result = dict(result)
                baseline_from_combo = False
                # 合并已过共同闸：落入下方 roster 路径（勿再 continue）
            else:
                if attempt >= retries:
                    raise
                correction = combination_correction_feedback(exc)
                _cli_backend._log(f"拟旨结构组合纠错重试 {attempt + 1}/{retries}: {exc}")
                continue
        # 组合纠错成功（纠错轮整包已过闸）：只采纳失败字段，再共同校验+roster 闸
        if baseline_from_combo and baseline_result is not None:
            result = _merge_combo_correction_preserving_roster(
                baseline_result,
                result,
                failed_fields=baseline_failed_fields,
            )
            _revalidate_merged_combo_result(
                result,
                failed_fields=baseline_failed_fields,
            )
            baseline_result = dict(result)
            baseline_from_combo = False
        if db is not None:
            result = _ground_relative_pay_order_deadlines(result, db)
        if db is None or content is None:
            return result
        has_roster_field = (
            "participant_roster" in result and result.get("participant_roster") is not None
        )
        if not has_roster_field:
            # 纠错路上抽掉参与人字段 = 除名企图 → 篡改，回禀
            if pending_unknown:
                raise UnknownParticipantEscalate(pending_unknown)
            return result
        try:
            validated = _apply_validated_roster_to_extract_result(
                result, db=db, content=content,
            )
        except ValueError as exc:
            if not is_unknown_participant_ref_error(exc):
                raise
            # 仅首败冻结基线；重试失败不得洗掉首抽合法参与人/未知名。
            # 组合路径可能已冻 baseline：仍要记下 pending_unknown 供 backfill。
            if not pending_unknown:
                pending_unknown = _invalid_participant_names_from_error(exc)
                prior_ids_at_fail = _person_ids_from_extract_result(
                    baseline_result if baseline_result is not None else result,
                )
            if baseline_result is None:
                baseline_result = dict(result)
            if attempt >= retries:
                raise UnknownParticipantEscalate(pending_unknown) from exc
            roster_facts = _draft_intent_character_roster_facts(content)
            correction = build_participant_correction_feedback(
                exc, roster_facts=roster_facts,
            )
            _cli_backend._log(
                f"拟旨参与人纠错重试 {attempt + 1}/{retries}: {exc}"
            )
            continue
        # 校验过了：若本轮曾因查无而纠错，禁「只删不改」；
        # 亦禁有替换时顺手抹掉本轮已在册的合法参与人。
        # prior 侧须过与 validated 同一条归一后再比（别名→规范名），
        # 禁生/熟键空间错位误杀自愈。
        # #1902 J1：替换只认结构化名册校验／模型交付，不扫正文子串或前缀。
        if pending_unknown:
            new_ids = _person_ids_from_extract_result(validated)
            prior_raw = [
                i for i in prior_ids_at_fail if i not in pending_unknown
            ]
            prior_valid = _canon_person_id_keys(
                prior_raw, db=db, content=content,
            )
            replacements = [i for i in new_ids if i not in prior_valid]
            lost_prior_valid = not set(prior_valid) <= set(new_ids)
            removal_only = (
                not replacements and set(new_ids) <= set(prior_valid)
            )
            if lost_prior_valid or removal_only:
                raise UnknownParticipantEscalate(pending_unknown)
            assert baseline_result is not None
            # 一一对应槽级修补（禁聚合候选池）；对应不明（新人计数/重排/多未知）→ escalate
            # 纠错轮用原形 result（保留机构槽位形），禁 validated 压缩后再对下标——
            # 机构/泛称被 normalize 丢掉会错位。人物合法性已由 validated 闸证明。
            backfilled = _backfill_healed_participant_refs(
                baseline_result,
                result,
                db=db,
                content=content,
            )
            if backfilled is None:
                raise UnknownParticipantEscalate(pending_unknown)
            return backfilled
        return validated


def _stalled_deliberation_push_facts(db: Any) -> str:
    """#658：自由下旨可强推的 stalled 廷议＋active issue 投影（候选相关切片）。"""
    if db is None:
        return ""
    # #1902 F1：库查询失败不得洗成空事实继续抽取；逐行脏载荷仍可跳过。
    # 门闸归 store.list_stalled_deliberations（deliberation_state，不拨 status）。
    rows = db.dossiers.list_stalled_deliberations()
    lines: List[str] = []
    for row in rows or []:
        payload = row["payload"]
        did = int(row["id"])
        try:
            issue = db.conn.execute(
                "SELECT id, title FROM issues WHERE origin_ref=? AND status='active' LIMIT 1",
                (f'dossier:{did}',),
            ).fetchone()
            if issue is None:
                continue
            # #1565/0142：题名只认结构化 title|target_id|既有 issue.title；
            # 正文唯一真源 payload.text，旧档 decree_text 仅作正文承接。
            # Free title/body for LLM feed: carry as-is (P6); no strip-assign.
            title = str(
                payload.get("title")
                or payload.get("target_id")
                or issue["title"]
                or ""
            )
            body = str(
                payload.get("text") or row.get("decree_text") or ""
            )
            # #658：完整 title/body 供唯一辨认；禁截断导致同前缀误绑定
            lines.append(
                f"  案卷ID={did} issue#{int(issue['id'])} 题={title} 正文={body}"
            )
        except (TypeError, ValueError, KeyError) as exc:
            # #1849：坏项隔离留痕（ADR 0005：只拒该项、不带走整批，但必须记原因）。
            _cli_backend._log(f"强推案卷事实跳过坏行（dossier={row.get('id')!r}）：{exc}")
            continue
    if not lines:
        return ""
    return (
        "【可御笔强推的议而不决案卷】仅当皇帝明确强推下列事项时填目标案卷ID；"
        "否则目标案卷ID留 null。\n"
        + "\n".join(lines) + "\n"
    )


def extract_draft_intent(
    player_message: Optional[str],
    minister_reply: str,
    llm_config: Any = None,
    content: Any = None,
    correction_feedback: str = "",
    pay_order_facts: str = "",
    db: Any = None,
) -> Dict[str, Any]:
    """现役单旨抽取（#1902 N5）：只承接补交 / heal 所需的单道拟旨模式。

    多旨批次、补充合并、现有候选指认、harvest/点将后置等旧模式已删；
    签名不再吞无生产消费者的关键字。

    合法「无」→ ``{"draft_action": "无", ...}``；解析失败/缺键/非法枚举响亮上抛（N1）。
    生产链 resubmit→heal 恒带 correction；LLM call/transport 失败原样上抛。
    content（#1428）注入名册接地。
    """
    roster_facts = _draft_intent_character_roster_facts(content)
    army_facts = _draft_intent_army_grounding_facts(content)
    # 纠错反馈可含原旨副本：strip 只判空，不得加工整份运输块（#1897 E2 / P6）。
    if correction_feedback is None:
        correction_block = ""
    elif isinstance(correction_feedback, str):
        correction_block = correction_feedback
    else:
        correction_block = str(correction_feedback)
    if correction_block.strip() and not correction_block.endswith("\n"):
        correction_block += "\n"
    stalled_push_facts = _stalled_deliberation_push_facts(db)
    open_affair_facts = _draft_intent_open_affair_facts(db)
    from ming_sim.action_clusters import (
        assert_action_candidate_shape,
        cluster_fields_prompt,
        project_cluster_fields,
    )
    grant_fields_prompt = cluster_fields_prompt("grant_allocation")

    def _normalize_grant_transport(value: Mapping[str, Any]) -> Dict[str, Any]:
        transport = dict(value)
        if "target_id" not in transport and "目标" not in transport and "目标ID" in transport:
            transport["target_id"] = transport["目标ID"]
        raw_mode = transport.get("mode", transport.get("颁布方式"))
        if raw_mode not in (None, ""):
            transport["mode"] = _directive_mode(raw_mode) or raw_mode
        normalized = assert_action_candidate_shape({**transport, "kind": "grant_allocation"})
        projected = project_cluster_fields("grant_allocation", normalized)
        if projected.get("grant_action") != "协饷" and not projected.get("target_kind"):
            projected["target_kind"] = "policy"
        return projected

    intent_schema_line = (
        '  "拟旨意图": "无|拟旨",\n'
        '  "动作类型": "policy|approve_reject|assignment|'
        'grant_allocation|authorization|secret_authorization|secret_investigation|'
        'protection|strategy_selection|punishment|pacification|referral|'
        'revoke_decree|revoke_authority|dismiss_assignment|military_order|'
        'pay_order_override",\n'
        '  "entries": [],              // 仅 pay_order_override：偿还序/折发调整清单，\n'
        '                             // 形如 [{"key":"due_haircut_bp_宗禄","value":5000,"duration_months":3}]；\n'
        '                             // key∈due_priority_<科目>[@省]|'
        'arrears_priority_<欠科目>[@省]|'
        'due_haircut_bp_<科目>[@省][#province|#central]；'
        'haircut 值=万分数(0,10000]；非该动作留 []\n'
        + grant_fields_prompt
        + '  "目标类型": "",\n'
        '  "目标ID": "",\n'
        '  "地区ID": "",\n'
        '  "施行范围": "",\n'
        '  "事务类别": "",\n'
        '  "承办人": "",\n'
        '  "参与人": [{"character_id":"规范名","tier":"主办|协办|知情","role":"本案职分","delegator_id":null}],\n'
        '  "期限月数": null,           // 军令必填正整数；非军令留 null\n'
        '  "事务声明": {"attach":"new|existing","name":"","origin":"","affair_id":null},\n'
        '  "目标案卷ID": null        // 御笔强推议而不决廷议时填该案卷整数 ID；非此意图留 null\n'
    )
    prompt = (
        "你是信息抽取器，不扮演、不写圣旨。读皇帝这句话 + 大臣回话，判断皇帝**本轮**"
        "是否在口头请大臣拟旨（如「拟旨吧」「你拟一道旨」「帮我起草」「草拟圣旨」等）。"
        "只输出一个 JSON 对象（无代码围栏、无多余字）：\n"
        "{\n"
        + intent_schema_line
        + "}\n"
        "判定要点：皇帝明确让大臣拟旨/起草圣旨→拟旨；仅商议/问询/催办/评论不算。语义判断，别拘字面。\n"
        + structured_decree_prompt_contract() + "\n"
        '非拨帑旨填共同契约目标/属地/事务类别/承办字段及“颁布方式”(普通|中旨直发)；拨帑旨只用 ACTION_CLUSTERS 字段。\n'
        '同一句交办只写一处事务声明（attach 仅 new|existing）；无声明不自建。\n'
        "御笔强推议而不决事项亦归拟旨，并填目标案卷ID。\n\n"
        + correction_block
        + roster_facts
        + army_facts
        + pay_order_facts
        + stalled_push_facts
        + open_affair_facts
        + "【皇帝】" + (player_message or "（无）") + "\n"
        + "【大臣回话】" + (minister_reply or "（无）") + "\n"
    )
    raw, _ = _cli_backend._run_backend_for_config(prompt, llm_config, tag="draft_intent")
    # #1849：解析失败/缺意图键/非法意图值都是抽取产物不可用，不是「无意图」；
    # 一律响亮拒收（同 _coerce_draft_target_kind / 动作类型非法的既有契约），
    # 禁再消解成合法无意图让写入口覆盖原草稿。
    from ming_sim.action_materialize import DecreeMaterializationValidationError
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if not isinstance(obj, dict):
        raise DecreeMaterializationValidationError("拟旨抽取产物不可解析为 JSON 对象")
    if "拟旨意图" not in obj:
        raise DecreeMaterializationValidationError("拟旨意图抽取缺「拟旨意图」键")
    _raw = str(obj.get("拟旨意图") if obj.get("拟旨意图") is not None else "").strip()
    if _raw not in {"无", "拟旨"}:
        raise ValueError(f"拟旨意图枚举非法：{_raw!r}")
    _action = _raw
    # #654 H：合法「无」立即短路（不附后置点将 harvest；该模式无生产消费者，N5 已清）。
    if _action == "无":
        return {
            "draft_action": "无", "draft_text": "", "target_candidate": "",
        }
    # #658：御笔强推与普通 triad 互斥；并存响亮拒绝，禁止静默吞旨
    from ming_sim.db import (
        classify_directive_structured_kind,
        imperial_push_target_dossier_id,
    )
    _probe: Dict[str, Any] = {}
    _raw_target = obj.get("目标案卷ID")
    if _raw_target is None:
        _raw_target = obj.get("target_dossier_id")
    if _raw_target is not None:
        _probe["target_dossier_id"] = _raw_target
    _act = str(obj.get("动作类型") or "").strip()
    if _act == "grant_allocation":
        _projected = _normalize_grant_transport(obj)
    else:
        _projected = {}
    _tk = str(
        _projected.get("target_kind")
        if _act == "grant_allocation" else obj.get("目标类型") or ""
    ).strip()
    _tid = str(
        _projected.get("target_id") if _act == "grant_allocation" else obj.get("目标ID") or ""
    ).strip()
    if _act:
        _probe["dossier_action_type"] = _act
    if _tk:
        _probe["target_kind"] = _tk
    if _tid:
        _probe["target_id"] = _tid
    kind = classify_directive_structured_kind(_probe) if _probe else "empty"
    if kind == "push":
        push_dossier_id = imperial_push_target_dossier_id(_probe)
        assert push_dossier_id is not None
        # 旨文原话：禁 strip 改写运输值（#1897 E2 / P6）。
        push_out: Dict[str, Any] = {
            "draft_action": "拟旨",
            # Free draft body: carry minister/player prose as-is (P6).
            "draft_text": (minister_reply or player_message or ""),
            "target_candidate": "",
            "target_dossier_id": push_dossier_id,
        }
        push_mode = _directive_mode(obj.get("颁布方式"))
        if push_mode is not None:
            push_out["mode"] = push_mode
        push_declaration = _affair_declaration_from_draft_obj(obj)
        if push_declaration:
            push_out["affair_declaration"] = _stamp_split_birth_key(
                push_declaration["affair_declaration"]
            )
        return push_out
    dossier_action = str(obj.get("动作类型") or "special_decree").strip()
    if dossier_action == "acting_appointment":
        # #529：署理交回既有人事候选链，不经草案 acting_appointment。
        return {
            "draft_action": "无", "draft_text": "", "target_candidate": "",
        }
    if dossier_action not in DRAFT_ACTION_TYPES:
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        raise DecreeMaterializationValidationError(
            f"动作类型非法：{dossier_action!r}",
            failed_fields=("dossier_action_type",),
        )
    _tk_raw = _projected.get("target_kind") if dossier_action == "grant_allocation" else obj.get("目标类型")
    target_kind = (
        str(_tk_raw or "").strip()
        if dossier_action == "grant_allocation"
        else _coerce_draft_target_kind(_tk_raw if _tk_raw not in (None, "") else "policy")
    )
    target_id_value = str(
        _projected.get("target_id") if dossier_action == "grant_allocation" else obj.get("目标ID") or ""
    ).strip()
    mode = _directive_mode(
        _projected.get("mode") if dossier_action == "grant_allocation" else obj.get("颁布方式")
    )
    mechanical = {
        "assignee": obj.get("承办人"),
        "deadline_months": obj.get("期限月数"),
        "entries": obj.get("entries"),
    }
    if dossier_action == "grant_allocation":
        mechanical.update(
            (key, item) for key, item in _projected.items()
            if key != "target_kind"
        )
    needs_combo = (
        dossier_action != "grant_allocation" or bool(target_kind and target_id_value)
    )
    if needs_combo:
        assembled = assemble_structured_decree(
            {
                **obj,
                **mechanical,
                "动作类型": dossier_action,
                "目标类型": target_kind,
                "目标ID": target_id_value,
            },
            validate=False,
        )
        apply_assembled_to_payload(mechanical, assembled)
        target_kind = str(assembled["target_kind"])
        target_id_value = str(assembled["target_id"])
    elif dossier_action == "grant_allocation":
        explicit_scope = _explicit_draft_locality_scope(
            obj.get("施行范围") or _projected.get("locality_scope")
        )
        if explicit_scope is not None:
            mechanical["locality_scope"] = explicit_scope
    if mode is not None:
        mechanical["mode"] = mode
    # 大臣回话为 LLM 旨文：原话过手，strip 只用于判空副本（#1897 E2 / P6）。
    reply_raw = minister_reply if isinstance(minister_reply, str) else str(minister_reply or "")
    # #654 H 已在上方对 _action=="无" 短路；此处仅保留 #653 pay_order 验形。
    # #1849：entries 非法是脏产物，响亮拒收；不得洗成「无意图」让写入口
    # 以 special_decree 覆盖原草稿（失败诚实宪法）。
    if dossier_action == "pay_order_override" and (
        not isinstance(mechanical.get("entries"), list) or not mechanical.get("entries")
    ):
        from ming_sim.action_materialize import DecreeMaterializationValidationError
        raise DecreeMaterializationValidationError(
            "pay_order_override 须有非空 entries 清单",
            failed_fields=("entries",),
        )
    # 大臣回话即草案（原话过手，不因 strip 改写）。
    draft_text = reply_raw
    # #1849：非法事务声明响亮拒收（禁静默弃声明后照样出成功草案）。
    single_declaration = _affair_declaration_from_draft_obj(obj)
    if single_declaration:
        single_declaration = {
            "affair_declaration": _stamp_split_birth_key(
                single_declaration["affair_declaration"]
            )
        }
    single_result = {
        "draft_action": _action, "draft_text": draft_text, "target_candidate": "",
        "dossier_action_type": dossier_action,
        "target_kind": target_kind, "target_id": target_id_value,
        "participant_roster": obj["参与人"] if "参与人" in obj else [],
        **mechanical,
        **single_declaration,
    }
    return _finalize_extract_with_combo(single_result, needs_combo=needs_combo)


# 八值 target_kind 真源在 decree_vocabulary.TARGET_KINDS（#654 / owner A 禁双定义）
from ming_sim.decree_vocabulary import TARGET_KINDS as _VALID_DRAFT_TARGET_KINDS
from ming_sim.execution_pressure import normalize_locality_scope as _normalize_locality_scope


def _coerce_draft_target_kind(raw: object) -> str:
    """#654 r3-B.2：非法 target_kind fail-loud，废除静默改 policy。"""
    from ming_sim.action_materialize import DecreeMaterializationValidationError
    kind = str(raw or "").strip()
    if kind not in _VALID_DRAFT_TARGET_KINDS:
        raise DecreeMaterializationValidationError(
            f"目标类型非法：{kind!r}",
            failed_fields=("target_kind",),
        )
    return kind


def _explicit_draft_locality_scope(raw: object) -> Optional[str]:
    """仅原始非空属地才归一；缺席返回 None（禁止预先洗成显式 none）。"""
    if raw is None or str(raw).strip() == "":
        return None
    return _normalize_locality_scope(raw)


def build_draft_admission_resubmit_feedback(
    *,
    failure_reason: str,
    bad_payload: Mapping[str, Any],
    decree_text: str = "",
) -> str:
    """#1769 成案拒收补交回喂：只告诉 LLM 失败事实与原产物（0150 D5-b）。

    结构契约/科目词表已由 extract_draft_intent 主 prompt 注入，不在 correction 再写一份。
    """
    payload_json = json.dumps(dict(bad_payload or {}), ensure_ascii=False, sort_keys=True)
    reason = str(failure_reason or "")
    if not reason.strip():
        reason = "（未给出具体拒因）"
    # Free decree body: empty-check without mutating carried 旨文 (P6).
    text = str(decree_text or "")
    parts = [
        "【成案校验失败，请按失败事实与原产物整份重交结构化字段（勿改旨文正文）】\n",
        f"失败事实：{reason}\n",
        f"原产物：{payload_json}\n",
    ]
    if text.strip():
        parts.append(f"原旨正文（不得改写）：{text}\n")
    return "".join(parts)


def project_draft_extract_to_directive_payload(
    captured: Mapping[str, Any],
    *,
    decree_text: str = "",
    existing_mode: object = None,
    db: Any = None,
    content: Any = None,
) -> Dict[str, object]:
    """把 extract_draft_intent 结果投影为 turn_directives.dossier_payload。"""
    declared_mode = resolve_directive_mode(
        extracted=captured.get("mode"), existing=existing_mode,
    )
    # 非拟旨兼容回落已删：生产调用方（补交）在入口已拒非拟旨；空声明仍走下方 empty 路径。
    payload: Dict[str, object] = {
        "dossier_action_type": captured.get("dossier_action_type"),
        "target_kind": captured.get("target_kind"),
        "target_id": captured.get("target_id"),
        "mode": declared_mode,
    }
    for field in (
        "amount", "account", "execution_surface", "assignee",
        "deadline_months", "participant_roster", "locality_scope", "entries",
        "target_dossier_id", "affair_declaration",
        "grant_action", "purpose", "cadence",
        "region_id", "transaction_category",
    ):
        if captured.get(field) not in (None, ""):
            payload[field] = captured[field]
    if (
        payload.get("dossier_action_type") == "grant_allocation"
        and payload.get("grant_action") == "协饷"
    ):
        xiexang_kwargs = dict(
            amount=payload.get("amount"),
            account=str(payload.get("account") or ""),
            purpose=str(payload.get("purpose") or ""),
            target_kind=str(payload.get("target_kind") or ""),
            target_id=str(payload.get("target_id") or ""),
            cadence=str(payload.get("cadence") or ""),
        )
        if db is not None:
            from ming_sim.action_materialize import require_materializable_xiexang_payload
            material = require_materializable_xiexang_payload(
                db, text=str(decree_text or ""), **xiexang_kwargs,
            )
            payload.update({k: v for k, v in material.items() if k != "text"})
        else:
            from ming_sim.action_materialize import require_explicit_xiexang_fields
            payload.update(require_explicit_xiexang_fields(**xiexang_kwargs))
    if payload.get("dossier_action_type") == "dismiss_assignment":
        payload["name"] = str(payload.get("target_id") or "").strip()
        payload["_office_action"] = "罢免"
    from ming_sim.db import (
        classify_directive_structured_kind,
        imperial_push_target_dossier_id,
    )
    # #1902 F1：分类失败不得伪造 ordinary 继续装配；沿用既有 ValueError 收口。
    pre_kind = classify_directive_structured_kind(payload)
    if pre_kind not in {"push", "empty"} and payload.get("target_kind") not in (None, ""):
        regions_content = getattr(content, "regions", None) if content is not None else None
        conn = getattr(db, "conn", None) if db is not None else None
        assembled = assemble_structured_decree(
            payload,
            conn=conn,
            regions_content=regions_content,
            validate=True,
        )
        apply_assembled_to_payload(payload, assembled)
    kind = classify_directive_structured_kind(payload)
    if kind == "push":
        push_id = imperial_push_target_dossier_id(payload)
        assert push_id is not None
        push_payload: Dict[str, object] = {
            "target_dossier_id": push_id,
            "mode": declared_mode,
        }
        declaration = captured.get("affair_declaration")
        if declaration not in (None, ""):
            push_payload["affair_declaration"] = declaration
        return push_payload
    if kind == "empty":
        # 空声明直接拒收；不再经旧手拟占位载荷编码后再识别拒收（#1902 EMPTY-LEGACY）。
        raise ValueError("拟旨结构为空")
    return payload


def resubmit_draft_admission_payload(
    decree_text: str,
    *,
    bad_payload: Mapping[str, Any],
    failure_reason: str,
    llm_config: Any = None,
    db: Any = None,
    content: Any = None,
    existing_mode: object = None,
) -> Dict[str, object]:
    """#1769 结算路 B：把成案失败事实与原产物告诉 LLM，重交结构化 payload。

    本函数单次重写；外层（session）按 DRAFT_ADMISSION_RESUBMIT_REWRITES 循环
    （原抽 + 重写 2 = 总计 3）。与 extract 内 heal_retries（组合/名册）独立——
    内部 heal 不冒充成案补交次数。不在引擎侧改写 LLM 输出（0142）。
    """
    from ming_sim.action_materialize import DecreeMaterializationValidationError
    # 补交运输：strip 只判空，原文送下一 LLM（#1897 E2 / P6 / ADR0142）。
    text = decree_text if isinstance(decree_text, str) else str(decree_text or "")
    if not text.strip():
        raise DecreeMaterializationValidationError("补交缺旨文正文")
    feedback = build_draft_admission_resubmit_feedback(
        failure_reason=failure_reason,
        bad_payload=bad_payload,
        decree_text=text,
    )
    prompt = f"请据此拟旨，并从以下已成旨文抽取结构，不得改写：\n{text}"
    try:
        captured = extract_draft_intent_with_roster_heal(
            prompt,
            text,
            llm_config=llm_config,
            db=db,
            content=content,
            initial_correction=feedback,
        )
    except UnknownParticipantEscalate as exc:
        # 名册产物错走本票 B 路预算/留存，不得升成整月 SettlementAbort 连带好旨。
        # 结算路无召对现场，不另作戏内回禀；只把不在册事实当失败事实回喂下一次重写。
        raise DecreeMaterializationValidationError(exc.fact) from exc
    # #1769 结算路 B：仅「仍为拟旨」才算本轮成功产物。
    # #1902：解析失败/缺键/非法枚举已在 extract 响亮上抛真因；此处只承接模型
    # 明确返回的合法「无」（非解析失败）。空结构在 project 内直接拒收。
    # 旧手拟空载占位专用识别已清退——无现役生产者，不靠占位协议拒收。
    if captured.get("draft_action") != "拟旨":
        raise DecreeMaterializationValidationError("结算补交重写未返回拟旨意图")
    return project_draft_extract_to_directive_payload(
        captured,
        decree_text=text,
        existing_mode=existing_mode or (bad_payload or {}).get("mode"),
        db=db,
        content=content,
    )


# 旧密令理解链承办人/祈使式正则与纯确认片段已随 _extract_secret_order 清退（#1902 S1）。
# 闭集与判定真源仍在 participant_roster（模块顶 import 别名）。
