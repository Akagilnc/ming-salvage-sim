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
from functools import partial
from shutil import copyfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
from mcp import Client
from openai.types.responses import (
    Response as OpenAIResponse,
    ResponseCompletedEvent,
    ResponseCreatedEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemDoneEvent,
)
from pydantic_ai._run_context import get_current_run_context
from pydantic_ai.providers.openai_codex import OpenAICodexProvider
from pydantic_ai.providers.openai import OpenAIProvider
from starlette.testclient import TestClient

from ming.__main__ import main
from ming.middle import codex_auth
from ming.middle.cli_model import GROK_OFF
from ming.middle.opening import opening_template
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
        calls.append((args, {**kwargs, "agent": (
            None if "--trust" in args else get_current_run_context().agent.name
        )}))
        if args[0] == "grok" and "--trust" in args:
            mark_trusted(Path(args[args.index("--cwd") + 1]))
            return finished(asyncio.StreamReader())
        if mode == "missing":
            raise FileNotFoundError(2, "No such file or directory", args[0])
        output = asyncio.StreamReader(limit=kwargs["limit"])
        if mode == "exit" or ("--model" in args and args[args.index("--model") + 1] == "rejected-model"):
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


def codex_response(
    request: httpx2.Request, outputs: list[dict[str, object]] | None = None,
    *, requests: list[httpx2.Request] | None = None, rejected: bool = False,
    read_args: dict[str, object] | None = None,
) -> httpx2.Response:
    if requests is not None:
        requests.append(request)
    if rejected:
        return httpx2.Response(400, json={"error": {"message": "unsupported effort"}})
    body = json.loads(request.content)
    name = get_current_run_context().agent.name
    if request.url.path.endswith("/chat/completions"):
        reply = REPLIES[name]
        completion = {
            "id": "chatcmpl-recorded", "object": "chat.completion", "created": 1,
            "model": CODEX_MODEL,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": reply},
                         "finish_reason": "stop"}],
        }
        if not body.get("stream"):
            return httpx2.Response(200, json=completion)
        completion["object"] = "chat.completion.chunk"
        completion["choices"] = [{"index": 0, "delta": {"role": "assistant", "content": reply},
                                   "finish_reason": "stop"}]
        return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                               content=f"data: {json.dumps(completion)}\n\ndata: [DONE]\n\n".encode())
    called = any(
        isinstance(item, dict) and item.get("type") == "function_call"
        for item in body.get("input") or []
    )
    if outputs is not None:
        outputs.extend(
            json.loads(item["output"])
            for item in body.get("input") or []
            if isinstance(item, dict) and item.get("type") == "function_call_output"
            and isinstance(item.get("output"), str)
        )
    if name == "simulation" and not called and read_args is not None:
        # Schema-only boundary input: keep native recordings unchanged and
        # use SDK events for the keyed query required by #1970.
        call = ResponseFunctionToolCall(
            type="function_call", id="fc_ledger", call_id="call_ledger",
            name="read_records", arguments=json.dumps(read_args), status="completed",
        )
        response = OpenAIResponse(
            id="resp_ledger", created_at=1792748281, model=CODEX_MODEL,
            object="response", output=[call], status="completed",
            parallel_tool_calls=True, tool_choice="auto", tools=[],
        )
        events = [
            ResponseCreatedEvent(type="response.created", sequence_number=0, response=response.model_copy(update={"status": "in_progress", "output": []})),
            ResponseOutputItemDoneEvent(type="response.output_item.done", sequence_number=1, output_index=0, item=call),
            ResponseCompletedEvent(type="response.completed", sequence_number=2, response=response),
        ]
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"},
            content="".join(f"event: {event.type}\ndata: {event.model_dump_json()}\n\n" for event in events),
        )
    if name in {"scene", "simulation"} and not called:
        return codex_stream("scene-tool" if name == "scene" else "read-records")
    return codex_stream(name)


def install_codex(monkeypatch, handler, provider=OpenAICodexProvider):
    codex_auth._PROVIDERS.clear()
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    real = provider.__init__

    def init(self, *args, **kwargs):
        kwargs["http_client"] = client
        real(self, *args, **kwargs)

    monkeypatch.setattr(provider, "__init__", init)


def watch(app) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    original = app.state.web.emit

    def spy(event: dict[str, object]) -> None:
        events.append(dict(event))
        original(event)

    app.state.web.emit = spy
    return events


def open_game(client: TestClient, settings: dict[str, object], game_db: Path | None) -> None:
    client.post("/actions", json={"action": "settings", "settings": settings}).raise_for_status()
    client.post("/actions", json={"action": "load", "save": game_db.name}
                if game_db else {"action": "new"}).raise_for_status()


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
    ("backend", "model", "effort"),
    [("claude-cli", "", ""), ("claude-cli", "sonnet", "native-unknown"),
     ("grok", "", ""), ("grok", "grok-4.7", "medium"),
     ("pi", "", ""), ("pi", f"{PI_MODEL}:high", "native-unknown")],
)
def test_process_subscription_scene_lands_and_streams(
    game_db: Path, monkeypatch, backend: str, model: str, effort: str
) -> None:
    tmp_path = game_db.parent
    before = {path: stamp(path) for path in USER_FILES}
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    calls, _snapshots = install_process(monkeypatch)
    app = create_app(game_db.parent)
    events = watch(app)
    with TestClient(app) as client:
        open_game(client, {"backend": backend, "model": model, "effort": effort}, game_db)
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
        flag = {"claude-cli": "--effort", "grok": "--reasoning-effort", "pi": "--thinking"}[backend]
        if effort:
            assert args[args.index(flag) + 1] == effort
        else:
            assert flag not in args
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


@pytest.mark.parametrize("channel", [
    ("codex", ""), ("codex", "native-unknown"),
    ("api", ""), ("api", "native-unknown"),
])
def test_codex_scene_lands_and_streams(tmp_path: Path, monkeypatch, game_db: Path, channel) -> None:
    before = {path: stamp(path) for path in USER_FILES}
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    bodies = []

    install_codex(monkeypatch, partial(codex_response, requests=bodies,
                                      rejected=channel[1] == "native-unknown"),
                  OpenAICodexProvider if channel[0] == "codex" else OpenAIProvider)
    app = create_app(game_db.parent)
    events = watch(app)
    with TestClient(app) as client:
        open_game(client, {"backend": channel[0], "model": CODEX_MODEL, "effort": channel[1],
                           "base_url": "https://api.example.test/v1", "api_key": "test-key"}, game_db)
        client.post("/actions", json={"action": "open"}).raise_for_status()
        client.post("/actions", json={"action": "say", "words": "宣王承恩"}).raise_for_status()
        client.post("/actions", json={"action": "dismiss"}).raise_for_status()
        client.portal.call(app.state.web.game.drain)
        state = client.get("/state").json()
    assert bodies
    for request in bodies:
        body = json.loads(request.content)
        effort = body.get("reasoning", {}).get("effort") if channel[0] == "codex" else body.get("reasoning_effort")
        assert effort == (channel[1] or None)
    if channel[1] == "native-unknown":
        assert state["game"]["failure"]["payload"]["type"] == "ModelHTTPError"
    elif channel[0] == "codex":
        assert_scene(state, events)
    else:
        assert state["game"]["failure"] is None
        assert state["game"]["night"]["result"] == "translated"
    assert {path: stamp(path) for path in USER_FILES} == before
    assert not (home / "config.toml").exists()


@pytest.mark.parametrize(
    ("channel", "month_options"),
    [(("grok", ""), None), (("codex", CODEX_MODEL), None),
     (("pi", f"{PI_MODEL}:high"),
      ["--month-backend", "pi", "--month-model", PI_MODEL, "--month-effort", "high"])]
    + [(("pi", PI_MODEL), flags) for flags in (
        [], ["--month-backend", ""], ["--month-model", "ignored"],
        ["--month-backend", "api", "--month-model", CODEX_MODEL, "--month-base-url", ""],
        ["--month-backend", "pi", "--month-model", "rejected-model", "--month-effort", "high"],
    )],
)
def test_cli_channel_reaches_its_host(
    game_db: Path, monkeypatch, capsys, channel: tuple[str, str], month_options
) -> None:
    tmp_path = game_db.parent
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    calls, _snapshots = install_process(monkeypatch)
    bodies: list[httpx2.Request] = []
    install_codex(monkeypatch, partial(codex_response, requests=bodies))
    actions = [{"action": "say", "words": "宣"}]
    if month_options is not None:
        actions += [{"action": action} for action in ("dismiss", "drain", "month", "drain")]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(json.dumps(action) for action in actions)))
    backend, name = channel
    main(["audience", "--db", str(game_db), "--backend", backend, "--model", name,
          "--effort", "medium", *(month_options or [])])
    state = json.loads(capsys.readouterr().out.splitlines()[-1])
    if "rejected-model" in (month_options or []):
        assert state["date"]["month"] == 10
        assert state["month_error"]["type"] == "RuntimeError"
        assert set(state["month_error"]) == {"type", "message", "log"}
    else:
        assert state["date"]["month"] == (10 if month_options is None else 11)
        assert state["month_error"] is None
    for args, info in calls:
        if "--trust" not in args and info["agent"] not in {"scene", "NightDeclaration"}:
            assert args[0] == "pi"
            assert args[args.index("--thinking") + 1] == (
                "high" if "--month-effort" in month_options else "medium"
            )
    if backend == "codex":
        assert json.loads(bodies[0].content)["model"] == CODEX_MODEL
        assert all(json.loads(request.content)["reasoning"]["effort"] == "medium" for request in bodies)
        assert not [args for args, _kwargs in calls if args and args[0] == "codex"]
        return
    model_calls = [args for args, _kwargs in calls if args[0] == backend and "--trust" not in args]
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


@pytest.mark.parametrize(("backend", "game_db", "expected_calls"), [
    ("grok", "opening_db", {"Declaration"}), ("pi", "opening_db", {"Declaration"}),
    ("codex", "opening_db", set()), ("api", "opening_db", set()),
    ("claude-cli", "secret_night", {"secret_report", "Declaration"}),
    ("claude-cli", "backed_night", {"deliberation", "Declaration"}),
], indirect=["game_db"])
def test_subscription_month_completes(tmp_path: Path, monkeypatch, backend: str, game_db: Path, expected_calls) -> None:
    template = opening_template()
    monkeypatch.setenv("GROK_HOME", str(tmp_path / "grok-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    opening_template().parent.mkdir(parents=True, exist_ok=True)
    copyfile(template, opening_template())
    monkeypatch.setattr("ming.middle.cli_model.GROK_SLOT_COUNT", 2)
    calls, snapshots = install_process(monkeypatch, delay=0.05 if backend == "grok" else 0)
    if "deliberation" in expected_calls:
        monkeypatch.setitem(REPLIES, "NightDeclaration", json.loads(
            (RECORDED / "night_endorsed.json").read_text()
        )["replies"][0])
    bodies = []
    if backend in {"api", "codex"}:
        home = tmp_path / "codex"
        auth_file(home / "auth.json", expired=False)
        monkeypatch.setenv("CODEX_HOME", str(home))

        install_codex(monkeypatch, partial(codex_response, requests=bodies),
                      OpenAIProvider if backend == "api" else OpenAICodexProvider)
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        settings = {
            "backend": "claude-cli" if backend == "claude-cli" else "pi",
            "model": PI_MODEL, "effort": "medium",
            "month_model": {"backend": backend, "model": CODEX_MODEL if backend in {"api", "codex"} else PI_MODEL,
                            "effort": "high", "base_url": "https://month.example.test/v1", "api_key": "month-key"},
        }
        open_game(client, settings, None if backend == "pi" else game_db)
        if backend == "pi":
            client.post("/actions", json={"action": "open"}).raise_for_status()
            client.post("/actions", json={"action": "say", "words": "宣王承恩"}).raise_for_status()
        if backend in {"pi", "claude-cli"}:
            client.post("/actions", json={"action": "dismiss"}).raise_for_status()
            client.portal.call(app.state.web.game.drain)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    assert state["game"]["failure"] is None
    assert state["game"]["date"]["month"] == 11
    assert state["settings"]["month_model"] == settings["month_model"]
    if backend in {"api", "codex"}:
        assert bodies
        for request in bodies:
            body = json.loads(request.content)
            assert body["model"] == CODEX_MODEL
            assert (body["reasoning"]["effort"] if backend == "codex" else body["reasoning_effort"]) == "high"
            if backend == "api":
                assert request.url.host == "month.example.test"
                assert request.headers["authorization"] == "Bearer month-key"
    for args, info in calls:
        if "--trust" in args:
            continue
        if info["agent"] in {"scene", "NightDeclaration"}:
            assert args[0] == ("claude" if backend == "claude-cli" else "pi")
            flag = "--effort" if backend == "claude-cli" else "--thinking"
            assert args[args.index(flag) + 1] == "medium"
        else:
            assert args[0] == ("claude" if backend == "claude-cli" else backend)
            flag = {"claude-cli": "--effort", "grok": "--reasoning-effort", "pi": "--thinking"}[backend]
            assert args[args.index(flag) + 1] == "high"
    assert {info["agent"] for _, info in calls} >= expected_calls
    if backend == "grok":
        assert snapshots
        assert any(len(set(shot.values())) == len(shot) and len(shot) >= 2 for shot in snapshots)
        assert max(len(shot) for shot in snapshots) <= 2
        trust = [args for args, _kwargs in calls if "--trust" in args]
        assert trust
        assert len(trust) == len({args[args.index("--cwd") + 1] for args in trust})


@pytest.mark.parametrize("optional", [
    {}, {"month_model": ""},
    {"month_model": {"model": PI_MODEL}},
    {"month_model": {"backend": "api", "model": CODEX_MODEL, "base_url": ""}},
])
def test_optional_channel_falls_back_and_configure_reopens(game_db, monkeypatch, optional):
    calls, _ = install_process(monkeypatch)
    settings = {"backend": "claude-cli", "model": "sonnet", "effort": "medium", **optional}
    (game_db.parent / "settings.json").write_text(json.dumps(settings))
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        if not optional:
            for action in ({"action": "open"}, {"action": "say", "words": "宣王承恩"}, {"action": "dismiss"}):
                client.post("/actions", json=action).raise_for_status()
            client.portal.call(app.state.web.game.drain)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        assert client.get("/state").json()["game"]["date"]["month"] == 11
        assert calls
        for args, _ in calls:
            assert args[0] == "claude"
            assert args[args.index("--model") + 1] == "sonnet"
            assert args[args.index("--effort") + 1] == "medium"
        if not optional:
            calls.clear()
            settings["month_model"] = {"backend": "pi", "model": PI_MODEL, "effort": "high"}
            client.post("/actions", json={"action": "settings", "settings": settings}).raise_for_status()
            client.post("/actions", json={"action": "month"}).raise_for_status()
            state = client.get("/state").json()
            assert state["game"]["failure"] is None
            assert state["game"]["date"]["month"] == 12
            assert calls
            for args, _ in calls:
                assert args[args.index("--thinking") + 1] == "high"


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


def test_codex_forwards_a_ledger_sized_tool_result(tmp_path: Path, monkeypatch, game_db: Path) -> None:
    home = tmp_path / "codex"
    auth_file(home / "auth.json", expired=False)
    monkeypatch.setenv("CODEX_HOME", str(home))
    planted = {"samples": list(range(60_000))}
    outputs: list[dict[str, object]] = []

    install_codex(
        monkeypatch,
        lambda request: codex_response(request, outputs, read_args={"kind": "world", "key": "天下"}),
    )
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        open_game(client, {"backend": "codex", "model": CODEX_MODEL}, game_db)
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
    monkeypatch.setenv("HOME", str(tmp_path))
    install_process(monkeypatch)
    app = create_app(game_db.parent)
    with TestClient(app) as client:
        open_game(client, {"backend": "claude-cli", "model": "sonnet", "effort": "medium",
                           "month_model": {"backend": backend, "model": "unknown-native", "effort": "native-unknown"}}, game_db)
        for action in ({"action": "open"}, {"action": "say", "words": "宣王承恩"}, {"action": "dismiss"}) if mode == "exit" else ():
            client.post("/actions", json=action).raise_for_status()
        client.portal.call(app.state.web.game.drain)
        assert client.get("/state").json()["game"]["failure"] is None
        calls, _ = install_process(monkeypatch, mode=mode)
        client.post("/actions", json={"action": "month"}).raise_for_status()
        state = client.get("/state").json()
    model_calls = [args for args, _ in calls if "--trust" not in args]
    assert model_calls
    for args in model_calls:
        assert args[0] == backend
        assert args[args.index("--model") + 1] == "unknown-native"
        flag = "--reasoning-effort" if backend == "grok" else "--thinking"
        assert args[args.index(flag) + 1] == "native-unknown"
    failure = state["game"]["failure"]
    assert {"type", "message", "log"} <= failure["payload"].keys()
    assert Path(failure["payload"]["log"]).is_file()
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
