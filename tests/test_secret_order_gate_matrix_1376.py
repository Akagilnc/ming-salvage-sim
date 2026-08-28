"""#1376 密令确认闸验证矩阵：3 入口 × 3 语义 = 9 格。

接缝（票面钉）：
- E1=`POST /api/ministers/毕自严/chat` 正文「密令如下：…」
- E2=`POST /api/ministers/毕自严/secret_order` 结构化载荷
- E3=`POST .../chat` 无前缀 + 分类器 stub 结构化密令判词
- S1 过月默认准 / S2 修改后准或过月 / S3 拒绝后过月不复活
- settle=`POST /api/decree/issue/stream` 消费到终态
- LLM 全 stub；确认/抽取/分类器只消费用例显式灌入的 typed 结果
- 行定位：调用前后 order-id 集差、pending id、候选 payload→落地 payload 动态传递

零写：复用 conftest 的 user-data 隔离，并将每例 HOME/DB 定向到 tmp_path。
V3 回归只在 tests/test_qa_c3_secret_order_path_1357_1376.py，本文件不包装重跑。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest
from fastapi.testclient import TestClient

import ming_sim.agents as agents_mod
import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an
from tests.test_session_write_queue_1353 import wait_pending_writes as _wait_pending_writes

# ── 矩阵常量 ───────────────────────────────────────────────────────────

# 票面 E1/E2/E3 指定王之臣；临时 DB 前置合法置于 beizhili/可召（ADR 0096），不改生产 gate。
MINISTER = "王之臣"
E1_MESSAGE = "密令如下：密察关宁欠饷"
E2_TITLE = "密察关宁欠饷"
E2_CONTENT = "密察关宁欠饷"
E3_MESSAGE = "你替朕悄悄查一查关宁欠饷实数"

# 抽取 stub 默认 typed 载荷（用例可覆盖）；S2 修改 material=测试自送正文
RESTATED_CONTENT = "密察关宁欠饷，据实密奏，不得声张。"
# 玩家修改输入是确定性材料（非 LLM 生成物）；S2 新正文唯取 typed new_content
S2_MODIFY_BODY = "  " + ("只查饷银去向" * 90) + "  "
# 自然语言修改表达（不含结构化「修改：」前缀），保证旧 prefix parser 无法直接产出
# S2_MODIFY_BODY——proof-of-red：生产须从 typed new_content 消费而非裁剪散文。
S2_MODIFY_MESSAGE = "朕要修改密令正文为只查饷银去向，不查动向"
S2_APPROVE_MESSAGE = "准"
# S3 三格分别使用的真实拒绝表达（stub 仅灌「拒绝」判词，不扫/不断言措辞）。
S3_REJECT_MESSAGES = {
    "E1S3": "此事作罢",
    "E2S3": "朕再思之，不必查了",
    "E3S3": "算了",
}

DEFAULT_EXTRACT_PAYLOAD: Dict[str, Any] = {
    "title": E2_TITLE,
    "content": RESTATED_CONTENT,
    "assignee": MINISTER,
    "tags": ["关宁", "欠饷"],
    "deadline_months": 3,
    "excluded_names": [],
    "excluded_offices": [],
    "dossier_links": [],
}


# ── LLM / 结算边界 stub ────────────────────────────────────────────────


class _CannedRun:
    content = "臣领密旨，请陛下定夺准驳。"
    tools: list = []


class _CannedAgent:
    def run(self, *_a, **_k):
        return _CannedRun()

    def get_last_run_output(self):
        return None


class _CannedExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"facts":[]}')


class _CannedEndorsementExtractor:
    def run(self, _material):
        return SimpleNamespace(content='{"endorsements":[]}')


class _CannedMindreading:
    def run(self, _material):
        return SimpleNamespace(content="近臣低声：边饷事重。")


class _CannedRelationJudge:
    def run(self, _prompt):
        return SimpleNamespace(content='{"events":[]}')


def _install_settlement_llm_stubs(monkeypatch) -> None:
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    monkeypatch.setattr(
        agents_mod, "create_audience_extractor_agent",
        lambda *a, **k: _CannedExtractor(),
    )
    monkeypatch.setattr(
        agents_mod, "create_endorsement_extractor_agent",
        lambda *a, **k: _CannedEndorsementExtractor(),
    )
    monkeypatch.setattr(
        mindreading_mod, "create_mindreading_agent",
        lambda *a, **k: _CannedMindreading(),
    )
    monkeypatch.setattr(
        agents_mod, "create_relation_judge_agent",
        lambda *a, **k: _CannedRelationJudge(),
    )
    monkeypatch.setattr(web_app, "run_highlight_judge", lambda **_k: [])
    monkeypatch.setattr(
        cli_backend,
        "capture_manual_directive_payload",
        lambda text, llm_config=None, **_k: {
            "dossier_action_type": "policy",
            "target_kind": "issue",
            "target_id": "secret-order-gate-1376",
            "mode": "ordinary",
        },
    )
    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod,
        "llm_promulgation_verdicts",
        lambda dossiers, _state, **_kwargs: [
            {"dossier_id": row["id"], "decision": "promulgated"} for row in dossiers
        ],
    )
    monkeypatch.setattr(
        decree_mod,
        "simulate_season_with_payload",
        lambda *a, **k: (
            "本月邸报：边饷静。",
            k.get("simulator_payload") or {},
        ),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "create_score_extractor_module_agent", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        decree_mod,
        "extract_scores_by_modules_with_agno",
        lambda *a, **k: ({}, "out", "in"),
    )
    monkeypatch.setattr(
        session_mod, "write_decree_with_agno",
        lambda *a, **k: "奉天承运，诏曰：着户部清核辽饷。",
    )
    monkeypatch.setattr(
        memories_mod,
        "run_agent_text",
        lambda *a, **k: '{"body": "本月边饷静。", "tags": ["边饷"]}',
    )


class _ConfirmStub:
    """确认判词 stub：只弹用例显式 push 的 typed 枚举，不读玩家散文。

    #1376：修改判词携带 typed new_content 作为唯一权威正文。push 接收
    (confirmation, new_content="")；new_content 仅修改判词时填写。
    """

    def __init__(self) -> None:
        self.queue: List[tuple] = []

    def push(self, confirmation: str, new_content: str = "") -> None:
        self.queue.append((confirmation, new_content))

    def __call__(
        self,
        player_message: str,
        minister_reply: str,
        pending_summaries: List[str],
        llm_config: Any = None,
    ) -> Dict[str, Any]:
        del player_message, minister_reply, pending_summaries, llm_config
        if self.queue:
            confirmation, new_content = self.queue.pop(0)
        else:
            confirmation, new_content = "无", ""
        return {"confirmation": confirmation, "target_ids": [], "new_content": new_content}


class _ExtractStub:
    """密令抽取 stub：返回用例配置的 typed 载荷，不扫 player_command 关键词。"""

    def __init__(self) -> None:
        self.payload: Dict[str, Any] = dict(DEFAULT_EXTRACT_PAYLOAD)

    def __call__(
        self,
        player_command: str,
        minister_reply: str,
        default_assignee: str,
        llm_config: Any = None,
        force_default_assignee: bool = False,
        dossier_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        del player_command, minister_reply, llm_config, force_default_assignee, dossier_candidates
        out = dict(self.payload)
        if default_assignee and not out.get("assignee"):
            out["assignee"] = default_assignee
        return out


class _ClassifierStub:
    """分类器 stub：mode 驱动 typed 返回；不解析消息语义。

    #1376 E1/E2 专项契约：mode=fail_if_called → 被调用即失败，证明
    E1/E2 经结构性前缀/端点路由达 stage，未经 classifier。
    """

    def __init__(self) -> None:
        self.mode: str = "fail_if_called"  # fail_if_called | secret_new

    def __call__(self, player_message: str, *args, **kwargs) -> List[Dict[str, Any]]:
        del player_message, args, kwargs
        if self.mode == "secret_new":
            return [{"kind": "secret", "secret_action": "新建"}]
        # fail_if_called：任何调用皆为契约违反
        raise AssertionError(
            "classifier must not be called for E1/E2 (fail-if-called)"
        )


# ── 公共 fixture ───────────────────────────────────────────────────────


def _item_sig(path: Path) -> Tuple[str, int, int]:
    """单路径轻量态：存在性 + mtime_ns + size；不读内容、不递归。"""
    if not path.exists():
        return ("missing", 0, 0)
    st = path.stat()
    kind = "file" if path.is_file() else "dir"
    return (kind, int(st.st_mtime_ns), int(st.st_size))


def _snapshot_write_surface(real_home: Path) -> dict:
    """真实入口可达的直写文件/文件族与必要子根的轻量前后态。

    覆盖 data/active_db.txt、data/ming_sim_*.db（仅 data 根 glob）、
    runtime_llm.json，以及 saves/error_packs/~/.ming_sim 的直接子项。
    不递归 hash。
    """
    repo = Path(__file__).resolve().parent.parent
    data = repo / "data"
    snap: dict = {}
    for p in (data / "active_db.txt", data / "runtime_llm.json"):
        snap[str(p)] = _item_sig(p)
    family: dict = {}
    if data.is_dir():
        for p in sorted(data.glob("ming_sim_*.db")):
            if p.is_file():
                family[p.name] = _item_sig(p)
    snap["data:ming_sim_*.db"] = family
    for root in (data / "saves", data / "error_packs", real_home / ".ming_sim"):
        kids: dict = {}
        if root.is_dir():
            for child in sorted(root.iterdir(), key=lambda x: x.name):
                kids[child.name] = _item_sig(child)
        snap[str(root)] = {"root": _item_sig(root), "children": kids}
    return snap


@pytest.fixture
def matrix_env(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """临时 HOME + user_data/DB；CLI 通道；LLM 全 stub。"""
    real_home = Path(os.environ.get("HOME") or Path.home())
    before = _snapshot_write_surface(real_home)
    home = tmp_path / "home"
    home.mkdir()
    ud = tmp_path / "user_data"
    ud.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(ud))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.delenv("MING_SIM_DB", raising=False)

    _install_settlement_llm_stubs(monkeypatch)

    confirm = _ConfirmStub()
    classifier = _ClassifierStub()
    extract = _ExtractStub()

    monkeypatch.setattr(cli_backend, "extract_confirmation_intent", confirm)
    monkeypatch.setattr(cli_backend, "classify_cli_action_intent", classifier)
    monkeypatch.setattr(cli_backend, "_extract_secret_order", extract)

    monkeypatch.setattr(web_app, "web_game", None)
    client = TestClient(web_app.app)

    new = client.post("/api/menu/new_game")
    assert new.status_code == 200, new.text
    game = web_app.web_game
    assert game is not None

    game.session.registry.get = lambda _ch: _CannedAgent()
    cfg = game.session.llm_config
    if getattr(cfg, "channel", None) != "cli":
        try:
            object.__setattr__(cfg, "channel", "cli")
        except Exception:
            game.session.llm_config = SimpleNamespace(
                **{
                    **{k: getattr(cfg, k, None) for k in dir(cfg) if not k.startswith("_")},
                    "channel": "cli",
                    "cli_runner": "agy",
                }
            )

    ministers = (new.json() or {}).get("state", {}).get("ministers") or []
    names = {str(m.get("name") or "") for m in ministers if isinstance(m, dict)}
    game.db.conn.execute(
        "UPDATE characters SET location='beizhili', transit_to='', "
        "transit_distance_remaining=NULL WHERE name=?",
        (MINISTER,),
    )
    game.db.conn.commit()
    if MINISTER not in names:
        st = game.db.get_character_status(MINISTER)
        assert st and st[0] == "active", f"{MINISTER} 非 active: {st!r}"

    yield {
        "client": client,
        "game": game,
        "confirm": confirm,
        "classifier": classifier,
        "extract": extract,
        "home": home,
        "ud": ud,
    }

    g = web_app.web_game
    if g is not None:
        try:
            _wait_pending_writes(g)
            g.session.close()
        finally:
            web_app.web_game = None

    after = _snapshot_write_surface(real_home)
    assert after == before, f"仓外/真实 user-data 零写失败: {before=} {after=}"


# ── helpers ────────────────────────────────────────────────────────────


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for block in (text or "").strip().split("\n\n"):
        cur: dict = {}
        for line in block.splitlines():
            if line.startswith("event:"):
                cur["event"] = line[len("event:"):].strip()
            elif line.startswith("data:"):
                cur["data"] = line[len("data:"):].strip()
        if cur:
            events.append(cur)
    return events


def _list_orders(client: TestClient) -> list[dict]:
    resp = client.get("/api/secret_orders")
    assert resp.status_code == 200, resp.text
    body = resp.json() or {}
    return list(body.get("orders") or [])


def _order_ids(client: TestClient) -> Set[int]:
    return {int(o["id"]) for o in _list_orders(client)}


def _orders_by_ids(client: TestClient, ids: Set[int]) -> list[dict]:
    return [o for o in _list_orders(client) if int(o["id"]) in ids]


def _db_order_ids(game) -> Set[int]:
    return {int(o["id"]) for o in game.db.list_secret_orders()}


def _db_pending_secret_new(game) -> list[dict]:
    rows = game.db.list_pending_actions(game.state.turn, minister_name=MINISTER)
    return [
        r for r in rows
        if r.get("kind") == "secret_order"
        and str(r.get("action") or "") == "新建"
        and str(r.get("status") or "") == "pending"
    ]


def _payload_of(row: dict) -> dict:
    try:
        p = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError):
        p = {}
    return p if isinstance(p, dict) else {}


def _issue_entry(env: dict, *, entry: str = "E1") -> dict:
    client: TestClient = env["client"]
    game = env["game"]
    classifier: _ClassifierStub = env["classifier"]

    if entry == "E1":
        # E1：显式前缀路由，classifier 不得被调用
        classifier.mode = "fail_if_called"
        resp = client.post(
            f"/api/ministers/{MINISTER}/chat",
            json={"message": E1_MESSAGE},
        )
    elif entry == "E2":
        # E2：结构化端点路由，classifier 不得被调用
        classifier.mode = "fail_if_called"
        resp = client.post(
            f"/api/ministers/{MINISTER}/secret_order",
            json={
                "title": E2_TITLE,
                "content": E2_CONTENT,
                "tags": ["关宁", "欠饷"],
                "deadline_months": 3,
            },
        )
    elif entry == "E3":
        # E3：无前缀 + classifier stub 返回 secret_new 判词
        classifier.mode = "secret_new"
        resp = client.post(
            f"/api/ministers/{MINISTER}/chat",
            json={"message": E3_MESSAGE},
        )
    else:
        raise AssertionError(f"unknown entry {entry}")

    assert resp.status_code == 200, f"{entry} inject → {resp.status_code}: {resp.text}"
    _wait_pending_writes(game)
    game.session.registry.get = lambda _ch: _CannedAgent()
    return resp.json() or {}


def _chat(env: dict, message: str) -> dict:
    client: TestClient = env["client"]
    game = env["game"]
    game.session.registry.get = lambda _ch: _CannedAgent()
    resp = client.post(
        f"/api/ministers/{MINISTER}/chat",
        json={"message": message},
    )
    assert resp.status_code == 200, f"chat {message!r} → {resp.status_code}: {resp.text}"
    _wait_pending_writes(game)
    return resp.json() or {}


def _settle_month(env: dict) -> dict:
    client: TestClient = env["client"]
    game = env["game"]
    _wait_pending_writes(game)

    turn = int(game.state.turn)
    d = client.post(
        "/api/directives",
        json={"text": "着户部清核辽饷（#1376 矩阵过月）。", "notes": ""},
    )
    assert d.status_code == 200, d.text
    _wait_pending_writes(game)

    resp = client.post(
        "/api/decree/issue/stream",
        json={"expected_turn": turn},
    )
    assert resp.status_code == 200, f"issue/stream → {resp.status_code}: {resp.text}"
    events = _parse_sse(resp.text)
    assert events, f"empty SSE: {resp.text!r}"
    terminal = events[-1]
    ev = terminal.get("event")
    raw = terminal.get("data") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = {"message": raw}
    if ev == "error":
        raise AssertionError(f"issue/stream error: {data!r}; sse={resp.text!r}")
    if ev == "decisions":
        decisions = (data or {}).get("decisions") or []
        assert decisions, data
        choices = []
        for dec in decisions:
            opts = dec.get("options") or []
            assert opts, dec
            opt0 = opts[0]
            # #1589：公共 resolve 缝不再接受无键位置载荷，须显式携带 decision_key
            key = str(dec.get("decision_key") or "")
            assert key, f"decision 行缺 decision_key：{dec}"
            if isinstance(opt0, dict):
                label = str(opt0.get("label") or "准")
            else:
                label = str(opt0) or "准"
            choices.append({"decision_key": key, "label": label})
        resolve = client.post(
            "/api/decree/resolve_decisions/stream",
            json={"choices": choices},
        )
        assert resolve.status_code == 200, resolve.text
        assert "event: error" not in resolve.text, resolve.text
        assert "event: done" in resolve.text, resolve.text
    elif ev != "done":
        raise AssertionError(f"unexpected terminal {ev!r}: {resp.text!r}")

    _wait_pending_writes(game)
    open_n = an.get_open_night(game.db)
    assert open_n is None or str(open_n.get("status")) == an.NIGHT_STATUS_CLOSED, open_n
    game.session.registry.get = lambda _ch: _CannedAgent()
    return data if isinstance(data, dict) else {}


# ── 9 格 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cell,entry",
    [
        ("E1S1", "E1"),
        ("E2S1", "E2"),
        ("E3S1", "E3"),
    ],
    ids=["E1S1", "E2S1", "E3S1"],
)
def test_matrix_S1_default_commit_on_settle(matrix_env, cell, entry):
    """S1：下令→列表无新 id→不确认→过月→唯一新 id，content=候选 payload 动态传递。"""
    env = matrix_env
    client = env["client"]
    game = env["game"]
    extract: _ExtractStub = env["extract"]

    ids_before = _order_ids(client)
    db_ids_before = _db_order_ids(game)

    inject = _issue_entry(env, entry=entry)
    assert int(inject.get("secret_order_id") or 0) == 0, f"{cell} 首包应 id=0: {inject!r}"

    pending = _db_pending_secret_new(game)
    assert len(pending) >= 1, f"{cell} stage 后须有 secret_order/新建 候选: {pending!r}"
    cand = pending[0]
    cand_id = int(cand["id"])
    staged_payload = _payload_of(cand)
    staged_content = str(staged_payload.get("content") or "")
    # 候选 content = 用例灌入的抽取 typed 字段（外部 pending 可见）
    assert staged_content == str(extract.payload.get("content") or ""), (
        f"{cell} 候选 content 须等于抽取 stub typed 载荷: "
        f"staged={staged_content!r} stub={extract.payload!r}"
    )

    assert _order_ids(client) == ids_before, (
        f"{cell} settle 前不得新增可见密令 id: before={ids_before!r} "
        f"now={_order_ids(client)!r}"
    )

    _settle_month(env)

    new_ids = _order_ids(client) - ids_before
    assert len(new_ids) == 1, f"{cell} settle 后须唯一新 id: {new_ids!r}"
    row = _orders_by_ids(client, new_ids)[0]
    assert int(row["id"]) > 0
    landed = str(row.get("content") or "")
    assert landed == staged_content, (
        f"{cell} 落地 content 须=候选 payload 动态传递: "
        f"landed={landed!r} staged={staged_content!r}"
    )
    assert all(int(p["id"]) != cand_id for p in _db_pending_secret_new(game)), (
        f"{cell} 候选 {cand_id} 须已消费"
    )
    assert _db_order_ids(game) - db_ids_before == new_ids


@pytest.mark.parametrize(
    "cell,entry,via_approve",
    [
        ("E1S2", "E1", True),
        ("E2S2", "E2", False),  # 修改→不准→过月
        ("E3S2", "E3", True),
    ],
    ids=["E1S2", "E2S2", "E3S2"],
)
def test_matrix_S2_modify_then_land(matrix_env, cell, entry, via_approve):
    """S2：下令→确认判词=修改+new_content→准或过月；候选 id 不变；落地=typed new_content。"""
    env = matrix_env
    client = env["client"]
    game = env["game"]
    confirm: _ConfirmStub = env["confirm"]
    classifier: _ClassifierStub = env["classifier"]

    ids_before = _order_ids(client)

    _issue_entry(env, entry=entry)
    pending_before = _db_pending_secret_new(game)
    assert len(pending_before) == 1, f"{cell} 须恰一候选: {pending_before!r}"
    cand_id = int(pending_before[0]["id"])
    staged_content = str(_payload_of(pending_before[0]).get("content") or "")
    assert _order_ids(client) == ids_before

    # 修改轮：确认判词 stub=修改 + typed new_content（不读玩家散文）
    # S2_MODIFY_MESSAGE 不含结构化「修改：」前缀→旧 prefix parser 无法直接产出 S2_MODIFY_BODY，
    # 证明生产须从 typed new_content 消费而非裁剪玩家散文。
    confirm.push("修改", new_content=S2_MODIFY_BODY)
    classifier.mode = "none"
    _chat(env, S2_MODIFY_MESSAGE)

    pending_mid = _db_pending_secret_new(game)
    assert len(pending_mid) == 1, (
        f"{cell} 修改后须仍唯一候选（非新建并行）: {pending_mid!r}"
    )
    assert int(pending_mid[0]["id"]) == cand_id, (
        f"{cell} 修改后候选 id 须不变: before={cand_id} after={pending_mid[0]['id']}"
    )
    mid_payload = _payload_of(pending_mid[0])
    mid_content = str(mid_payload.get("content") or "")
    # 外部可见：候选 content = typed new_content（唯一权威正文）
    assert mid_content == S2_MODIFY_BODY, (
        f"{cell} 修改后候选 content 须=typed new_content: "
        f"got={mid_content!r} want={S2_MODIFY_BODY!r} staged={staged_content!r}"
    )

    if via_approve:
        confirm.push("应允")
        out = _chat(env, S2_APPROVE_MESSAGE)
        oid = int(out.get("secret_order_id") or 0)
        assert oid > 0, f"{cell} 准后 secret_order_id 须>0: {out!r}"
    else:
        _settle_month(env)

    new_ids = _order_ids(client) - ids_before
    assert len(new_ids) == 1, f"{cell} 落地后须唯一新 id: {new_ids!r}"
    landed = str(_orders_by_ids(client, new_ids)[0].get("content") or "")
    assert landed == S2_MODIFY_BODY, (
        f"{cell} 真表 content 须=typed new_content: "
        f"landed={landed!r} want={S2_MODIFY_BODY!r}"
    )


@pytest.mark.parametrize(
    "cell,entry",
    [
        ("E1S3", "E1"),
        ("E2S3", "E2"),
        ("E3S3", "E3"),
    ],
    ids=["E1S3", "E2S3", "E3S3"],
)
def test_matrix_S3_reject_then_settle_no_resurrection(matrix_env, cell, entry):
    """S3：下令→确认判词=拒绝→过月；无新 order id；候选取消；过月不复活。"""
    env = matrix_env
    client = env["client"]
    game = env["game"]
    confirm: _ConfirmStub = env["confirm"]

    ids_before = _order_ids(client)
    db_ids_before = _db_order_ids(game)

    _issue_entry(env, entry=entry)
    assert len(_db_pending_secret_new(game)) >= 1
    assert _order_ids(client) == ids_before

    # S3 三格分别使用不同的真实拒绝表达；stub 仅灌「拒绝」判词，不扫/不断言措辞
    s3_reject_msg = S3_REJECT_MESSAGES[cell]
    confirm.push("拒绝")
    classifier_mode = env["classifier"]
    classifier_mode.mode = "none"  # 确认轮 classifier 可跑但不得影响判词
    _chat(env, s3_reject_msg)

    assert _db_pending_secret_new(game) == [], (
        f"{cell} 拒绝后 pending 新建候选须清除: {_db_pending_secret_new(game)!r}"
    )
    assert _order_ids(client) == ids_before

    _settle_month(env)
    assert _order_ids(client) - ids_before == set(), (
        f"{cell} 过月后不得新增密令 id: {_order_ids(client) - ids_before!r}"
    )
    assert _db_order_ids(game) - db_ids_before == set(), (
        f"{cell} DB 真表不得新增密令 id: {_db_order_ids(game) - db_ids_before!r}"
    )
