"""官职分类经真实授官和开局入口验证 DB 与运行态，不以推断 helper 自证。"""

from __future__ import annotations

import pytest

import ming_sim.cli_backend as cb
import ming_sim.db as dbmod
import ming_sim.issues as issues_mod
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.models import LLMConfig


def _cli_cfg() -> LLMConfig:
    return LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.3-codex-spark",
        cli_timeout_seconds=240,
    )


@pytest.mark.parametrize("office,expected", [
    # 代表性锚：每类一条 + 历史误判样本（#1185 缩表，非穷举词表）
    ("礼部尚书,东阁大学士", "内阁"),   # 复合衔内阁优先
    ("兵部尚书,左都御史", "兵部"),     # 六部首衔优先于都察院
    ("都察院右佥都御史", "都察院"),
    ("庶常", "翰林院"),                 # 曾误归生员
    ("司礼监掌印太监", "司礼监"),        # stem 命中，不靠 bare 掌印太监
    ("御马监掌印太监", "内廷"),           # bare 掌印太监 不得吞入司礼监
    ("锦衣卫都指挥使", "锦衣卫"),
    ("蓟辽总督", "地方"),               # 督抚不被边镇地名吞
    ("荡寇将军", "边镇"),               # 旧版武职漏判
    ("中宫皇后", "后宫"),               # 旧版进待铨
    ("诸生（应天府学）", "生员"),
    ("陕北流寇首领", "流寇"),
    ("绝无此名的杜撰怪衔甲乙丙", "待铨"),
])
def test_office_type_from_table(game, monkeypatch, office, expected):
    db, state, _ = game
    content = GameContent.load()
    db.content = content
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    before = db.conn.execute("SELECT office, office_type FROM characters WHERE name='刘鸿训'").fetchone()
    result = issues_mod.apply_office_appointment(
        db, state, content, "刘鸿训", office, region_id="shaanxi",
    )
    row = db.conn.execute("SELECT office, office_type FROM characters WHERE name='刘鸿训'").fetchone()
    if expected == "后宫":
        # 后宫授官已退役；不能绕过真实任命闸只保 helper 的分类成功。
        assert result["rejected"] and result["category"] == "invalid_enum"
        assert tuple(row) == tuple(before)
    else:
        assert not result.get("rejected")
        assert tuple(row) == (office, expected)
        assert content.characters["刘鸿训"].office_type == expected


def test_runtime_cli_unknown_office_uses_configured_runner_without_env(game, monkeypatch):
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    seen = {}
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def fake_run(prompt, llm_config=None, tag="", *, policy=None):
        seen["prompt"] = prompt
        seen["config"] = llm_config
        return "边镇", 1

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_run)
    cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )

    db, state, content = game
    issues_mod.apply_office_appointment(db, state, content, "刘鸿训", "绝无此名的杜撰怪衔庚辛壬", llm_config=cfg, region_id="shaanxi")
    assert db.conn.execute("SELECT office_type FROM characters WHERE name='刘鸿训'").fetchone()[0] == "边镇"
    assert content.characters["刘鸿训"].office_type == "边镇"
    assert seen["config"] is cfg


def test_api_channel_unknown_office_ignores_cli_derived_cache(game, monkeypatch):
    office = "绝无此名的杜撰怪衔缓存测试"
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def fake_run(prompt, llm_config=None, tag="", *, policy=None):
        return "边镇", 1

    monkeypatch.setattr(cb, "_run_backend_for_config", fake_run)
    cli_cfg = LLMConfig(
        api_key="cli-backend",
        base_url="",
        model="api-fallback",
        channel="cli",
        cli_runner="codex",
        cli_model="gpt-5.5",
        cli_timeout_seconds=240,
    )
    db, state, content = game
    issues_mod.apply_office_appointment(db, state, content, "刘鸿训", office, llm_config=cli_cfg, region_id="shaanxi")
    assert db.conn.execute("SELECT office_type FROM characters WHERE name='刘鸿训'").fetchone()[0] == "边镇"

    called = []
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_run_backend", lambda prompt: called.append(prompt) or ("边镇", 1))
    api_cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-api",
        channel="api",
    )

    issues_mod.apply_office_appointment(db, state, content, "毕自严", office, llm_config=api_cfg)
    assert db.conn.execute("SELECT office_type FROM characters WHERE name='毕自严'").fetchone()[0] == "待铨"
    assert content.characters["毕自严"].office_type == "待铨"
    assert called == []


def test_fresh_gamesession_start_makes_no_backend_calls(tmp_path, monkeypatch):
    """全路径回归（new_game 真实路径）：GameSession(fresh) 构造 + begin_turn 整段零 CLI 后端。
    覆盖 seed_static_data 与 _sync_offices_from_db_impl 两条逐人 infer 路径——后者每 begin_turn
    都跑，缓存填法一变风暴会从 seed 搬到 sync（实测教训），故端到端锁死整段零调用。"""
    from ming_sim.session import GameSession

    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    calls = []
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda prompt, llm_config=None, tag="", *, policy=None: calls.append(prompt) or ("待铨", 1),
    )
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    sess = GameSession(
        db_path=str(tmp_path / "start.db"),
        llm_config=_cli_cfg(),
        content=content,
    )
    try:
        sess.begin_turn()
        sess.begin_turn()  # 再跑一回合：sync 路径每回合复跑，确认仍零调用
        assert calls == [], f"开局全路径不应调 CLI 后端，实调 {len(calls)} 次：{calls[:3]}"
        for name, expected in (("皇太极", "外臣"), ("朱常洵", "宗藩"), ("郑成功", "未仕")):
            assert sess.db.conn.execute("SELECT office_type FROM characters WHERE name=?", (name,)).fetchone()[0] == expected
            assert sess.content.characters[name].office_type == expected
    finally:
        try:
            sess.close()
        except Exception:
            pass


def test_sync_preserves_persisted_court_office_type_on_table_miss(tmp_path):
    """cmr R2 回归（codex high, cross-section）：_sync_offices_from_db_impl 每回合 begin_turn 都跑，
    不得把 DB 里已持久化的朝堂类 office_type 在 office 文本表查不中时降级成 待铨——否则动态任命
    （use_llm=True 路径）落库的 礼部/兵部 等会在下一回合 sync 时被悄悄降级，内存与 DB 不一致且每回合复发。"""
    from tests.month_chain_helpers import make_light_session

    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    db = GameDB(str(tmp_path / "sync.db"), content=content, llm_config=_cli_cfg())
    db.seed_static_data()
    # 模拟一次动态任命：DB 里某人 office=生造朝堂官名(表查不中) + office_type=礼部(持久化真相)
    db.conn.execute(
        "UPDATE characters SET office=?, office_type=? WHERE name=?",
        ("册封朝鲜使归途", "礼部", "刘鸿训"),
    )
    db.conn.commit()
    session = make_light_session(db, db.load_state(), content)
    session.llm_config = _cli_cfg()
    session.begin_turn()
    assert content.characters["刘鸿训"].office_type == "礼部", \
        "sync 不得把 DB 持久化的朝堂类 office_type 在表查不中时降级成待铨"


def test_sync_restores_office_region_from_character_offices(tmp_path):
    """DB→Character 重建必须带回 character_offices.region_id 任所（#1812）。"""
    from tests.month_chain_helpers import make_light_session

    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    db = GameDB(str(tmp_path / "sync-region.db"), content=content, llm_config=_cli_cfg())
    db.seed_static_data()
    name = next(
        n for n, ch in content.characters.items()
        if ch.office_type not in {"后宫", "宗藩"}
        and db.characters.get_character_status(n)[0] == "active"
    )
    db.conn.execute(
        "UPDATE characters SET office=?, office_type=? WHERE name=?",
        ("河南巡抚", "地方", name),
    )
    db._record_character_office(name, "河南巡抚", "地方", "test-sync", region_id="henan")
    db.conn.commit()
    # Wipe runtime projection then rebuild from DB only.
    content.characters = {}
    session = make_light_session(db, db.load_state(), content)
    session.llm_config = _cli_cfg()
    session.begin_turn()
    assert name in content.characters
    assert content.characters[name].office_region == "henan"
    assert db.characters.office_region(name) == "henan"


def test_appointment_seat_identity_reuses_local_and_strips_central(game):
    """一次任职 resolved seat：地方同职省略 region 续任不跨省挤位；中央夹带 region 归一空。"""
    from ming_sim.issues import (
        apply_office_appointment,
    )

    db, state, content = game
    rows = db.conn.execute(
        "SELECT name FROM characters WHERE status='active' AND power_id='ming' "
        "AND office_type NOT IN ('后宫','宗藩') ORDER BY name LIMIT 2"
    ).fetchall()
    a, b = str(rows[0]["name"]), str(rows[1]["name"])

    r1 = apply_office_appointment(
        db, state, content, a, "巡抚",
        new_office_type="督抚", region_id="shaanxi", reason="seat-a",
    )
    assert not r1.get("rejected")
    r2 = apply_office_appointment(
        db, state, content, b, "巡抚",
        new_office_type="督抚", region_id="henan", reason="seat-b",
    )
    assert not r2.get("rejected")
    assert db.characters.office_region(a) == "shaanxi"
    assert db.characters.office_region(b) == "henan"

    # Same-office local continuation omits region → reuse shaanxi; henan intact.
    r3 = apply_office_appointment(
        db, state, content, a, "巡抚",
        new_office_type="督抚", region_id="", reason="reappoint-omit-region",
    )
    assert not r3.get("rejected")
    assert not r3.get("displaced"), r3
    assert content.characters[a].office == "巡抚"
    assert content.characters[a].office_region == "shaanxi"
    assert db.characters.office_region(a) == "shaanxi"
    assert content.characters[b].office == "巡抚"
    assert content.characters[b].office_region == "henan"
    assert db.characters.office_region(b) == "henan"

    # Central appointment persists no local seat.
    r4 = apply_office_appointment(
        db, state, content, a, "户部尚书",
        new_office_type="户部", region_id="henan", reason="central-noise-region",
    )
    assert not r4.get("rejected")
    assert db.characters.office_region(a) == ""
    assert content.characters[a].office_region == ""
