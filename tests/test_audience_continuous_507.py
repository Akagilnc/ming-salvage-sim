"""#507 连场编排——presence-aware 组装：谁在场听到了什么，区间事实送对。

一条外部行为契约：连场一夜里，对话流按在场名单送入组装——侍立者的补话组装输入
含其在场时段殿上公开对话（AC2 区间取数），未在场者的组装输入不含殿内对话（AC3），
且回奏输入按角色见闻分流（AC4，千人千答非旧询问机制）。

北极星「乾清宫一夜」骨架（AUDIENCE_NORTH_STAR）：宣毕自严→留侍→宣徐光启→
毕自严插话站台→宣洪承畴+王绍徽同殿。区间取数/可闻性复用 #500 audible_entries_for
（御前低语不流入），本片验在真实 GameSession 组装路由与账本读边界。每正向配显式负向。
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim import audience_night as an
from ming_sim.audience_night import AUDIBILITY_PRIVATE, AUDIBILITY_PUBLIC
from ming_sim.session import GameSession

STANDING = "王承恩"  # 常在员额（内廷近臣全程在场）


def _activate(db, state, *names: str) -> None:
    for n in names:
        if db.get_character_status(n)[0] != "active":
            db.set_character_status(state, n, "active", reason="连场测试置在场")


def _public(db, nid, name, body):
    return an.append_ledger_entry(
        db, nid, person_names=[name], body=body, audibility=AUDIBILITY_PUBLIC,
    )


def _extract_exit(db, state, nid, name, body):
    """经真实 S3 抽取管线落一条抽取账 presence_effect='exit'（机器可读出场，无 TAG_EXIT）。"""
    ctid = db.create_chat_turn(state, name, "s", 0, night_id=nid)
    seq = db.conn.execute(
        "SELECT night_seq FROM chat_turns WHERE id=?", (ctid,)
    ).fetchone()["night_seq"]
    db.settle_story_extraction(
        ctid, nid,
        [{"person_names": [name], "body": body, "presence_effect": "exit"}],
        int(seq),
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
        db, nid, person_names=[STANDING], body="王承恩附耳：此人跋扈。",
        audibility=AUDIBILITY_PRIVATE,
    )

    recap = an.audience_scene_recap(db, "毕自严", night_id=nid)
    # 正向：侍立区间内殿上公开对话可被引用（区间取数）
    assert "徐光启奏：宜用洪承畴督师陕西。" in recap
    # 负向：御前低语不流入侍立者组装输入
    assert "此人跋扈" not in recap
    _ = (heard, whisper)

    # 负向（AC3）：从未入殿者的组装输入不含殿内对话，取空
    assert an.audience_scene_recap(db, "洪承畴", night_id=nid) == ""


def test_scene_recap_excludes_dialogue_before_person_entered(game):
    """侍立区间之前的殿上公开对话不流入（后入者听不到入殿前的话）。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])

    an.summon_enter(db, nid, "毕自严")
    _public(db, nid, "毕自严", "毕自严先奏钱粮九边。")   # 徐光启入殿前
    an.summon_enter(db, nid, "徐光启")                # 徐光启侍立区间起点
    _public(db, nid, "徐光启", "徐光启方入奏水利。")

    recap = an.audience_scene_recap(db, "徐光启", night_id=nid)
    assert "徐光启方入奏水利" in recap            # 正向：区间内
    assert "毕自严先奏钱粮九边" not in recap       # 负向：入殿前不闻


# ── AC2/AC3 生产路由：真实召对组装（_audience_prompt_for_message）──────────


def test_audience_prompt_carries_heard_hall_dialogue_for_present_attendant(game):
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启", "洪承畴")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "徐光启")
    _public(db, nid, "徐光启", "徐光启奏：宜用洪承畴督师陕西。")

    session = SimpleNamespace(db=db, state=state)
    # 正向：侍立在场的毕自严补话组装输入含其在场时段所闻殿上公开对话
    prompt_present = GameSession._audience_prompt_for_message(
        session, "卿以为如何？", content.characters["毕自严"])
    assert "徐光启奏：宜用洪承畴督师陕西。" in prompt_present

    # 负向（AC3）：未在场者（洪承畴，仅置 active 未入殿）组装输入不含殿内对话
    prompt_absent = GameSession._audience_prompt_for_message(
        session, "卿以为如何？", content.characters["洪承畴"])
    assert "徐光启奏：宜用洪承畴督师陕西" not in prompt_absent


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


def test_reply_input_routes_per_character_knowledge_not_one_answer_for_all(game):
    """同一朝局实况问在场的近臣与普通大臣，组装输入按各自见闻分流（非千人一答）。"""
    db, state, content = game
    _activate(db, state, "毕自严")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")

    session = SimpleNamespace(db=db, state=state)
    question = "陕西巡抚可有？"

    # 正向：问常在近臣王承恩——回奏输入取自其角色见闻。断言**去掉玩家原问后仍在**的见闻
    # 注入标记（近臣查访得督抚官缺实况），锁的是知识注入而非问句回声——「陕西巡抚」本在原问
    # 里、断言其存在恒真=假绿；「近臣查访」只由角色见闻投影渲染进 prompt、不在原问中。
    prompt_attendant = GameSession._audience_prompt_for_message(
        session, question, content.characters[STANDING])
    assert "近臣查访" in prompt_attendant.replace(question, "")

    # 负向：同一问题问不知情的普通大臣——不注入近臣查访见闻（答复因见闻不同而不同，千人千答）
    prompt_minister = GameSession._audience_prompt_for_message(
        session, question, content.characters["毕自严"])
    assert "近臣查访" not in prompt_minister


# ── 出殿边界：告退后殿上公开对话不入其组装（区间终点，两条出场路径各一）──────


def test_audience_prompt_excludes_hall_dialogue_after_command_dismiss(game):
    """出殿边界·command dismiss 路径（TAG_EXIT）：令退后的殿上公开对话不入其组装输入。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "徐光启")
    _public(db, nid, "徐光启", "徐光启奏：陕西糜烂当速定督抚。")  # 毕自严退前所闻
    an.dismiss_from_audience(db, "毕自严", night_id=nid)         # 令退（口令 TAG_EXIT）
    _public(db, nid, "徐光启", "徐光启续奏：九边军饷全无着落。")  # 毕自严退后

    session = SimpleNamespace(db=db, state=state)
    prompt = GameSession._audience_prompt_for_message(
        session, "卿以为如何？", content.characters["毕自严"])
    assert "陕西糜烂当速定督抚" in prompt        # 正向：退前所闻仍在区间内
    assert "九边军饷全无着落" not in prompt      # 负向：退后公开对话越出侍立区间、不入组装


def test_audience_prompt_excludes_hall_dialogue_after_extraction_exit(game):
    """出殿边界·抽取 presence_effect='exit' 路径（无 TAG_EXIT）：机器可读出场后的殿上
    公开对话不入其组装——修前 recap 只认 tags、漏抽取出场，区间终点错（AC2/AC3 回归钉）。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "徐光启")
    _public(db, nid, "徐光启", "徐光启奏：陕西糜烂当速定督抚。")  # 毕自严退前所闻
    _extract_exit(db, state, nid, "毕自严", "毕自严自请退至殿侧。")  # 抽取出场（无 TAG_EXIT）
    _public(db, nid, "徐光启", "徐光启续奏：九边军饷全无着落。")  # 毕自严退后

    session = SimpleNamespace(db=db, state=state)
    prompt = GameSession._audience_prompt_for_message(
        session, "卿以为如何？", content.characters["毕自严"])
    assert "陕西糜烂当速定督抚" in prompt        # 正向：退前所闻仍在
    assert "九边军饷全无着落" not in prompt      # 负向：抽取出场后公开对话不入组装


def test_present_roster_reflects_both_exit_paths_single_core(game):
    """单一在场步进（_presence_delta）：command dismiss 与抽取 presence_effect='exit' 两条
    出场路径都从在场名单去人——修前 persons_present_tonight 漏 command 出、recap 漏抽取出（双真源）。"""
    db, state, content = game
    _activate(db, state, "毕自严", "徐光启")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "徐光启")
    assert {"毕自严", "徐光启"} <= an.persons_present_tonight(db, nid)  # 正向：宣入皆在场

    an.dismiss_from_audience(db, "毕自严", night_id=nid)          # command 出
    _extract_exit(db, state, nid, "徐光启", "徐光启告退。")        # 抽取出
    present = an.persons_present_tonight(db, nid)
    assert "毕自严" not in present   # 负向：command dismiss 去人（修前漏）
    assert "徐光启" not in present   # 负向：抽取 presence_effect=exit 去人
