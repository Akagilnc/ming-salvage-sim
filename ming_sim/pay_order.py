#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 / ADR 0090 偿还序 override ＋ Due 折发系数——fiscal_config 键族机制。

票面（冻结票面 r1–r4 修正案）钉死的表示法：
- **序**：每科目一键 ``due_priority_<科目>``（INTEGER 序位，越小越先；默认基准
  军饷10/官俸20/宗禄30/赈济40）；旧欠序键族 ``arrears_priority_<科目>``（默认
  军饷欠10/官俸欠20/宗禄欠30）。读取=按值升序，值并列按默认基准稳定 tie-break。
- **折发系数**：``due_haircut_bp_<科目>``（INTEGER 万分数，合法域 (0,10000]，
  10000=无折，5000=折半）；越界 fail-loud。舍入=``floor(Due × bp / 10000)``，
  余数计入免除额（折发=免除，不是欠账）。
- **scope 词法承载于键名**：全国=裸键；省域=``<键>@<region_id>``；饷源=军饷键可缀
  ``#province``/``#central``（仅军饷合法）。r3 白名单：priority 两族仅 裸/@region
  两形（序无饷源维度）；haircut 军饷六形、其它科目两形。非法形状 fail-loud 拒写。
- **读取优先级全序**（最特定者独胜）：``@region#source`` > ``@region`` >
  ``#source`` > 裸键；同一（科目×省×饷源）恰取一个胜出键。
- **期限**：物化时同写伴随键 ``<完整键名>_until_turn``（INTEGER 绝对 turn）；读取端
  ``turn > until`` → 该形状退出格律（按次特定者或默认取值；键与 provenance 保留）。
- **hub 恒先不可 override**（r2 宪法边界）：hub tier 的 tier 序与 0023 D9 合并 k 分母
  不读 priority 键、不被 override；``#central`` 折发键只改写中央份额 Due **输入值**
  （flows 读端按 r3 全序取胜出键、floor 折算，余数=免除不入欠），hub 恒先、合并 k
  公式与中央旧欠不自动偿还（0023 D7③）一律不动。

持久化**只**经 fiscal_config 行＋``record_fiscal_config_change``（immutable
provenance、origin_ref=dossier:<id>），禁第二份旨意真源或新表（F1.2）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ── 科目全集与默认基准（r1 F1.1 / r2 更正：省级四科目，hub 另一资金池非成员）──
DUE_SUBJECTS = ("军饷", "官俸", "宗禄", "赈济")
ARREARS_SUBJECTS = ("军饷欠", "官俸欠", "宗禄欠")
DEFAULT_DUE_PRIORITY = {"军饷": 10, "官俸": 20, "宗禄": 30, "赈济": 40}
DEFAULT_ARREARS_PRIORITY = {"军饷欠": 10, "官俸欠": 20, "宗禄欠": 30}

DUE_PRIORITY_FAMILY = "due_priority_"
ARREARS_PRIORITY_FAMILY = "arrears_priority_"
HAIRCUT_FAMILY = "due_haircut_bp_"
_HAIRCUT_SOURCES = ("province", "central")
_UNTIL_SUFFIX = "_until_turn"

# r3 scope 白名单：family → 允许的科目集合；科目 → 允许的后缀形状数
_PRIORITY_FAMILIES = (DUE_PRIORITY_FAMILY, ARREARS_PRIORITY_FAMILY)


class PayOrderKeyError(ValueError):
    """override 键形状/值域非法（fail-loud，非法旨不得物化 config）。"""


@dataclass(frozen=True)
class ParsedOverrideKey:
    """解析后的 override 键。family/subject/region/source 均为规范化词位。"""
    family: str          # due_priority_ / arrears_priority_ / due_haircut_bp_
    subject: str         # 科目（军饷/官俸/宗禄/赈济 或 军饷欠/官俸欠/宗禄欠）
    region: str = ""     # @<region_id>；裸键为 ""
    source: str = ""     # #province / #central；无缀为 ""

    @property
    def specificity(self) -> int:
        """r3 特定度全序：@region#source=3 > @region=2 > #source=1 > 裸=0。"""
        return (2 if self.region else 0) + (1 if self.source else 0)


def parse_override_key(key: str) -> ParsedOverrideKey:
    """按 r3 白名单解析 override 键；非法形状 raise PayOrderKeyError（=ValueError）。

    词法：``<family><subject>[@<region_id>][#<source>]``。@ 必须先于 #；
    空词位（悬空 @ / #）、未知 family/subject、priority 族带 #、非军饷带 # 一律非法。
    本函数纯词法，不查 regions 表（region 存在性由物化端校验，防 @SX 类幻影 region）。
    """
    raw = str(key or "")
    body = raw
    source = ""
    if "#" in body:
        body, _, source = body.partition("#")
        if source not in _HAIRCUT_SOURCES:
            raise PayOrderKeyError(f"override 键 {raw!r}：#饷源后缀仅限 province/central")
    region = ""
    if "@" in body:
        body, _, region = body.partition("@")
        if not region:
            raise PayOrderKeyError(f"override 键 {raw!r}：@后 region_id 为空")
    if "@" in region or "#" in region:
        raise PayOrderKeyError(f"override 键 {raw!r}：scope 后缀顺序须为 @region#source")
    for family in (HAIRCUT_FAMILY, *_PRIORITY_FAMILIES):
        if body.startswith(family):
            subject = body[len(family):]
            break
    else:
        raise PayOrderKeyError(f"override 键 {raw!r}：未知键族（须 due_priority_*/arrears_priority_*/due_haircut_bp_*）")
    if family == HAIRCUT_FAMILY:
        if subject not in DUE_SUBJECTS:
            raise PayOrderKeyError(f"override 键 {raw!r}：未知折发科目 {subject!r}")
        if source and subject != "军饷":
            raise PayOrderKeyError(f"override 键 {raw!r}：饷源后缀仅军饷科目合法")
    else:
        legal = DUE_SUBJECTS if family == DUE_PRIORITY_FAMILY else ARREARS_SUBJECTS
        if subject not in legal:
            raise PayOrderKeyError(f"override 键 {raw!r}：{family}*/ 未知科目 {subject!r}")
        if source:
            # r3：序无饷源维度，# 后缀非法
            raise PayOrderKeyError(f"override 键 {raw!r}：priority 键族不允许 #饷源后缀")
    return ParsedOverrideKey(family=family, subject=subject, region=region, source=source)


def validate_override_value(key: str, value: int) -> None:
    """值域校验（fail-loud）：priority=整数序位；haircut=INTEGER 万分数 ∈ (0,10000]。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayOrderKeyError(f"override 键 {key!r} 值须为整数：{value!r}")
    parsed = parse_override_key(key)
    if parsed.family == HAIRCUT_FAMILY and not (0 < value <= 10000):
        raise PayOrderKeyError(f"override 键 {key!r} 折发万分数须在 (0,10000]：{value}")


def _is_override_key(key: str) -> bool:
    try:
        parse_override_key(key)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ResolvedPayOrder:
    """单省单结算点的 override 解析结果（喂 settle_tick 的 p 扩展键）。"""
    due_order: Tuple[str, ...]
    arrears_order: Tuple[str, ...]
    haircut_bp: Dict[str, int] = field(default_factory=dict)


def _live(config: Dict[str, int], key: str, turn: int) -> bool:
    """键在位且未到期（伴随键 <完整键名>_until_turn：turn > until → 退出格律）。"""
    if key not in config:
        return False
    until = config.get(str(key) + _UNTIL_SUFFIX)
    if until is not None and turn > int(until):
        return False
    return True


def _resolve_priority(
    config: Dict[str, int],
    family: str,
    subjects: Tuple[str, ...],
    defaults: Dict[str, int],
    region_id: str,
    turn: int,
) -> Tuple[str, ...]:
    """按值升序排科目；值并列按默认基准稳定 tie-break（r2）。"""
    def priority_of(subject: str) -> int:
        # 候选：@region（特定度2）> 裸键（0）；priority 无 # 维度。
        for key in (f"{family}{subject}@{region_id}", f"{family}{subject}"):
            if _live(config, key, turn):
                return int(config[key])
        return defaults[subject]

    return tuple(
        sorted(subjects, key=lambda s: (priority_of(s), defaults[s]))
    )


def resolve_haircut_winning_key(
    config: Dict[str, int],
    subject: str,
    region_id: str,
    turn: int,
    source: str,
) -> Optional[str]:
    """r3 全序取胜出键名：@region#source > @region > #source > 裸键；到期形状退出。
    region_id 为空（无属地军）时 @region 两形不参与。无胜出键 → None。"""
    rid = str(region_id or "").strip()
    candidates = (
        f"{HAIRCUT_FAMILY}{subject}@{rid}#{source}",
        f"{HAIRCUT_FAMILY}{subject}@{rid}",
        f"{HAIRCUT_FAMILY}{subject}#{source}",
        f"{HAIRCUT_FAMILY}{subject}",
    )
    best: Tuple[int, str] = (-1, "")  # (specificity, key)
    for key in candidates:
        if not _live(config, key, turn):
            continue
        spec = parse_override_key(key).specificity
        if spec > best[0]:
            best = (spec, key)
    return best[1] or None


def resolve_haircut_bp(
    config: Dict[str, int],
    subject: str,
    region_id: str,
    turn: int,
    source: str,
) -> Optional[int]:
    """按 r3 全序取该（科目×省×饷源）胜出键的折发万分数；无胜出键 → None。
    省内池结算消费 source='province'；中央份额 Due 消费 source='central'（flows 读端）。"""
    key = resolve_haircut_winning_key(config, subject, region_id, turn, source)
    return int(config[key]) if key is not None else None


def _resolve_haircut_bp(
    config: Dict[str, int],
    subject: str,
    region_id: str,
    turn: int,
    source: str,
) -> Optional[int]:
    """r3 全序取胜出键（resolve_haircut_bp 别名，模块内沿旧名）。"""
    return resolve_haircut_bp(config, subject, region_id, turn, source)


def resolve_pay_order_overrides(
    config: Dict[str, int],
    region_id: str,
    turn: int,
) -> Optional[ResolvedPayOrder]:
    """从 fiscal_config 快照解析单省 override；无任何**在位** override 键 → None
    （调用方零合并，结算逐字节走默认路径＝回归不破）。

    纯函数（config dict 进、结果出），TSV/golden 可断言；region 存在性由物化端守。
    """
    live_keys = [
        k for k in config
        if _is_override_key(k) and _live(config, k, turn)
    ]
    if not live_keys:
        return None
    due_order = _resolve_priority(
        config, DUE_PRIORITY_FAMILY, DUE_SUBJECTS, DEFAULT_DUE_PRIORITY, region_id, turn,
    )
    arrears_order = _resolve_priority(
        config, ARREARS_PRIORITY_FAMILY, ARREARS_SUBJECTS,
        DEFAULT_ARREARS_PRIORITY, region_id, turn,
    )
    haircut_bp: Dict[str, int] = {}
    for subject in DUE_SUBJECTS:
        # 省内池结算消费 province 侧；中央侧（hub tier）由 flows 读端按
        # resolve_haircut_bp(source='central') 独立取胜出键（只改 Due 输入值）。
        bp = _resolve_haircut_bp(config, subject, region_id, turn, "province")
        if bp is not None and bp != 10000:
            haircut_bp[subject] = bp
    return ResolvedPayOrder(
        due_order=due_order, arrears_order=arrears_order, haircut_bp=haircut_bp,
    )


def haircut_due(due: float, bp: int) -> Tuple[float, float]:
    """折发记账语义（F1.5/r2）：应得=``floor(Due × bp / 10000)``；余数=免除额。
    返回 (折后应得, 免除额)。免除不入 CLAIM、不积欠。"""
    if isinstance(bp, bool) or not isinstance(bp, int) or not (0 < bp <= 10000):
        raise PayOrderKeyError(f"折发万分数越界：{bp!r}")
    if bp == 10000:
        return float(due), 0.0
    effective = float(math.floor(float(due) * bp / 10000))
    return effective, float(due) - effective


def prepare_pay_order_entries(
    db: Any, entries: List[Dict[str, Any]],
) -> List[Tuple[str, int, Optional[int]]]:
    """整道旨载荷先验后写（fail-loud、零副作用）：键形白名单、值域、同道重复键、
    幻影 region 一律 ValueError 拒**整道旨**。成案点（create_decree_dossier staging）
    与物化点（materialize_pay_order_decree）共此同一验形，禁两套漂移。"""
    seen: set[str] = set()
    prepared: List[Tuple[str, int, Optional[int]]] = []
    for entry in entries:
        key = str((entry or {}).get("key") or "")
        parsed = parse_override_key(key)  # 非法形状 fail-loud
        if key in seen:
            raise PayOrderKeyError(f"同道旨内重复键 {key!r}")
        seen.add(key)
        value = (entry or {}).get("value")
        validate_override_value(key, value)
        until_raw = (entry or {}).get("until_turn")
        until: Optional[int]
        if until_raw is None:
            until = None
        else:
            if isinstance(until_raw, bool) or not isinstance(until_raw, int) or until_raw <= 0:
                raise PayOrderKeyError(f"override 键 {key!r} 期限 until_turn 须为正整数：{until_raw!r}")
            until = int(until_raw)
        if parsed.region:
            row = db.conn.execute(
                "SELECT 1 FROM regions WHERE id = ?", (parsed.region,)
            ).fetchone()
            if row is None:
                # r4：不新增 alias、不造虚拟 region——幻影 region_id fail-loud 拒写整道旨
                raise PayOrderKeyError(f"override 键 {key!r}：region_id {parsed.region!r} 不存在（禁 alias/虚拟 region）")
        prepared.append((key, int(value), until))
    return prepared


def materialize_pay_order_decree(
    db: Any,
    *,
    turn: int,
    entries: List[Dict[str, Any]],
    origin_ref: str,
    reason: str = "",
    commit: bool = True,
) -> List[Dict[str, Any]]:
    """一道 override 旨的唯一次物化入口（F1.2/F1.3，ADR 0055 判后物化缝）。

    只可由颁布关调用：origin_ref 必须指到**真实存在的 pay_order_override 案卷**，
    且该案卷已过合法颁布门（顺颁/强颁，dossier_authorizes_effects）；打回案卷零写入
    （效果跟判决走，本函数根本不会被调）。entries：
    ``[{"key": <override 键>, "value": <int>, "until_turn": <int|None>}, ...]``。
    整批先验后写（非法形状/值域/幻影 region → ValueError，**零写入**＝非法旨不得
    物化 config）；写 fiscal_config 行（缺则 INSERT、有则 UPDATE，kind='override'）
    ＋期限伴随键 ``<完整键名>_until_turn``；每写一键留一行 ``fiscal_config_changes``
    provenance。不删键、不静默合并（同维冲突由后旨覆写前旨＝last-write-wins，两次
    写入各留一行）。

    **覆写清旧期限（F1.4 stale until）**：新旨无期限（永久）覆写旧有期限键时，同事务
    清除遗留 ``<键>_until_turn`` 行——否则旧期限仍使新永久旨到期。清除走既有
    ``fiscal_config_tombstones`` append-only 审计＋一行 provenance，不增表。
    """
    origin = str(origin_ref or "").strip()
    if not origin.startswith("dossier:") or not origin[len("dossier:"):]:
        raise PayOrderKeyError(f"override 旨 origin_ref 须形如 dossier:<id>：{origin_ref!r}")
    dossier_id = int(origin[len("dossier:"):])
    dossier = db.get_decree_dossier(dossier_id)
    if dossier is None:
        raise PayOrderKeyError(f"override 旨案卷不存在：{origin}")
    if str(dossier.get("action_type") or "") != "pay_order_override":
        raise PayOrderKeyError(
            f"override 旨案卷 action_type 非法：{dossier.get('action_type')!r}（须 pay_order_override）"
        )
    if not db.dossier_authorizes_effects(dossier_id):
        raise PayOrderKeyError(
            f"override 旨案卷 {origin} 未过合法颁布门（顺颁/强颁），禁物化 config"
        )
    turn = int(turn)
    prepared = prepare_pay_order_entries(db, entries)

    written: List[Dict[str, Any]] = []
    current = db.get_fiscal_config()
    owns = db.owns_transaction() if commit else False
    for key, value, until in prepared:
        old = int(current.get(key, _default_of(key)))
        db.conn.execute(
            "INSERT INTO fiscal_config (key, value, kind, note) VALUES (?, ?, 'override', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value, "偿还序override/折发系数（#653 ADR 0090）"),
        )
        db.conn.execute("UPDATE fiscal_config SET origin_ref = ? WHERE key = ?", (origin, key))
        db.record_fiscal_config_change(
            turn=turn, key=key, old_value=old, new_value=value,
            origin_ref=origin, reason=reason,
        )
        written.append({"key": key, "old": old, "new": value, "until_turn": until})
        until_key = f"{key}{_UNTIL_SUFFIX}"
        if until is not None:
            old_until = int(current.get(until_key, 0))
            db.conn.execute(
                "INSERT INTO fiscal_config (key, value, kind, note) VALUES (?, ?, 'override', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (until_key, until, "override 期限伴随键（#653 r2/r3）"),
            )
            db.conn.execute(
                "UPDATE fiscal_config SET origin_ref = ? WHERE key = ?", (origin, until_key)
            )
            db.record_fiscal_config_change(
                turn=turn, key=until_key, old_value=old_until, new_value=until,
                origin_ref=origin, reason=reason,
            )
            written[-1]["until_key"] = until_key
        elif until_key in current:
            # F1.4 stale until：永久旨覆写旧有期限键 → 同事务清遗留伴随键，
            # 否则旧期限仍使新旨过期。tombstone append-only 审计＋一行 provenance，不增表。
            stale_until = int(current[until_key])
            db.conn.execute(
                "INSERT INTO fiscal_config_tombstones"
                " (removed_turn, key, value, kind, origin_ref, reason, beyond_intent)"
                " VALUES (?, ?, ?, 'override', ?, ?, 0)",
                (turn, until_key, stale_until, origin,
                 "永久旨覆写清旧期限（#653 F1.4 stale until）"[:240]),
            )
            db.conn.execute("DELETE FROM fiscal_config WHERE key = ?", (until_key,))
            db.record_fiscal_config_change(
                turn=turn, key=until_key, old_value=stale_until, new_value=0,
                origin_ref=origin, reason="永久旨覆写清旧期限（stale until 清除）",
            )
            written[-1]["cleared_until_key"] = until_key
    if commit and owns:
        db.conn.commit()
    return written


def revoke_pay_order_decree(
    db: Any,
    *,
    turn: int,
    keys: List[str],
    origin_ref: str,
    reason: str = "",
    commit: bool = True,
) -> List[Dict[str, Any]]:
    """撤销旨＝写回默认值的新 config change（r2：old/new provenance 链即审计账）。
    到期路径（until_turn）不删键，读取端按 turn 判退出；撤销把值钉回默认基准。"""
    entries = [
        {"key": key, "value": _default_of(key)}
        for key in keys
    ]
    return materialize_pay_order_decree(
        db, turn=turn, entries=entries, origin_ref=origin_ref,
        reason=reason or "撤销 override 旨，恢复祖制默认序/系数", commit=commit,
    )


def _default_of(key: str) -> int:
    parsed = parse_override_key(key)
    if parsed.family == DUE_PRIORITY_FAMILY:
        return DEFAULT_DUE_PRIORITY[parsed.subject]
    if parsed.family == ARREARS_PRIORITY_FAMILY:
        return DEFAULT_ARREARS_PRIORITY[parsed.subject]
    return 10000  # haircut 无旨=无折
