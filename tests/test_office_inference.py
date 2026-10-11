from __future__ import annotations
import ming_sim.cli_backend as cb
import ming_sim.db as dbmod
from ming_sim.entities.character.appointment import apply_office_appointment
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.db import infer_office_type_from_office as infer
from ming_sim.models import LLMConfig
import pytest
"""官职分类经真实授官和开局入口验证 DB 与运行态，不以推断 helper 自证。"""





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
    apply_office_appointment(db, state, content, "刘鸿训", "绝无此名的杜撰怪衔庚辛壬", llm_config=cfg, region_id="shaanxi")
    assert db.conn.execute("SELECT office_type FROM characters WHERE name='刘鸿训'").fetchone()[0] == "边镇"
    assert content.characters["刘鸿训"].office_type == "边镇"
    assert seen["config"] is cfg


def test_api_channel_unknown_office_ignores_cli_derived_cache(monkeypatch):
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
    assert infer(office, llm_config=cli_cfg) == "边镇"

    called = []
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_run_backend_for_config", lambda prompt, *a, **k: called.append(prompt) or ("边镇", 1))
    api_cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-api",
        channel="api",
    )

    assert infer(office, llm_config=api_cfg) == "待铨"
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
