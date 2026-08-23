"""#1376 密令确认闸验证矩阵（v4.3）：3 入口 × 3 语义 = 9 格 + V3 回归。

接缝（票面钉）：
- E1=`POST /api/ministers/王之臣/chat` 正文「密令如下：密察关宁欠饷」
- E2=`POST /api/ministers/王之臣/secret_order` 结构化载荷
- E3=`POST .../chat` 无前缀 + 分类器 stub 结构化密令判词
- S1 过月默认准 / S2 修改后准或过月 / S3 拒绝后过月不复活
- settle=`POST /api/decree/issue/stream` 消费到终态
- LLM 全 stub 于 registry/agent/分类器/确认/抽取/结算边界；断言判词→状态转移

零写：所有可写目标在首个 HTTP 写入前机械钉入每例临时根。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

import ming_sim.agents as agents_mod
import ming_sim.cli_backend as cli_backend
import ming_sim.decree as decree_mod
import ming_sim.memories as memories_mod
import ming_sim.llm_config as llm_config_mod
import ming_sim.paths as paths_mod
import ming_sim.mindreading as mindreading_mod
import ming_sim.session as session_mod
import web_app
from ming_sim import audience_night as an

# ── 矩阵常量（票面原轨）────────────────────────────────────────────────

MINISTER = "王之臣"
E1_MESSAGE = "密令如下：密察关宁欠饷"
E2_TITLE = "密察关宁欠饷"
E2_CONTENT = "密察关宁欠饷"
E3_MESSAGE = "你替朕悄悄查一查关宁欠饷实数"

# stub 结构化 content：复述版 / 修改版（不断言散文匹配，只钉判词→落库映射）
RESTATED_CONTENT = "密察关宁欠饷，据实密奏，不得声张。"
# 修改正文=去「修改：」前缀后的御旨材料（P5：不二次抽取；与 production strip 同口径）
MODIFIED_CONTENT = "只查饷银去向，不查动向"
MODIFIED_TITLE = "只查饷银去向"

S2_MODIFY_MESSAGE = "修改：只查饷银去向，不查动向"
S2_APPROVE_MESSAGE = "准"
S3_REJECT = {
    "E1S3": "此事作罢",
    "E2S3": "朕再思之，不必查了",
    "E3S3": "算了",
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


def _install_settlement_llm_stubs(monkeypatch) -> None:
    """过月 SSE 外层 LLM 边界 canned（与 #1468 tracer 同形，结算核真跑）。"""
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


def _secret_payload_from_command(
    player_command: str, default_assignee: str,
) -> Dict[str, Any]:
    """结构化密令 stub：按命令材料在复述版/修改版间切换（不扫自由散文语义）。"""
    cmd = player_command or ""
    if "只查饷银" in cmd or "不查动向" in cmd:
        title, content = MODIFIED_TITLE, MODIFIED_CONTENT
    else:
        title, content = E2_TITLE, RESTATED_CONTENT
    return {
        "title": title,
        "content": content,
        "assignee": default_assignee or MINISTER,
        "tags": ["关宁", "欠饷"],
        "deadline_months": 3,
        "excluded_names": [],
        "excluded_offices": [],
        "dossier_links": [],
    }


class _ConfirmStub:
    """确认判词 stub：按格灌入队列；断言判词→状态转移，不断言散文匹配。"""

    def __init__(self) -> None:
        self.queue: List[str] = []
        self.calls: List[str] = []
        self.results: List[str] = []

    def push(self, *values: str) -> None:
        self.queue.extend(values)

    def __call__(
        self,
        player_message: str,
        minister_reply: str,
        pending_summaries: List[str],
        llm_config: Any = None,
    ) -> str:
        del minister_reply, pending_summaries, llm_config
        text = (player_message or "").strip()
        self.calls.append(text)
        # 测试边界模拟结构化 LLM 枚举：短应允句 / 队列灌入的修改·拒绝
        compact = re.sub(r"[\s，,。.!！?？；;：:、]+", "", text)
        if compact in {"准", "可", "允", "好", "行", "善"} or compact in {
            "准奏", "照准", "准了", "照办",
        }:
            result = "应允"
        elif self.queue:
            result = self.queue.pop(0)
        else:
            result = "无"
        self.results.append(result)
        return result


class _ClassifierStub:
    """分类器 stub：E3 入口返回结构化密令判词；其它默认 []。记录真实调用契约。"""

    def __init__(self) -> None:
        self.mode: str = "none"  # none | secret_new | secret_modify
        self.calls: List[str] = []
        self.results: List[List[Dict[str, Any]]] = []

    def __call__(self, player_message: str, *args, **kwargs) -> List[Dict[str, Any]]:
        del args, kwargs
        text = (player_message or "").strip()
        self.calls.append(text)
        if self.mode == "secret_new":
            result: List[Dict[str, Any]] = [{"kind": "secret", "secret_action": "新建"}]
        elif self.mode == "secret_modify":
            result = [{
                "kind": "secret",
                "secret_action": "新建",
                "new_title": MODIFIED_TITLE,
                "new_content": MODIFIED_CONTENT,
            }]
        else:
            result = []
        self.results.append(result)
        return result


# ── 公共 fixture：临时 HOME/DB + TestClient ─────────────────────────────


def _assert_write_targets_within(root: Path, targets: list[Path]) -> None:
    """机械边界：本矩阵已知的每个可写目标必须落在本例临时根内。"""
    resolved_root = root.resolve()
    escaped = []
    for target in targets:
        resolved = target.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            escaped.append(str(resolved))
    assert not escaped, f"写目标越出临时根 {resolved_root}: {escaped!r}"


def test_write_boundary_rejects_target_outside_case_root(tmp_path):
    """负例不写盘：伪造根外目标时，零写边界必须响亮失败。"""
    with pytest.raises(AssertionError, match="写目标越出临时根"):
        _assert_write_targets_within(tmp_path / "case", [tmp_path / "outside.db"])


@pytest.fixture
def matrix_env(tmp_path, monkeypatch, _offline_scene_beat_generator):
    """临时 HOME + user_data/DB；CLI 通道以便 E3 分类器路径可达；LLM 全 stub。"""
    home = tmp_path / "home"
    home.mkdir()
    # conftest 已建 tmp_path/user_data；复用
    ud = tmp_path / "user_data"
    ud.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MING_SIM_USER_DATA_DIR", str(ud))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # CLI 通道：E3 无前缀分类器路径；E1/E2 前缀仍确定性路由
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.delenv("MING_SIM_DB", raising=False)

    # 首个 HTTP 写入前先钉所有路径解析 seam；越界目标在触盘前即失败。
    _assert_write_targets_within(
        tmp_path,
        [
            Path.home(),
            paths_mod.user_data_dir(),
            Path(web_app.UPLOAD_PORTRAIT_DIR),
            Path(llm_config_mod.RUNTIME_LLM_PATH),
            Path(web_app._active_db_path_file()),
            Path(web_app._get_main_db_path()),
            ud / "ming_sim_generated.db",
        ],
    )

    _install_settlement_llm_stubs(monkeypatch)

    confirm = _ConfirmStub()
    classifier = _ClassifierStub()

    def _fake_extract(
        player_command: str,
        minister_reply: str,
        default_assignee: str,
        llm_config: Any = None,
        force_default_assignee: bool = False,
        dossier_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        del minister_reply, llm_config, force_default_assignee, dossier_candidates
        return _secret_payload_from_command(player_command, default_assignee)

    monkeypatch.setattr(cli_backend, "extract_confirmation_intent", confirm)
    monkeypatch.setattr(cli_backend, "classify_cli_action_intent", classifier)
    monkeypatch.setattr(cli_backend, "_extract_secret_order", _fake_extract)
    # resolve_minister_actions 内调 _extract_secret_order——已 patch 模块属性即可

    monkeypatch.setattr(web_app, "web_game", None)
    client = TestClient(web_app.app)

    new = client.post("/api/menu/new_game")
    assert new.status_code == 200, new.text
    game = web_app.web_game
    assert game is not None
    _assert_write_targets_within(
        tmp_path,
        [
            Path(web_app._active_db_path_file()),
            Path(web_app._get_main_db_path()),
            Path(game.db.path),
        ],
    )
    # 大臣回话 agent 边界
    game.session.registry.get = lambda _ch: _CannedAgent()
    # 强制 CLI 通道（runtime 可能被 load 覆盖）
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

    # 王之臣必须可召
    ministers = (new.json() or {}).get("state", {}).get("ministers") or []
    names = {str(m.get("name") or "") for m in ministers if isinstance(m, dict)}
    if MINISTER not in names:
        # 名册投影可能截断；以 DB/content 为准校验 active
        st = game.db.get_character_status(MINISTER)
        assert st and st[0] == "active", f"{MINISTER} 非 active: {st!r}"

    yield {
        "client": client,
        "game": game,
        "confirm": confirm,
        "classifier": classifier,
        "home": home,
        "ud": ud,
    }

    # teardown
    g = web_app.web_game
    if g is not None:
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            pending = int(getattr(g, "_pending_writes_count", 0) or 0)
            if pending <= 0:
                break
            time.sleep(0.01)
        try:
            g.session.close()
        except Exception:
            pass
        web_app.web_game = None


# ── helpers ────────────────────────────────────────────────────────────


def _wait_pending_writes(game, *, timeout_s: float = 3.0) -> None:
    deadline = time.perf_counter() + float(timeout_s)
    while time.perf_counter() < deadline:
        pending = int(getattr(game, "_pending_writes_count", 0) or 0)
        if pending <= 0:
            gate = getattr(game, "_write_gate", None)
            if gate is None:
                return
            if gate.acquire(blocking=False):
                gate.release()
                return
        time.sleep(0.01)
    raise AssertionError(
        f"pending writes did not drain in {timeout_s}s; "
        f"count={getattr(game, '_pending_writes_count', None)}"
    )


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


def _turn_of_game(game) -> int:
    return int(game.state.turn)


def _list_orders(client: TestClient) -> list[dict]:
    resp = client.get("/api/secret_orders")
    assert resp.status_code == 200, resp.text
    body = resp.json() or {}
    return list(body.get("orders") or [])


def _orders_matching(orders: list[dict], *, needle: str) -> list[dict]:
    """按 title/content 子串找本矩阵令（避免与开局种子密令混淆）。"""
    out = []
    for o in orders:
        blob = f"{o.get('title') or ''}{o.get('content') or ''}"
        if needle in blob or "关宁" in blob or "饷" in blob and "只查" in blob:
            # 收窄：本矩阵 stub 标题/内容
            if (
                needle in blob
                or E2_TITLE in blob
                or MODIFIED_TITLE in blob
                or RESTATED_CONTENT in blob
                or MODIFIED_CONTENT in blob
                or "关宁欠饷" in blob
            ):
                out.append(o)
    # 去重逻辑简化：用 stub 指纹再滤
    filtered = []
    for o in out:
        blob = f"{o.get('title') or ''}{o.get('content') or ''}"
        if any(
            token in blob
            for token in (E2_TITLE, MODIFIED_TITLE, RESTATED_CONTENT, MODIFIED_CONTENT, "关宁欠饷", "欠饷实数")
        ):
            filtered.append(o)
    return filtered


def _db_pending_secret_new(game) -> list[dict]:
    rows = game.db.list_pending_actions(game.state.turn, minister_name=MINISTER)
    return [
        r for r in rows
        if r.get("kind") == "secret_order" and str(r.get("action") or "") == "新建"
        and str(r.get("status") or "") == "pending"
    ]


def _payload_of(row: dict) -> dict:
    try:
        p = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError):
        p = {}
    return p if isinstance(p, dict) else {}


def _issue_entry(env: dict, *, message: Optional[str] = None, entry: str = "E1") -> dict:
    """三入口之一注入密令；返回 chat/secret_order JSON。"""
    client: TestClient = env["client"]
    game = env["game"]
    classifier: _ClassifierStub = env["classifier"]

    if entry == "E1":
        classifier.mode = "none"  # 前缀确定性路由，不经分类器
        resp = client.post(
            f"/api/ministers/{MINISTER}/chat",
            json={"message": message or E1_MESSAGE},
        )
    elif entry == "E2":
        classifier.mode = "none"
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
        classifier.mode = "secret_new"
        resp = client.post(
            f"/api/ministers/{MINISTER}/chat",
            json={"message": message or E3_MESSAGE},
        )
    else:
        raise AssertionError(f"unknown entry {entry}")

    assert resp.status_code == 200, f"{entry} inject → {resp.status_code}: {resp.text}"
    _wait_pending_writes(game)
    # registry 可能在 begin_turn 后仍在；确保 canned
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
    """POST /api/decree/issue/stream 消费到终态（票面 S1/S2/S3 过月）。"""
    client: TestClient = env["client"]
    game = env["game"]
    _wait_pending_writes(game)

    # 无诏亦可过月：先试 advance_without_edict 同语义的 issue 空诏路径；
    # 票面钉 issue/stream——若需草案则补一条最小拟旨再颁。
    turn = _turn_of_game(game)
    # 最小拟旨，保证 issue 路径有可颁材料（不过度扩大 scope）
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
        # 亲裁最短续跑
        decisions = (data or {}).get("decisions") or []
        assert decisions, data
        choices = []
        for dec in decisions:
            opts = dec.get("options") or []
            assert opts, dec
            opt0 = opts[0]
            if isinstance(opt0, dict):
                choices.append({"label": str(opt0.get("label") or "准")})
            else:
                choices.append({"label": str(opt0)})
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
    # 夜应收
    open_n = an.get_open_night(game.db)
    assert open_n is None or str(open_n.get("status")) == an.NIGHT_STATUS_CLOSED, open_n
    game.session.registry.get = lambda _ch: _CannedAgent()
    return data if isinstance(data, dict) else {}


def _matrix_orders(client: TestClient) -> list[dict]:
    return _orders_matching(_list_orders(client), needle="关宁")


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
    """S1：下令→先观测列表不含→不确认→过月→唯一一行 id>0 content=复述版。"""
    env = matrix_env
    client = env["client"]
    game = env["game"]

    inject = _issue_entry(env, entry=entry)
    # 首包设计口径：secret_order_id=0（暂存态）
    assert int(inject.get("secret_order_id") or 0) == 0, f"{cell} 首包应 id=0: {inject!r}"

    classifier: _ClassifierStub = env["classifier"]
    # 结构性信号：E1/E2 不经分类器亦达 stage；E3 经分类器 stub
    pending = _db_pending_secret_new(game)
    assert len(pending) >= 1, f"{cell} stage 后须有 secret_order/新建 候选: {pending!r}"
    cand = pending[0]
    cand_id = int(cand["id"])
    payload = _payload_of(cand)
    assert str(payload.get("content") or "") == RESTATED_CONTENT, (
        f"{cell} 候选 content 须为完整复述版: {payload!r}"
    )

    if entry == "E3":
        # 真实分类器调用契约：注入文被记录，且返回含 kind=secret 的结构化判词
        assert classifier.calls, f"{cell} E3 须打到分类器 stub"
        assert any(
            E3_MESSAGE == c or E3_MESSAGE in c or "悄悄查" in c
            for c in classifier.calls
        ), f"{cell} E3 分类器须收到无前缀密令文: {classifier.calls!r}"
        assert classifier.results, f"{cell} E3 分类器须有返回记录"
        assert any(
            isinstance(item, dict) and item.get("kind") == "secret"
            for result in classifier.results
            for item in result
        ), f"{cell} E3 分类器返回须含 secret 判词: {classifier.results!r}"
    else:
        # E1/E2：前缀/端点确定性路由——mode=none 时 stub 返回 []，仍达 stage（上面 pending）
        assert classifier.mode == "none", f"{cell} 结构性入口 classifier.mode 须为 none"
        assert all(
            not any(
                isinstance(item, dict) and item.get("kind") == "secret"
                for item in result
            )
            for result in classifier.results
        ), (
            f"{cell} E1/E2 不得依赖分类器密令判词达 stage: "
            f"calls={classifier.calls!r} results={classifier.results!r}"
        )

    # 先观测 settle 前不可见（票面 v4.3 观测序）
    before = _matrix_orders(client)
    assert before == [], f"{cell} settle 前列表须不含此令: {before!r}"

    # 不确认 → 过月默认准
    _settle_month(env)

    after = _matrix_orders(client)
    assert len(after) == 1, f"{cell} settle 后须唯一一行: {after!r}"
    row = after[0]
    assert int(row["id"]) > 0
    content = str(row.get("content") or "")
    assert content == RESTATED_CONTENT, (
        f"{cell} content 须为完整复述版 {RESTATED_CONTENT!r}，得 {content!r}"
    )
    # 候选已消费
    assert _db_pending_secret_new(game) == [] or all(
        int(p["id"]) != cand_id for p in _db_pending_secret_new(game)
    )


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
    """S2：下令→修改（判词 stub=修改+新内容）→准或过月；候选 id 不变；真表 content=修改版。"""
    env = matrix_env
    client = env["client"]
    game = env["game"]
    confirm: _ConfirmStub = env["confirm"]
    classifier: _ClassifierStub = env["classifier"]

    _issue_entry(env, entry=entry)
    pending_before = _db_pending_secret_new(game)
    assert len(pending_before) == 1, f"{cell} 须恰一候选: {pending_before!r}"
    cand_id = int(pending_before[0]["id"])
    assert _matrix_orders(client) == []

    # 修改轮：确认判词 stub=修改；分类器/抽取给新内容
    confirm.push("修改")
    if entry == "E3":
        classifier.mode = "secret_modify"
    else:
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
    assert MODIFIED_CONTENT in mid_content or mid_content == MODIFIED_CONTENT, (
        f"{cell} 修改后候选 content 须=修改版: {mid_payload!r}"
    )
    # 确认判词→修改 映射被消费（results 记录结构化枚举，非散文自证）
    assert "修改" in confirm.results, (
        f"{cell} 修改轮须消费确认判词=修改: calls={confirm.calls!r} results={confirm.results!r}"
    )
    assert any(S2_MODIFY_MESSAGE == c or "只查饷银" in c for c in confirm.calls), confirm.calls

    if via_approve:
        out = _chat(env, S2_APPROVE_MESSAGE)
        oid = int(out.get("secret_order_id") or 0)
        assert oid > 0, f"{cell} 准后 secret_order_id 须>0: {out!r}"
    else:
        # E2S2：不准→过月默认准
        _settle_month(env)

    after = _matrix_orders(client)
    assert len(after) == 1, f"{cell} 落地后须唯一一行: {after!r}"
    content = str(after[0].get("content") or "")
    assert MODIFIED_CONTENT in content or content == MODIFIED_CONTENT, (
        f"{cell} 真表 content 须=修改版: {content!r}"
    )
    assert int(after[0]["id"]) > 0


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
    """S3：下令→拒绝判词 stub→过月；真表无此令；候选取消；过月不复活。"""
    env = matrix_env
    client = env["client"]
    game = env["game"]
    confirm: _ConfirmStub = env["confirm"]

    _issue_entry(env, entry=entry)
    assert len(_db_pending_secret_new(game)) >= 1
    assert _matrix_orders(client) == []

    reject_msg = S3_REJECT[cell]
    confirm.push("拒绝")
    _chat(env, reject_msg)

    # 候选态=取消/清除
    assert _db_pending_secret_new(game) == [], (
        f"{cell} 拒绝后 pending 新建候选须清除: {_db_pending_secret_new(game)!r}"
    )
    assert _matrix_orders(client) == []
    # 拒绝判词须被真实消费（禁 `or confirm.calls` 恒真尾）
    assert reject_msg in confirm.calls, (
        f"{cell} 拒绝轮须调用确认判词: calls={confirm.calls!r}"
    )
    assert "拒绝" in confirm.results, (
        f"{cell} 拒绝轮须消费确认判词=拒绝: results={confirm.results!r}"
    )

    # 过月不复活
    _settle_month(env)
    assert _matrix_orders(client) == [], (
        f"{cell} 过月后不得复活: {_matrix_orders(client)!r}"
    )
    # DB 真表亦无
    db_orders = [
        o for o in game.db.list_secret_orders()
        if any(
            t in f"{o.get('title')}{o.get('content')}"
            for t in (E2_TITLE, MODIFIED_TITLE, RESTATED_CONTENT, "关宁欠饷", "欠饷实数")
        )
    ]
    assert db_orders == [], f"{cell} DB 真表不得有此令: {db_orders!r}"


# ── V3 回归引用 ─────────────────────────────────────────────────────────


def test_V3_regression_confirm_visible(
    tmp_path, monkeypatch, _offline_scene_beat_generator,
):
    """V3：既有 test_qa_c3… 准后 id>0 + 立刻可见——全绿保持。"""
    from tests.test_qa_c3_secret_order_path_1357_1376 import (
        test_confirm_secret_order_http_returns_id_and_list_visible,
    )

    test_confirm_secret_order_http_returns_id_and_list_visible(
        tmp_path, monkeypatch, _offline_scene_beat_generator,
    )
