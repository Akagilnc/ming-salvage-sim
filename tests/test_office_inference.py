"""office_type 推断走 offices.json 参考表（替代旧正则词表）。

无 CLI 后端时 LLM 兜底不触发（表查不中→待铨），故这里只测表命中的确定性分类，
重点覆盖旧版漏判进『待铨』的：后宫/武职/民间。
"""

from __future__ import annotations

import pytest

import ming_sim.cli_backend as cb
import ming_sim.db as dbmod
import ming_sim.issues as issues_mod
from ming_sim.content import GameContent
from ming_sim.context import bind_content
from ming_sim.db import GameDB
from ming_sim.db import infer_office_type_from_office as infer
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
])
def test_office_type_from_table(office, expected):
    assert infer(office) == expected


def test_后宫_current_type_short_circuits():
    assert infer("妃", current_type="后宫") == "后宫"


def test_unknown_falls_to_daiquan_without_backend(monkeypatch):
    # 无 CLI 后端 + 表查不中 → 待铨（不误判、不崩）
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    assert infer("绝无此名的杜撰怪衔甲乙丙") == "待铨"


def test_api_channel_unknown_office_does_not_use_backend_env(monkeypatch):
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    called = []
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(cb, "_run_backend", lambda prompt: called.append(prompt) or ("边镇", 1))
    cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-api",
        channel="api",
    )

    assert infer("绝无此名的杜撰怪衔丁戊己", llm_config=cfg) == "待铨"
    assert called == []


def test_runtime_cli_unknown_office_uses_configured_runner_without_env(monkeypatch):
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    seen = {}
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def fake_run(prompt, llm_config=None, tag=""):
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

    assert infer("绝无此名的杜撰怪衔庚辛壬", llm_config=cfg) == "边镇"
    assert "官名：绝无此名的杜撰怪衔庚辛壬" in seen["prompt"]
    assert seen["config"] is cfg


def test_api_channel_unknown_office_ignores_cli_derived_cache(monkeypatch):
    office = "绝无此名的杜撰怪衔缓存测试"
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)

    def fake_run(prompt, llm_config=None, tag=""):
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
    monkeypatch.setattr(cb, "_run_backend", lambda prompt: called.append(prompt) or ("边镇", 1))
    api_cfg = LLMConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-api",
        channel="api",
    )

    assert infer(office, llm_config=api_cfg) == "待铨"
    assert called == []


def test_use_llm_false_skips_backend_and_trusts_content_type(monkeypatch):
    """静态名册接档：content 已写好 office_type 时不该再问 LLM。
    use_llm=False → 表查不中直接信传入的 current_type（非朝堂类原样返回）、零后端调用。
    默认 use_llm=True 行为不变（动态生造官名仍交 LLM）。"""
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    called = []
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda prompt, llm_config=None, tag="": called.append(prompt) or ("内阁", 1),
    )
    cfg = _cli_cfg()
    # 外藩官名表查不中 + content=外臣（非朝堂类）→ use_llm=False 原样保留、不打后端
    assert infer("后金汗", current_type="外臣", llm_config=cfg, use_llm=False) == "外臣"
    # 朝堂六部类(COURT) current_type 表查不中：use_llm=False 信 content/DB 既定值原样保留(礼部),
    # 不降级成待铨——否则每回合 DB sync 会把动态任命落库的朝堂类 office_type 悄悄降级(cmr R2 codex high)。
    assert infer("册封朝鲜使归途", current_type="礼部", llm_config=cfg, use_llm=False) == "礼部"
    assert called == [], "use_llm=False 不得调 CLI 后端"
    # 默认 use_llm=True：动态路径仍问后端
    assert infer("后金汗", current_type="外臣", llm_config=cfg) == "内阁"
    assert called, "默认 use_llm=True 应仍走 LLM 兜底"


def test_fresh_seed_makes_no_office_type_backend_calls(tmp_path, monkeypatch):
    """开局 LLM 风暴回归（new_game 慢 5 分钟根因）：seed_static_data 灌 101 人静态名册时，
    凡 office 文本查不中明廷参考表的（外藩/宗藩/平民），绝不逐人现拉 codex 判 office_type。
    CLI 通道下整段 seed 必须零后端调用，且这些角色按 content 既定 office_type 落库。"""
    dbmod._OFFICE_TYPE_LLM_CACHE.clear()
    monkeypatch.delenv("MING_SIM_LLM_BACKEND", raising=False)
    calls = []
    monkeypatch.setattr(
        cb, "_run_backend_for_config",
        lambda prompt, llm_config=None, tag="": calls.append(prompt) or ("待铨", 1),
    )
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    db = GameDB(str(tmp_path / "seed.db"), content=content, llm_config=_cli_cfg())
    db.seed_static_data()

    assert calls == [], f"seed 不应调 CLI 后端，实调 {len(calls)} 次：{calls[:3]}"

    def otype(name: str) -> str:
        row = db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?", (name,)
        ).fetchone()
        return row["office_type"] if row else ""

    # 外藩按 content=外臣；宗藩、平民按各自 content 值；均未被 LLM 污染成明廷职
    assert otype("皇太极") == "外臣"
    assert otype("朱常洵") == "宗藩"
    assert otype("郑成功") == "未仕"


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
        lambda prompt, llm_config=None, tag="": calls.append(prompt) or ("待铨", 1),
    )
    content = GameContent.load()
    bind_content(content)
    issues_mod.bind_content(content)
    sess = GameSession(
        db_path=str(tmp_path / "start.db"),
        llm_config=_cli_cfg(),
        content=content,
        verify_llm=False,
    )
    try:
        sess.begin_turn()
        sess.begin_turn()  # 再跑一回合：sync 路径每回合复跑，确认仍零调用
        assert calls == [], f"开局全路径不应调 CLI 后端，实调 {len(calls)} 次：{calls[:3]}"
    finally:
        try:
            sess.close()
        except Exception:
            pass


def test_sync_preserves_persisted_court_office_type_on_table_miss(tmp_path):
    """cmr R2 回归（codex high, cross-section）：_sync_offices_from_db_impl 每回合 begin_turn 都跑，
    不得把 DB 里已持久化的朝堂类 office_type 在 office 文本表查不中时降级成 待铨——否则动态任命
    （use_llm=True 路径）落库的 礼部/兵部 等会在下一回合 sync 时被悄悄降级，内存与 DB 不一致且每回合复发。"""
    from ming_sim.session import _sync_offices_from_db_impl

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
    _sync_offices_from_db_impl(content, db, _cli_cfg())
    assert content.characters["刘鸿训"].office_type == "礼部", \
        "sync 不得把 DB 持久化的朝堂类 office_type 在表查不中时降级成待铨"
