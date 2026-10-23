"""Subscription hosts that serve game tools and stream text back.

Claude, Grok and Pi each use their own switches. Codex is not a process host.
No SDK shutdown and no second validation retry. Explicit replacement terminates
only the superseded native call.
"""

import asyncio
import json
import os
import socket
import sys
import tomllib
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Sequence
from typing import Any, Protocol, cast
from concurrent.futures import Future
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile

import uvicorn
from mcp.server.mcpserver import MCPServer
from pydantic_ai import RunContext, Tool
from pydantic_ai._instrumentation import get_instructions
from pydantic_ai._run_context import get_current_run_context
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    ModelResponseStreamEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.models import ModelRequestParameters, StreamedResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings

GROK_SLOT_COUNT = 16
GROK_MAX_OUTPUT = 256 * 1024 * 1024
# Compat scans are the CLI's own switches. User MCP under ~/.grok has no
# switch that does not rewrite that file, so it stays; the trust list is the
# one authorized write, and only for a directory that is not already trusted.
GROK_OFF = (
    "GROK_CLAUDE_MCPS_ENABLED",
    "GROK_CLAUDE_SKILLS_ENABLED",
    "GROK_CLAUDE_AGENTS_ENABLED",
    "GROK_CLAUDE_HOOKS_ENABLED",
    "GROK_CLAUDE_RULES_ENABLED",
    "GROK_CURSOR_MCPS_ENABLED",
    "GROK_CURSOR_SKILLS_ENABLED",
    "GROK_CURSOR_AGENTS_ENABLED",
    "GROK_CURSOR_HOOKS_ENABLED",
    "GROK_CURSOR_RULES_ENABLED",
)
_SLOT_POOLS: dict[tuple[str, int, int], "SlotPool"] = {}


class HostEvents[T](Protocol):
    def observe(self, message: dict[str, Any]) -> Iterator[T]: ...

    def failure(self, code: int | None, stderr: str) -> str | None: ...


async def wait_until_started(
    server: uvicorn.Server,
    serving: asyncio.Future[Any] | Future[Any],
) -> None:
    while not server.started:
        if serving.done():
            serving.result()
            raise RuntimeError("local server exited before startup")
        await asyncio.sleep(0.01)


def as_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return None


@asynccontextmanager
async def court_server(
    tools: Sequence[Tool[Any]],
) -> AsyncGenerator[str | None]:
    if not tools:
        yield None
        return
    mcp = MCPServer("court")
    context = get_current_run_context()
    for tool in tools:
        function = tool.function
        if tool.takes_ctx:
            function = partial(function, context)
            setattr(function, "__name__", tool.name)
        mcp.add_tool(function, name=tool.name, description=tool.description)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(
            uvicorn.Config(
                mcp.streamable_http_app(),
                log_config=None,
                access_log=False,
            )
        )
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            await wait_until_started(server, serving)
            yield f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
        finally:
            server.should_exit = True
            await asyncio.shield(serving)


def prompt_bytes(messages: list[ModelMessage]) -> bytes:
    return ModelMessagesTypeAdapter.dump_json(messages, indent=2)


async def stream_process[T](
    argv: list[str],
    *,
    cwd: str,
    prompt: Any,
    events: HostEvents[T],
    env: dict[str, str] | None = None,
) -> AsyncGenerator[T]:
    with TemporaryFile() as errors:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdin=prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=errors,
            env=env,
            limit=sys.maxsize,
        )
        assert proc.stdout is not None
        message: dict[str, Any] | None = None
        try:
            async for line in proc.stdout:
                message = cast(dict[str, Any], json.loads(line))
                for text in events.observe(message):
                    yield text
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.terminate()
            raise
        finally:
            await asyncio.shield(proc.communicate())
        errors.seek(0)
        failure = events.failure(proc.returncode, errors.read().decode())
    if failure is not None:
        raise RuntimeError(f"{failure}\n{json.dumps(message, ensure_ascii=False)}")


class ClaudeEvents:
    def __init__(self) -> None:
        self.result: dict[str, Any] | None = None

    def observe(self, message: dict[str, Any]) -> Iterator[str]:
        if message["type"] == "stream_event":
            event = message["event"]
            if event["type"] == "content_block_start":
                block = event["content_block"]
                if block["type"] == "text" and block["text"]:
                    yield block["text"]
            elif event["type"] == "content_block_delta":
                delta = event["delta"]
                if delta["type"] == "text_delta":
                    yield delta["text"]
        elif message["type"] == "result":
            self.result = message

    def failure(self, code: int | None, stderr: str) -> str | None:
        result = self.result
        if code or result is None or result.get("is_error"):
            return (
                f"claude CLI exited {code}\n{stderr}\n"
                f"{json.dumps(result, ensure_ascii=False)}"
            )
        return None


class GrokEvents:
    def __init__(self) -> None:
        self.terminal: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None

    def observe(self, message: dict[str, Any]) -> Iterator[str]:
        kind = message.get("type")
        data = message.get("data")
        if kind == "text" and isinstance(data, str) and data:
            yield data
        elif kind == "error":
            self.error = message
            self.terminal = message
        elif kind == "end":
            self.terminal = message

    def failure(self, code: int | None, stderr: str) -> str | None:
        if code or self.error is not None or self.terminal is None:
            return (
                f"grok exited {code}\n{stderr}\n"
                f"{json.dumps(self.error or self.terminal, ensure_ascii=False)}"
            )
        return None


def pi_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in cast(list[object], content):
        body = as_dict(item)
        text = body.get("text") if body is not None and body.get("type") == "text" else None
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts)


class PiEvents:
    def __init__(self) -> None:
        self.error: dict[str, Any] | None = None
        self.settled = False
        self.completed = TextPart("")

    def observe(self, message: dict[str, Any]) -> Iterator[str | TextPart]:
        kind = message.get("type")
        if kind == "message_update":
            event = as_dict(message.get("assistantMessageEvent"))
            if event is not None and event.get("type") == "text_delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    yield delta
            return
        body = as_dict(message.get("message"))
        if kind == "auto_retry_start" or (
            kind == "message_start" and body is not None and body.get("role") == "assistant"
        ):
            yield self.completed
        if (
            kind == "message_end"
            and body is not None
            and body.get("role") == "assistant"
        ):
            self.error = message if body.get("stopReason") in {"error", "aborted"} else None
            part = TextPartDelta(pi_text(body.get("content"))).apply(self.completed)
            if self.error is None:
                self.completed = part
            yield part
        if kind == "auto_retry_end":
            self.error = None if message.get("success") else message
        if kind == "agent_settled":
            self.settled = True
            if message.get("aborted"):
                self.error = message

    def failure(self, code: int | None, stderr: str) -> str | None:
        if code or self.error is not None or not self.settled:
            return (
                f"pi exited {code}\n{stderr}\n"
                f"{json.dumps(self.error, ensure_ascii=False)}"
            )
        return None


def grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME") or Path.home() / ".grok")


def slot_trusted(slot: Path) -> bool:
    store = grok_home() / "trusted_folders.toml"
    if not store.is_file():
        return False
    folders = as_dict(tomllib.loads(store.read_text(encoding="utf-8")).get("folders"))
    if folders is None:
        return False
    target = slot.resolve()
    for key, value in folders.items():
        body = as_dict(value)
        if body is None:
            continue
        try:
            same = Path(key).resolve() == target
        except OSError:
            same = False
        if same and body.get("trusted") is True:
            return True
    return False


async def trust_slot(slot: Path) -> None:
    if slot_trusted(slot):
        return
    proc = await asyncio.create_subprocess_exec(
        "grok",
        "--trust",
        "--cwd",
        str(slot.resolve()),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if not slot_trusted(slot):
        raise RuntimeError(stderr.decode() or f"grok --trust exited {proc.returncode}")


def grok_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in GROK_OFF:
        env[key] = "0"
    env["GROK_MAX_MCP_OUTPUT_BYTES"] = str(GROK_MAX_OUTPUT)
    return env


def write_grok_config(slot: Path, url: str | None) -> None:
    path = slot / ".grok" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"[mcp]\nmax_output_bytes = {GROK_MAX_OUTPUT}\n"
    if url is not None:
        body += (
            "\n[mcp_servers.court]\n"
            f"url = {json.dumps(url)}\n"
            "enabled = true\n"
        )
    path.write_text(body, encoding="utf-8")


def write_pi_mcp(directory: Path, url: str) -> None:
    path = directory / ".pi" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"mcpServers": {"court": {"url": url, "exposure": "direct"}}}
        ),
        encoding="utf-8",
    )


class SlotPool:
    def __init__(self, root: Path, count: int) -> None:
        self.root = root
        self.count = count
        self._queue: asyncio.Queue[Path] | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> Path:
        await self._ensure()
        assert self._queue is not None
        return await self._queue.get()

    async def _ensure(self) -> None:
        async with self._lock:
            if self._queue is not None:
                return
            paths = [self.root / str(index) for index in range(self.count)]
            for path in paths:
                path.mkdir(parents=True, exist_ok=True)
            for path in paths:
                await trust_slot(path)
            queue: asyncio.Queue[Path] = asyncio.Queue()
            for path in paths:
                queue.put_nowait(path)
            self._queue = queue

    def release(self, slot: Path) -> None:
        if self._queue is not None:
            self._queue.put_nowait(slot)


def slots() -> SlotPool:
    root = Path(os.environ.get("MING_GROK_SLOTS") or Path.home() / ".ming" / "grok-slots")
    key = (str(root), id(asyncio.get_running_loop()), GROK_SLOT_COUNT)
    pool = _SLOT_POOLS.get(key)
    if pool is None:
        pool = SlotPool(root, GROK_SLOT_COUNT)
        _SLOT_POOLS[key] = pool
    return pool


class CliHost(FunctionModel):
    host = "cli"

    def __init__(self, name: str = "", tools: Sequence[Tool[Any]] = ()) -> None:
        self.tools = tools
        self.cli_name = name
        super().__init__(
            function=self._request,
            stream_function=self._stream,
            model_name=name or self.host,
        )

    @property
    def system(self) -> str:
        return self.host

    async def _request(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        text = "".join([part async for part in self._stream(messages, info)])
        return ModelResponse(parts=[TextPart(text)], model_name=self.model_name)

    async def _stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""


class ClaudeCliModel(CliHost):
    host = "claude-cli"

    def argv(self, config: dict[str, Any], info: AgentInfo) -> list[str]:
        return [
            "claude",
            "-p",
            *(["--model", self.cli_name] if self.cli_name else []),
            "--tools",
            "",
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            json.dumps(config),
            *(
                [
                    "--allowedTools",
                    *[f"mcp__court__{tool.name}" for tool in self.tools],
                ]
                if self.tools
                else []
            ),
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--disable-slash-commands",
            "--system-prompt",
            info.instructions or "",
        ]

    async def _stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        async with court_server(self.tools) as url:
            config: dict[str, Any] = {"mcpServers": {}}
            if url is not None:
                config = {"mcpServers": {"court": {"type": "http", "url": url}}}
            with (
                TemporaryDirectory(prefix="ming-claude-") as directory,
                TemporaryFile() as prompt,
            ):
                prompt.write(prompt_bytes(messages))
                prompt.seek(0)
                async for text in stream_process(
                    self.argv(config, info),
                    cwd=directory,
                    prompt=prompt,
                    events=ClaudeEvents(),
                ):
                    yield text


class GrokCliModel(CliHost):
    host = "grok"

    def argv(self, slot: Path, prompt_path: Path, info: AgentInfo) -> list[str]:
        argv = [
            "grok",
            "--cwd",
            str(slot),
            "--prompt-file",
            str(prompt_path),
            "--output-format",
            "streaming-json",
            "--always-approve",
            "--system-prompt-override",
            info.instructions or "",
            "--tools",
            "search_tool,use_tool",
            "--no-subagents",
            "--disable-web-search",
        ]
        if self.cli_name:
            argv.extend(["--model", self.cli_name])
        return argv

    async def _stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        pool = slots()
        slot = await pool.acquire()
        prompt_path = slot / "prompt.json"
        try:
            async with court_server(self.tools) as url:
                write_grok_config(slot, url)
                prompt_path.write_bytes(prompt_bytes(messages))
                with prompt_path.open("rb") as prompt:
                    async for text in stream_process(
                        self.argv(slot, prompt_path, info),
                        cwd=str(slot),
                        prompt=prompt,
                        events=GrokEvents(),
                        env=grok_env(),
                    ):
                        yield text
        finally:
            prompt_path.unlink(missing_ok=True)
            pool.release(slot)


@dataclass
class PiStreamedResponse(StreamedResponse):
    _model_name: str
    _iter: AsyncIterator[str | TextPart]
    _timestamp: datetime = field(default_factory=partial(datetime.now, UTC))

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        produced = False
        async for item in self._iter:
            produced = True
            if isinstance(item, TextPart):
                yield self._parts_manager.handle_part(vendor_part_id="content", part=item)
            else:
                for event in self._parts_manager.handle_text_delta(
                    vendor_part_id="content", content=item
                ):
                    yield event
        if not produced:
            yield self._parts_manager.handle_part(
                vendor_part_id="content", part=TextPart("")
            )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def provider_name(self) -> None:
        return None

    @property
    def provider_url(self) -> None:
        return None

    @property
    def timestamp(self) -> datetime:
        return self._timestamp


class PiCliModel(CliHost):
    host = "pi"

    def argv(self, instructions: str, tools: bool) -> list[str]:
        argv = [
            "pi",
            "--mode",
            "json",
            "-p",
            "--no-session",
            "--approve",
            "--no-skills",
            "--no-prompt-templates",
            "--no-context-files",
            "--no-builtin-tools",
            "--no-extensions",
            "--system-prompt",
            instructions,
        ]
        if tools:
            argv.extend(
                ["-e", "builtin:mcp", "--tools", "mcp__court__*"]
            )
        else:
            argv.append("--no-mcp")
        if self.cli_name:
            argv.extend(["--model", self.cli_name])
        return argv

    async def _stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        """Use the same final response for non-streaming FunctionModel requests."""
        async with self.request_stream(
            messages, info.model_settings, info.model_request_parameters
        ) as response:
            async for _ in response:
                pass
            for part in response.get().parts:
                if isinstance(part, TextPart):
                    yield part.content

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[Any] | None = None,
    ) -> AsyncGenerator[StreamedResponse]:
        _, parameters = self.prepare_request(model_settings, model_request_parameters)
        async with court_server(self.tools) as url:
            with (
                TemporaryDirectory(prefix="ming-pi-") as directory,
                TemporaryFile() as prompt,
            ):
                if url is not None:
                    write_pi_mcp(Path(directory), url)
                prompt.write(prompt_bytes(messages))
                prompt.seek(0)
                async with aclosing(
                    stream_process(
                        self.argv(
                            get_instructions(messages, parameters) or "", url is not None
                        ),
                        cwd=directory,
                        prompt=prompt,
                        events=PiEvents(),
                    )
                ) as parts:
                    yield PiStreamedResponse(parameters, self.model_name, parts)
