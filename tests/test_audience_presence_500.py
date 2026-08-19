"""#500 在场推导与进出账——真实 GameDB + 真实 content 语境的进出账 → 在场末态。

一条外部行为契约：进出账（入殿/告退/传召在途）经确定性推导器得出「任一时刻
谁在场」，以及侍立区间可闻性取数。真实 open_night 落常在员额（王承恩），真实
summon_enter 落入殿账；断言推导器读账的机器承重态（在场/不在场）。

北极星案例（AUDIENCE_NORTH_STAR）：王绍徽入殿时徐光启/毕自严已侍立；王承恩
（常在员额）全程在场。不锁叙事正文；每正向配显式负向。
"""

from __future__ import annotations

import pytest

from ming_sim import audience_night as an
from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    TAG_ENTER,
    TAG_EXIT,
    AudienceNightError,
)

STANDING = "王承恩"  # 常在员额（信邸内官随驾 → 内廷近臣）


def _activate(db, state, *names: str) -> None:
    """把北极星在场者置为 active（徐光启开局 offstage 罢居），供入殿账。"""
    for n in names:
        if db.get_character_status(n)[0] != "active":
            db.set_character_status(state, n, "active", reason="召对测试置在场")


def _last_seq(db, night_id: int) -> int:
    entries = an.list_ledger(db, night_id)
    return int(entries[-1]["seq"]) if entries else 0


# ── AC1：「令 X 退下」口令 → 确定性告退账 → 名单查询即时变化（数据→引擎→交互）──


def test_dismiss_command_updates_roster_immediately(game):
    db, state, content = game
    _activate(db, state, "毕自严", "王绍徽")
    night = an.open_night(db, state, location="乾清宫", time_of_day="戌时")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.summon_enter(db, nid, "王绍徽")

    before = an.present_names_at(db, nid)
    assert {"毕自严", "王绍徽", STANDING} <= before

    entry_id = an.dismiss_from_audience(db, "毕自严", night_id=nid)
    assert entry_id  # 确定性落告退账
    exit_e = an.list_ledger(db, nid)[-1]
    assert TAG_EXIT in exit_e["tags"] and "毕自严" in exit_e["person_names"]

    after = an.present_names_at(db, nid)
    assert "毕自严" not in after  # 名单即时去人
    assert {"王绍徽", STANDING} <= after  # 未被令退者仍在场


def test_dismiss_noop_when_not_present(game):
    """负向：令一个不在场者退下 → 不落账、名单不变、返回 None。"""
    db, state, content = game
    _activate(db, state, "王绍徽")
    night = an.open_night(db, state, location="乾清宫")
    nid = int(night["id"])
    an.summon_enter(db, nid, "王绍徽")

    before = an.present_names_at(db, nid)
    seq_before = _last_seq(db, nid)
    assert an.dismiss_from_audience(db, "毕自严", night_id=nid) is None
    assert _last_seq(db, nid) == seq_before  # 未追加任何账
    assert an.present_names_at(db, nid) == before

    with pytest.raises(AudienceNightError) as ei:
        an.dismiss_from_audience(db, "  ", night_id=nid)
    assert ei.value.code == "empty_person"


# ── AC1 真实入口 tracer：CLI 玩家「退下」口令 → 引擎告退账 → 名单即时去人 ──


def _cli_session(db, state, content):
    from types import SimpleNamespace

    def chat(_name, _question, chat_turn_id=0):
        return SimpleNamespace(
            answer="臣有本奏。", proposed_directive=None, appointed_minister="",
            registered_minister="", displaced_minister="", court_action="",
            next_minister="", secret_order_id=0, pending_action_id=0,
            pending_action_failures=[],
        )

    return SimpleNamespace(
        db=db, state=state, content=content, temporary_characters=set(), chat=chat,
        # #542 scene lifecycle seams（CLI minister_chat / 退下会调）；替身 no-op。
        start_chat_turn_scene=lambda *_a, **_k: None,
        start_chat_turn_exit_scene=lambda *_a, **_k: None,
        join_chat_turn_scene=lambda *_a, **_k: [],
        persist_chat_turn_scene=lambda *_a, **_k: None,
        abandon_chat_turn_scene=lambda *_a, **_k: None,
    )


def _active_minister(db, content):
    return next(
        c for c in content.characters.values()
        if db.get_character_status(c.name)[0] == "active"
        and getattr(c, "power_id", "ming") == "ming"
        and getattr(c, "office_type", "") != "后宫"
    )


def test_dismiss_via_cli_command_writes_exit_ledger(game, monkeypatch):
    """AC1 真实入口：起聊入殿 → 「退下」口令 → 告退账落地、present 即时去人。"""
    import ming_sim.cli.terminal as term

    db, state, content = game
    character = _active_minister(db, content)
    session = _cli_session(db, state, content)
    answers = iter(["朕问卿边事如何？", "退下"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(session, character) == "dismiss"

    nid = int(an.get_open_night(db)["id"])
    last = an.list_ledger(db, nid)[-1]
    assert TAG_EXIT in last["tags"] and character.name in last["person_names"]
    assert character.name not in an.present_names_at(db, nid)


def test_court_break_writes_no_exit_ledger(game, monkeypatch):
    """负向：退朝不落个人告退账（#526 收夜链 ≠ dismiss 告退）。"""
    import ming_sim.cli.terminal as term

    db, state, content = game
    character = _active_minister(db, content)
    session = _cli_session(db, state, content)
    closed_nid: dict[str, int] = {}

    # #526：CLI 退朝走收夜；本测只证「无个人告退账」，收夜本体 stub 成功。
    # #1353：生产 epilogue 传 write_gate=…；假体须收 **kwargs，禁 TypeError。
    def _close_ok(court_action: str, **_kwargs) -> None:
        assert court_action == "court_break"
        open_n = an.get_open_night(db)
        assert open_n is not None
        nid = int(open_n["id"])
        closed_nid["id"] = nid
        an._set_night_fields(
            db, nid, status=an.NIGHT_STATUS_CLOSED, closed_at="test",
        )

    session.close_night_after_chat_if_needed = _close_ok
    answers = iter(["朕问卿边事如何？", "退朝"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert term.minister_chat(session, character) == "court_break"

    nid = closed_nid["id"]
    exits = [
        e for e in an.list_ledger(db, nid)
        if TAG_EXIT in e["tags"] and character.name in e["person_names"]
    ]
    assert exits == []  # 未落个人告退账
    assert an.get_night(db, nid)["status"] == an.NIGHT_STATUS_CLOSED


# ── L1 R2：court_action=dismiss 单缝——非流式 web /api/ministers/{name}/chat
#          与 CLI tool 路共 GameSession.chat 产源，令退落告退账、名单即时去人 ──


def _session_double(db, state, content, registry):
    from types import SimpleNamespace
    from ming_sim.session import GameSession

    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = registry
    sess.llm_config = SimpleNamespace(channel="api")
    sess.temporary_characters = set()
    sess._audience_prompt_for_message = lambda message: message
    sess._start_cli_action_intent = lambda *a, **k: None
    sess._finish_cli_action_intent = lambda *a, **k: None
    return sess


def _tool_registry(tools):
    from types import SimpleNamespace

    class Agent:
        def run(self, _message):
            return SimpleNamespace(content="臣领旨。", tools=list(tools))

    class Registry:
        def get(self, _character):
            return Agent()

        def build_draft_line(self):
            return "无"

    return Registry()


def test_session_chat_tool_dismiss_writes_exit_ledger(game):
    from types import SimpleNamespace
    from ming_sim.session import GameSession

    db, state, content = game
    minister = _active_minister(db, content)
    an.attach_chat_turn_to_night(db, state, minister.name)  # 生产同：session.chat 前已开夜入殿
    nid = int(an.get_open_night(db)["id"])
    assert minister.name in an.present_names_at(db, nid)

    registry = _tool_registry(
        [SimpleNamespace(tool_name="dismiss_minister", result="__dismiss__")]
    )
    result = GameSession.chat(_session_double(db, state, content, registry), minister.name, "臣请退。")

    assert result.court_action == "dismiss"
    last = an.list_ledger(db, nid)[-1]
    assert TAG_EXIT in last["tags"] and minister.name in last["person_names"]
    assert minister.name not in an.present_names_at(db, nid)


def test_session_chat_non_dismiss_leaves_present(game):
    """负向：非令退 tool 轮不落告退账、当前对谈大臣仍在场。"""
    from ming_sim.session import GameSession

    db, state, content = game
    minister = _active_minister(db, content)
    an.attach_chat_turn_to_night(db, state, minister.name)
    nid = int(an.get_open_night(db)["id"])

    result = GameSession.chat(
        _session_double(db, state, content, _tool_registry([])), minister.name, "边饷如何？",
    )

    assert result.court_action == ""
    exits = [
        e for e in an.list_ledger(db, nid)
        if TAG_EXIT in e["tags"] and minister.name in e["person_names"]
    ]
    assert exits == []
    assert minister.name in an.present_names_at(db, nid)


# ── L2：告退后再宣入须重新落入殿账（present_names_at 单一在场真源）──────────


def test_reenter_after_exit_reappears_in_roster(game):
    db, state, content = game
    _activate(db, state, "毕自严")
    night = an.open_night(db, state, location="乾清宫")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    an.dismiss_from_audience(db, "毕自严", night_id=nid)
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
    an.dismiss_from_audience(db, "徐光启", night_id=nid); seqs["徐光启_退"] = _last_seq(db, nid)
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
        db, nid, body="（补跑抽取账·无在场效果）", order_key=float(xu_seq) + 0.5,
    )
    present = an.present_names_at(db, nid, at_seq=bi_seq)
    assert "毕自严" in present  # 旧码在大 seq 抽取账处误 break → 毕自严漏掉
    assert "徐光启" in present


def test_standing_roster_present_throughout(game):
    """AC3：王承恩（常在员额）全程在场——每个关键时刻均在名单。"""
    db, state, content = game
    nid, seqs = _build_presence_night(db, state)
    checkpoints = [
        seqs["徐光启_入"], seqs["毕自严_入"], seqs["洪承畴_途"],
        seqs["王绍徽_入"], seqs["徐光启_退"], None,
    ]
    for at in checkpoints:
        assert STANDING in an.present_names_at(db, nid, at_seq=at)
    # 负向：常在员额从未落告退账 → 无 TAG_EXIT 条目挂其名
    exits = [
        e for e in an.list_ledger(db, nid)
        if TAG_EXIT in e["tags"] and STANDING in e["person_names"]
    ]
    assert exits == []


# ── AC6：侍立区间取数只含殿上公开条目（御前低语不流入）──────────────────


def test_audible_interval_public_only(game):
    db, state, content = game
    _activate(db, state, "毕自严", "王绍徽")
    night = an.open_night(db, state, location="乾清宫")
    nid = int(night["id"])
    an.summon_enter(db, nid, "毕自严")
    # 王绍徽入殿前的公开对话：不在其侍立区间，不该流入
    before_id = an.append_ledger_entry(
        db, nid, person_names=["毕自严"], body="毕自严先奏钱粮。",
        audibility=AUDIBILITY_PUBLIC,
    )
    an.summon_enter(db, nid, "王绍徽")  # 王绍徽侍立区间起点
    # 区间内御前低语：私账不流入
    whisper_id = an.append_ledger_entry(
        db, nid, person_names=[STANDING], body="王承恩附耳低语。",
        audibility=AUDIBILITY_PRIVATE,
    )
    # 区间内公开条目：应流入
    public_id = an.append_ledger_entry(
        db, nid, person_names=["王绍徽"], body="王绍徽当廷奏对。",
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
