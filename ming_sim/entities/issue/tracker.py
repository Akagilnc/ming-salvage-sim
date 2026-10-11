"""局势追踪落库核。

助手从定义它们的模块显式引入。issues 在函数体内引入，避免与
issues 加载人物段时再进入本模块形成的环。
"""

from __future__ import annotations

import ming_sim.strict_types as strict_types
from ming_sim.exceptions import DeclarationDataError, DeclarationReferenceError
import ming_sim.settlement.preflight as settlement_preflight

import re
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, RejectedItem
from ming_sim.settlement.outcome import IssueSectionResult
from ming_sim.db import GameDB
import ming_sim.entities.issue.event_terminal as event_terminal
import ming_sim.entities.issue.records as issue_records
from ming_sim.entities.metric.apply import declare_metric_pairs
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.models import GameState, effect_dict_has_work, loads_effect_dict

def apply_issue_tracker_output(
    db: GameDB,
    state: GameState,
    tracker_output: Dict[str, object],
    llm_config: Any = None,
    content=None,
    candidate_event_ids_at_input: Optional[set[str]] = None,
    candidate_event_ids_authoritative: bool = False,
    impeachment_surge_candidates_at_input: Optional[List[Dict[str, object]]] = None,
    event_result_delta_event_ids: Optional[set[str]] = None,
    defer_event_trigger_ids: Optional[set[str]] = None,
    open_affair_ids_at_input: Optional[set[int]] = None,
    source: Provenance = Provenance.system_simulation,
) -> IssueSectionResult:
    import ming_sim.issues as issues
    import ming_sim.entities.issue.effects as issue_effects
    # Do not re-copy open_affair_ids_at_input: settle path already hands the single
    # internal working set from the settlement orchestrator; a second copy would drop
    # same-batch new_issues births from later carriers (close / durable origin).
    applied_advances: List[Dict[str, object]] = []
    applied_new: List[Dict[str, object]] = []
    applied_cancels: List[Dict[str, object]] = []
    # 与成功回执并列的真实拒收通道，由编排器统一耐久化。
    entity_rejections: List[RejectedItem] = []
    issue_person_changes: List[Dict[str, object]] = []
    runtime_content = content if content is not None else issues._ctx()
    event_by_id = runtime_content.event_by_id
    # 内存快照归事务主人（编排器或自行 BEGIN 的调用方）。本函数不判事务、不提交。
    candidate_snapshot_authoritative = (
        candidate_event_ids_at_input is not None and candidate_event_ids_authoritative
    )
    candidate_event_ids = (
        set(candidate_event_ids_at_input)
        if candidate_event_ids_at_input is not None
        else {candidate.id for candidate in issues.gather_candidate_events(state, db)}
    )
    event_result_delta_event_ids = set(event_result_delta_event_ids or set())
    defer_event_trigger_ids = set(defer_event_trigger_ids or set())
    consumed_event_ids: set[str] = set()
    current_candidate_event_ids: set[str] = set()
    candidates_dirty = True
    # 1) advances（ADR 0008 决定1：LLM 脏数据逐项拒收留痕，不裸 continue 静默丢；db.advance_issue
    #    的代码/DB 异常上抛 SettlementAbort，同 close_issues / new_issues 段，#63）
    for adv in tracker_output.get("advances", []) or []:
        if not isinstance(adv, dict):
            # 非 dict 项：sanitize_delta_shape 已在前置闸按 ADR 0015 逐项拒收并剔除；
            # 此处再守一道，直调 tracker / 绕过前置闸时同样不崩整月（同 close_issues）。
            entity_rejections.append(RejectedItem(item={"raw_value": adv}, reason=f"advances 条目非对象（应为 dict）：{adv!r}", category="invalid_enum", source=source))
            continue
        try:
            # _parse_sqlite_id：非整数/bool/float/超 SQLite 64-bit → ValueError（含 10**100 这类
            # int() 过得了但绑定 SQLite 抛 OverflowError 的脏 id，避免上抛崩整月，同 close_issues）。
            issue_id = strict_types._parse_sqlite_id(adv.get("issue_id"))
        except (TypeError, ValueError):
            entity_rejections.append(RejectedItem(item=adv, reason=f"advances issue_id 非法（非整数或超 SQLite 范围）：{adv.get('issue_id')!r}", category="invalid_enum", source=source))
            continue
        try:
            # delta_bar/inertia_delta 用 _strict_int（拒 bool/float/inf/非数）：原裸 int() 在此 try
            # 之外，int("高")/int(1e309) 直接逃逸成 SettlementAbort、int(True)=1 静默截断。缺省/null → 0。
            _db_raw = adv.get("delta_bar")
            delta_bar = _strict_int(0 if _db_raw is None else _db_raw)
            _id_raw = adv.get("inertia_delta")
            inertia_delta = _strict_int(0 if _id_raw is None else _id_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            entity_rejections.append(RejectedItem(item=adv, reason=f"advances 字段强转失败（delta_bar/inertia_delta 脏数据）：{exc}", category="invalid_enum", source=source))
            continue
        stage_text = str(adv.get("stage_text") or "")
        narrative = str(adv.get("narrative") or "")
        # 先验 issue 存在且 active（与 db.advance_issue 的 None 条件 row is None / status!=active 一致）：
        # 未找到/已非 active → missing_ref 逐项拒收留痕（陈旧/幻觉引用，同 close_issues None 归类，#63），
        # 不裸 continue 静默丢。**必须先验、再应用 metric**：原序先 _apply_metric_dict（就地 mutate
        # state.metrics）后判 None，会让拒收项的 metric_delta 副作用已落 state、与「未落地」矛盾且结算
        # commit 无 rollback（cmr advances r1 codex high + claude concur）。
        _chk = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
        if _chk is None or _chk["status"] != "active":
            entity_rejections.append(RejectedItem(item=adv, reason=f"advances 引用未找到或已非 active 的 issue {issue_id}", category="missing_ref", source=source))
            continue
        # 确认 active 后才应用 metric（单线程内 _apply_metric_dict 不改 issue 表 status，故下方
        # advance_issue 必非 None——pre-check 与其内部判定同条件）。
        metric_delta_raw = adv.get("metric_delta")
        if metric_delta_raw is None:
            metric_delta_raw = {}
        if isinstance(metric_delta_raw, dict):
            applied_metrics, refused_metrics = declare_metric_pairs(
                state, list(metric_delta_raw.items()), db=db,
                source=source, item_base={"issue_id": issue_id},
            )
            entity_rejections.extend(refused_metrics)
        else:
            applied_metrics = {}
            entity_rejections.append(RejectedItem(
                item={"issue_id": issue_id, "field": "metric_delta", "raw_value": metric_delta_raw},
                reason="局势推进指标须为对象", category="invalid_shape", source=source,
            ))
        new_row = db.advance_issue(
            state, issue_id,
            trigger_kind="decree",
            delta_bar=delta_bar,
            stage_text=stage_text,
            narrative=narrative,
            metric_delta=applied_metrics,
            inertia_delta=inertia_delta,
            commit=False,
        )
        # 终结结算：bar 自然推到 100/0 触发的 resolved/failed，与 close_issues 一样落终结效果（含建筑）
        if new_row["status"] == "resolved":
            effect = loads_effect_dict(new_row["effect_on_resolve"])
            parent_origin_ref = issue_records._canonical_issue_origin(db, new_row)
            entity_rejections.extend(
                issue_effects._apply_issue_entities(
                    db,
                    state,
                    effect,
                    f"局势#{issue_id}结案",
                    content=runtime_content,
                    llm_config=llm_config,
                    applied_person_changes=issue_person_changes,
                    issue_id=issue_id, issue_title=str(new_row["title"]),
                origin_ref=parent_origin_ref,
                source=source))
        elif new_row["status"] == "failed":
            effect = loads_effect_dict(new_row["effect_on_fail"])
            parent_origin_ref = issue_records._canonical_issue_origin(db, new_row)
            entity_rejections.extend(
                issue_effects._apply_issue_entities(
                    db,
                    state,
                    effect,
                    f"局势#{issue_id}失败",
                    content=runtime_content,
                    llm_config=llm_config,
                    applied_person_changes=issue_person_changes,
                    origin_ref=parent_origin_ref,
                source=source))
        applied_advances.append({
            "issue_id": issue_id,
            "title": new_row["title"],
            "from_value": int(new_row["bar_value"]) - delta_bar,
            "to_value": int(new_row["bar_value"]),
            "stage_text": new_row["stage_text"],
            "status": new_row["status"],
            "narrative": narrative,
        })

    # 2) new_issues：接三种来源——decree、静态 event_pool，以及
    #    当前输入事实可重验的动态 impeachment_surge。其它来源一律拒。
    # #1790：在办 initiative 数量硬上限已废——下旨一律落地，压力由执行判官两轴涌现。
    consumed_surge_candidates: set[tuple[str, str]] = set()
    for ni in tracker_output.get("new_issues", []) or []:
        if not isinstance(ni, dict):
            # 非 dict 项：sanitize_delta_shape 已在前置闸按 ADR 0015 逐项拒收并剔除；
            # 此处再守一道，直调 tracker / 绕过前置闸时同样不崩整月（ADR 0008 决定 1，同 close_issues）。
            entity_rejections.append(RejectedItem(item={"raw_value": ni}, reason=f"new_issues 条目非对象（应为 dict）：{ni!r}", category="invalid_enum", source=source))
            continue
        raw_title = ni.get("title")
        origin_kind = str(ni.get("origin_kind") or "").lower()
        if origin_kind == "impeachment_surge":
            candidate_id = str(ni.get("candidate_id") or "").strip()
            surge_candidates = (
                impeachment_surge_candidates_at_input
                if impeachment_surge_candidates_at_input is not None
                else issues.gather_impeachment_surge_candidates(state, db)
            )
            candidates = {str(item["id"]): item for item in surge_candidates}
            candidate = candidates.get(candidate_id)
            roster = ni.get("target_roster")
            stage_text = ni.get("stage_text")
            title = raw_title if isinstance(raw_title, str) else ""
            roster_shape_valid = (
                isinstance(roster, list)
                and bool(roster)
                and all(isinstance(character_id, str) and character_id.strip() for character_id in roster)
            )
            target_ids = (
                list(dict.fromkeys(character_id.strip() for character_id in roster))
                if roster_shape_valid else []
            )
            reason = ""
            if candidate is None:
                reason = (
                    "动态候选不在本次 LLM 输入快照"
                    if impeachment_surge_candidates_at_input is not None
                    else "动态候选不存在、陈旧或已消费"
                )
            elif not isinstance(raw_title, str) or not raw_title.strip():
                reason = "弹劾潮 title 须为非空文本"
            elif not isinstance(stage_text, str):
                reason = "弹劾潮 stage_text 须为文本"
            elif str(ni.get("faction_hint") or "").strip() != candidate["faction_id"]:
                reason = "弹劾潮 faction_hint 与候选派系不符"
            elif (str(candidate["origin_ref"]), str(candidate["faction_id"])) in consumed_surge_candidates:
                reason = "弹劾潮候选已在本次调用内消费"
            elif not roster_shape_valid:
                reason = "弹劾潮 target_roster 须为非空人物身份列表"
            elif not set(target_ids).issubset(set(candidate["eligible_target_ids"])):
                reason = "弹劾潮标靶越过 eligible_target_ids 闭集"
            if reason:
                entity_rejections.append(RejectedItem(item=ni, reason=reason, category="issue", source=source))
                continue
            issue_id = db.insert_issue(
                state,
                kind="situation",
                title=title,
                origin_kind="impeachment_surge",
                origin_ref=str(candidate["origin_ref"]),
                bar_value=40,
                bar_good_meaning="",
                bar_bad_meaning="",
                stage_text=stage_text,
                faction_hint=str(candidate["faction_id"]),
                participants=[],
                target_roster=target_ids,
                cancellable="never",
                commit=False,
            )
            consumed_surge_candidates.add(
                (str(candidate["origin_ref"]), str(candidate["faction_id"]))
            )
            applied_new.append({"id": candidate_id, "issue_id": issue_id, "kind": "situation", "title": title})
            continue
        title = str(raw_title or "")
        if origin_kind == "event_pool":
            # 预设事件触发：id 必须是真实预设 event，照预设字段立 issue（不用 LLM 给的字段）
            event_id = str(ni.get("id") or ni.get("origin_ref") or "").strip()
            ev = event_by_id.get(event_id)
            if ev is None:
                print(f"[INFO] new_issue 已拒：event_pool id={event_id!r} 非预设事件，疑似臆造。")
                entity_rejections.append(RejectedItem(item={"id": event_id, "title": title or event_id}, reason="event_pool id 非预设事件", category="issue", source=source))
                continue
            if getattr(ev, "auto_trigger", False):
                # auto_trigger 事件只能程序硬触发，LLM 不准从候选池立项
                print(f"[INFO] new_issue 已拒：event {event_id} 标了 auto_trigger，只能程序硬触发。")
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason="auto_trigger 事件仅程序可触发", category="issue", source=source))
                continue
            if issues._is_fiscal_levy_event(ev):
                # 候选快照里残留的饷率 id 也不许在此记触发。结局只经御批写口。
                print(f"[INFO] new_issue 已拒：event {event_id} 是饷率事件，结局只经御批。")
                applied_new.append({
                    "id": ev.id, "title": ev.title, "rejected": True,
                    "reason": "饷率事件结局只经御批写口",
                })
                continue
            if db.event_terminal_state(ev.id) == "expired":
                print(f"[INFO] new_issue 已拒：event {event_id} 已过期终态，不再从 event_pool 立项。")
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason="事件已过期终态", category="issue", source=source))
                continue
            if (
                ev.id not in candidate_event_ids
                or ev.id in consumed_event_ids
            ):
                # LLM 只能从本回合候选池中挑选事件；落库端重验窗口、trigger_gate 与已触发状态，
                # 避免陈旧/伪造 id 穿透候选层后直接应用确定性后果（#203 CMR）。
                print(f"[INFO] new_issue 已拒：事件 {event_id} 当前未进 event_pool 候选池。")
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason="事件当前未进候选池（窗口/前提门/已触发不满足）", category="issue", source=source))
                continue
            terminal_state = db.event_terminal_state(ev.id)
            if terminal_state:
                terminal_reason = {
                    "obsolete": "事件已作废终态",
                    "avoided": "事件已避过终态",
                    "triggered": "事件已触发终态",
                }.get(str(terminal_state), f"事件已有终态：{terminal_state}")
                print(f"[INFO] new_issue 已拒：event {event_id} 已有终态 {terminal_state!r}，不再从 event_pool 立项。")
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason=terminal_reason, category="issue", source=source))
                continue
            # 重查候选：级联作废 / 新满足前提门的事件可能新进/退出候选池。
            # 权威快照（authoritative）只增不减——union 进新候选、不缩窄初始绑定（#399 cmr R1 codex P2）；
            # 非权威快照额外过滤——advances/前置事件效果关门后，已退出候选的事件不得沿用旧快照触发。
            if candidates_dirty:
                current_candidate_event_ids = {candidate.id for candidate in issues.gather_candidate_events(state, db)}
                candidates_dirty = False
                if candidate_snapshot_authoritative:
                    candidate_event_ids |= current_candidate_event_ids
            if not candidate_snapshot_authoritative and ev.id not in current_candidate_event_ids:
                print(f"[INFO] new_issue 已拒：事件 {event_id} 当前未进 event_pool 候选池。")
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason="事件当前未进候选池（窗口/前提门/已触发不满足）", category="issue", source=source))
                continue
            if (
                settlement_preflight._is_strategic_foreign_node_event(ev)
                and ev.id not in event_result_delta_event_ids
            ):
                print(f"[INFO] new_issue 已拒：战略/外敌事件 {event_id} 缺世界状态主账结果。")
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason="战略/外敌战事缺世界状态主账结果（地区/军队/人物变更/新建军队）", category="issue", source=source))
                continue
            if ev.event_type != "situation":
                if ev.id in defer_event_trigger_ids:
                    consumed_event_ids.add(ev.id)
                    candidates_dirty = True
                    print(f"[INFO] new_issue 已接收：事件 {event_id} 为 {ev.event_type}，待软判结果落主账后记触发。")
                    applied_new.append({"id": ev.id, "title": ev.title, "deferred_trigger": True, "reason": f"event_type={ev.event_type} 待软判结果落主账后记触发"})
                    continue
                if ev.effect_on_trigger:
                    entity_rejections.extend(
                        issue_effects._apply_issue_entities(
                            db,
                            state,
                            (ev.effect_on_trigger),
                            f"事件#{ev.id}触发",
                            content=runtime_content,
                            llm_config=llm_config,
                            applied_person_changes=issue_person_changes,
                        source=source)
                    )
                db.mark_event_triggered(state, ev.id, commit=False)
                event_terminal.apply_event_cascading_invalidations(state, db)
                consumed_event_ids.add(ev.id)
                candidates_dirty = True
                print(f"[INFO] new_issue 已拒：事件 {event_id} 为 {ev.event_type}，不转 issue。")
                applied_new.append({"id": ev.id, "title": ev.title, "reason": f"event_type={ev.event_type} 已记为触发"})
                continue
            issue_id = issue_records.event_to_issue(db, state, ev)
            if issue_id is not None and ev.effect_on_trigger:
                # #1893：模型选中即触发——事件自带的核心后果（如 huangtaiji_chengdi 的
                # 改国号）随这一次写口落定，不另按日期旁路补。situation 类事件的
                # effect_on_trigger 历来只在 auto_trigger 硬触发路应用；模型选中路
                # 原缺这一步，属改触发方式后漏接的既有核心后果。
                entity_rejections.extend(
                    issue_effects._apply_issue_entities(
                        db,
                        state,
                        ev.effect_on_trigger,
                        f"事件#{ev.id}触发",
                        content=runtime_content,
                        llm_config=llm_config,
                        applied_person_changes=issue_person_changes,
                        source=source,
                    )
                )
            if issue_id is None:
                # issue_records.event_to_issue 移除 broad except 后，返回 None 只剩一种语义：同源 issue 已存在的
                # 幂等去重跳过（在其 insert try 之外 early-return）；insert 的真代码/DB 异常现已上抛、
                # 不再走此 None 分支（cmr ni r7 codex high），故 reason 不再含「或落库失败」。
                entity_rejections.append(RejectedItem(item={"id": ev.id, "title": ev.title}, reason="事件已触发过（同源局势已立，幂等跳过）", category="issue", source=source))
            else:
                consumed_event_ids.add(ev.id)
                candidates_dirty = True
                applied_new.append({"id": ev.id, "issue_id": issue_id, "kind": "situation", "title": ev.title})
            continue
        if origin_kind != "decree":
            print(f"[INFO] new_issue 已拒：'{title}'（origin_kind={origin_kind!r}，仅接 decree / event_pool）。")
            entity_rejections.append(RejectedItem(item={"title": title}, reason="来源非 decree/event_pool 不许新立", category="issue", source=source))
            continue
        # kind 缺省/null/空串 → 默认 initiative；present 非法值（含 false/0/[] 这类 falsy 非串，
        # 原 `or "initiative"` 会把它们静默默认、绕过白名单，cmr ni r6 codex）→ 留给白名单拒收。
        _kind_raw = ni.get("kind")
        kind = "initiative" if _kind_raw in (None, "") else str(_kind_raw)
        if kind not in ("situation", "initiative"):
            # 脏 kind（LLM 偶给 "reform"/"policy"/"局势" 等，见 DELTA_SCHEMA.md）→ insert_issue 会
            # 抛 ValueError；本刀移除 broad except 后会逃逸成 SettlementAbort，故须在此预检拒整项
            # （与 4 个脏强转同口径，cmr ni r1 Claude+codex concur）。
            entity_rejections.append(RejectedItem(item=ni, reason=f"new_issue kind 非法 '{kind}'（须 situation/initiative）", category="invalid_enum", source=source))
            continue
        def _eff_dict(v, field):
            if isinstance(v, dict):
                return v
            if v is not None and v != "":
                entity_rejections.append(RejectedItem(
                    item={"field": field, "raw_value": v, "title": title},
                    reason="局势效果须为对象", category="invalid_shape", source=source,
                ))
            return {}
        ongoing_eff = _eff_dict(ni.get("ongoing_effects"), "ongoing_effects")
        resolve_eff = _eff_dict(ni.get("effect_on_resolve"), "effect_on_resolve")
        fail_eff = _eff_dict(ni.get("effect_on_fail"), "effect_on_fail")
        semantic_ongoing_has_work = effect_dict_has_work(ongoing_eff)
        ongoing_has_work = issue_records._monthly_ongoing_effects_has_work(ongoing_eff)
        unsupported_ongoing_fields = issue_records._unsupported_monthly_ongoing_fields(ongoing_eff)
        # 坏子项留痕，不牵连可构造的局势主体。
        origin_ref = str(ni.get("origin_ref") or "").strip()
        stop_condition_raw = ni.get("stop_condition")
        stop_condition = issue_records._issue_condition_text(stop_condition_raw)
        commitment_kind = issue_records._normalize_commitment_kind(ni.get("commitment_kind"))
        try:
            end_turn_marker_shape = _strict_int(
                0 if ni.get("end_turn", 0) in (None, "") else ni.get("end_turn", 0)
            ) > 0
        except (TypeError, ValueError, OverflowError) as exc:
            # 在场坏 end_turn ≠ 缺席无标记；逐项拒收，不洗成 False 走常形。
            entity_rejections.append(RejectedItem(
                item=ni,
                reason=f"new_issue end_turn 非法：{ni.get('end_turn')!r}（{exc}）",
                category="invalid_enum",
                source=source,
            ))
            continue
        commitment_shape_without_marker = (
            not commitment_kind
            and kind == "initiative"
            and (
                end_turn_marker_shape
                or (isinstance(stop_condition_raw, (dict, list)) and bool(stop_condition))
                or (
                    isinstance(stop_condition_raw, str)
                    and bool(str(stop_condition).strip())
                    and bool(origin_ref)
                    and not resolve_eff
                    and not fail_eff
                )
                or (semantic_ongoing_has_work and not resolve_eff and not fail_eff and bool(origin_ref))
            )
        )
        if commitment_shape_without_marker:
            entity_rejections.append(RejectedItem(item=ni, reason="new_issue commitment_kind 必填（承诺形态不得靠 origin_kind/字段形状推断）", category="invalid_enum", source=source))
            continue
        is_commitment = bool(commitment_kind)
        if is_commitment:
            need_stop_validate = False
            try:
                if kind != "initiative":
                    raise ValueError("kind 须为 initiative")
                if not origin_ref:
                    raise ValueError("origin_ref 必填，须指回诏书")
                _et_raw = ni.get("end_turn", 0)
                end_turn_for_commitment = _strict_int(0 if _et_raw in (None, "") else _et_raw)
                if (
                    ongoing_has_work
                    and end_turn_for_commitment > 0
                    and end_turn_for_commitment <= int(state.turn)
                ):
                    raise ValueError(
                        f"end_turn 必须大于当前 turn（{state.turn}）；"
                        "有月度持续动作的承诺不能立项即到期"
                    )
                invalid_person_rating = issue_records._invalid_monthly_person_rating_reason(ongoing_eff)
                if invalid_person_rating:
                    raise ValueError(f"ongoing_effects {invalid_person_rating}")
                if unsupported_ongoing_fields:
                    raise ValueError(
                        "ongoing_effects 含非月度持续字段："
                        + ", ".join(unsupported_ongoing_fields)
                    )
                from ming_sim.staged_commitment import (
                    stages_list_from_source,
                    stages_source_from_issue_item,
                )
                stages_for_commitment = stages_list_from_source(
                    stages_source_from_issue_item(ni),
                )
                has_stages = bool(stages_for_commitment)
                if not ongoing_has_work and end_turn_for_commitment <= 0 and not has_stages:
                    raise ValueError("ongoing_effects、end_turn 或 stages 至少一项必填")
                if stop_condition_raw in (None, "", {}):
                    if end_turn_for_commitment <= 0 and not ongoing_has_work and not has_stages:
                        raise ValueError("stop_condition 须为非空 dict，除非承诺带 end_turn 或 stages")
                    need_stop_validate = False
                    stop_condition = ""
            except (TypeError, ValueError, OverflowError) as exc:
                entity_rejections.append(RejectedItem(item=ni, reason=f"new_issue commitment 字段非法（origin_ref/ongoing_effects/stop_condition）：{exc}", category="invalid_enum", source=source))
                continue
            try:
                if stop_condition_raw not in (None, "", {}):
                    stop_condition = issue_records._validate_commitment_stop_condition(stop_condition_raw, state, db)
                origin_ref = db.resolve_commitment_origin_ref(
                    state, origin_ref, origin_kind=str(ni.get("origin_kind") or ""),
                )
            except DeclarationDataError as exc:
                entity_rejections.append(RejectedItem(item=ni, reason=str(exc), category="invalid_enum", source=source))
                continue
            origin_error = db.effect_origin_rejection(origin_ref)
            if origin_error:
                entity_rejections.append(RejectedItem(item=ni, reason=origin_error["reason"], category=origin_error["category"], source=source))
                continue
        # 国策效果由上游语义转译/声明供给；落账核不再调用旧 initiative 效果设计补全。
        # 字段强转脏数据 → 拒整项（ADR 0008 决定 1：new_issue 即「项」，坏字段令该项无法洁净构造
        # → 拒留痕，非默认掩盖）。这些强转会因脏 LLM 数据抛：bar_value/severity 的 int()、
        # tags 的 list(5)、issue_records._compute_inertia 的 legacy `int(inertia)`
        # 回退（其 expected_months 路自带兜底，但旧 inertia 字段在 try 外，cmr ni r2 codex）。
        # issue_records._normalize_cancellable / 各 str() 自带兜底不抛。原 except Exception WARN-skip 整项保留为
        # 「拒收留痕」，insert 的代码/DB 异常分出去上抛。
        try:
            # 整数字段用 _strict_int（与 region/army/faction 段一致）：拒 bool/float（int(3.7)=3 截断、
            # int(True)=1 都非合法整数 delta，cmr ni r6 codex）+ 非数串/inf/nan/超界。缺省/null → 默认，
            # 0 须保留（原 `or 50` 把合法 severity=0 静默改 50=保真 bug，cmr ni r4）；脏值落 except 拒整项。
            _bv = ni.get("bar_value", 25)
            bar_value = _strict_int(25 if _bv is None else _bv)
            _sv = ni.get("severity", 50)
            severity = _strict_int(50 if _sv is None else _sv)
            _et = ni.get("end_turn", 0)
            end_turn = _strict_int(0 if _et in (None, "") else _et)
            # tags 严格化：缺省/null/空串 → []；present 必须是 list/tuple 且元素全为 str。
            # 拒标量串拆字与非串元素静默落库。
            _tags_raw = ni.get("tags")
            if _tags_raw is None or _tags_raw == "":
                tags = []
            elif isinstance(_tags_raw, (list, tuple)) and all(isinstance(t, str) for t in _tags_raw):
                tags = list(_tags_raw)
            else:
                raise ValueError(f"tags 须为字符串列表（拒标量串拆字 / 非串元素）：{_tags_raw!r}")
            if "inertia" in ni:
                raise ValueError("new_issues.inertia 已退役，使用 expected_months")
            inertia = issue_records._compute_inertia(ni)
            if is_commitment:
                inertia = 0
            cancellable_norm = (
                "decree" if is_commitment
                else issue_records._normalize_cancellable(ni.get("cancellable"))
            )
        except (TypeError, ValueError, OverflowError) as exc:
            # OverflowError：JSON 里 1e309 解析成 float('inf')，超界 int 绑定亦抛；_strict_int 已把
            # float（含 inf/nan）归 ValueError，OverflowError 兜超大 int 等残余路（cmr ni r3 codex）。
            entity_rejections.append(RejectedItem(item=ni, reason=f"new_issue 字段强转失败（bar_value/severity/end_turn/tags/inertia 脏数据）：{exc}", category="invalid_enum", source=source))
            continue
        raw_resolve = ni.get("resolve_condition")
        resolve_condition = issue_records._issue_condition_text(raw_resolve)
        if isinstance(raw_resolve, str) and raw_resolve.strip():
            resolve_stored = raw_resolve
        else:
            resolve_stored = resolve_condition
        # A structured roster is an item-level contract.  In particular a
        # mapping is not an iterable roster: iterating it would persist its
        # keys (\"character_id\", \"tier\") as phantom participants.
        roster_input = next(
            (ni.get(key) for key in ("participant_roster", "participants", "participant_names", "actors")
             if ni.get(key) is not None),
            None,
        )
        if roster_input is not None:
            try:
                if not isinstance(roster_input, (list, tuple)):
                    raise ValueError("participant_roster 须为列表")
                for participant in roster_input:
                    if isinstance(participant, str):
                        if not participant.strip():
                            raise ValueError("participant_roster 人名不得为空")
                        continue
                    if not isinstance(participant, dict):
                        raise ValueError("participant_roster 每项须为对象或人名")
                    if not str(participant.get("character_id") or participant.get("name") or "").strip():
                        raise ValueError("participant_roster 每项须有 character_id")
                    # 缺省「知情」为既有可选字段契约；封闭枚举校验保留（不作一律删除）.
                    # #1847：不把缺字段升格为必填拒收护栏。
                    tier = str(participant.get("tier") or participant.get("档") or "知情").strip()
                    if tier not in {"主办", "协办", "知情"}:
                        raise ValueError(f"participant_roster tier 非法：{tier}")
            except ValueError as exc:
                entity_rejections.append(RejectedItem(item=ni, reason=str(exc), category="invalid_participant_roster", source=source))
                continue
        # insert_issue 不再裹 broad except：代码/DB 异常上抛 → SettlementAbort（ADR 0005 fail-loud），
        # 不再当 WARN 吞（那会半落库 + 丢决策，违 P1 铁律）。
        # 注：字符串字段含孤代理（JSON 解析出的 "\\ud800"）会在 SQLite bind 抛 UnicodeEncodeError。
        # 原文不在 SQLite bind 前改写；包括 UnicodeEncodeError 在内的持久写故障
        # 上抛并回滚，JSON 序列化只在编码层转义、不改变载荷的 codepoints。
        # Validate typed affair authority before any write. A decree issue may be
        # grounded either by a promulgated dossier or by its typed affair declaration.
        from ming_sim.entities.affair import ATTACH_BIRTH, declaration_from_payload
        try:
            issue_affair = declaration_from_payload(ni, allowed=ATTACH_BIRTH)
        except (TypeError, ValueError) as exc:
            entity_rejections.append(RejectedItem(item=ni, reason=str(exc), category="invalid_enum", source=source))
            continue
        if (
            issue_affair is not None
            and issue_affair.get("attach") == "existing"
            and isinstance(open_affair_ids_at_input, set)
            and int(issue_affair["affair_id"]) not in open_affair_ids_at_input
        ):
            entity_rejections.append(RejectedItem(item=ni, reason="事务不在本批可见输入", category="invalid_enum", source=source))
            continue
        origin_error = db.effect_origin_rejection(origin_ref) if origin_ref else None
        dossier_origin = bool(re.fullmatch(r"dossier:[1-9][0-9]*", origin_ref))
        if issue_affair is None and (not dossier_origin or origin_error):
            entity_rejections.append(RejectedItem(item=ni, reason=(origin_error or {}).get(
                    "reason", "new decree issue 须有已颁 dossier:<id> 或合法事务声明"
                ), category="missing_ref", source=source))
            continue
        if issue_affair is not None and dossier_origin:
            try:
                db.affairs.assert_origin_matches_declaration(origin_ref, issue_affair)
            except (DeclarationReferenceError, DeclarationDataError) as exc:
                entity_rejections.append(RejectedItem(item=ni, reason=str(exc), category="invalid_enum", source=source))
                continue
        from ming_sim.staged_commitment import (
            stages_list_from_source,
            stages_source_from_issue_item,
        )
        stages_norm = (
            stages_list_from_source(stages_source_from_issue_item(ni))
            if is_commitment
            else []
        )
        # 段派生 end_turn（max stage due）不落 DB；落库会在末段到期 + ongoing 时误走 mechanical expire（#620）。
        # issue+affair 成对写由 GameDB 拥有（ADR 0150-D3）；本段不自包事务生命周期。
        _issue_fields = dict(
            kind=kind,
            title=title if str(title).strip() else "无名事项",
            origin_kind="decree",
            origin_ref=origin_ref,
            bar_value=bar_value,
            bar_good_meaning=str(ni.get("bar_good_meaning") or "已成"),
            bar_bad_meaning=str(ni.get("bar_bad_meaning") or "废止"),
            inertia=inertia,
            stage_text=str(ni.get("stage_text") or ""),
            severity=severity,
            region_hint=str(ni.get("region_hint") or ""),
            faction_hint=str(ni.get("faction_hint") or ""),
            tags=tags,
            # Keep ADR 0053's structured roster intact.  insert_issue writes the
            # compatibility name list and the durable roster together; reducing
            # dict entries to str(dict) creates phantom character names.
            participants=roster_input or [],
            ongoing_effects=ongoing_eff,
            cancellable="decree" if is_commitment else issue_records._normalize_cancellable(ni.get("cancellable")),
            effect_on_resolve=resolve_eff,
            effect_on_fail=fail_eff,
            resolve_condition=resolve_stored,
            fail_condition=str(ni.get("fail_condition") or ""),
            end_turn=end_turn,
            stop_condition=stop_condition,
            commitment_kind=commitment_kind,
            stages_json=stages_norm,
            commit=False,
        )
        if issue_affair is not None:
            issue_id = db.insert_issue_with_affair_declaration(
                state,
                affair_declaration=issue_affair,
                authorized_ids=(
                    open_affair_ids_at_input
                    if isinstance(open_affair_ids_at_input, set) else None
                ),
                **_issue_fields,
            )
        else:
            issue_id = db.insert_issue(state, **_issue_fields)
        applied_item = {"issue_id": issue_id, "kind": kind, "title": title}
        if commitment_kind:
            applied_item["commitment_kind"] = commitment_kind
        if stages_norm:
            applied_item["stages"] = stages_norm
        applied_new.append(applied_item)

    # 3) closes（LLM 主动结案/失败，不看 bar 门槛）
    applied_closes: List[Dict[str, object]] = []
    for cl in tracker_output.get("close_issues", []) or []:
        # ADR 0008 决定 1：LLM 脏数据逐项拒收留痕（坏 id/reason/陈旧引用），不静默丢；
        # db.close_issue 的代码/DB 异常不再 WARN 吞，上抛触发 SettlementAbort（ADR 0005 fail-loud）。
        if not isinstance(cl, dict):
            # 非 dict 项（如 close_issues:[null]/标量，_sanitize 不清列表项可达）：cl.get 会抛
            # AttributeError（不在下方 except 内）崩整月——逐项拒收，不让坏项带走整批（codex r4）。
            entity_rejections.append(RejectedItem(item={"raw_value": cl}, reason=f"close_issues 条目非对象（应为 dict）：{cl!r}", category="invalid_enum", source=source))
            continue
        try:
            # _parse_sqlite_id：非整数/bool/float/超 SQLite 64-bit 范围 → ValueError（含 10**100
            # 这类 int() 过得了但绑定 SQLite 抛 OverflowError 的脏 id，避免上抛崩整月，codex r1）。
            issue_id = strict_types._parse_sqlite_id(cl.get("issue_id"))
        except (TypeError, ValueError):
            entity_rejections.append(RejectedItem(item=cl, reason=f"close_issues issue_id 非法（非整数或超 SQLite 范围）：{cl.get('issue_id')!r}", category="invalid_enum", source=source))
            continue
        reason = str(cl.get("reason") or "").strip().lower()
        if reason not in ("resolved", "failed", "acknowledged"):
            entity_rejections.append(RejectedItem(item=cl, reason=f"close_issues reason 非法 '{reason}'（须 resolved/failed/acknowledged），issue {issue_id}", category="invalid_enum", source=source))
            continue
        narrative = str(cl.get("narrative") or "")
        chk = db.conn.execute(
            "SELECT * FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        if reason == "acknowledged":
            from ming_sim.staged_commitment import is_stage_derived_end_turn
            if chk is None:
                category, why = "missing_ref", f"close_issues 引用未找到的 issue {issue_id}"
            elif chk["status"] != "active":
                category, why = "missing_ref", f"close_issues 引用已非 active（{chk['status']}）的 issue {issue_id}"
            elif not str(chk["commitment_kind"] or "").strip():
                category, why = "invalid_enum", f"close_issues acknowledged 只允许到期待裁承诺 issue {issue_id}"
            elif effect_dict_has_work(chk["ongoing_effects"]):
                category, why = "invalid_enum", f"close_issues acknowledged 不允许收尾持续承诺 issue {issue_id}"
            elif int(chk["end_turn"] or 0) <= 0 or int(chk["end_turn"] or 0) > int(state.turn):
                category, why = "invalid_enum", f"close_issues acknowledged 只允许已到期承诺 issue {issue_id}"
            elif is_stage_derived_end_turn(chk["stages_json"], int(chk["end_turn"] or 0)):
                category, why = (
                    "invalid_enum",
                    f"close_issues acknowledged 不得收尾段派生 end_turn 承诺 issue {issue_id}",
                )
            else:
                new_row = issue_records._ack_due_commitment_issue(
                    db,
                    state,
                    chk,
                    narrative=narrative,
                )
                applied_closes.append({"issue_id": issue_id, "title": new_row["title"], "reason": reason, "narrative": narrative})
                continue
            entity_rejections.append(RejectedItem(item=cl, reason=why, category=category, source=source))
            continue
        if (
            reason in ("resolved", "failed")
            and chk is not None
            and chk["status"] == "active"
            and str(chk["commitment_kind"] or "").strip()
        ):
            entity_rejections.append(RejectedItem(item=cl, reason=f"close_issues 对承诺型 issue {issue_id} 误判 {reason}（须走专门完成闭环）", category="invalid_enum", source=source))
            continue
        new_row = db.close_issue(
            state,
            issue_id,
            reason=reason,
            narrative=narrative,
            commit=False,
        )
        if new_row is None:
            # close_issue 回 None 有三态，回查 status 精确归类（cmr Claude high）：
            #   ① 未找到 / ② 已非 active → 陈旧/幻觉引用（missing_ref）；
            #   ③ 找到且仍 active 却被拒 → close_issue 唯一剩余 None 路径＝reason=failed 用于
            #      不可崩坏局势（无 effect_on_fail，保持 active）＝LLM 语义误判（invalid_enum），非「未找到」。
            chk = db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
            if chk is None:
                category, why = "missing_ref", f"close_issues 引用未找到的 issue {issue_id}"
            elif chk["status"] != "active":
                category, why = "missing_ref", f"close_issues 引用已非 active（{chk['status']}）的 issue {issue_id}"
            elif reason == "failed":
                # 找到且 active 却被拒，今天 close_issue 唯一这条 active-None 路径＝reason=failed
                # 用于无 effect_on_fail 的不可崩坏局势（LLM 语义误判，保持 active）。
                category, why = "invalid_enum", (
                    f"close_issues 对不可崩坏局势 issue {issue_id} 误判 failed"
                    "（无 effect_on_fail，拒结案、保持 active）"
                )
            else:
                # reason=resolved 对 active issue 今天必返回非 None（不可达此分支）；留通用兜底
                # 防 close_issue 未来新增 active-None 路径时消息说谎（gemini-code-assist）。
                category, why = "invalid_enum", f"close_issues 结案被拒、issue {issue_id} 保持 active"
            entity_rejections.append(RejectedItem(item=cl, reason=why, category=category, source=source))
            continue
        # 终结效果：以 issue 立项时预设的 effect 为底，叠加 LLM 在本次结案项 cl 里现给的 effect。
        # 现给优先——event_pool 预设 issue（如阉党之祸）立项时 effect 多为空，帝国修正只能结案当下给。
        if reason == "resolved":
            effect = loads_effect_dict(new_row["effect_on_resolve"])
            cl_effect = cl.get("effect_on_resolve")
        else:
            effect = loads_effect_dict(new_row["effect_on_fail"])
            cl_effect = cl.get("effect_on_fail")
        if isinstance(cl_effect, dict):
            # 浅合并：metrics/economy/factions/buildings/legacy 等顶层段，现给覆盖预设
            effect = {**effect, **cl_effect}
        elif cl_effect is not None:
            entity_rejections.append(RejectedItem(
                item={"issue_id": issue_id, "field": "effect_on_resolve" if reason == "resolved" else "effect_on_fail", "raw_value": cl_effect},
                reason="局势结案后果须为对象", category="invalid_shape", source=source,
            ))
        parent_origin_ref = issue_records._canonical_issue_origin(db, new_row)
        building_ops: List[Dict[str, object]] = []
        close_person_changes: List[Dict[str, object]] = []
        entity_rejections.extend(issue_effects._apply_issue_entities(
            db,
            state,
            effect,
            f"局势#{issue_id}{'结案' if reason == 'resolved' else '失败'}",
            content=runtime_content,
            llm_config=llm_config,
            applied_person_changes=close_person_changes, applied_buildings=building_ops,
            issue_id=issue_id, issue_title=str(new_row["title"]),
                                 origin_ref=parent_origin_ref,
        source=source))
        issue_person_changes.extend(close_person_changes)
        close_record = {
            "issue_id": issue_id,
            "title": new_row["title"],
            "reason": reason,
            "narrative": narrative,
            "building_ops": building_ops,
        }
        if close_person_changes:
            close_record["applied_person_changes"] = close_person_changes
        applied_closes.append(close_record)

    # 4) cancels
    for cn in tracker_output.get("cancels", []) or []:
        try:
            issue_id = int(cn.get("issue_id"))
        except (TypeError, ValueError):
            continue
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if row is None or row["status"] != "active":
            continue
        if row["cancellable"] != "decree":
            # 不可撤：当作 advance 处理（皇威 -2）
            db.advance_issue(
                state, issue_id,
                trigger_kind="decree",
                delta_bar=0,
                stage_text=row["stage_text"],
                narrative=str(cn.get("narrative") or "陛下欲罢，然此事非诏可消。"),
                metric_delta={"皇威": -2},
                commit=False,
            )
            state.metrics["皇威"] = max(0, int(state.metrics.get("皇威", 0)) - 2)
            entity_rejections.append(RejectedItem(item={"issue_id": issue_id, "title": row["title"]}, reason="此事非诏可消（不可撤国策），已转强行推进并损皇威 2 点。", category="non_cancellable_converted", source=source))
            continue
        # #1894 / ADR 0075 后出修订：明确撤令（cancels）不再强制挽留下一场。
        # 若已有他类松手产生的 pending 改弦条，cancel=坚持撤 → finalize_persist；
        # 无 pending 则直接落入下方可撤成命路径（外廷准行当月见结果）。
        if str(row["commitment_kind"] or "").strip():
            from ming_sim.breach_plea import (
                BREACH_KIND_POLICY_REVERSAL,
                finalize_persist,
                find_pending_plea,
            )
            plea_todo = find_pending_plea(
                db, issue_id, breach_kind=BREACH_KIND_POLICY_REVERSAL,
            )
            if plea_todo is not None:
                finalize_persist(db, state, plea_todo)
                applied_cancels.append({"issue_id": issue_id, "title": row["title"], "breach_plea_decision": "persist"})
                continue
        # 可撤成命：若事项来自已颁案卷，ADR 0056 的确定性毁约轨拥有撤旨后果，
        # 防同一次撤旨双罚。
        linked_dossier = None
        origin_ref = str(row["origin_ref"] or "").strip()
        if re.fullmatch(r"dossier:[1-9][0-9]*", origin_ref) and db.effect_origin_rejection(origin_ref) is None:
            linked_dossier = db.get_decree_dossier(int(origin_ref.split(":", 1)[1]))
        deterministic_breach = bool(
            linked_dossier
            and (
                linked_dossier["status"] in {"promulgated", "executing"}
                or (
                    linked_dossier["status"] == "closed"
                    and bool(row["commitment_kind"])
                    and db.dossier_authorizes_effects(int(linked_dossier["id"]))
                )
            )
        )
        if deterministic_breach:
            # #1894 / ADR 0075：明确撤令只落 0056 名声账，不抢关原案卷；
            # 结案留给执行格判官本月 dossier_executions（同 finalize_persist / 撤旨尾）。
            db.breach_decree_dossier(
                state, int(linked_dossier["id"]),
                reason=str(cn.get("narrative") or "撤回成命"), commit=False,
            )
        raw_cost = cn.get("applied_cost")
        cost = {} if raw_cost is None or deterministic_breach else raw_cost
        if deterministic_breach and raw_cost:
            entity_rejections.append(RejectedItem(
                item={"field": "applied_cost", "raw_value": raw_cost},
                reason="撤旨后果由案卷执行格拥有", category="invalid_transition", source=source,
            ))
        if not isinstance(cost, dict):
            entity_rejections.append(RejectedItem(
                item={"field": "applied_cost", "raw_value": cost},
                reason="撤回后果须为对象", category="invalid_shape", source=source,
            ))
            cost = {}
        parent_origin_ref = issue_records._canonical_issue_origin(db, row)
        entity_rejections.extend(issue_effects._apply_issue_entities(
            db, state, cost, f"局势#{issue_id}撤回", content=runtime_content,
            llm_config=llm_config, applied_person_changes=issue_person_changes,
            issue_id=issue_id, issue_title=str(row["title"]),
            origin_ref=parent_origin_ref, source=source,
        ))
        db.cancel_issue(
            state, issue_id,
            narrative=str(cn.get("narrative") or ""),
            applied_cost=cost if isinstance(cost, dict) else {},
            commit=False,
        )
        applied_cancels.append({"issue_id": issue_id, "title": row["title"]})

    state.clamp()
    return IssueSectionResult(
        advances=applied_advances, new_issues=applied_new,
        closes=applied_closes, cancels=applied_cancels,
        rejected=entity_rejections, applied_person_changes=issue_person_changes,
    )
