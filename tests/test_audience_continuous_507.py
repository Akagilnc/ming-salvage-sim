"""#507 连场编排——presence-aware 组装：谁在场听到了什么，区间事实送对。

连场一夜中，可闻账按在场区间分流：侍立者听到区间内公开对话，
未入殿和已退者不闻殿内对应时段的对话。

北极星「乾清宫一夜」骨架（AUDIENCE_NORTH_STAR）：宣毕自严→留侍→宣徐光启→
毕自严插话站台→宣洪承畴+王绍徽同殿。区间取数/可闻性复用 #500 audible_entries_for
（御前低语不流入），本片验在账本可闻性读边界。每正向配显式负向。
"""

from __future__ import annotations
from ming_sim.audience_night import PRESENCE_EXIT

from ming_sim import audience_night as an
from ming_sim.audience_night import AUDIBILITY_PUBLIC

STANDING = "王承恩"  # 常在员额（内廷近臣全程在场）


def _activate(db, state, *names: str) -> None:
    for n in names:
        if db.get_character_status(n)[0] != "active":
            db.set_character_status(state, n, "active", reason="连场测试置在场")



def _public(db, nid, name, body):
    return an.append_ledger_entry(
        db, nid, person_names=[name], body=body, audibility=AUDIBILITY_PUBLIC,
    )



def _record_exit(db, nid, name):
    return an.append_ledger_entry(
        db, nid,
        person_names=[name],
        audibility=AUDIBILITY_PUBLIC,
        body="",
        presence_effect=PRESENCE_EXIT,
        check_dead=False,
    )



# ── AC2/AC3：侍立者补话组装取其在场时段殿上公开对话；未在场者取空 ──────────


# ── AC1：乾清宫一夜连场骨架可跑（宣→留侍→宣→插话站台→同殿）──────────────


# ── AC4：回奏输入按角色见闻分流（同问不同答/臣不知，千人千答非旧询问机制）──


# ── 出殿边界：告退后殿上公开对话不入其组装（区间终点，两条出场路径各一）──────


def test_exit_excludes_later_public_ledger_from_character_hearing(game):
    """出殿边界：退前所闻保留，退后的公开事实不可闻。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "徐光启")
    heard_id = _public(db, nid, "徐光启", "徐光启奏：陕西糜烂当速定督抚。")
    _record_exit(db, nid, "毕自严")
    unheard_id = _public(db, nid, "徐光启", "徐光启续奏：九边军饷全无着落。")

    visible_ids = {r["id"] for r in an.audible_entries_for(db, nid, "毕自严")}
    assert heard_id in visible_ids
    assert unheard_id not in visible_ids
