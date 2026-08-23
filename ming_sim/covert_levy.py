"""#651／ADR 0089 暗渠摊派：缺口悬置→摊派变形触发、两本账落账、暴露读端与处置三选。

canonical＝ADR 0089：暗渠＝隐性摊派，零新造机制，即 0072 执行变形的财政特例——
奏报口径「已筹措」（承办 LLM 长出，禁硬编码模板）、实况账「摊到某省小农」（0073
两本账骑 #622 轨）；实况账驱动流民入池走 #649 S2 转移原语（reason='摊派' 与明渠
合流同一本累积账）；暴露走 #476 三通道（稽核/政敌检举/民变自长），处置＝管理：
禁摊派→缺口顶回皇帝案头／默许→积流民／查办→得罪经手人。不可根治只可管理。

本模块新契约（ADR 0089 唯一新拍）：
- 触发：财政缺口悬置事实读账（armies 双分源欠饷列＋#314 floor(arrears/needed) 月数
  口径）满足 N 月才可判摊派；触发因子并入 0072 判官输入面（due_review 输入闭集，
  #622 AC5 门控同构先例：不满足键不出现）。
- 落账：book_covert_levy_case 两本账不同 origin 全量落库＋案件行（处置状态载体）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

# 戒条(b)：N 月命名常量钉死（测试配边界 mutation）。取 2：早于军心 tick 的 ≥3 月
# 流失档（flows.army_loyalty_tick_delta dead-band），官僚转嫁先于兵变浮现。
COVERT_LEVY_SUSPENDED_MONTHS = 2

# 处置三选（ADR 0089 明文三分支，不可根治只可管理）。
COVERT_LEVY_DISPOSITIONS = ("禁摊派", "默许", "查办")

_CASE_STATUS_ACTIVE = "active"
_CASE_STATUS_EXPOSED = "exposed"
_CASE_STATUS_DISPOSED = "disposed"


def read_shortfall_suspension_facts(db: Any) -> List[Dict[str, object]]:
    """缺口悬置事实读账：ming 自养除外、有兵军中 floor(arrears/needed)≥N 者。

    月数口径单源＝#314 军心 tick 同款 floor(arrears/full_needed)；应发单源＝
    flows.army_needed（rate<=0 锚定同一咽喉）。自养/土司军欠饷不并入朝廷饷源
    （迁移既有口径），不入事实底料。
    """
    from ming_sim.flows import army_needed

    rows = db.conn.execute(
        "SELECT id, name, station, owner_power, manpower, salary_rate, arrears "
        "FROM armies WHERE owner_power='ming' AND self_funded_pay=0 AND is_tusi=0 "
        "ORDER BY id"
    ).fetchall()
    facts: List[Dict[str, object]] = []
    for row in rows:
        needed = int(army_needed(row))
        if needed <= 0:
            continue
        arrears = max(0.0, float(row["arrears"] or 0))
        months = int(math.floor(arrears / needed))
        if months < COVERT_LEVY_SUSPENDED_MONTHS:
            continue
        facts.append({
            "army_id": str(row["id"]),
            "army_name": str(row["name"]),
            "station": str(row["station"]),
            "arrears": arrears,
            "monthly_needed": needed,
            "months_in_arrears": months,
        })
    return facts


def build_covert_levy_trigger_factor(db: Any) -> Dict[str, object] | None:
    """触发因子：无悬置军 → None（判官输入面键不出现）；有 → 特征化事实包。

    只供事实（欠饷月数/应发），不代 LLM 判结果、不带系统词进呈现面（P6/P7）。
    """
    facts = read_shortfall_suspension_facts(db)
    if not facts:
        return None
    return {
        "suspended_armies": facts,
        "suspended_months_gate": COVERT_LEVY_SUSPENDED_MONTHS,
    }


# ── 暴露读端与处置三选（AC4） ────────────────────────────────────────────


def _exposure_channel(db: Any, dossier_id: int) -> str:
    """通道归因：政敌检举／稽核链在场者按既有写端留痕认定，余为民变自长。

    三通道共用同一分叉谓词读端（read_dossier_fork_state，#622/#627 单源），
    此处只做通道留痕；不新造第二分叉判定（0089 零新造机制）。
    """
    hit = db.conn.execute(
        "SELECT 1 FROM faction_denunciations WHERE target_dossier_id=? LIMIT 1",
        (int(dossier_id),),
    ).fetchone()
    if hit is not None:
        return "政敌检举"
    for link in db.list_dossier_links(int(dossier_id), direction="incoming"):
        if str(link.get("relation_type") or "").strip() == "稽核":
            return "稽核"
    return "民变自长"


def refresh_covert_levy_exposures(
    db: Any, state: Any, *, commit: bool = True,
) -> List[Dict[str, object]]:
    """暴露扫描：active 案件的案卷分叉成立即翻 exposed 并留痕（turn＋通道）。

    分叉事实单源＝read_dossier_fork_state（奏报面 vs 实况账）；稽核/检举/民变
    自长三通道在 #476 家族各有既有读端，此处只消费同一谓词，任一通道命中即
    暴露。返回本批新暴露案件快照。
    """
    rows = db.conn.execute(
        "SELECT * FROM covert_levy_cases WHERE status='active' ORDER BY id"
    ).fetchall()
    exposed: List[Dict[str, object]] = []
    owns = commit and not db.conn.in_transaction
    for row in rows:
        fork = db.read_dossier_fork_state(int(row["dossier_id"]))
        if not fork["fork"]:
            continue
        channel = _exposure_channel(db, int(row["dossier_id"]))
        db.conn.execute(
            "UPDATE covert_levy_cases SET status='exposed', exposed_turn=?, "
            "exposed_channel=? WHERE id=?",
            (int(state.turn), channel, int(row["id"])),
        )
        item = dict(row)
        item["case_id"] = int(row["id"])
        item["status"] = _CASE_STATUS_EXPOSED
        item["exposed_turn"] = int(state.turn)
        item["exposed_channel"] = channel
        exposed.append(item)
    if owns and exposed:
        db.conn.commit()
    return exposed


def apply_covert_levy_disposition(
    db: Any,
    state: Any,
    case_id: int,
    disposition: str,
    *,
    content: Any = None,
    commit: bool = True,
) -> Dict[str, object]:
    """处置三选（ADR 0089：不可根治只可管理），各自代价当回合落库。

    - 禁摊派：结案；缺口重新顶回皇帝案头＝悬置军仍留在触发因子里（事实读账
      不撒谎），该军禁开新暗账（写端门控）；代价留痕 decree_cost_events。
    - 默许：不结案、处置留档；流民池随后续暗账继续涨（无额外写）。
    - 查办：经手人处置事件走 character_status_changes 单核当回合落库（戒条 c），
      结怨边经 record_relation_edge_event 唯一写口，另留代价痕迹。

    未暴露不可处置（皇帝尚不知情，无从处置）；未知处置响亮 ValueError。
    """
    import contextlib

    from ming_sim.decree import atomic_and_reload

    disposition = str(disposition or "").strip()
    if disposition not in COVERT_LEVY_DISPOSITIONS:
        raise ValueError(f"未知处置：{disposition!r}（枚举：{'/'.join(COVERT_LEVY_DISPOSITIONS)}）")
    case = get_covert_levy_case(db, int(case_id))
    if case is None:
        return {"rejected": True, "reason": f"暗账案件不存在：{case_id}"}
    if str(case["status"]) != _CASE_STATUS_EXPOSED:
        return {"rejected": True, "reason": f"案件未暴露，不可处置（status={case['status']}）"}
    dossier_id = int(case["dossier_id"])
    handler = str(case["handler_character_id"])
    reason_text = f"暗渠摊派处置·{disposition}（{case['army_name'] if 'army_name' in case else case['army_id']}转嫁{case['region_id']}）"

    if commit and not db.conn.in_transaction:
        transaction = atomic_and_reload(db, state)
    else:
        transaction = contextlib.nullcontext()
    with transaction:
        # 代价留痕统一挂载点（幂等键 UNIQUE(dossier,cost_identity,cost_kind,target)）
        db._record_decree_cost(
            dossier_id, int(state.turn), disposition, "character", handler,
            0, reason_text, cost_identity="covert_levy_disposition",
        )
        if disposition == "默许":
            db.conn.execute(
                "UPDATE covert_levy_cases SET disposition='默许' WHERE id=?",
                (int(case_id),),
            )
        else:
            db.conn.execute(
                "UPDATE covert_levy_cases SET status='disposed', disposition=?, "
                "disposed_turn=? WHERE id=?",
                (disposition, int(state.turn), int(case_id)),
            )
        if disposition == "查办":
            from ming_sim.issues import _apply_person_changes

            results = _apply_person_changes(
                db,
                state,
                [{
                    "name": handler,
                    "动作": "处置",
                    "status": "imprisoned",
                    "reason": reason_text,
                    "origin_ref": f"dossier:{dossier_id}",
                }],
                content=content,
                source="covert_levy_disposition",
                external_transaction=True,
            )
            rejected = [
                r for r in results if isinstance(r, dict) and r.get("rejected")
            ]
            if rejected:
                raise RuntimeError(f"查办处置事件物化失败，回滚：{rejected!r}")
            db.record_relation_edge_event(
                source="皇帝", target=handler, event_kind="结怨",
                context=reason_text, origin=f"dossier:{dossier_id}:查办",
                turn=int(state.turn), year=int(state.year), period=int(state.period),
            )
    return {"rejected": False, "case_id": int(case_id), "disposition": disposition}


# ── 落账核：两本账＋案件行 ────────────────────────────────────────


def get_covert_levy_case(db: Any, case_id: int) -> Dict[str, object] | None:
    row = db.conn.execute(
        "SELECT * FROM covert_levy_cases WHERE id=?", (int(case_id),)
    ).fetchone()
    return dict(row) if row is not None else None


def book_covert_levy_case(
    db: Any,
    state: Any,
    *,
    dossier_id: int,
    army_id: str,
    region_id: str,
    handler_character_id: str,
    displaced_amount: int,
    squeezed_silver: int,
    commit: bool = True,
) -> Dict[str, object]:
    """暗渠摊派落账核（ADR 0089 新拍契约的写端，一案一活跃暗账）。

    两本账不同 origin 全量落库（AC2）：奏报面由承办 LLM 经 record_dossier_progress
    自行长出（戒条 a，本核不代笔）；实况账在此——旨外国库流水（骑 #622 轨，
    beyond_intent 同列）＋摊派转移入池（走 #649 S2 唯一落库核，与明渠合流同一本
    流民账，AC3）。案件行当回合落库（处置状态载体）。触发门控机械强制：缺口未
    悬置、案卷不存在、被禁摊派军、重复活跃案件均响亮拒绝且零写入（AC1 不满足
    绝不触落在写端的对偶）。
    """
    import contextlib

    from ming_sim.decree import atomic_and_reload
    from ming_sim.flows import _apply_population_transfers

    if build_covert_levy_trigger_factor(db) is None:
        return {"rejected": True, "reason": "缺口未悬置，暗渠不可触发"}
    if db.get_decree_dossier(int(dossier_id)) is None:
        return {"rejected": True, "reason": f"案卷不存在：{dossier_id}"}
    army_row = db.conn.execute(
        "SELECT id, name FROM armies WHERE id=?", (str(army_id),)
    ).fetchone()
    if army_row is None:
        return {"rejected": True, "reason": f"未知军队：{army_id!r}"}
    if db.conn.execute(
        "SELECT 1 FROM regions WHERE id=?", (str(region_id),)
    ).fetchone() is None:
        return {"rejected": True, "reason": f"未知省份：{region_id!r}"}
    handler_row = db.conn.execute(
        "SELECT status FROM characters WHERE name=?", (str(handler_character_id),)
    ).fetchone()
    if handler_row is None or str(handler_row["status"] or "") == "dead":
        return {"rejected": True, "reason": f"经手人不可用：{handler_character_id!r}"}
    for name, value in (("displaced_amount", displaced_amount), ("squeezed_silver", squeezed_silver)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return {"rejected": True, "reason": f"{name} 须为正整数：{value!r}"}
    dup = db.conn.execute(
        "SELECT id FROM covert_levy_cases WHERE dossier_id=? AND status IN ('active','exposed')",
        (int(dossier_id),),
    ).fetchone()
    if dup is not None:
        return {"rejected": True, "reason": f"该案已有活跃暗账（case {dup[0]}）"}
    banned = db.conn.execute(
        "SELECT id FROM covert_levy_cases WHERE army_id=? AND disposition='禁摊派'",
        (str(army_id),),
    ).fetchone()
    if banned is not None:
        return {
            "rejected": True,
            "reason": f"该军已被禁摊派（case {banned[0]}），不得再开暗账",
        }

    origin_ref = f"dossier:{int(dossier_id)}"
    if commit and not db.conn.in_transaction:
        transaction = atomic_and_reload(db, state)
    else:
        transaction = contextlib.nullcontext()
    with transaction:
        cur = db.conn.execute(
            """INSERT INTO covert_levy_cases
               (dossier_id, army_id, region_id, handler_character_id,
                displaced_amount, squeezed_silver, status, created_turn)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
            (int(dossier_id), str(army_id), str(region_id),
             str(handler_character_id), int(displaced_amount),
             int(squeezed_silver), int(state.turn)),
        )
        case_id = int(cur.lastrowid)
        # 实况账②：旨外国库流水（骑 #622 beyond_intent 同列轨）
        moved = db.record_issue_economy_move(
            state, "国库", int(squeezed_silver), "摊派",
            f"暗渠摊派入账（{army_row['name']}欠饷转嫁{region_id}小农）",
            origin_ref=origin_ref, beyond_intent=True, commit=False,
        )
        if moved == 0:
            raise RuntimeError("暗渠摊派国库流水零落账（余额饱和），回滚")
        # 实况账①：入池走 S2 转移原语唯一落库核（与明渠合流同一本账）
        transfers, rejections = _apply_population_transfers(
            db,
            [{
                "origin_ref": origin_ref,
                "source": f"农民@{region_id}",
                "target": f"流民@{region_id}",
                "amount": int(displaced_amount),
                "reason": "摊派",
            }],
            commit=False,
        )
        if rejections:
            raise RuntimeError(f"暗渠摊派转移被拒，回滚：{rejections!r}")
    return {
        "rejected": False,
        "case_id": case_id,
        "origin_ref": origin_ref,
        "transfer": transfers[0],
    }
