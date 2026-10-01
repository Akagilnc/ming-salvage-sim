"""人物变更落库核。

写核住在人物实体（ADR 0150 决定 1/8）。局势模块与其它调用方引用本函数，
不再在 ``issues`` 里留一份平行实现。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem, Provenance

from typing import Any, Dict, List


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
) -> List[Dict[str, object]]:
    import json

    import ming_sim.entities.character.appointment as office_appointment
    from ming_sim.appointment_tenure import appointment_tenure_from
    from ming_sim.person_archive_contract import (
        PERSON_ALLEGIANCE_CHANGE_WAYS,
        PERSON_IDENTITY_TITLES,
        normalize_reason_code,
        resolve_person_transition,
    )
    from ming_sim.issues import (
        _admit_transit_departure,
        _load_pending_gate_valid_regions,
        _parse_sqlite_id,
        _payload_owned_person_duplicate,
    )

    def rejected(item, reason, category, *, status=None) -> RejectedItem:
        return RejectedItem(item=item, reason=reason, category=category, source=source)

    def project_appointment_result(item, result):
        if isinstance(result, RejectedItem):
            result.item = item
        return result

    def origin_rejected(item: Dict[str, object]) -> Dict[str, object] | None:
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
        *,
        commit: bool | None = None,
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
            if key not in {"rejected", "category", "item", "backlash_results"}
        }
        db.record_person_log(
            state,
            name,
            action,
            payload_summary=summary,
            derived_from=str(result.get("derived_from") or derived_from or ""),
            normalized=normalized,
            source=source,
            commit=False if commit is None else commit,
            origin_ref=origin_ref,
        )

    def identity_title_for_allegiance(item: Dict[str, object], new_power: str) -> str:
        title = str(item.get("new_title") or item.get("title") or "").strip()
        if title:
            return title if title in PERSON_IDENTITY_TITLES else ""
        way = str(item.get("方式") or item.get("way") or "").strip()
        if new_power == "ming" or way == "主动归附":
            return "归附"
        return "降臣"

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
            log_applied(result, item, commit=False)
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
            log_applied(result, item, commit=False)
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
            cur_status, _ = db.get_character_status(name)
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
            except ValueError:
                rejections.append(rejected(item, "任别非白名单", "invalid_enum"))
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
                            commit=False, source=source,
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
            if derive_label:
                release_status = "offstage" if derive_label in {"放归", "赦还"} else "active"
                # 必要前置（放归/赦还）执行 status 迁移原语（→offstage 居家），再由任命级联置 active。
                # 政治标记（起复/昭雪/夺情）为纯审计记录、不迁移 status（决定4）——status→active+绑名分
                # 由下面 apply_office_appointment 原子完成，避免「先置 active、名分未绑」的中间态（不变式1 全程成立）。
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
                    # applier 合成级联回声（放归/赦还/起复/昭雪/夺情）：
                    # 信用写端只消费 extractor 宣告本体行，禁盯 derived_from 文本特判。
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
                    commit=False, source=source,
                ),
            )
            wrapped = result if isinstance(result, RejectedItem) else {"动作": effective_action, **result}
            if derive_label:
                if isinstance(wrapped, dict):
                    wrapped["derived_from"] = derive_label
                if isinstance(wrapped, RejectedItem):
                    # transit_start_turn 与 transit_to 成对回滚：派生任命前置 set_character_status
                    # （放归/赦还→offstage 属 ousted）现会清 transit_start_turn=0，回滚须对称还原，
                    # 否则留「transit_to 非空 + start=0」被兜底当 legacy-overdue 误判（CMR r2 防御）。
                    db.conn.execute(
                        "UPDATE characters SET status=?, office=?, office_type=?, "
                        "status_reason=?, status_changed_turn=?, reason_code=?, transit_to=?, "
                        "transit_distance_remaining=?, transit_speed_factor=?, transit_start_turn=? "
                        "WHERE name=?",
                        (
                            row["status"], row["office"], row["office_type"],
                            row["status_reason"], row["status_changed_turn"], row["reason_code"],
                            row["transit_to"], row["transit_distance_remaining"],
                            row["transit_speed_factor"], row["transit_start_turn"], name,
                        ),
                    )
                    if content is not None and name in content.characters:
                        ch = content.characters[name]
                        ch.status = str(row["status"] or "")
                        ch.office = str(row["office"] or "")
                        ch.office_type = str(row["office_type"] or ch.office_type)
                        ch.transit_to = str(row["transit_to"] or "")
                        ch.transit_distance_remaining = row["transit_distance_remaining"]
                        ch.transit_speed_factor = row["transit_speed_factor"]
                        ch.transit_start_turn = int(row["transit_start_turn"] or 0)
                        # 对称 DB 侧回滚（上方 UPDATE 已还原全 7 字段）：内存也还原缘由/码，
                        # 守三面同步（决定6），免前置步刷过内存缘由后此路回滚留脏值（PR#106 R2 gemini）。
                        ch.status_reason = str(row["status_reason"] or "")
                        ch.reason_code = str(row["reason_code"] or "")
                else:
                    applied.append(release_result)
                    log_applied(release_result, item, commit=False)
            elif isinstance(wrapped, dict) and transition.startswith("normalize:"):
                wrapped["normalized"] = f"{action}->{effective_action}"
            if isinstance(wrapped, RejectedItem):
                rejections.append(wrapped)
                continue
            applied.append(wrapped)
            log_applied(wrapped, item, commit=False if derive_label else None)
            for displacement_result in displaced_talent_pool_results(wrapped.get("displaced")):
                applied.append(displacement_result)
                log_applied(displacement_result, item, commit=False if derive_label else None)
            continue

        if action == "易主":
            way = str(item.get("方式") or item.get("way") or "").strip()
            backlash = item.get("反噬", item.get("backlash"))
            if not way:
                rejections.append(rejected(item, "易主 缺 方式", "missing_field"))
                continue
            if way not in PERSON_ALLEGIANCE_CHANGE_WAYS:
                rejections.append(rejected(item, "易主 方式非白名单", "invalid_enum"))
                continue
            if not isinstance(backlash, dict):
                rejections.append(rejected(item, "易主 缺 反噬", "missing_field"))
                continue
            if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
                rejections.append(rejected(item, "易主 反噬 项必须是 object(dict)", "invalid_enum"))
                continue
            row = character_row(name)
            if row is None:
                rejections.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                action,
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
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
            requested_new_power = str(item.get("new_power") or "")
            old_power = str(row["power_id"] or "").strip()
            if way == "主动归附" and requested_new_power == "ming":
                backlash_power_ids = {
                    str(power_id).strip()
                    for power_id in backlash.keys()
                    if str(power_id).strip()
                }
                if any(power_id != old_power for power_id in backlash_power_ids):
                    rejections.append(
                        rejected(
                            item,
                            f"主动归附反噬只能指向原势力股 {old_power}",
                            "invalid_transition",
                        )
                    )
                    continue
            new_title = identity_title_for_allegiance(item, requested_new_power)
            if not new_title:
                rejections.append(
                    rejected(
                        item,
                        "易主 new_title 非身名分白名单",
                        "invalid_enum",
                    )
                )
                continue
            origin_error = origin_rejected(item)
            if origin_error:
                rejections.append(origin_error)
                continue
            # #522：招抚案卷效果绑定 canonical target；generic special_decree
            # 不得授权招抚式易主。其它 dossier/盘面自发路径保持既有授权。
            if require_origin and str(origin_ref or "").startswith("dossier:"):
                try:
                    dossier_id = _parse_sqlite_id(str(origin_ref).split(":", 1)[1])
                except ValueError:
                    dossier_id = 0
                dossier = db.get_decree_dossier(dossier_id) if dossier_id else None
                if dossier is not None:
                    action_type = str(dossier.get("action_type") or "").strip()
                    if (
                        action_type == "special_decree"
                        and way == "主动归附"
                        and requested_new_power == "ming"
                    ):
                        rejections.append(
                            rejected(
                                item,
                                "special_decree 不得授权招抚易主",
                                "invalid_origin_ref",
                            )
                        )
                        continue
                    if action_type == "pacification":
                        try:
                            payload = dossier.get("payload") or json.loads(
                                str(dossier.get("payload_json") or "{}")
                            )
                        except (TypeError, ValueError):
                            payload = {}
                        if not isinstance(payload, dict):
                            payload = {}
                        bound_target = str(
                            payload.get("target_id") or dossier.get("target_id") or ""
                        ).strip()
                        if not bound_target or name != bound_target:
                            rejections.append(
                                rejected(
                                    item,
                                    f"招抚案卷仅可易主 {bound_target or '案卷目标'}，不得易主 {name}",
                                    "invalid_origin_ref",
                                )
                            )
                            continue
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
            backlash_results, backlash_rejections = db.apply_power_deltas(
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
                if backlash_rejections:
                    wrapped["backlash_results"] = backlash_rejections
                applied.append(wrapped)
                log_applied(wrapped, item)
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
            valid_regions = _load_pending_gate_valid_regions(db)
            departure, error = _admit_transit_departure(item, dict(row), valid_regions)
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
                log_applied(result, item, commit=False)
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

