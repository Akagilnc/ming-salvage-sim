"""朝臣任命落地核。

写前字段、任所、任别作用域、独占实职顶替与拒收映射与核同住本模块。
``issues`` 在人物去重与事件闸预览处显式引用这些助手。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from ming_sim.applier import Provenance, RejectedItem
from ming_sim.appointment_tenure import appointment_tenure_from
from ming_sim.content import GameContent
from ming_sim.db import (
    GameDB,
    infer_office_type_from_office,
    normalize_office,
    resolve_office_type_preserving_title,
)
from ming_sim.exceptions import OfficeAppointmentRejection
from ming_sim.models import GameState, is_vassal_prince

def _appointment_region_id(payload: Dict[str, object]) -> str:
    """Typed 任所 from appointment payload keys; never inferred from title/location."""
    return str(
        payload.get("region_id")
        or payload.get("任所")
        or payload.get("辖区")
        or payload.get("office_region")
        or ""
    ).strip()


def _canonical_appointment_fields(
    payload: Dict[str, object], *, current_office_type: str = "", llm_config=None,
) -> tuple[str, str, str, str]:
    """Canonical fields consumed by both appointment apply and payload dedup.

    Fourth element is typed region_id before seat resolve. Non-local office
    types always normalize to empty — caller-stuffed region must not mint a
    central seat identity. Local bare titles still carry raw region here;
    :func:`_resolve_appointment_seat` turns that into the once-per-appointment
    resolved seat for write / dedup / displace.
    """
    try:
        tenure = appointment_tenure_from(payload)
    except ValueError as exc:
        raise OfficeAppointmentRejection(str(exc), category="invalid_enum") from exc
    office = normalize_office(str(payload.get("office") or payload.get("new_office") or ""))
    office_type = resolve_office_type_preserving_title(
        office,
        str(payload.get("office_type") or payload.get("new_office_type") or ""),
        current_office_type,
        llm_config,
    )
    raw_region = _appointment_region_id(payload)
    if office_type not in GameDB._LOCAL_ARCHIVE_OFFICE_TYPES:
        return office, office_type, tenure, ""
    return office, office_type, tenure, raw_region


def _resolve_appointment_seat(
    db: GameDB,
    *,
    name: object = "",
    office: object,
    office_type: object,
    region_id: object = "",
) -> str:
    """Once-per-appointment resolved seat via existing typed 任所 helper.

    Local same-office continuation reuses character_offices.region_id when the
    caller omits region; central / non-local always empty; unknown or missing
    local seat still raises OfficeAppointmentRejection from the helper.
    """
    return db._require_local_office_region(
        name=name,
        office=office,
        office_type=office_type,
        region_id=region_id,
    )


# 独占实职关键词：office 分项以此结尾者视为「一人一缺」，须顶替去重。
# 群体职（大学士/侍郎/郎中/主事/御史/翰林等）不在内，可多员并存。
_EXCLUSIVE_OFFICE_SUFFIXES = (
    "首辅", "次辅", "尚书", "总督", "巡抚", "总兵", "督师", "经略", "提督",
)


def _is_exclusive_office(part: str) -> bool:
    """office 单个分项是否独占实职。南京XX为留都缺，与京职互不冲突，单独算一缺。"""
    return any(part.endswith(suf) for suf in _EXCLUSIVE_OFFICE_SUFFIXES)


def _displace_duplicate_offices(
    db: GameDB,
    content: Optional[GameContent],
    new_holder: str,
    new_office: str,
    *,
    region_id: str = "",
) -> List[str]:
    """新任者 new_holder 拿到 new_office 后，把其中每个独占实职分项从其他 active 官员
    office 里剔除，避免双缺官。返回被腾出的 (旧任者:职) 描述列表。

    ``region_id`` 必须是一次任职的 resolved seat（经 _resolve_appointment_seat /
    character_offices），不是调用方原始字符串。中央 resolved 为空 → 按 office
    文字挤位；地方 resolved 非空 → 仅同 seat 互挤（同名巡抚跨省不顶替）。
    """
    new_parts = [p for p in normalize_office(new_office).split(",") if _is_exclusive_office(p)]
    if not new_parts:
        return []
    new_seat = str(region_id or "").strip()
    displaced: List[str] = []
    displaced_names: set[str] = set()  # #9 cmr R1：被顶替者去重，循环后逐派系重算 leverage。
    rows = db.conn.execute(
        "SELECT name, office FROM characters WHERE status='active' AND power_id='ming' AND name!=?",
        (new_holder,),
    ).fetchall()
    for row in rows:
        holder_parts = [p.strip() for p in str(row["office"]).split(",") if p.strip()]
        # Seat-aware exclusive collision: resolved local seat only bumps the
        # same seat; empty resolved seat is central identity (title-only).
        if new_seat:
            holder_seat = db.character_office_region(row["name"])
            if holder_seat != new_seat:
                continue
        conflicting = [p for p in holder_parts if p in new_parts]
        if not conflicting:
            continue  # 此人不占同名独缺
        kept = [p for p in holder_parts if p not in conflicting]
        displaced_names.add(row["name"])
        for lost in conflicting:
            displaced.append(f"{row['name']}:{lost}")
        fully_displaced = not kept
        new_holder_office = "听用候铨" if fully_displaced else ",".join(kept)
        # 剔掉一个分项后,保留官职对应的 office_type 可能变了(如剔「兵部尚书」后只剩「左都御史」=都察院)。
        # 若独占实职被完全腾空,旧任仍 active,但其名分必须落入人才池的「听用候铨」,
        # 不能留下 active + 空 office 的半身份（ADR 0009 S5）。
        old_type_row = db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?", (row["name"],)).fetchone()
        old_type = old_type_row["office_type"] if old_type_row else ""
        new_type = (
            "身名分"
            if fully_displaced
            else infer_office_type_from_office(new_holder_office, old_type, db.llm_config)
        )
        # 排挤后 character_offices / 内存 office_region 与 characters 同事务同步：
        # 全顶替 → 名分，备档删除、任所清空；部分保留 → 余职 + 原 seat 入 record。
        # 内存 seat 必须以备档真源对齐（record 后可能因非地方 office_type 钳空）。
        retained_seat = "" if fully_displaced else str(
            db.character_office_region(row["name"]) or ""
        ).strip()
        if fully_displaced:
            db.conn.execute(
                "UPDATE characters SET office=?, office_type=?, status_reason=?, reason_code=? WHERE name=?",
                (new_holder_office, new_type, "被顶替", "被顶替", row["name"]),
            )
            db.set_character_transit(str(row["name"]), content=content, commit=False)
        else:
            db.conn.execute(
                "UPDATE characters SET office=?, office_type=? WHERE name=?",
                (new_holder_office, new_type, row["name"]),
            )
        db._record_character_office(
            row["name"], new_holder_office, new_type, "被顶替", region_id=retained_seat,
        )
        archived_seat = str(db.character_office_region(row["name"]) or "").strip()
        if content is not None and row["name"] in content.characters:
            ch = content.characters[row["name"]]
            ch.office = new_holder_office
            ch.office_type = new_type
            ch.office_region = archived_seat
            if fully_displaced:
                ch.status_reason = "被顶替"
                ch.reason_code = "被顶替"
    # #9 cmr R1：被顶替者的 office_type 经上方裸 UPDATE 改了（全顶替→身名分=0 权重），绕过了
    # set_character_office 钩子，故其所属派系（常与新任者异派系）的 leverage 须在此补重算，否则
    # 残留偏高、违 #9 不变式。新任者自身派系已由 set_character_office 钩子重算，这里只补被顶替者。
    # commit 前调用——recompute 读当前在朝成员、不内部 commit，正反映刚改完的 office_type；
    # 绝对幂等（非白名单 return、重复无害）。去重后逐派系各调一次。
    displaced_factions = set()
    for dn in displaced_names:
        frow = db.conn.execute(
            "SELECT faction FROM characters WHERE name=?", (dn,)
        ).fetchone()
        # 空/None faction 提前滤掉（recompute_faction_leverage("") 虽被白名单校验 no-op，
        # 但提前过滤免去无意义调用，集合也不残留空串。线上 R5 gemini medium。
        if frow is not None and frow["faction"]:
            displaced_factions.add(str(frow["faction"]))
    for fac in displaced_factions:
        db.recompute_faction_leverage(fac)
    return displaced


@contextmanager
def _appointment_tenure_scope(db: GameDB, appointment_tenure: str):
    previous_tenure = getattr(db.conn, "_appointment_tenure", "真除")
    db.conn._appointment_tenure = appointment_tenure
    try:
        yield
    finally:
        db.conn._appointment_tenure = previous_tenure


def _office_appointment_failure(
    name: str,
    new_office: str,
    exc: BaseException,
    *,
    kind: str = "",
    reason_suffix: str = "",
    source: Provenance = Provenance.system_simulation,
) -> RejectedItem:
    """Map known appointment write failures to typed rejection categories.

    Category comes only from typed exception attributes — never from message text.
    """
    return RejectedItem(
        item={"name": name, "new_office": new_office, **({"kind": kind} if kind else {})},
        reason=f"落库失败：{exc}{reason_suffix}",
        category=getattr(exc, "category", None) or "invalid_transition",
        source=source,
    )


def apply_office_appointment(
    db: GameDB,
    state: GameState,
    content,
    name: str,
    new_office: str,
    *,
    reason: str = "",
    new_office_type: str = "",
    faction: str = "中立",
    appointment_tenure: str = "真除",
    region_id: str = "",
    llm_config: Any = None,
    source: Provenance = Provenance.system_simulation,
) -> Dict[str, object] | RejectedItem:
    """朝臣任命/调任的唯一落地核。

    写前数据失败返回 RejectedItem。授官、起复、建档与顶替的写口异常原样上抛，
    由外层事务回滚；本核不做快照、不把代码故障记成拒收。
    """
    name = str(name or "").strip()
    new_office = str(new_office or "").strip()
    if not name or not new_office:
        return RejectedItem(item={"name": name, "new_office": new_office}, reason="name 或 new_office 空", category="missing_field", source=source)
    if content is not None:
        from ming_sim.session import _find_existing_minister
        canon = _find_existing_minister(content, name, db)
        if canon:
            name = canon
    in_roster = content is not None and name in content.characters
    cur_status = db.get_character_status(name)[0] if in_roster else ""
    current_office_type = content.characters[name].office_type if in_roster else ""

    def _fields_before_write(*, current_office_type: str):
        office, office_type, tenure, raw_seat = _canonical_appointment_fields(
            {
                "office": new_office,
                "office_type": new_office_type,
                "任别": appointment_tenure,
                "region_id": region_id,
            },
            current_office_type=current_office_type,
            llm_config=llm_config or db.llm_config,
        )
        if office_type == "后宫":
            raise OfficeAppointmentRejection("后宫任命已退役", category="invalid_enum")
        seat = _resolve_appointment_seat(
            db,
            name=name,
            office=office,
            office_type=office_type,
            region_id=raw_seat,
        )
        return office, office_type, tenure, seat

    if in_roster:
        if cur_status == "dead":
            return RejectedItem(item={"name": name, "new_office": new_office}, reason="人物已故，不能重新启用", category="invalid_transition", source=source)
        appointee = content.characters.get(name)
        if appointee is not None and is_vassal_prince(appointee):
            return RejectedItem(item={"name": name, "new_office": new_office}, reason="宗藩（就藩宗室）非朝堂命官，不可授官", category="invalid_transition", source=source)
        old_office = content.characters[name].office
        try:
            new_office, new_office_type, appointment_tenure, seat = _fields_before_write(
                current_office_type=current_office_type,
            )
        except OfficeAppointmentRejection as exc:
            return _office_appointment_failure(name, new_office, exc, source=source)
        if cur_status != "active":
            db.set_character_status(
                state,
                name,
                "active",
                reason if str(reason).strip() else "诏书任命",
                content=content,
                commit=False,
            )
        with _appointment_tenure_scope(db, appointment_tenure):
            db.set_character_office(
                name, new_office, new_office_type,
                source=reason if str(reason).strip() else "诏书调任", llm_config=llm_config,
                commit=False,
                region_id=seat,
            )
        if cur_status == "active":
            db.conn.execute(
                "UPDATE characters SET status_reason='', reason_code='' WHERE name=?",
                (name,),
            )
            if content is not None and name in content.characters:
                content.characters[name].status_reason = ""
                content.characters[name].reason_code = ""
        seat = db.character_office_region(name) or seat
        displaced_parts = _displace_duplicate_offices(
            db, content, name, new_office, region_id=seat,
        )
        holder = content.characters[name]
        holder.office = new_office
        holder.office_type = new_office_type
        holder.office_region = seat
        return {
            "name": name, "old_status": cur_status, "old_office": old_office, "new_office": new_office,
            "kind": "transfer", "reason": reason,
            **({"displaced": displaced_parts} if displaced_parts else {}),
        }
    if content is None:
        return RejectedItem(item={"name": name, "new_office": new_office}, reason="无 content，跳过建档", category="missing_field", source=source)
    from ming_sim.session import apply_appointment
    try:
        new_office, new_office_type, appointment_tenure, seat = _fields_before_write(
            current_office_type="",
        )
    except OfficeAppointmentRejection as exc:
        return _office_appointment_failure(
            name, new_office, exc, kind="appoint",
            reason_suffix=f"；原 status={cur_status or '不在册'}",
            source=source,
        )
    appointment = {
        "name": name, "office": new_office, "office_type": new_office_type,
        "faction": faction, "reason": reason, "approved": True,
        "office_region": seat,
    }
    with _appointment_tenure_scope(db, appointment_tenure):
        appointed, _ = apply_appointment(
            db, state, content, appointment, llm_config=llm_config, commit=False,
        )
    if not appointed:
        return RejectedItem(item={"name": name, "new_office": new_office, "kind": "appoint"}, reason=f"建档失败（查重/字段不合）；原 status={cur_status or '不在册'}", category="invalid_transition", source=source)
    seat = db.character_office_region(appointed) or seat
    displaced_parts = _displace_duplicate_offices(
        db, content, appointed, new_office, region_id=seat,
    )
    return {
        "name": appointed, "new_office": new_office, "kind": "appoint", "reason": reason,
        **({"displaced": displaced_parts} if displaced_parts else {}),
    }


def _payload_owned_person_duplicate(
    db: GameDB,
    item: Dict[str, object],
    *,
    current_office_type: str = "",
    llm_config=None,
) -> bool:
    from ming_sim.entities.authority.apply import _payload_owned_dossier_for_origin
    dossier = _payload_owned_dossier_for_origin(db, item.get("origin_ref") or item.get("来源引用"))
    if dossier is None or dossier.get("action_type") not in {"appointment", "dismiss_assignment"}:
        return False
    payload = dossier["payload"]
    person = str(item.get("name") or item.get("人物") or "").strip()
    target = str(payload.get("_minister_name") or payload.get("minister_name") or dossier.get("target_id") or "").strip()
    payload_action = str(payload.get("_office_action") or "").strip()
    item_action = str(item.get("动作") or item.get("action") or "").strip()
    if not person or person != target:
        return False
    if payload_action == "罢免":
        return item_action in {"罢黜", "罢免"}
    if payload_action != "任命" or item_action not in {"任命", "调任"}:
        return False
    canonical_kwargs = {
        "current_office_type": current_office_type,
        "llm_config": llm_config,
    }

    def _fields(src: Dict[str, object]) -> tuple[str, str, str, str]:
        office, office_type, tenure, raw_seat = _canonical_appointment_fields(
            src, **canonical_kwargs,
        )
        if not office:
            return office, office_type, tenure, raw_seat
        try:
            seat = _resolve_appointment_seat(
                db,
                name=person,
                office=office,
                office_type=office_type,
                region_id=raw_seat,
            )
        except OfficeAppointmentRejection:
            # Typed seat reject only: missing/unknown region keeps raw for identity compare.
            seat = raw_seat
        return office, office_type, tenure, seat

    payload_fields = _fields(payload)
    return bool(payload_fields[0]) and payload_fields == _fields(item)
