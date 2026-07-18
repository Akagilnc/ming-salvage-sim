"""pytest 基建：只读 opening 盘面 + 按用例隔离的临时库 fixture。

纯读用例可共享一次真实 seed 的只读盘面；写库用例仍各拿一个全新临时 SQLite，
互不污染。content 绑定到 context 和 issues 两个模块（各有自己的 _ctx）。
"""

from __future__ import annotations

import copy
import os
import shutil
import tempfile

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB

# 全新库 load_state 只 seed 危机/账本/邸报，不 seed powers/完整军政盘面（那些另处加载）。
# 测试需要齐全盘面（powers/characters/armies），用现有存档副本作基底，最可靠。
_SEED_DB = os.path.join(os.path.dirname(__file__), "..", "data", "probe.db")


@pytest.fixture(scope="session")
def content() -> GameContent:
    c = GameContent.load()
    ctx_bind(c)
    issues_mod.bind_content(c)
    return c


@pytest.fixture(scope="session")
def read_game(content):
    """返回共享的真实开局盘面，供不改变 DB/state/content 的纯读测试使用。

    只 seed 一次，并用 SQLite ``query_only`` 把误写变成响亮失败。任何写库路径、
    会改变 state/content 的路径，或需要验证事务/隔离的测试必须继续使用 ``game``。
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        db = GameDB(path, content)
        db.seed_static_data()
        state = db.load_state()
        issues_mod.sync_opening_legacies(db, state)
        db.conn.execute("PRAGMA query_only = ON")
        yield db, state, content
    finally:
        if db is not None:
            db.close()
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


@pytest.fixture(autouse=True)
def _restore_content_characters(content):
    """content 是 session 作用域共享对象，但建 GameSession（读档/_sync_offices_from_db_impl）
    会按 DB characters 表重建并**整体替换** content.characters。基底 data/probe.db 是旧档、
    缺 characters.json 独有的角色（如宗藩王 朱常洵 等），一旦某用例建过 session，content
    就从 101 缩成 58、宗藩王永久消失，泄漏到后续用例——实证宗藩可见性测试（含 /chat 守门）
    在全量里被静默 skip（「基底盘面无宗藩人物」），等于没验。

    每用例前快照、后还原 content.characters（深拷贝，连带 in-place 改的 office_type/status
    等字段一并隔离），从根上断掉这层跨用例泄漏。只拷 characters：观测到的泄漏在此面，
    region/faction 等不涉，避免无谓开销。"""
    saved = copy.deepcopy(content.characters)
    yield
    content.characters = saved


@pytest.fixture
def game(content):
    """返回 (db, state, content)：全新临时库经 seed_static_data 初始化静态盘面（offices/characters/
    character_offices/classes/factions/armies/regions/powers 齐全）+ load_state（开局危机/账本/邸报），
    用例间隔离。

    不依赖 gitignored data/probe.db（#5）：原 fixture copy probe.db 副本，缺则 skip——而 probe.db
    被 .gitignore 忽略，干净 checkout / CI 上依赖它的用例大面积 skip 当过=假绿。改走真实新档路径
    （seed_static_data，与生产开局同核）后，CI 无需任何外部 DB 即可跑；且 characters 直接来自
    content（101 全），不被 probe.db 旧档（缺 characters.json 独有的宗藩王等、缩成 58）掩盖。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        db = GameDB(path, content)
        db.seed_static_data()
        state = db.load_state()
        # 与生产开局序列一致（session.py：seed_static_data → load_state → sync_opening_legacies）：补开局
        # 负面帝国修正 modifiers——metric/economy delta 会查 active legacy modifier 做 %修正，缺则盘面与
        # 生产不一致、依赖修正的断言对不上（codex #5 r1 high）。不立 issue、不进推演（同生产）。
        issues_mod.sync_opening_legacies(db, state)
        yield db, state, content
    finally:
        # setup（GameDB/seed/load_state）抛错也清 temp——原 setup 在 try 外，失败绕过 teardown 泄漏
        # 临时 DB 文件/句柄（cmr #5 r2 coderabbit）。走封装的 db.close() 而非裸 conn.close()（gemini #5）。
        if db is not None:
            db.close()
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


@pytest.fixture
def saved_game(content):
    """返回 (db, state, content)：data/probe.db「玩过存档」副本（带历史 issue / 账本流水 / 已退场
    人物 / 到期密令 / 帝国修正等运行时状态），用例间隔离。

    与 `game`（fresh seed 开局态）区别：这些用例的断言依赖**玩过后的特定运行时状态**（某历史
    issue、国库余额、帝国修正下的 metric 增量、due secret_order 等），fresh seed 无法复现。暂用
    probe.db 隔离，缺则**明确 skip 并注明原因**（非隐藏假绿，#5）——区别于原 `game` 缺 probe.db
    时静默 skip 掉**全部**盘面用例。后续应逐个 deterministic 化（测试自带 setup 注入所需状态），
    见 #5 followup。"""
    if not os.path.exists(_SEED_DB):
        pytest.skip("缺玩过存档 data/probe.db（gitignored）；本用例依赖运行时状态，待 deterministic 化（#5 followup）")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        shutil.copy(_SEED_DB, path)
        db = GameDB(path, content)
        state = db.load_state()
        yield db, state, content
    finally:
        # setup（copy/GameDB/load_state）抛错也清 temp（cmr #5 r2 coderabbit）；封装 db.close()（gemini #5）。
        if db is not None:
            db.close()
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def active_ming_character(db, content) -> str:
    """取一个开局 active 的大明大臣姓名，供人物状态测试用（不硬编死名字）。"""
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            return name
    raise AssertionError("找不到 active 的大明大臣")


@pytest.fixture(autouse=True)
def _isolated_user_data_dir(tmp_path):
    """全套测试隔离 user-data（错误包/拒收镜像）——集中兜底（cmr S1 r2 P1）。

    没有它，任何走 run_settle/写包路径的用例都把测试产物写进真实 data/error_packs
    （实证 18 包 75MB + 假行混真 jsonl + attempt 序号灌高）。各用例自己 setenv 指
    自己的 tmp_path 仍可覆盖本兜底（后设者胜）。

    用独立 MonkeyPatch 实例而非共享的 monkeypatch fixture：后者与测试同一实例，
    测试里 monkeypatch.undo() 会把本兜底一并撤掉（实证 test_noready_recovery
    undo 后 settle 把空目录建回真实 data/）。"""
    mp = pytest.MonkeyPatch()
    mp.setenv("MING_SIM_USER_DATA_DIR", str(tmp_path / "user_data"))
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _isolate_cli_bin_resolution():
    """全套测试隔离 runner 可执行定位：清 _BIN_CACHE，并把登录 shell 探测短路成
    "不触发"（_DISCOVERED_LOGIN_PATH="" → _login_shell_path 立即返 None）。

    这样任何走 _resolve_cli_bin 的 runner 测试（test_cli_backend / test_llm_channel_config
    等）在缺 codex/claude/agy 的机器上都不会真 spawn 一个 zsh，解析类测试也不串 cache。
    （cmr r2 codex X-R1：原 fixture 只在 test_cli_backend.py，漏了 test_llm_channel_config.py
    的 runner 测试——移到 conftest 集中兜底。）

    用独立 MonkeyPatch 实例（同 _isolated_user_data_dir）：测试里 monkeypatch.undo() 不会
    把本兜底一并撤掉。需真跑 _login_shell_path 解析逻辑的测试，自行把 _DISCOVERED_LOGIN_PATH
    重置为 None 并 mock _RAW_RUN。"""
    import ming_sim.cli_backend as _cb
    _cb._BIN_CACHE.clear()
    mp = pytest.MonkeyPatch()
    mp.setattr(_cb, "_DISCOVERED_LOGIN_PATH", "")
    yield
    mp.undo()
    _cb._BIN_CACHE.clear()
