"""Subscription channels from the HTTP entry. Stand-ins sit at the process or HTTP boundary."""

import asyncio
import base64
import gzip
import io
import json
import os
import time
import tomllib
from pathlib import Path
from shutil import copyfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
from mcp import Client
from pydantic_ai._run_context import get_current_run_context
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from starlette.testclient import TestClient

from ming.__main__ import main
from ming.middle import codex_auth
from ming.middle.cli_model import GROK_OFF
from ming.web import create_app
from tests.conftest import RECORDED, RECORDED_REPLIES

CODEX_MODEL = "gpt-6.1-sol"
PI_MODEL = f"openai-codex/{CODEX_MODEL}"
REPLIES = RECORDED_REPLIES | {
    "scene": "殿上有人",
    "NightDeclaration": (RECORDED / "night_empty.txt").read_text(),
}
USER_FILES = (
    Path.home() / ".codex" / "auth.json",
    Path.home() / ".codex" / "config.toml",
    Path.home() / ".grok" / "config.toml",
    Path.home() / ".grok" / "trusted_folders.toml",
    Path.home() / ".pi" / "agent" / "settings.json",
    Path.home() / ".pi" / "agent" / "mcp.json",
)


def stamp(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def jwt(payload: dict[str, object]) -> str:
    def enc(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc({'alg': 'none'})}.{enc(payload)}.x"


def auth_file(path: Path, *, expired: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exp = int(time.time()) - 100 if expired else int(time.time()) + 3600
    path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": jwt({"exp": exp, "account_id": "acct"}),
                    "account_id": "acct",
                    "id_token": "kept-id",
                    "refresh_token": "old-refresh",
                },
            }
        )
    )


def mcp_url(args: tuple[str, ...], kwargs: dict[str, object]) -> str | None:
    cwd = Path(str(kwargs.get("cwd") or "."))
    if args[0] == "claude":
        config = json.loads(args[args.index("--mcp-config") + 1])
        return config["mcpServers"].get("court", {}).get("url")
    if args[0] == "grok":
        config = cwd / ".grok" / "config.toml"
        if not config.is_file():
            return None
        servers = tomllib.loads(config.read_text(encoding="utf-8")).get("mcp_servers", {})
        return servers.get("court", {}).get("url")
    listed = cwd / ".pi" / "mcp.json"
    if not listed.is_file():
        return None
    servers = json.loads(listed.read_text())["mcpServers"]
    return next(iter(servers.values()))["url"]


def mark_trusted(slot: Path) -> None:
    store = Path(os.environ["GROK_HOME"]) / "trusted_folders.toml"
    store.parent.mkdir(parents=True, exist_ok=True)
    existing = store.read_text() if store.is_file() else ""
    key = json.dumps(str(slot))
    if key in existing:
        return
    if "[folders]" not in existing:
        existing = "[folders]\n" + existing
    store.write_text(existing + f"{key} = {{ trusted = true }}\n")


def host_lines(binary: str, chunks: list[str], *, mode: str = "ok") -> list[bytes]:
    if (binary in {"grok", "pi"} and mode == "ok") or (binary == "pi" and mode == "empty"):
        name = get_current_run_context().agent.name if mode == "ok" else "empty"
        return [gzip.decompress(
            (RECORDED / "channels" / binary / f"{name}.jsonl.gz").read_bytes()
        )]
    error = "down" if mode == "error" else None
    events: list[dict[str, object]]
    if binary == "claude":
        events = [
            {"type": "stream_event", "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": chunk},
            }}
            for chunk in chunks
        ]
        events.append({"type": "result", "is_error": bool(error)})
    else:
        # Semantic host errors still await a native recording.
        events = [
            {"type": "message_end", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": ""}],
                "stopReason": "error",
                "errorMessage": error,
            }},
            {"type": "agent_settled", "aborted": False},
        ]
    return [json.dumps(item).encode() + b"\n" for item in events]


def finished(output: asyncio.StreamReader, code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        stdout=output,
        returncode=code,
        communicate=AsyncMock(return_value=(b"", b"")),
        terminate=lambda: None,
    )


async def chunks_for(url: str | None) -> list[str]:
    if url is not None:
        async with Client(url) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            if "set_hall" in names:
                await client.call_tool("set_hall", {"add": ["王承恩"], "remove": []})
            if "read_records" in names:
                await client.call_tool("read_records", {})
    text = REPLIES[get_current_run_context().agent.name]
    return [text[: len(text) // 2], text[len(text) // 2 :]]


def install_process(monkeypatch, *, mode: str = "ok", delay: float = 0):
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    snapshots: list[dict[str, str]] = []
    inflight: dict[str, str] = {}

    async def spawn(*args: str, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        if args[0] == "grok" and "--trust" in args:
            mark_trusted(Path(args[args.index("--cwd") + 1]))
            return finished(asyncio.StreamReader())
        if mode == "missing":
            raise FileNotFoundError(2, "No such file or directory", args[0])
        output = asyncio.StreamReader(limit=kwargs["limit"])
        if mode == "exit":
            output.feed_eof()
            return finished(output, 1)
        cwd = str(kwargs.get("cwd"))
        url = mcp_url(args, kwargs)
        if url is not None:
            inflight[cwd] = url
            if len(inflight) >= 2:
                snapshots.append(dict(inflight))
        if delay:
            await asyncio.sleep(delay)
        inflight.pop(cwd, None)
        chunks = await chunks_for(url) if mode == "ok" else []
        for line in host_lines(args[0], chunks, mode=mode):
            output.feed_data(line)
        output.feed_eof()
        if args[0] == "grok" and mode == "ok":
            kwargs["stderr"].write(b"warning: plugin slow\n")
        return finished(output)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls, snapshots


def codex_stream(name: str) -> httpx2.Response:
    body = gzip.decompress((RECORDED / "channels" / "codex" / f"{name}.sse.gz").read_bytes())
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def codex_response(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    name = get_current_run_context().agent.name
    called = any(
        isinstance(item, dict) and item.get("type") == "function_call"
        for item in body.get("input") or []
    )
    if name in {"scene", "simulation"} and not called:
        return codex_stream("scene-tool" if name == "scene" else "read-records")
    return codex_stream(name)


def install_codex(monkeypatch, handler):
    codex_auth._PROVIDERS.clear()
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    real = OpenAICodexProvider.__init__

    def init(self, *args, **kwargs):
        kwargs["http_client"] = client
        real(self, *args, **kwargs)

    monkeypatch.setattr(OpenAICodexProvider, "__init__", init)


def watch(app) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    original = app.state.web.emit

    def spy(event: dict[str, object]) -> None:
        events.append(dict(event))
        original(event)

    app.state.web.emit = spy
    return events


def open_game(client: TestClient, settings: dict[str, str], game_db: Path) -> None:
    client.post("/actions", json={"action": "settings", "settings": settings}).raise_for_status()
    client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()


def assert_scene(state: dict[str, object], events: list[dict[str, object]]) -> None:
    game = state["game"]
    assert isinstance(game, dict)
    assert game["failure"] is None
    night = game["night"]
    assert isinstance(night, dict)
    assert night["result"] == "translated"
    assert "王承恩" in night["hall"]
    deltas = [event["data"] for event in events if event["event"] == "delta"]
    assert len(deltas) >= 2
    live = ""
    for item in deltas:
        live = item["replace"] if isinstance(item, dict) else live + str(item)
    assert live == night["turns"][-1]["scene"]


@pytest.mark.parametrize(
    ("backend", "model"),
    [("claude-cli", ""), ("claude-cli", "sonnet"), ("grok", ""),
     ("grok", "grok-4.7"), ("pi", ""), ("pi", f"{PI_MODEL}:high")],
)
def test_process_subscription_scene_lands_and_streams(
    tmp_path: Path, monkeypatch, backend: str, model: str, game_db: Path
) -> None:
    before = {path: stamp(path) for path in USER_FILES}
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    calls, _snapshots = install_process(monkeypatch)
    app = create_app(game_db.parent)
    events = watch(app)
    with TestClient(app) as client:
        open_game(client, {"backend": backend, "model": model}, game_db)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "宣王承恩"}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(app.state.web.game.drain)
        state = client.get("/state").json()
    assert_scene(state, events)
    assert state["settings"]["backend"] == backend
    assert state["settings"]["model"] == model
    model_calls = [args for args, _kwargs in calls if "--trust" not in args]
    assert model_calls
    for args in model_calls:
        assert args[0] == ("claude" if backend == "claude-cli" else backend)
        if model:
            assert args[args.index("--model") + 1] == model
        else:
            assert "--model" not in args
    if backend == "grok":
        args, kwargs = next((args, kwargs) for args, kwargs in calls if "--trust" not in args)
        assert args[args.index("--tools") + 1] == "search_tool,use_tool"
        assert Path(args[args.index("--prompt-file") + 1]).suffix != ".json"
        assert "--verbatim" in args
        assert "--always-approve" in args and "--no-subagents" in args
        assert "--json-schema" not in args
        args = model_calls[-1]
        assert "decree_events" in json.loads(args[args.index("--json-schema") + 1])["properties"]
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert all(env[key] == "0" for key in GROK_OFF)
    elif backend == "pi":
        args = model_calls[0]
        assert "--approve" in args and "--no-mcp" not in args
        assert args[args.index("--tools") + 1] == "mcp__court__*"
        assert "-e" in args and args[args.index("-e") + 1] == "builtin:mcp"
    assert {path: stamp(path) for path in USER_FILES} == before


def test_codex_scene_lands_and_streams(tmp_path: Path, monkeypatch, game_db: Path) -> None:
    before = {path: stamp(path) for path in USER_FILES}
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    install_codex(monkeypatch, codex_response)
    app = create_app(game_db.parent)
    events = watch(app)
    with TestClient(app) as client:
        open_game(client, {"backend": "codex", "model": CODEX_MODEL}, game_db)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "宣王承恩"}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(app.state.web.game.drain)
        state = client.get("/state").json()
    assert_scene(state, events)
    assert {path: stamp(path) for path in USER_FILES} == before
    assert not (home / "config.toml").exists()


@pytest.mark.parametrize(
    "scene_model",
    ["grok", f"pi:{PI_MODEL}:high", f"codex:{CODEX_MODEL}", f"openai-codex:{CODEX_MODEL}"],
)
def test_cli_model_string_reaches_its_host(
    tmp_path: Path, monkeypatch, game_db: Path, scene_model: str
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    calls, _snapshots = install_process(monkeypatch)
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return codex_stream("scene")

    install_codex(monkeypatch, handler)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"action": "say", "words": "宣"}) + "\n")
    )
    main(["audience", "--db", str(game_db), "--scene-model", scene_model])
    if scene_model.startswith(("codex:", "openai-codex:")):
        assert bodies[0]["model"] == CODEX_MODEL
        assert not [args for args, _kwargs in calls if args and args[0] == "codex"]
        return
    binary, _, name = scene_model.partition(":")
    model_calls = [args for args, _kwargs in calls if args[0] == binary and "--trust" not in args]
    assert model_calls
    if name:
        assert model_calls[0][model_calls[0].index("--model") + 1] == name
    else:
        assert "--model" not in model_calls[0]


def test_codex_settings_require_a_model(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path)) as client:
        response = client.post(
            "/actions", json={"action": "settings", "settings": {"backend": "codex"}}
        )
    assert response.status_code == 400


@pytest.mark.parametrize("backend", ["grok", "pi", "codex"])
def test_subscription_month_completes(tmp_path: Path, monkeypatch, backend: str, game_db: Path) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("ming.middle.cli_model.GROK_SLOT_COUNT", 2)
    calls, snapshots = install_process(monkeypatch, delay=0.05 if backend == "grok" else 0)
    if backend == "codex":
        home = tmp_path / "codex"
        auth_file(home / "auth.json", expired=False)
        monkeypatch.setenv("CODEX_HOME", str(home))
        install_codex(monkeypatch, codex_response)
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        settings = {"backend": backend, "model": CODEX_MODEL if backend == "codex" else ""}
        open_game(client, settings, game_db)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    assert state["game"]["failure"] is None
    assert state["game"]["date"]["month"] == 11
    if backend == "grok":
        assert snapshots
        assert any(len(set(shot.values())) == len(shot) and len(shot) >= 2 for shot in snapshots)
        assert max(len(shot) for shot in snapshots) <= 2
        trust = [args for args, _kwargs in calls if "--trust" in args]
        assert trust
        assert len(trust) == len({args[args.index("--cwd") + 1] for args in trust})


def test_grok_second_month_does_not_trust_again(tmp_path: Path, monkeypatch, game_db: Path) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    calls, _snapshots = install_process(monkeypatch)
    with TestClient(create_app(game_db.parent)) as client:
        open_game(client, {"backend": "grok", "model": ""}, game_db)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        trusted = sum("--trust" in args for args, _kwargs in calls)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    assert state["game"]["failure"] is None
    assert sum("--trust" in args for args, _kwargs in calls) == trusted


def test_pi_empty_assistant_is_not_a_transport_failure(
    game_db: Path, monkeypatch
) -> None:
    calls, _snapshots = install_process(monkeypatch, mode="empty")
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        open_game(client, {"backend": "pi", "model": ""}, game_db)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "无"}).raise_for_status()
        state = client.get("/state").json()
    model_calls = [args for args, _kwargs in calls if args[0] == "pi"]
    assert len(model_calls) == 2
    assert state["game"]["night"]["turns"] == []
    assert state["game"]["failure"]["status"] == "failed"


@pytest.mark.parametrize(("backend", "mode"), [("grok", "exit"), ("grok", "missing"), ("pi", "error")])
def test_process_failure_stops_month(tmp_path: Path, monkeypatch, backend: str, mode: str, game_db: Path) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    install_process(monkeypatch, mode=mode)
    with TestClient(create_app(game_db.parent)) as client:
        open_game(client, {"backend": backend, "model": ""}, game_db)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    failure = state["game"]["failure"]
    assert state["game"]["date"]["month"] == 10
    assert failure["status"] == "failed"
    assert failure["action"] == "month"
    assert failure["payload"]["type"] == (
        "FileNotFoundError" if mode == "missing" else "RuntimeError"
    )


@pytest.mark.parametrize("problem", ["missing", "rejected"])
def test_codex_credential_failure_stops_month(tmp_path: Path, monkeypatch, problem: str, game_db: Path) -> None:
    before = stamp(Path.home() / ".codex" / "config.toml")
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    if problem == "rejected":
        auth_file(home / "auth.json", expired=True)
        original = (home / "auth.json").read_bytes()

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "auth.openai.com":
            return httpx2.Response(
                400, json={"error": "invalid_grant", "error_description": "REFRESH-REJECTED"}
            )
        return httpx2.Response(401, json={"error": {"message": "expired"}})

    install_codex(monkeypatch, handler)
    with TestClient(create_app(game_db.parent)) as client:
        open_game(client, {"backend": "codex", "model": CODEX_MODEL}, game_db)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    failure = state["game"]["failure"]
    assert state["game"]["date"]["month"] == 10
    assert failure["status"] == "failed"
    assert failure["payload"]["type"] == (
        "UserError" if problem == "missing" else "CredentialsRefreshError"
    )
    assert not (home / "config.toml").exists()
    assert stamp(Path.home() / ".codex" / "config.toml") == before
    if problem == "rejected":
        assert (home / "auth.json").read_bytes() == original


def test_codex_parallel_refresh_writes_one_credential(tmp_path: Path, monkeypatch, game_db: Path, opening_db: Path) -> None:
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=True)
    monkeypatch.setenv("CODEX_HOME", str(home))
    refreshes: list[int] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "auth.openai.com":
            refreshes.append(1)
            await asyncio.sleep(0.2)
            return httpx2.Response(
                200,
                json={
                    "access_token": jwt({"exp": int(time.time()) + 3600, "account_id": "acct"}),
                    "refresh_token": "new-refresh",
                },
            )
        return codex_stream("scene")

    install_codex(monkeypatch, handler)

    second_directory = tmp_path / "b"
    second_directory.mkdir()
    copyfile(opening_db, second_directory / opening_db.name)

    async def run() -> None:
        transport_a = httpx.ASGITransport(app=create_app(game_db.parent))
        transport_b = httpx.ASGITransport(app=create_app(second_directory))
        async with (
            httpx.AsyncClient(transport=transport_a, base_url="http://a") as first,
            httpx.AsyncClient(transport=transport_b, base_url="http://b") as second,
        ):
            for client in (first, second):
                response = await client.post(
                    "/actions",
                    json={
                        "action": "settings",
                        "settings": {"backend": "codex", "model": CODEX_MODEL},
                    },
                )
                response.raise_for_status()
                response = await client.post(
                    "/actions", json={"action": "load", "save": opening_db.name}
                )
                response.raise_for_status()
                response = await client.post("/actions", json={"action": "open"})
                response.raise_for_status()
            await asyncio.gather(
                first.post("/actions", json={"action": "say", "words": "甲"}),
                second.post("/actions", json={"action": "say", "words": "乙"}),
            )
            for client in (first, second):
                state = (await client.get("/state")).json()
                assert state["game"]["failure"] is None
                assert state["game"]["night"]["turns"]

    asyncio.run(run())
    data = json.loads((home / "auth.json").read_text())
    assert len(refreshes) == 1
    assert data["tokens"]["refresh_token"] == "new-refresh"
    assert data["tokens"]["id_token"] == "kept-id"
    assert data["tokens"]["account_id"] == "acct"
    assert data["auth_mode"] == "chatgpt"
    assert data["OPENAI_API_KEY"] is None
    assert data["last_refresh"]
    assert not (home / "config.toml").exists()
