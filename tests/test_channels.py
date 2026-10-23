"""Subscription channels from the HTTP entry. Stand-ins sit at the process or HTTP boundary."""

import asyncio
import base64
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
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from starlette.testclient import TestClient

from ming.__main__ import main
from ming.middle import codex_auth
from ming.middle.cli_model import GROK_OFF
from ming.web import create_app

RECORDED = Path(__file__).parent / "recorded"
SCENE = ["殿上", "有人"]
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


def embedded(text: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    decoder = json.JSONDecoder()
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return found
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            found.append(value)
        index = end


def schema_fields(text: str) -> tuple[set[str], set[str]]:
    props: set[str] = set()
    defs: set[str] = set()
    for obj in embedded(text):
        properties = obj.get("properties")
        if obj.get("type") == "object" and isinstance(properties, dict):
            props.update(str(key) for key in properties)
        definitions = obj.get("$defs")
        if isinstance(definitions, dict):
            defs.update(str(key) for key in definitions)
    return props, defs


def recorded_reply(text: str) -> str:
    props, defs = schema_fields(text)
    if "UrgentPetition" in defs or "ImpeachmentPetition" in defs:
        return (RECORDED / "sources_empty.txt").read_text()
    if "month_end" in props:
        return (RECORDED / "simulation.txt").read_text()
    if "verdict" in props:
        return (RECORDED / "deliberation.txt").read_text()
    if "decrees" in props:
        return '{"facts":[],"decrees":[]}'
    if "facts" in props:
        return '{"facts":[]}'
    return (RECORDED / "gazette.txt").read_text()


def system_prompt(args: tuple[str, ...]) -> str:
    for flag in ("--system-prompt-override", "--system-prompt"):
        if flag in args:
            return args[args.index(flag) + 1]
    return ""


def mcp_url(args: tuple[str, ...], kwargs: dict[str, object]) -> str | None:
    cwd = Path(str(kwargs.get("cwd") or "."))
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


def host_lines(binary: str, chunks: list[str], *, error: str | None = None) -> list[bytes]:
    if binary == "grok":
        lines = [{"type": "text", "data": chunk} for chunk in chunks]
        end: dict[str, object] = {"type": "end", "stopReason": "end_turn"}
        if error:
            end = {"type": "error", "message": error}
        return [json.dumps(item).encode() + b"\n" for item in (*lines, end)]
    events: list[dict[str, object]] = []
    for chunk in chunks:
        events.append(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": chunk},
            }
        )
    message: dict[str, object] = {
        "role": "assistant",
        "content": [{"type": "text", "text": "".join(chunks)}],
        "stopReason": "error" if error else "stop",
    }
    if error:
        message["errorMessage"] = error
    events.append({"type": "message_end", "message": message})
    events.append({"type": "agent_settled", "aborted": False})
    return [json.dumps(item).encode() + b"\n" for item in events]


def finished(output: asyncio.StreamReader, code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        stdout=output,
        returncode=code,
        communicate=AsyncMock(return_value=(b"", b"")),
        terminate=lambda: None,
    )


def prompt_text(prompt: object) -> str:
    if not hasattr(prompt, "read"):
        return ""
    pos = prompt.tell()
    raw = prompt.read()
    prompt.seek(pos)
    return raw.decode() if isinstance(raw, bytes) else str(raw)


async def chunks_for(url: str | None, request: str) -> list[str]:
    if url is None:
        return [recorded_reply(request)]
    async with Client(url) as client:
        listed = await client.list_tools()
        names = [tool.name for tool in listed.tools]
        if "set_hall" in names:
            await client.call_tool("set_hall", {"add": ["王承恩"], "remove": []})
            return SCENE
        if "read_records" in names:
            await client.call_tool("read_records", {})
    return [recorded_reply(request)]


def install_process(monkeypatch, *, mode: str = "ok", delay: float = 0):
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    snapshots: list[dict[str, str]] = []
    inflight: dict[str, str] = {}

    async def spawn(*args: str, **kwargs: object) -> SimpleNamespace:
        calls.append((args, kwargs))
        errors = kwargs.get("stderr")
        if args[0] == "grok" and "--trust" in args:
            mark_trusted(Path(args[args.index("--cwd") + 1]))
            return finished(asyncio.StreamReader())
        if mode == "missing":
            raise FileNotFoundError(2, "No such file or directory", args[0])
        output = asyncio.StreamReader()
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
        if mode == "error":
            chunks, error = [], "down"
        elif mode == "empty":
            chunks, error = [], None
        else:
            request = system_prompt(args) + "\n" + prompt_text(kwargs.get("stdin"))
            chunks, error = await chunks_for(url, request), None
        for line in host_lines(args[0], chunks, error=error):
            output.feed_data(line)
        output.feed_eof()
        if hasattr(errors, "write") and args[0] == "grok":
            errors.write(b"warning: plugin slow\n")
        return finished(output)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return calls, snapshots


def created(resp_id: str) -> dict[str, object]:
    return {
        "type": "response.created",
        "response": {
            "id": resp_id,
            "object": "response",
            "created_at": 1,
            "status": "in_progress",
            "model": "gpt-5.4",
            "output": [],
        },
    }


def text_stream(text: str) -> httpx2.Response:
    parts = [text[: len(text) // 2], text[len(text) // 2 :]]
    events = [created("resp_text")]
    events.extend(
        {
            "type": "response.output_text.delta",
            "item_id": "msg",
            "output_index": 0,
            "content_index": 0,
            "delta": part,
        }
        for part in parts
        if part
    )
    events.append(
        {
            "type": "response.completed",
            "response": {
                "id": "resp_text",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-5.4",
                "output": [
                    {
                        "id": "msg",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": text, "annotations": []}
                        ],
                    }
                ],
            },
        }
    )
    body = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events)
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def tool_call(name: str, arguments: dict[str, object]) -> httpx2.Response:
    item = {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": name,
        "arguments": json.dumps(arguments),
        "status": "completed",
    }
    events = [
        created("resp_tool"),
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {
            "type": "response.completed",
            "response": {
                "id": "resp_tool",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "gpt-5.4",
                "output": [item],
            },
        },
    ]
    body = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events)
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


def codex_text(body: dict[str, object]) -> str:
    chunks: list[str] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str):
        chunks.append(instructions)
    for item in body.get("input") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
    return "\n".join(chunks)


def tool_records(body: dict[str, object]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for item in body.get("input") or []:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        output = item.get("output")
        if not isinstance(output, str):
            continue
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            found.append(parsed)
    return found


def codex_response(
    body: dict[str, object], outputs: list[dict[str, object]] | None = None
) -> httpx2.Response:
    text = codex_text(body)
    props, _defs = schema_fields(text)
    called = any(
        isinstance(item, dict) and item.get("type") == "function_call"
        for item in body.get("input") or []
    )
    if "month_end" in props and not called:
        return tool_call("read_records", {})
    if outputs is not None and "month_end" in props:
        outputs.extend(tool_records(body))
    return text_stream(recorded_reply(text))


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
    assert "王承恩" in night["hall"]
    deltas = [event["data"] for event in events if event["event"] == "delta"]
    assert len(deltas) >= 2
    live = ""
    for item in deltas:
        live = item["replace"] if isinstance(item, dict) else live + str(item)
    assert live == night["turns"][-1]["scene"]


@pytest.mark.parametrize(
    ("backend", "model"),
    [("grok", ""), ("pi", ""), ("pi", "xai/grok-4.7:high")],
)
def test_process_subscription_scene_lands_and_streams(
    tmp_path: Path, monkeypatch, backend: str, model: str, game_db: Path
) -> None:
    before = {path: stamp(path) for path in USER_FILES}
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("MING_GROK_SLOTS", str(tmp_path / "slots"))
    calls, _snapshots = install_process(monkeypatch)
    app = create_app(game_db.parent)
    events = watch(app)
    with TestClient(app) as client:
        open_game(client, {"backend": backend, "model": model}, game_db)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "宣王承恩"}).raise_for_status()
        state = client.get("/state").json()
    assert_scene(state, events)
    assert state["settings"]["backend"] == backend
    assert state["settings"]["model"] == model
    model_calls = [args for args, _kwargs in calls if "--trust" not in args]
    assert model_calls
    for args in model_calls:
        assert args[0] == backend
        if model:
            assert args[args.index("--model") + 1] == model
        else:
            assert "--model" not in args
    if backend == "grok":
        args, kwargs = next((args, kwargs) for args, kwargs in calls if "--trust" not in args)
        assert args[args.index("--tools") + 1] == "search_tool,use_tool"
        assert "--always-approve" in args and "--no-subagents" in args
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert all(env[key] == "0" for key in GROK_OFF)
    else:
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
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        bodies.append(payload)
        if len(bodies) == 1:
            return tool_call("set_hall", {"add": ["王承恩"], "remove": []})
        return text_stream("".join(SCENE))

    install_codex(monkeypatch, handler)
    app = create_app(game_db.parent)
    events = watch(app)
    with TestClient(app) as client:
        open_game(client, {"backend": "codex", "model": "gpt-5.4"}, game_db)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "宣王承恩"}).raise_for_status()
        state = client.get("/state").json()
    assert_scene(state, events)
    assert {path: stamp(path) for path in USER_FILES} == before
    assert not (home / "config.toml").exists()


@pytest.mark.parametrize(
    "scene_model",
    ["grok", "pi:xai/grok-4.7:high", "codex:gpt-5.4", "openai-codex:gpt-5.4"],
)
def test_cli_model_string_reaches_its_host(
    tmp_path: Path, monkeypatch, game_db: Path, scene_model: str
) -> None:
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("MING_GROK_SLOTS", str(tmp_path / "slots"))
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    calls, _snapshots = install_process(monkeypatch)
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return text_stream("殿上")

    install_codex(monkeypatch, handler)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"action": "say", "words": "宣"}) + "\n")
    )
    main(["audience", "--db", str(game_db), "--scene-model", scene_model])
    if scene_model.startswith(("codex:", "openai-codex:")):
        assert bodies[0]["model"] == "gpt-5.4"
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
    monkeypatch.setenv("MING_GROK_SLOTS", str(tmp_path / "slots"))
    monkeypatch.setattr("ming.middle.cli_model.GROK_SLOT_COUNT", 2)
    calls, snapshots = install_process(monkeypatch, delay=0.05 if backend == "grok" else 0)
    if backend == "codex":
        home = tmp_path / "codex"
        auth_file(home / "auth.json", expired=False)
        monkeypatch.setenv("CODEX_HOME", str(home))

        def handler(request: httpx2.Request) -> httpx2.Response:
            return codex_response(json.loads(request.content))

        install_codex(monkeypatch, handler)
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        settings = {"backend": backend, "model": "gpt-5.4" if backend == "codex" else ""}
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
    monkeypatch.setenv("MING_GROK_SLOTS", str(tmp_path / "slots"))
    calls, _snapshots = install_process(monkeypatch)
    with TestClient(create_app(game_db.parent)) as client:
        open_game(client, {"backend": "grok", "model": ""}, game_db)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        trusted = sum("--trust" in args for args, _kwargs in calls)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    assert state["game"]["failure"] is None
    assert sum("--trust" in args for args, _kwargs in calls) == trusted


def test_codex_forwards_a_ledger_sized_tool_result(tmp_path: Path, monkeypatch, game_db: Path) -> None:
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    planted = {"text": "账" * 100_000}
    outputs: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        return codex_response(json.loads(request.content), outputs)

    install_codex(monkeypatch, handler)
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        open_game(client, {"backend": "codex", "model": "gpt-5.4"}, game_db)
        app.state.web.game.court.record(("world", "天下"), [("note", planted)])
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    assert state["game"]["failure"] is None
    assert any(
        fact.get("kind") == "note" and fact.get("detail") == planted
        for record in outputs
        for fact in record.get("facts", [])
        if isinstance(fact, dict)
    )


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
    monkeypatch.setenv("MING_GROK_SLOTS", str(tmp_path / "slots"))
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
        open_game(client, {"backend": "codex", "model": "gpt-5.4"}, game_db)
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
        return text_stream("".join(SCENE))

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
                        "settings": {"backend": "codex", "model": "gpt-5.4"},
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
