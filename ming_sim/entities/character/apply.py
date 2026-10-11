"""人物变更落库核。

写核住在人物实体（ADR 0150 决定 1/8）。局势模块与其它调用方引用本函数，
不再在 ``issues`` 里留一份平行实现。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
if TYPE_CHECKING:
    from ming_sim.db import GameDB
    from ming_sim.models import GameState


def identity_title_for_allegiance(item: Dict[str, object], new_power: str) -> str:
    """易主落库身名分唯一真源：显式白名单标题，或归附/降臣缺省。"""
    from ming_sim.person_archive_contract import PERSON_IDENTITY_TITLES

    title = str(item.get("new_title") or item.get("title") or "").strip()
    if title:
        return title if title in PERSON_IDENTITY_TITLES else ""
    way = str(item.get("方式") or item.get("way") or "").strip()
    if new_power == "ming" or way == "主动归附":
        return "归附"
    return "降臣"


def allegiance_change_rejection(
    item: Dict[str, object],
    row: Any,
    *,
    db: Any = None,
    origin_ref: str = "",
    require_origin: bool = False,
) -> Optional[Tuple[str, str]]:
    """易主准入唯一权威：返回 (reason, category) 拒收，或 None 表示可落。

    只供人物写核调用；禁止对待落项另立平行预判副本。
    """
    from ming_sim.person_archive_contract import (
        PERSON_ALLEGIANCE_CHANGE_WAYS,
        resolve_person_transition,
    )
    from ming_sim.strict_types import _parse_sqlite_id

    way = str(item.get("方式") or item.get("way") or "").strip()
    backlash = item.get("反噬", item.get("backlash"))
    if not way:
        return ("易主 缺 方式", "missing_field")
    if way not in PERSON_ALLEGIANCE_CHANGE_WAYS:
        return ("易主 方式非白名单", "invalid_enum")
    if not isinstance(backlash, dict):
        return ("易主 缺 反噬", "missing_field")
    if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
        return ("易主 反噬 项必须是 object(dict)", "invalid_enum")
    if row is None:
        return ("非既有人物", "hallucinated_id")
    cur_status = str(row["status"] or "active")
    transition = resolve_person_transition(
        cur_status,
        "易主",
        reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
    )
    if transition.startswith("reject:"):
        return (
            f"{cur_status} 无 易主 出边",
            transition.removeprefix("reject:") or "invalid_transition",
        )
    requested_new_power = str(item.get("new_power") or "").strip()
    if not requested_new_power:
        return ("易主 缺 new_power", "missing_field")
    old_power = str(row["power_id"] or "").strip()
    if way == "主动归附" and requested_new_power == "ming":
        backlash_power_ids = {
            str(power_id).strip()
            for power_id in backlash.keys()
            if str(power_id).strip()
        }
        if any(power_id != old_power for power_id in backlash_power_ids):
            return (
                f"主动归附反噬只能指向原势力股 {old_power}",
                "invalid_transition",
            )
    if not identity_title_for_allegiance(item, requested_new_power):
        return ("易主 new_title 非身名分白名单", "invalid_enum")
    if require_origin and db is not None:
        error = db.effect_origin_rejection(origin_ref)
        if error:
            return (str(error["reason"]), str(error["category"]))
        if str(origin_ref or "").startswith("dossier:"):
            dossier_id = _parse_sqlite_id(str(origin_ref).split(":", 1)[1])
            dossier = db.dossiers.get(dossier_id) if dossier_id else None
            if dossier is not None:
                action_type = str(dossier.get("action_type") or "").strip()
                if (
                    action_type == "special_decree"
                    and way == "主动归附"
                    and requested_new_power == "ming"
                ):
                    return ("special_decree 不得授权招抚易主", "invalid_origin_ref")
                if action_type == "pacification":
                    payload = dossier["payload"]
                    bound_target = str(
                        payload.get("target_id") or dossier.get("target_id") or ""
                    ).strip()
                    name = str(item.get("name") or "").strip()
                    if not bound_target or name != bound_target:
                        return (
                            f"招抚案卷仅可易主 {bound_target or '案卷目标'}，不得易主 {name}",
                            "invalid_origin_ref",
                        )
    return None


def apply_person_changes(
    db: GameDB,
    state: GameState,
    changes: List[Dict[str, object]],
    content=None,
    llm_config: Any = None,
    source: str = "system_simulation",
    derived_from: str = "",
    origin_ref: str = "",
    require_origin: bool = False,
) -> Tuple[List[Dict[str, object]], List[RejectedItem]]:
    pass

    import ming_sim.entities.character.appointment as office_appointment
    from ming_sim.appointment_tenure import appointment_tenure_from
    from ming_sim.person_archive_contract import (
        PERSON_ALLEGIANCE_CHANGE_WAYS,
        PERSON_IDENTITY_TITLES,
        normalize_reason_code,
        resolve_person_transition,
    )
    from ming_sim.strict_types import _parse_sqlite_id
    from ming_sim.entities.character.appointment import _payload_owned_person_duplicate
    from ming_sim.entities.character.transit import admit_transit_departure, load_valid_regions

    def rejected(item, reason, category, *, status=None) -> RejectedItem:
        return RejectedItem(item=item, reason=reason, category=category, source=source)

    def project_appointment_result(item, result):
        if isinstance(result, RejectedItem):
            result.item = item
        return result

    def origin_rejected(item: Dict[str, object]) -> RejectedItem | None:
        error = db.effect_origin_rejection(origin_ref) if require_origin else None
        return rejected(item, str(error["reason"]), str(error["category"])) if error else None

    def character_row(name: str):
        return db.conn.execute(
            "SELECT name, status, office, office_type, power_id, status_reason, "
            "status_changed_turn, reason_code, transit_to, transit_distance_remaining, "
            "transit_speed_factor, transit_start_turn "
            "FROM characters WHERE name=?",
            (name,),
        ).fetchone()

    def log_applied(
        result: Dict[str, object],
        item: Dict[str, object],
    ) -> None:
        if isinstance(result, RejectedItem):
            return
        name = str(result.get("name") or "").strip()
        action = str(result.get("动作") or result.get("action") or "").strip()
        if not name or not action:
            return
        if db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone() is None:
            return
        summary = (
            str(result.get("reason") or item.get("reason") or "")
            or str(result.get("new_office") or result.get("office") or "")
            or str(result.get("status") or result.get("new_power") or result.get("transit_to") or "")
        )
        normalized = {
            key: value
            for key, value in result.items()
            if key not in {"rejected", "category", "item"}
        }
        db.record_person_log(
            state,
            name,
            action,
            payload_summary=summary,
            derived_from=str(result.get("derived_from") or derived_from or ""),
            normalized=normalized,
            source=source,
            commit=False,
            origin_ref=origin_ref,
        )

    def displaced_talent_pool_results(displaced_parts: object) -> List[Dict[str, object]]:
        if not isinstance(displaced_parts, list):
            return []
        results: List[Dict[str, object]] = []
        for part in displaced_parts:
            name_part = str(part).split(":", 1)[0].strip()
            if not name_part:
                continue
            row = character_row(name_part)
            if row is None:
                continue
            if str(row["office"] or "") != "听用候铨" or str(row["reason_code"] or "") != "被顶替":
                continue
            results.append(
                {
                    "name": name_part,
                    "动作": "处置",
                    "status": "active",
                    "reason": "被顶替",
                    "reason_code": "被顶替",
                    "office": "听用候铨",
                    "office_type": "身名分",
                    "derived_from": "被顶替",
                    # applier 合成级联回声：信用写端只消费 extractor 宣告本体行。
                    "cascade_echo": True,
                }
            )
        return results

    applied: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    person_statuses = {
        "active",
        "offstage",
        "dismissed",
        "imprisoned",
        "exiled",
        "retired",
        "dead",
    }
    disposition_statuses = person_statuses - {"active"}
    for item in changes:
        name = str(item.get("name") or "").strip()
        action = str(item.get("动作") or "").strip()
        if not name or not action:
            rejections.append(rejected(item, "name 或 动作 缺失", "missing_field"))
            continue
        if content is not None:
            from ming_sim.session import _find_existing_minister
            canon = _find_existing_minister(content, name, db)
            if canon:
                name = canon

        if action == "评定":
            if content is not None and name not in content.characters:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = db.conn.execute(
                "SELECT name, loyalty FROM characters WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            raw_delta = item.get("loyalty")
            if isinstance(raw_delta, bool) or not isinstance(raw_delta, int) or raw_delta == 0:
                rejections.append(rejected(item, "评定 loyalty 须为非零整数增量", "invalid_enum"))
                continue
            old_loyalty = int(row["loyalty"])
            new_loyalty = max(0, min(100, old_loyalty + raw_delta))
            origin_error = origin_rejected(item)
            if origin_error:
                rejections.append(origin_error)
                continue
            db.conn.execute(
                "UPDATE characters SET loyalty=? WHERE name=?",
                (new_loyalty, name),
            )
            if content is not None and name in content.characters:
                content.characters[name].loyalty = new_loyalty
            result = {
                "name": name,
                "动作": action,
                "loyalty": raw_delta,
                "old_loyalty": old_loyalty,
                "new_loyalty": new_loyalty,
                "reason": str(item.get("reason") or ""),
            }
            applied.append(result)
            log_applied(result, item)
            continue

        if action == "性情":
            if content is not None and name not in content.characters:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = db.conn.execute(
                "SELECT name, style FROM characters WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            raw_style = item.get("style")
            if not isinstance(raw_style, str) or not raw_style.strip():
                rejections.append(rejected(item, "性情 style 须为非空字符串", "invalid_enum"))
                continue
            # 空白探测仅作拒收；自由文本正文按原串字节透传（P6 / ADR 0142）。
            new_style = raw_style
            old_style = str(row["style"] or "")
            origin_error = origin_rejected(item)
            if origin_error:
                rejections.append(origin_error)
                continue
            db.conn.execute(
                "UPDATE characters SET style=? WHERE name=?",
                (new_style, name),
            )
            if content is not None and name in content.characters:
                content.characters[name].style = new_style
            result = {
                "name": name,
                "动作": action,
                "style": new_style,
                "old_style": old_style,
                "new_style": new_style,
                "reason": str(item.get("reason") or ""),
            }
            applied.append(result)
            log_applied(result, item)
            continue

        if action in {"处置", "罢黜"}:
            status = "dismissed" if action == "罢黜" else str(item.get("status") or "").strip()
            reason_text = str(item.get("reason") or item.get("status_reason") or "")
            if status not in person_statuses:
                rejections.append(rejected(item, "status 非白名单", "invalid_enum", status=status))
                continue
            if status not in disposition_statuses:
                rejections.append(
                    rejected(
                        item,
                        "处置 不直接迁入 active，走任命级联",
                        "invalid_transition",
                        status=status,
                    )
                )
                continue
            if content is not None and name not in content.characters:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id", status=status))
                continue
            row = db.conn.execute("SELECT name FROM characters WHERE name=?", (name,)).fetchone()
            if row is None:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id", status=status))
                continue
            cur_status, _ = db.characters.get_character_status(name)
            reason_code = normalize_reason_code(item.get("reason_code"))
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=reason_code,
            )
            if transition.startswith("reject:"):
                reject_reason = f"{cur_status} 无 {action} 出边"
                if cur_status == "dead" and status != "dead":
                    reject_reason = "dead 无 status 出边"
                rejections.append(
                    rejected(
                        item,
                        reject_reason,
                        transition.removeprefix("reject:") or "invalid_transition",
                        status=status,
                    )
                )
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                rejections.append(origin_error)
                continue
            if action == "罢黜" and _payload_owned_person_duplicate(db, item):
                continue
            db.set_character_status(
                state,
                name,
                status,
                reason_text,
                reason_code=reason_code if reason_code else None,
                content=content,
                commit=False,
            )
            result = {
                "name": name,
                "动作": action,
                "status": status,
                "reason": reason_text,
            }
            if reason_code:
                result["reason_code"] = reason_code
            applied.append(result)
            log_applied(result, item)
            continue

        if action in {"任命", "调任"}:
            # 别名归一已在动作分派前统一完成，确保任命与处置/行止/易主同口径。
            try:
                appointment_tenure = appointment_tenure_from(item)
            except ValueError as exc:
                rejections.append(rejected(item, str(exc), "invalid_enum"))
                continue
            if content is not None and name not in content.characters:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = character_row(name)
            if row is None:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            current_office = str(row["office"] or "").strip()
            current_office_type = str(row["office_type"] or "").strip()
            current_title_kind = (
                "身名分"
                if not current_office
                or current_office_type == "身名分"
                or current_office in PERSON_IDENTITY_TITLES
                else "职名分"
            )
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                action,
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
                current_title_kind=current_title_kind,
            )
            if transition.startswith("reject:"):
                rejections.append(
                    rejected(
                        item,
                        f"{row['status']} 无 {action} 出边",
                        transition.removeprefix("reject:") or "invalid_transition",
                    )
                )
                continue
            derive_label = transition.removeprefix("derive:") if transition.startswith("derive:") else ""
            effective_action = transition.removeprefix("normalize:") if transition.startswith("normalize:") else action
            new_office = str(item.get("office") or item.get("new_office") or "")
            if not new_office.strip():
                result = rejected(item, "name 或 new_office 空", "missing_field")
                rejections.append(result)
                continue
            if content is None:
                if _payload_owned_person_duplicate(
                    db,
                    item,
                    current_office_type=current_office_type,
                    llm_config=llm_config or db.llm_config,
                ):
                    continue
                result = project_appointment_result(
                        item,
                        office_appointment.apply_office_appointment(
                            db,
                            state,
                            content,
                            name,
                            new_office,
                            reason=str(item.get("reason") or ""),
                            new_office_type=str(item.get("office_type") or item.get("new_office_type") or ""),
                            faction=str(item.get("faction") or "中立"),
                            appointment_tenure=appointment_tenure,
                            region_id=str(
                                item.get("region_id")
                                or item.get("任所")
                                or item.get("辖区")
                                or ""
                            ).strip(),
                            llm_config=llm_config,
                            source=source,
                        ),
                    )
                if isinstance(result, RejectedItem):
                    rejections.append(result)
                    continue
                result = {"动作": effective_action, **result}
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            row_power_id = str(row["power_id"] or "").strip()
            content_power_id = ""
            if content is not None and name in content.characters:
                content_power_id = str(getattr(content.characters[name], "power_id", "") or "").strip()
            effective_power_id = row_power_id or content_power_id or "ming"
            if effective_power_id != "ming":
                result = rejected(
                    item,
                    f"{name}不属大明朝廷，不能授予大明官职",
                    "invalid_transition",
                )
                rejections.append(result)
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                rejections.append(origin_error)
                continue
            if _payload_owned_person_duplicate(
                db,
                item,
                current_office_type=str(content.characters[name].office_type or ""),
                llm_config=llm_config or db.llm_config,
            ):
                continue
            # 派生任命（放归/赦还）是复合写：前置 status 迁移会 interrupt 案卷。
            # 项级 SAVEPOINT / 运行态恢复由编排侧独占（ADR 0150 决定 3），本核只写。
            release_result = None
            if derive_label:
                release_status = "offstage" if derive_label in {"放归", "赦还"} else "active"
                # 必要前置：放归/赦还 → offstage 居家，再由任命级联置 active。
                # 政治标记（起复/昭雪/夺情）不迁 status（决定4）。
                if derive_label in {"放归", "赦还"}:
                    db.set_character_status(
                        state,
                        name,
                        release_status,
                        derive_label,
                        reason_code="",
                        content=content,
                        commit=False,
                    )
                release_result = {
                    "name": name,
                    "动作": "处置",
                    "status": release_status,
                    "reason": derive_label,
                    "derived_from": derive_label,
                    "cascade_echo": True,
                }
            result = project_appointment_result(
                item,
                office_appointment.apply_office_appointment(
                    db,
                    state,
                    content,
                    name,
                    new_office,
                    reason=str(item.get("reason") or ""),
                    new_office_type=str(
                        item.get("office_type") or item.get("new_office_type") or ""
                    ),
                    faction=str(item.get("faction") or "中立"),
                    appointment_tenure=appointment_tenure,
                    region_id=str(
                        item.get("region_id")
                        or item.get("任所")
                        or item.get("辖区")
                        or ""
                    ).strip(),
                    llm_config=llm_config,
                    source=source,
                ),
            )
            wrapped = result if isinstance(result, RejectedItem) else {"动作": effective_action, **result}
            if derive_label and isinstance(wrapped, dict):
                wrapped["derived_from"] = derive_label
            if isinstance(wrapped, RejectedItem):
                rejections.append(wrapped)
                continue
            if release_result is not None:
                applied.append(release_result)
                log_applied(release_result, item)
            elif transition.startswith("normalize:"):
                wrapped["normalized"] = f"{action}->{effective_action}"
            applied.append(wrapped)
            log_applied(wrapped, item)
            for displacement_result in displaced_talent_pool_results(wrapped.get("displaced")):
                applied.append(displacement_result)
                log_applied(displacement_result, item)
            continue

        if action == "易主":
            row = character_row(name)
            reject = allegiance_change_rejection(
                item, row, db=db, origin_ref=origin_ref, require_origin=require_origin,
            )
            if reject is not None:
                rejections.append(rejected(item, reject[0], reject[1]))
                continue
            way = str(item.get("方式") or item.get("way") or "").strip()
            backlash = item.get("反噬", item.get("backlash"))
            requested_new_power = str(item.get("new_power") or "")
            new_title = identity_title_for_allegiance(item, requested_new_power)
            power_results, power_rejections = db.apply_character_power_changes(
                [
                    {
                        "name": name,
                        "new_power": requested_new_power,
                        "reason": str(item.get("reason") or ""),
                    }
                ],
                commit=False, source=source,
            )
            rejections.extend(rejected(item, refusal.reason, refusal.category) for refusal in power_rejections)
            if not power_results:
                if not power_rejections:
                    rejections.append(rejected(item, "易主 未产生变更", "noop"))
                continue
            _backlash_applied, backlash_rejections = db.apply_power_deltas(
                state,
                backlash,
                commit=False,
                origin_ref=origin_ref,
                require_origin=True,
                source=source,
            ) if backlash else ([], [])
            for result in power_results:
                new_power = str(result.get("new_power") or "")
                if (
                    content is not None
                    and result.get("name") in content.characters
                ):
                    ch = content.characters[str(result["name"])]
                    ch.power_id = new_power
                    ch.office = new_title
                    ch.office_type = "身名分"
                    ch.status = "active"
                    ch.reason_code = ""
                    ch.status_reason = str(item.get("reason") or "")
                # 易主后人仍 active（在新主任事，持身名分=降臣/归附），不变式1 不破；清原 reason_code/
                # status_reason（如陷虏「松山兵败被执」）——已投敌、不再是本朝在押，旧因不能滞留（决定3）；
                # status_changed_turn 记本回合（易主即状态变更）。
                db.conn.execute(
                    "UPDATE characters SET office=?, office_type=?, status='active', "
                    "reason_code='', status_reason=?, status_changed_turn=? WHERE name=?",
                    (new_title, "身名分", str(item.get("reason") or ""), state.turn, name),
                )
                db.set_character_transit(name, content=content, commit=False)
                wrapped = {"动作": action, "方式": way, "反噬": backlash, **result}
                wrapped["new_title"] = new_title
                applied.append(wrapped)
                log_applied(wrapped, item)
                rejections.extend(backlash_rejections)
            continue

        if action == "行止":
            if content is not None and name not in content.characters:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = db.conn.execute(
                "SELECT status, location, transit_to, transit_distance_remaining, "
                "transit_speed_factor, transit_start_turn FROM characters WHERE name=?",
                (name,),
            ).fetchone()
            if row is None:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            from ming_sim.matching import is_capital_location

            prior_status = str(row["status"] or "active").strip() or "active"
            prior_transit = str(row["transit_to"] or "").strip()
            prior_location = str(row["location"] or "").strip()
            # ADR 0096：候见不变式（行止前）——active ∧ 在京 ∧ 无 transit。
            waiting_posture = (
                prior_status == "active"
                and not prior_transit
                and is_capital_location(prior_location)
            )
            valid_regions = load_valid_regions(db)
            departure, error = admit_transit_departure(item, dict(row), valid_regions)
            if error is not None:
                rejections.append(rejected(item, error[0], error[1]))
                continue
            if departure is None:
                continue
            location = str(departure["location"])
            transit_to = str(departure["transit_to"])
            distance = departure["distance"]
            speed = departure["speed"]
            if not departure["material"]:
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                rejections.append(origin_error)
                continue
            new_transit_start_turn = state.turn if transit_to else 0
            result = {
                "name": name,
                "动作": action,
                "location": location,
                "transit_to": transit_to,
            }
            # 候见中再奉旨离京：行止 + person_log + 召旨结清须同一原子单元，
            # 防结清失败后留下已启程人物与未结 origin（#670 / ADR 0009）。
            leave_waiting = waiting_posture and (
                bool(str(transit_to or "").strip())
                or not is_capital_location(location)
            )
            if leave_waiting:
                # 行止 + 行迹 + 召旨结清是同一笔写。事务、快照与提交归调用方
                # （编排器或 apply_person_changes_only），本核只写。
                db.set_character_transit(
                    name,
                    location=location,
                    transit_to=transit_to,
                    distance_remaining=distance,
                    speed_factor=speed,
                    start_turn=new_transit_start_turn,
                    content=content,
                    commit=False,
                )
                applied.append(result)
                log_applied(result, item)
                from ming_sim.audience_night import (
                    settle_unsettled_summons_for_person,
                )

                settle_unsettled_summons_for_person(
                    db, name, commit=False,
                )
            else:
                db.set_character_transit(
                    name,
                    location=location,
                    transit_to=transit_to,
                    distance_remaining=distance,
                    speed_factor=speed,
                    start_turn=new_transit_start_turn,
                    content=content,
                    commit=False,
                )
                applied.append(result)
                log_applied(result, item)
            continue

        rejections.append(
            rejected(item, "人物变更动作写路径未接", "invalid_transition")
        )
    return applied, rejections
