from __future__ import annotations
from ming_sim import audience_night as an
import pytest
from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    PRESENCE_EXIT,
    TAG_ENTER,
    TAG_EXIT,
    AudienceNightError,
)
from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    TAG_ENTER,
    TAG_EXIT,
    AudienceNightError,
)
"""#500 在场推导与进出账——真实 GameDB + 真实 content 语境的进出账 → 在场末态。

一条外部行为契约：进出账（入殿/告退/传召在途）经确定性推导器得出「任一时刻
谁在场」，以及侍立区间可闻性取数。真实 open_night 落常在员额（王承恩），真实
summon_enter 落入殿账；断言推导器读账的机器承重态（在场/不在场）。

北极星案例（AUDIENCE_NORTH_STAR）：王绍徽入殿时徐光启/毕自严已侍立；王承恩
（常在员额）全程在场。不锁叙事正文；每正向配显式负向。
"""




STANDING = "王承恩"  # 常在员额（信邸内官随驾 → 内廷近臣）


def _activate(db, state, *names: str) -> None:
    """把北极星在场者置为 active（徐光启开局 offstage 罢居），供入殿账。"""
    for n in names:
        if db.characters.get_character_status(n)[0] != "active":
            db.set_character_status(state, n, "active", reason="召对测试置在场")


def _last_seq(db, night_id: int) -> int:
    entries = an.list_ledger(db, night_id)
    return int(entries[-1]["seq"]) if entries else 0


# ── AC1：「令 X 退下」口令 → 确定性告退账 → 名单查询即时变化（数据→引擎→交互）──






# ── AC1 真实入口 tracer：CLI 玩家「退下」口令 → 引擎告退账 → 名单即时去人 ──










# ── L1 R2：court_action=dismiss 单缝——非流式 web /api/audience/chat
#          与 CLI tool 路共 GameSession.chat 产源，令退落告退账、名单即时去人 ──


# ── L2：告退后再宣入须重新落入殿账（present_names_at 单一在场真源）──────────


def test_reenter_after_exit_reappears_in_roster(game):
    db, state, content = game
    _activate(db, state, "毕自严")
    night = an.open_night(db, state, location="乾清宫")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    _record_exit(db, nid, "毕自严")
    assert "毕自严" not in an.present_names_at(db, nid)

    def _enters() -> int:
        return sum(
            1 for e in an.list_ledger(db, nid)
            if TAG_ENTER in e["tags"] and "毕自严" in e["person_names"]
        )

    before = _enters()
    reid = an.ensure_summon_enter(db, nid, "毕自严")  # 告退后再宣 → 重新落账
    assert reid  # 非 None
    assert "毕自严" in an.present_names_at(db, nid)
    assert _enters() == before + 1
    # 负向：在场者 ensure 幂等，不重复落入殿账
    assert an.ensure_summon_enter(db, nid, "毕自严") is None
    assert _enters() == before + 1


# ── L3：传召在途召法校验与 summon_enter 对齐 ──────────────────────────────


def test_transit_rejects_bad_method(game):
    db, state, content = game
    _activate(db, state, "洪承畴")
    night = an.open_night(db, state, location="乾清宫")
    nid = int(night["id"])
    seq_before = _last_seq(db, nid)
    with pytest.raises(AudienceNightError) as ei:
        an.record_summon_in_transit(db, nid, "洪承畴", method="密召")
    assert ei.value.code == "bad_summon_method"
    assert _last_seq(db, nid) == seq_before  # 非法召法不落账
    # 正向：合法召法入账，在途者不在场
    eid = an.record_summon_in_transit(db, nid, "洪承畴", method=an.METHOD_CHUANZHAO)
    assert eid and "洪承畴" not in an.present_names_at(db, nid)


# ── AC2/3/5：表驱动进出账 → 任一时刻在场名单 ────────────────────────────


def _build_presence_night(db, state):
    """建一夜进出账；返回 (night_id, seqs)。seqs 记各关键账的 seq。"""
    _activate(db, state, "徐光启", "毕自严", "王绍徽", "洪承畴")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    seqs = {}
    an.summon_enter(db, nid, "徐光启"); seqs["徐光启_入"] = _last_seq(db, nid)
    an.summon_enter(db, nid, "毕自严"); seqs["毕自严_入"] = _last_seq(db, nid)
    an.record_summon_in_transit(db, nid, "洪承畴"); seqs["洪承畴_途"] = _last_seq(db, nid)
    an.summon_enter(db, nid, "王绍徽"); seqs["王绍徽_入"] = _last_seq(db, nid)
    _record_exit(db, nid, "徐光启"); seqs["徐光启_退"] = _last_seq(db, nid)
    return nid, seqs


# (label, at_seq_key, expected_present ⊇, expected_absent)
_PRESENCE_CASES = [
    (
        "王绍徽入殿时徐光启/毕自严已侍立（北极星）",
        "王绍徽_入",
        {"徐光启", "毕自严", "王绍徽", STANDING},
        set(),
    ),
    (
        "传召在途者不在名单；徐光启入殿前不在名单",
        "徐光启_入",
        {"徐光启", STANDING},
        {"毕自严", "王绍徽", "洪承畴"},
    ),
    (
        "告退后末态即时去人；在途者始终不入名单",
        None,  # 夜内末态
        {"毕自严", "王绍徽", STANDING},
        {"徐光启", "洪承畴"},
    ),
]


@pytest.mark.parametrize(
    "label,at_key,expected_present,expected_absent",
    _PRESENCE_CASES,
    ids=[c[0] for c in _PRESENCE_CASES],
)
def test_present_names_at_table(game, label, at_key, expected_present, expected_absent):
    db, state, content = game
    nid, seqs = _build_presence_night(db, state)
    at_seq = None if at_key is None else seqs[at_key]
    present = an.present_names_at(db, nid, at_seq=at_seq)
    assert expected_present <= present, f"{label}: 缺 {expected_present - present}"
    assert not (expected_absent & present), f"{label}: 误含 {expected_absent & present}"
    assert not any(TAG_EXIT in entry["tags"] and STANDING in entry["person_names"]
                   for entry in an.list_ledger(db, nid))


def test_present_names_at_uses_timeline_key_not_raw_seq(game):
    """回归（coderabbit #1087）：list_ledger 按 COALESCE(order_key, seq) 排序，补跑抽取账
    order_key 可小于其自身 seq。present_names_at 若按裸 seq 截断，会在早排却大 seq 的抽取账
    处误 break、漏掉其后命令账。断言按时序键截断——时序上更晚的入殿账仍计入名单。"""
    db, state, content = game
    _activate(db, state, "徐光启", "毕自严")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "徐光启")
    xu_seq = _last_seq(db, nid)
    an.summon_enter(db, nid, "毕自严")
    bi_seq = _last_seq(db, nid)
    # 补跑抽取账：时序键落在两道入殿账之间（早排），但其自身 seq 最大（补跑晚落）。
    an.append_ledger_entry(
        db, nid, order_key=float(xu_seq) + 0.5,
    )
    present = an.present_names_at(db, nid, at_seq=bi_seq)
    assert "毕自严" in present  # 旧码在大 seq 抽取账处误 break → 毕自严漏掉
    assert "徐光启" in present




# ── AC6：侍立区间取数只含殿上公开条目（御前低语不流入）──────────────────


def test_audible_interval_public_only(game):
    db, state, content = game
    _activate(db, state, "毕自严", "王绍徽")
    night = an.open_night(db, state, location="乾清宫")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    # 王绍徽入殿前的公开对话：不在其侍立区间，不该流入
    before_id = an.append_ledger_entry(
        db, nid, person_names=["毕自严"],
        audibility=AUDIBILITY_PUBLIC,
    )
    an.summon_enter(db, nid, "王绍徽")  # 王绍徽侍立区间起点
    # 区间内御前低语：私账不流入
    whisper_id = an.append_ledger_entry(
        db, nid, person_names=[STANDING],
        audibility=AUDIBILITY_PRIVATE,
    )
    # 区间内公开条目：应流入
    public_id = an.append_ledger_entry(
        db, nid, person_names=["王绍徽"],
        audibility=AUDIBILITY_PUBLIC,
    )

    audible = an.audible_entries_for(db, nid, "王绍徽")
    ids = {int(e["id"]) for e in audible}
    assert public_id in ids  # 正向：区间内公开条目流入
    assert whisper_id not in ids  # 负向：御前低语不流入
    assert before_id not in ids  # 负向：侍立区间之前的条目不流入
    assert all(e["audibility"] == AUDIBILITY_PUBLIC for e in audible)

    # 不在场者取数为空
    assert an.audible_entries_for(db, nid, "洪承畴") == []

def _record_exit(db, night_id: int, name: str, **kwargs):
    """现役在场 exit 供料：走已有账本入口 presence_effect，不经已退役独立写口。"""
    return an.append_ledger_entry(
        db, night_id,
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body="",
        presence_effect=PRESENCE_EXIT,
        check_dead=False,
        **kwargs,

    )
