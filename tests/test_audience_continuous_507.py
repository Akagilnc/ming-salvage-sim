"""#507 连场编排——presence-aware 组装：谁在场听到了什么，区间事实送对。

连场一夜中，可闻账按在场区间分流：侍立者听到区间内公开对话，
未入殿和已退者不闻殿内对应时段的对话。

北极星「乾清宫一夜」骨架（AUDIENCE_NORTH_STAR）：宣毕自严→留侍→宣徐光启→
毕自严插话站台→宣洪承畴+王绍徽同殿。区间取数/可闻性复用 #500 audible_entries_for
（御前低语不流入），本片验在账本可闻性读边界。每正向配显式负向。
"""

from __future__ import annotations

from ming_sim import audience_night as an
from ming_sim.audience_night import AUDIBILITY_PRIVATE, AUDIBILITY_PUBLIC

STANDING = "王承恩"  # 常在员额（内廷近臣全程在场）


def _activate(db, state, *names: str) -> None:
    for n in names:
        if db.characters.get_character_status(n)[0] != "active":
            db.set_character_status(state, n, "active", reason="连场测试置在场")


def _public(db, nid, name, body):
    return an.append_ledger_entry(
        db, nid, person_names=[name], body=body, audibility=AUDIBILITY_PUBLIC,
    )


# ── AC2/AC3：侍立者补话组装取其在场时段殿上公开对话；未在场者取空 ──────────


def test_scene_recap_quotes_public_dialogue_within_presence_interval(game):
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启", "洪承畴")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])

    an.summon_enter(db, nid, "毕自严")            # 毕自严侍立区间起点
    an.summon_enter(db, nid, "徐光启")
    heard = _public(db, nid, "徐光启", "徐光启奏：宜用洪承畴督师陕西。")
    whisper = an.append_ledger_entry(
        db, nid, person_names=[STANDING], body="此人跋扈",
        audibility=AUDIBILITY_PRIVATE,
    )

    # 可闻性/私语排除：以账条目 id + audibility 为身份，不拿正文当 oracle。
    audible_ids = {r["id"] for r in an.audible_entries_for(db, nid, "毕自严")}
    assert heard in audible_ids
    assert whisper not in audible_ids
    assert all(
        r.get("audibility") == AUDIBILITY_PUBLIC
        for r in an.audible_entries_for(db, nid, "毕自严")
    )
    recap = an.audience_scene_recap(db, "毕自严", night_id=nid)
    # 正向：侍立区间内公开账进入 recap 读面（正文为字段搬运，非身份）
    heard_body = next(
        str(e.get("body") or "")
        for e in an.list_ledger(db, nid) if int(e["id"]) == heard
    )
    assert heard_body in recap

    # 负向（AC3）：从未入殿者的组装输入不含殿内对话，取空
    assert an.audience_scene_recap(db, "洪承畴", night_id=nid) == ""
    assert an.audible_entries_for(db, nid, "洪承畴") == []


def test_scene_recap_excludes_dialogue_before_person_entered(game):
    """侍立区间之前的殿上公开对话不流入（后入者听不到入殿前的话）。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])

    an.summon_enter(db, nid, "毕自严")
    before_id = _public(db, nid, "毕自严", "毕自严先奏钱粮九边。")  # 徐光启入殿前
    an.summon_enter(db, nid, "徐光启")                # 徐光启侍立区间起点
    within_id = _public(db, nid, "徐光启", "徐光启方入奏水利。")

    audible_ids = {r["id"] for r in an.audible_entries_for(db, nid, "徐光启")}
    assert within_id in audible_ids                 # 正向：区间内
    assert before_id not in audible_ids             # 负向：入殿前不闻（条目身份）
    within_body = next(
        str(e.get("body") or "")
        for e in an.list_ledger(db, nid) if int(e["id"]) == within_id
    )
    assert within_body in an.audience_scene_recap(db, "徐光启", night_id=nid)




# ── AC1：乾清宫一夜连场骨架可跑（宣→留侍→宣→插话站台→同殿）──────────────


def test_qianqing_continuous_night_skeleton_runs(game):
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启", "洪承畴", "王绍徽")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])

    # 宣毕自严
    an.summon_enter(db, nid, "毕自严")
    assert "毕自严" in an.present_names_at(db, nid)

    # 宣徐光启——毕自严不退则留侍（宣下一个不断场、前一位留殿侧侍立）
    an.summon_enter(db, nid, "徐光启")
    present = an.present_names_at(db, nid)
    assert {"毕自严", "徐光启", STANDING} <= present

    # 毕自严插话站台：其补话组装可引用侍立时段所闻徐光启奏对
    _public(db, nid, "徐光启", "徐光启奏：陕西糜烂，非洪承畴不可。")
    recap = an.audience_scene_recap(db, "毕自严", night_id=nid)
    assert "非洪承畴不可" in recap
    _public(db, nid, "毕自严", "毕自严出班为洪承畴站台作保。")

    # 宣洪承畴 + 王绍徽同殿——前面诸位皆未退，同殿侍立
    an.summon_enter(db, nid, "洪承畴")
    an.summon_enter(db, nid, "王绍徽")
    final = an.present_names_at(db, nid)
    assert {"毕自严", "徐光启", "洪承畴", "王绍徽", STANDING} <= final

    # 负向：同殿骨架里无人误落告退账（无人被强制转移出场）
    exits = [e for e in an.list_ledger(db, nid) if an.TAG_EXIT in e["tags"]]
    assert exits == []


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
    an.dismiss_from_audience(db, "毕自严", night_id=nid)
    unheard_id = _public(db, nid, "徐光启", "徐光启续奏：九边军饷全无着落。")

    visible_ids = {r["id"] for r in an.audible_entries_for(db, nid, "毕自严")}
    assert heard_id in visible_ids
    assert unheard_id not in visible_ids


def test_present_roster_reflects_command_dismissal(game):
    """召退命令从现役在场名单移除召入者，并保留仍侍立者。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "徐光启")
    assert {"毕自严", "徐光启"} <= an.persons_present_tonight(db, nid)  # 正向：宣入皆在场

    an.dismiss_from_audience(db, "毕自严", night_id=nid)
    present = an.persons_present_tonight(db, nid)
    assert "毕自严" not in present
    assert "徐光启" in present
