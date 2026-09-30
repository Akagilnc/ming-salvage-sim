"""pytest 基建：只读 opening 盘面 + 按用例隔离的临时库 fixture。

纯读用例可共享一次真实 seed 的只读盘面；写库用例仍各拿一个全新临时 SQLite，
互不污染。content 绑定到 context 和 issues 两个模块（各有自己的 _ctx）。
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
import os
import shutil
import tempfile
import threading

import pytest

from ming_sim.content import GameContent
from ming_sim.context import bind_content as ctx_bind
import ming_sim.issues as issues_mod
from ming_sim.db import GameDB

# 全新库 load_state 只 seed 危机/账本/开局公共见闻，不 seed powers/完整军政盘面（那些另处加载）。
# #1356：不再 seed 固定开局邸报文。测试需要齐全盘面（powers/characters/armies），用现有存档副本作基底，最可靠。
_SEED_DB = os.path.join(os.path.dirname(__file__), "..", "data", "probe.db")


@pytest.fixture(scope="session")
def content() -> GameContent:
    c = GameContent.load()
    ctx_bind(c)
    issues_mod.bind_content(c)
    return c


def _seed_opening_db(path: str, content) -> None:
    """生产开局同核：seed_static_data + load_state + sync_opening_legacies，写入 path。"""
    db = GameDB(path, content)
    try:
        db.seed_static_data()
        state = db.load_state()
        issues_mod.sync_opening_legacies(db, state)
    finally:
        db.close()


@contextmanager
def _opening_game(content):
    """创建并清理一个与生产开局序列同核的临时盘面。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        _seed_opening_db(path, content)
        db = GameDB(path, content)
        state = db.load_state()
        yield db, state, content
    finally:
        if db is not None:
            db.close()
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


def own_session_until_game_teardown(db, owner) -> None:
    """让 ``game`` fixture 在关闭 SQLite 前排空该 session 的已接纳工作。"""
    owners = getattr(db, "_test_session_owners", None)
    if owners is None:
        owners = []
        db._test_session_owners = owners
    queue = getattr(owner, "_write_queue", None)
    for existing in owners:
        if existing is owner:
            return
        if queue is not None and getattr(existing, "_write_queue", None) is queue:
            return
    owners.append(owner)


def note_queue_until_game_teardown(db, queue) -> None:
    """登记写队列本身。drain 不得因此关掉夹具拥有的连接。"""
    from types import SimpleNamespace

    own_session_until_game_teardown(db, SimpleNamespace(_write_queue=queue))


def _install_tail_owner_note(mp: pytest.MonkeyPatch) -> None:
    """机械尾的 owner 可能是未 bind 的临时对象，轻壳登记覆盖不到。

    在既有 ``_submit_tail`` 入口把该写队列送进排空名单。不改生产调度。
    """
    import ming_sim.mechanical_tail as tail_mod
    from ming_sim.session_write_queue import get_session_write_queue

    real_submit = tail_mod._submit_tail

    def _submit_and_note(session, **kwargs):
        note_queue_until_game_teardown(
            session.db, get_session_write_queue(session),
        )
        return real_submit(session, **kwargs)

    mp.setattr(tail_mod, "_submit_tail", _submit_and_note)


def _drain_registered_sessions_before_close(db) -> None:
    """排空已登记队列上未完成的写票，再由夹具自己关库。

    关库顺序只看写票是否完成，不看执行器类型。委托真实线程池的替身
    仍有在飞任务时，barrier 等到票完成才返回。
    """
    from ming_sim.session_write_queue import drain_and_close_session

    owners = list(getattr(db, "_test_session_owners", ()) or ())
    for owner in reversed(owners):
        drain_and_close_session(owner)


@pytest.fixture(scope="session")
def _game_template_path(content):
    """Session 级开局模板 DB（只 seed 一次）。供 ``game`` 每案文件拷贝，避免逐案建库。

    方案 (c)：模板 DB 一次建 + 每案文件拷贝。不用 (d) 事务回滚——全 suite 大量用例自带
    commit/rollback、跨连接可见性、崩溃恢复与 applier 事务边界（ADR 0008 族），禁区命中。
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _seed_opening_db(path, content)
        yield path
    finally:
        for p in (path, f"{path}_agno.db"):
            if os.path.exists(p):
                os.remove(p)


@pytest.fixture(scope="session")
def read_game(content):
    """返回共享的真实开局盘面，供不改变 DB/state/content 的纯读测试使用。

    只 seed 一次，并用 SQLite ``query_only`` 把误写变成响亮失败。任何写库路径、
    会改变 state/content 的路径，或需要验证事务/隔离的测试必须继续使用 ``game``。
    """
    with _opening_game(content) as opening:
        db, _state, _content = opening
        db.conn.execute("PRAGMA query_only = ON")
        yield opening


def _rebind_session_content(content) -> None:
    """把各模块 _content 绑回 session 级共享 GameContent。

    WebGame/GameSession 常 `GameContent.load()` 新对象并 `_bind_all_content`，
    把 issues/context/agents/… 指到另一份盘面；仅还原 `content.characters`
    不够——后续 `game` 夹具仍用 session content，而 `apply_person_changes_only`
    走 `_ctx()` 会改到已退役的那份，DB 与断言侧 content 分叉。
    """
    from ming_sim.session import _bind_all_content

    _bind_all_content(content)


@pytest.fixture(autouse=True)
def _restore_content_characters(content):
    """content 是 session 作用域共享对象，但建 GameSession（读档/_sync_offices_from_db_impl）
    会按 DB characters 表重建并**整体替换** content.characters。基底 data/probe.db 是旧档、
    缺 characters.json 独有的角色（如宗藩王 朱常洵 等），一旦某用例建过 session，content
    就从 101 缩成 58、宗藩王永久消失，泄漏到后续用例——实证宗藩可见性测试（含 /chat 守门）
    在全量里被静默 skip（「基底盘面无宗藩人物」），等于没验。

    每用例前快照、后还原 content.characters（深拷贝，连带 in-place 改的 office_type/status
    等字段一并隔离），并从前后两端把 bind_content 模块绑回本 session content，
    断掉 GameSession 另 load 后留下的跨用例 _content 漂移。只拷 characters：
    观测到的泄漏在此面，region/faction 等不涉，避免无谓开销。"""
    saved = copy.deepcopy(content.characters)
    _rebind_session_content(content)
    yield
    content.characters = saved
    _rebind_session_content(content)


@pytest.fixture(autouse=True)
def _transport_retry_interval_instant():
    """#1792：测试默认不真等 attempt 间隔（生产默认 5s）。

    需时钟断言的用例自行 monkeypatch `_sleep_retry_interval` 推进受控时钟。
    独立 MonkeyPatch：测试内 monkeypatch.undo() 不会撤掉本兜底。
    """
    import ming_sim.llm_transport as transport_mod

    mp = pytest.MonkeyPatch()
    mp.setattr(transport_mod, "_sleep_retry_interval", lambda _seconds: None)
    try:
        yield
    finally:
        mp.undo()


@pytest.fixture
def game(content, _game_template_path, monkeypatch):
    """返回 (db, state, content)：开局同核临时库，用例间隔离。

    Setup 形态（#1233 刀1 方案 c）：session 模板 DB 一次 seed，每案 ``shutil.copyfile``
    后 ``GameDB``+``load_state``。断言语义与逐案 ``seed_static_data`` 相同（同核开局态），
    只把 setup 从 O(seed) 降到 O(copy)。

    不依赖 gitignored data/probe.db（#5）：characters 直接来自 content（101 全）。
    """
    del monkeypatch
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    # 独立 MonkeyPatch：测试内 monkeypatch.undo() 不撤掉尾票登记。
    tail_note = pytest.MonkeyPatch()
    try:
        shutil.copyfile(_game_template_path, path)
        db = GameDB(path, content)
        state = db.load_state()
        _install_tail_owner_note(tail_note)
        yield db, state, content
    finally:
        try:
            if db is not None:
                _drain_registered_sessions_before_close(db)
                db.close()
            for p in (path, f"{path}_agno.db"):
                if os.path.exists(p):
                    os.remove(p)
        finally:
            tail_note.undo()


@pytest.fixture
def saved_game(content):
    """返回 (db, state, content)：data/probe.db「玩过存档」副本（带历史 issue / 账本流水 / 已退场
    人物 / 到期密令 / 帝国修正等运行时状态），用例间隔离。

    与 `game`（fresh seed 开局态）区别：这些用例的断言依赖**玩过后的特定运行时状态**（某历史
    issue、国库余额、帝国修正下的 metric 增量、due secret_order 等），fresh seed 无法复现。暂用
    probe.db 隔离，缺则**明确 skip 并注明原因**（非隐藏假绿，#5）——区别于原 `game` 缺 probe.db
    时静默 skip 掉**全部**盘面用例。后续应逐个 deterministic 化（测试自带 setup 注入所需状态），
    见 #5 followup。"""
    if not os.path.exists(_SEED_DB) or os.path.getsize(_SEED_DB) == 0:
        pytest.skip("缺玩过存档 data/probe.db（gitignored）；本用例依赖运行时状态，待 deterministic 化（#5 followup）")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = None
    try:
        shutil.copy(_SEED_DB, path)
        db = GameDB(path, content)
        region_n = db.conn.execute("SELECT COUNT(*) AS n FROM regions").fetchone()["n"]
        if int(region_n or 0) == 0:
            pytest.skip("data/probe.db 无盘面（空库）；本用例依赖玩过存档")
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


# ADR 0010 / #1023 / #547：人物抽象轴偏门哨兵（单一真源；世界事实数值不在此列）。
CHARACTER_AXIS_SENTINEL = {
    "loyalty": 17,
    "ability": 37,
    "integrity": 57,
    "courage": 77,
    "identity": 97,
}


def plant_character_axis_sentinels(db, content, name: str) -> dict[str, int]:
    """把人物五轴写成 CHARACTER_AXIS_SENTINEL（DB + content 内存镜像同步）。"""
    db.conn.execute(
        "UPDATE characters SET loyalty=?, ability=?, integrity=?, courage=?, identity=? "
        "WHERE name=?",
        (*CHARACTER_AXIS_SENTINEL.values(), name),
    )
    db.conn.commit()
    character = content.characters[name]
    for field, value in CHARACTER_AXIS_SENTINEL.items():
        setattr(character, field, value)
    return dict(CHARACTER_AXIS_SENTINEL)


def open_audience_night(db, state, *, time_of_day: str = "戌时", location: str = "乾清宫") -> int:
    """开一场召对夜，返回 night_id（539/547 夜脚手架真源）。"""
    from ming_sim import audience_night as an

    return int(an.open_night(db, state, time_of_day=time_of_day, location=location)["id"])


def append_night_chat(
    db, state, night_id: int, minister: str, user_text: str, answer: str, seq: int,
) -> tuple[int, int]:
    """写入一对 user/minister 消息 + chat_turns 行；返回 (turn_id, minister_message_id)。"""
    uid = db.append_chat_message(minister, state.turn, "user", user_text)
    mid = db.append_chat_message(minister, state.turn, "minister", answer)
    cur = db.conn.execute(
        "INSERT INTO chat_turns "
        "(minister_name,turn,year,period,user_message_id,minister_message_id,night_id,night_seq) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (minister, state.turn, state.year, state.period, uid, mid, night_id, seq),
    )
    db.conn.commit()
    return int(cur.lastrowid), int(mid)


@pytest.fixture(autouse=True)
def _isolated_user_data_dir(tmp_path):
    """全套测试隔离 user-data（错误包/拒收镜像）——集中兜底（cmr S1 r2 P1）。

    没有它，任何走 run_settle/写包路径的用例都把测试产物写进真实 data/error_packs
    （实证 18 包 75MB + 假行混真 jsonl + attempt 序号灌高）。各用例自己 setenv 指
    自己的 tmp_path 仍可覆盖本兜底（后设者胜）。

    同步把 import 时钉死的 user_data 常量（``UPLOAD_PORTRAIT_DIR`` /
    ``RUNTIME_LLM_PATH``）拨到本用例 tmp——否则 env 改了
    常量仍指仓内 ``data/``，xdist 多 worker 会抢同一固定路径（#1233 刀2 gate）。

    用独立 MonkeyPatch 实例而非共享的 monkeypatch fixture：后者与测试同一实例，
    测试里 monkeypatch.undo() 会把本兜底一并撤掉（实证 test_noready_recovery
    undo 后 settle 把空目录建回真实 data/）。"""
    import ming_sim.llm_config as _llm_config
    import web_app as _web_app

    user_root = tmp_path / "user_data"
    portrait_dir = user_root / "uploads" / "portraits"
    portrait_dir.mkdir(parents=True, exist_ok=True)

    mp = pytest.MonkeyPatch()
    mp.setenv("MING_SIM_USER_DATA_DIR", str(user_root))
    mp.setattr(_web_app, "UPLOAD_PORTRAIT_DIR", str(portrait_dir))
    mp.setattr(_llm_config, "RUNTIME_LLM_PATH", str(user_root / "runtime_llm.json"))
    yield
    mp.undo()


def open_hall_turn(
    db, state, minister_name, *, agno_session_id="", agno_runs_before=0, route="",
    **_ignored,
):
    """测试 setup（非生产 API）：开夜 + 建轮 + 具名大臣 ensure_summon_enter。

    只组合现行生产 seam，不复活已删 attach/beat。
    """
    from ming_sim.audience_night import (
        METHOD_XUANRU,
        NIGHT_STATUS_CLOSING,
        NIGHT_STATUS_OPEN,
        SCENE_CHAT_SPEAKER,
        ensure_open_night_for_audience,
        ensure_summon_enter,
        get_open_night,
    )
    night = get_open_night(db)
    if night is not None and str(night.get("status") or "") == NIGHT_STATUS_CLOSING:
        ensure_open_night_for_audience(db, state)  # raises
    if night is None or str(night.get("status") or "") != NIGHT_STATUS_OPEN:
        night = ensure_open_night_for_audience(db, state)
    night_id = int(night["id"])
    ctid = int(db.create_chat_turn(
        state,
        minister_name,
        agno_session_id or f"test:{minister_name}",
        int(agno_runs_before or 0),
        night_id=night_id,
        status="generating",
    ))
    name = str(minister_name or "").strip()
    if name and name != SCENE_CHAT_SPEAKER:
        ensure_summon_enter(
            db, night_id, name,
            method=METHOD_XUANRU,
            origin_chat_turn_id=ctid,
        )
    return night_id, ctid


# The offline model needs the exact reply, not a parsed fragment of a prose prompt.
# ContextVar keeps concurrent translation workers' inputs independent.
from tests.offline_audience_reply import reply as _offline_audience_reply


def offline_empty_audience_translate(prompt, llm_config):
    """离线转译边界：无政务声明，但逐字保留受控输入中的回话。"""
    del prompt, llm_config
    reply = _offline_audience_reply.get()
    if reply is None:
        raise RuntimeError("离线转译未收到本轮结构化回话")
    return {"commissions": [], "promises": [], "scene_facts": [
        {"body": reply, "role": "scene", "audibility": "殿上公开", "person_names": []},
    ]}


class LegRendezvous:
    """并行腿的会合：N 条腿同时在飞才算成立，且**永不把主线程挂死**（#1898）。

    会合只回答一件事——「这些腿真的并行跑了吗」，故腿侧只用标准库
    ``threading.Barrier``；真实入口、并行与隔离契约都不动。

    上一轮漏掉的是**次序**：主线程若先卡在 ``wait_idle``，``finally`` 里的
    abort 永远到不了，而在等的那条腿正占着票据 —— 两边互锁，只能等 CI 杀进程。
    故本轮把「判否」提前到排空**之前**，判据只用一条真实事实（均不靠墙钟）：

    * **再无可能抵达的腿，且已不再有腿要提交**：只有「已开跑但还没抵达
      会合点」的腿才可能补上缺口，故 :attr:`_pending` 归零即「再无人会到」；
      同时 :meth:`close` 标记「不会再有新腿被提交」。两者同时成立且
      ``arrived < parties`` 时，需求确定不可满足 → :meth:`abort`。
      两条判据缺一不可：只判 ``_pending == 0`` 会在「主线程先提交一条、
      等它到达后再提交下一条」的两档用例里误杀（第一条抵达的瞬间
      ``_pending`` 短暂归零，但第二条还没提交）。这一条同时盖住：扇出正常
      返回但少提交一条腿、某腿抛错或被取消、参与方压根没提交、提交本身失败。
    * **用例收尾**：:meth:`abort` 公开，用例 ``finally`` 仍调一次，覆盖主线程
      断言失败、第二次调度直接返回 False 这类连 Future 都没有的路。

    :meth:`settle` 是主线程排空前的落点：会合成立或已判否即返回，故
    ``settle()`` → ``wait_pending_writes()`` 的次序本身就不可能挂死。
    用例提交完所有腿后调一次 :meth:`close`（扇出型用例由父腿自动 close）。
    """

    def __init__(self, monkeypatch, parties: int = 2) -> None:
        self._parties = parties
        self._barrier = threading.Barrier(parties)
        self._first = threading.Event()      # 首条腿到达
        self._settled = threading.Event()    # 会合成立或已判否
        self._lock = threading.Lock()
        self._arrived = 0
        # 已开跑、尚未抵达会合点的腿数（抵达/跑完任一即退出此计数）。
        self._pending = 0
        self._closed = False                  # 已声明「不会再有新腿被提交」
        self._local = threading.local()   # 本腿的 arrived 标记
        self._install(monkeypatch)

    # ── 观测缝 ────────────────────────────────────────────────────────
    def _install(self, monkeypatch) -> None:
        import ming_sim.audience_translation as audience_translation

        real_executor = audience_translation._executor
        rendezvous = self

        class _CountingExecutor:
            """只旁听每条腿的「是否还可能抵达会合点」，其余透传真执行器。

            必须在执行器**实例**上替换整个对象：``submit`` 是只读槽描述符，
            monkeypatch 直接改实例属性会 AttributeError。

            腿内再提交子腿者即扇出父腿（开夜扫描）：它跑完时子腿已全部提交，
            故自动 close —— 此后不会再有新腿，判否条件成立。
            """

            def submit(self, fn, *args, **kwargs):
                leg_state = {"arrived": False, "fanout": False}
                is_fanout = getattr(rendezvous._local, "state", None) is not None
                leg_state["fanout"] = is_fanout
                rendezvous._arm(leg_state)

                def leg(*a, **k):
                    rendezvous._local.state = leg_state
                    try:
                        return fn(*a, **k)
                    finally:
                        rendezvous._local.state = None
                        rendezvous._disarm(leg_state)
                        if is_fanout:
                            rendezvous.close()

                try:
                    return real_executor.submit(leg, *args, **kwargs)
                except BaseException:
                    # 提交本身失败：这条腿永远不会抵达，计数须当场归还，
                    # 否则 _pending 永不归零、判否永不触发（#1898 扇出失败路）。
                    rendezvous._disarm(leg_state)
                    if is_fanout:
                        rendezvous.close()
                    raise

            def __getattr__(self, name):
                return getattr(real_executor, name)

        monkeypatch.setattr(
            audience_translation, "_executor", _CountingExecutor(),
        )

    def _unsatisfiable(self) -> bool:
        """已关闭提交 + 无可能再抵达的腿 + 仍不足 parties → 需求不可满足。"""
        with self._lock:
            return self._closed and self._pending <= 0 and self._arrived < self._parties

    def close(self) -> None:
        """声明「不会再有新腿被提交」（用例提交完所有腿后调；幂等）。

        扇出型用例无需显式调：父腿在腿内提交子腿，父腿跑完即自动 close。
        """
        with self._lock:
            self._closed = True
        if self._unsatisfiable():
            self.abort()

    def _arm(self, leg_state: dict) -> None:
        """一条腿开跑：计入「仍可能抵达」（提交成功与否都先记，失败即归还）。"""
        with self._lock:
            self._pending += 1

    def _disarm(self, leg_state: dict) -> None:
        """这条腿不再可能抵达（已抵达过 / 已跑完 / 提交失败）：只计一次。"""
        with self._lock:
            if leg_state["arrived"]:
                return                      # 已在 _arrive 归还过，不重复
            self._pending -= 1
        if self._unsatisfiable():
            self.abort()

    def _arrive(self, leg_state: dict) -> int:
        """本腿抵达会合点：计入到达数并退出「可能抵达」计数（只减一次）。

        抵达后当场复判：此刻本腿即将卡在 ``barrier.wait()`` 上（它自己不会再让
        ``_pending`` 变化），故判否必须在这里下，否则就没人再下判断。
        """
        with self._lock:
            if not leg_state["arrived"]:
                leg_state["arrived"] = True
                self._pending -= 1
            self._arrived += 1
            arrived = self._arrived
        if self._unsatisfiable():
            self.abort()
        return arrived

    # ── 放闸 ──────────────────────────────────────────────────────────
    def abort(self) -> None:
        """打破会合：在等的腿立刻拿 BrokenBarrierError 退出并归还票据。幂等。"""
        self._barrier.abort()
        self._first.set()
        self._settled.set()

    @property
    def _current(self) -> dict:
        """当前线程所处那条腿的 arrived 标记（不在腿内则给一次性空标记）。"""
        state = getattr(self._local, "state", None)
        if state is None:
            state = {"arrived": False}
            self._local.state = state
        return state

    def meet(self) -> bool:
        """本腿到达会合点并等同伙腿。False = 需求已不可满足（有腿终结/缺席）。"""
        arrived = self._arrive(self._current)
        parties = self._parties
        self._first.set()
        try:
            self._barrier.wait()
        except threading.BrokenBarrierError:
            return False
        if arrived >= parties:
            self._settled.set()
        return True

    def settle(self) -> bool:
        """主线程在**排空之前**的落点：会合成立或已判否即返回（不靠墙钟）。"""
        self._settled.wait()
        return self.arrived >= self._parties

    def wait_first_arrival(self) -> bool:
        """主线程等第一条腿到达。False = 会合已破（无人会再到达）。"""
        self._first.wait()
        return self.arrived >= 1

    @property
    def arrived(self) -> int:
        """已到达会合点的腿数（用例断言用）。"""
        with self._lock:
            return self._arrived



@pytest.fixture(scope="session", autouse=True)
def _offline_audience_translation_provider():
    """测试 worker 全生命周期隔离 audience provider。

    后台转译可能晚于单个 test teardown 才进入 provider；因此此桩必须覆盖整个
    pytest worker，而不是随 function-scoped monkeypatch 提前撤销。需特定结果的
    用例仍可在本边界上临时覆盖，撤销后回到离线实现。
    """
    import ming_sim.audience_translate as audience_translate

    mp = pytest.MonkeyPatch()
    build_prompt = audience_translate.build_audience_translate_prompt

    def capture_reply(*, reply, **kwargs):
        _offline_audience_reply.set(reply)
        return build_prompt(reply=reply, **kwargs)

    mp.setattr(audience_translate, "build_audience_translate_prompt", capture_reply)
    mp.setattr(
        audience_translate, "_default_translate_runner", offline_empty_audience_translate,
    )
    yield
    mp.undo()


def stub_scene_agent(monkeypatch, agent):
    """#1842：经 create_scene_agent 工厂缝注入 scene agent（禁实例双桩属性）。

    Stream calls emit RunContent events; non-stream calls return the agent output directly.
    """
    class _RunContent:
        event = "RunContent"

        def __init__(self, content: str):
            self.content = content

    class _RunCompleted:
        content = ""
        tools: list = []

    class _SceneAgentAdapter:
        def __init__(self, inner):
            self._inner = inner
            self.name = getattr(inner, "name", "scene")

        def run(self, *a, **k):
            out = self._inner.run(*a, **k) if hasattr(self._inner, "run") else self._inner
            if not k.get("stream"):
                return out
            if hasattr(out, "__iter__") and not hasattr(out, "content"):
                return out

            def events():
                text = str(getattr(out, "content", "") or "")
                if text:
                    yield _RunContent(text)
                done = _RunCompleted()
                done.content = text
                done.tools = list(getattr(out, "tools", None) or [])
                yield done

            return events()

    adapted = _SceneAgentAdapter(agent)
    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent",
        lambda *a, **k: adapted,
    )
    return adapted


def stub_audience_translate(monkeypatch, fn=None):
    """#1842：经 `_default_translate_runner` 缝注入转译（禁实例 `_audience_translate_fn`）。"""
    runner = offline_empty_audience_translate if fn is None else fn
    monkeypatch.setattr(
        "ming_sim.audience_translate._default_translate_runner",
        runner,
    )
    return runner


def persist_and_schedule_scene(sess, db, result, *, speaker: str = "殿上"):
    """#1842 单权威：镜像 Web/CLI——回话落定后再 schedule（ADR 0155 / 0036）。

    测试侧不得再复制本流程；生产入口仍走 Web/CLI 各自 persist 尾。
    """
    pending = getattr(result, "pending_audience_translation", None)
    if not pending:
        return None
    ctid = int(pending.get("chat_turn_id") or 0)
    if ctid <= 0:
        return None
    answer = str(getattr(result, "answer", "") or "")
    db.persist_minister_reply(
        speaker, int(sess.state.turn), answer, ctid,
    )
    return sess.schedule_pending_scene_translation(result)


@pytest.fixture
def _offline_scene_beat_generator():
    """兼容旧请求名：仅保留离线转译 stub。"""
    import ming_sim.audience_translate as at
    mp = pytest.MonkeyPatch()
    mp.setattr(at, "_default_translate_runner", offline_empty_audience_translate)
    yield
    mp.undo()


@pytest.fixture
def _atomic_connless_test_shell_compat():
    """#542：无 conn 轻壳测试显式 opt-in 的 atomic 兼容（非 autouse）。

    生产 chat/retry/stream 落回话无条件 `with atomic(self.db)`；真实 DB 测试默认
    走生产 atomic。仅轻壳（故意无 conn，以保持 stub 缝）请求本 fixture：
    missing conn → no-op CM；真 _SuspendableConnection 仍走真实 atomic。
    """
    import contextlib

    import ming_sim.applier as applier
    import web_app

    real_atomic = applier.atomic

    @contextlib.contextmanager
    def atomic_for_tests(db):
        if getattr(db, "conn", None) is None:
            yield
            return
        with real_atomic(db):
            yield

    mp = pytest.MonkeyPatch()
    mp.setattr(applier, "atomic", atomic_for_tests)
    mp.setattr(web_app, "atomic", atomic_for_tests)
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


def covering_monthly_extract(_agents, db, state, _narrative=None, *args, **kwargs):
    """Settlement extractor stub that satisfies 0058 complete-coverage for active secret orders."""
    extracted = with_monthly_reports(db, {})
    return extracted, "out", "in"


def monthly_progress_reports(db):
    return [
        {
            "dossier_id": item["dossier_id"],
            "progress_band": "在办",
            "memorial_text": "本月密奏已达",
        }
        for item in db.list_monthly_dossier_progress_nudges()
    ]


def with_monthly_reports(db, extracted=None):
    out = dict(extracted or {})
    if "dossier_progress_reports" in out:
        return out
    reports = monthly_progress_reports(db)
    if reports:
        out["dossier_progress_reports"] = reports
    return out
