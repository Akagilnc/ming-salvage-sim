"""Claude's native MCP and stream-json transport; Pydantic AI owns declarations.

No SDK shutdown, host-session persistence or second validation retry.
Explicit replacement terminates only the superseded native call.
"""

import asyncio
import json
import socket
import sys
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from functools import partial
from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from pydantic_ai import Tool
from pydantic_ai._run_context import get_current_run_context
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel


async def wait_until_started(
    server: uvicorn.Server,
    done: Callable[[], bool],
    sleep: Callable[[float], Awaitable[None]],
    failed: Callable[[], Awaitable[object]],
) -> None:
    while not server.started:
        if done():
            await failed()
            raise RuntimeError("local server exited before startup")
        await sleep(0.01)


class ClaudeCliModel(FunctionModel):
    def __init__(self, name: str = "", tools: Sequence[Tool[Any]] = ()) -> None:
        self.tools = tools
        self.cli_name = name
        super().__init__(
            function=self._request,
            stream_function=self._stream,
            model_name=name or "claude-cli",
        )

    @property
    def system(self) -> str:
        return "claude-cli"

    @asynccontextmanager
    async def _mcp(self) -> AsyncGenerator[dict[str, Any]]:
        if not self.tools:
            yield {"mcpServers": {}}
            return
        mcp = MCPServer("court")
        context = get_current_run_context()
        for tool in self.tools:
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
                await wait_until_started(
                    server, serving.done, asyncio.sleep, lambda: serving
                )
                yield {
                    "mcpServers": {
                        "court": {
                            "type": "http",
                            "url": f"http://127.0.0.1:{listener.getsockname()[1]}/mcp",
                        }
                    }
                }
            finally:
                server.should_exit = True
                await asyncio.shield(serving)

    async def _request(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        text = "".join([part async for part in self._stream(messages, info)])
        return ModelResponse(parts=[TextPart(text)], model_name=self.model_name)

    async def _stream(
        self, messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        async with self._mcp() as config:
            with (
                TemporaryDirectory(prefix="ming-claude-") as directory,
                TemporaryFile() as prompt,
                TemporaryFile() as errors,
            ):
                prompt.write(ModelMessagesTypeAdapter.dump_json(messages, indent=2))
                prompt.seek(0)
                proc = await asyncio.create_subprocess_exec(
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
                    cwd=directory,
                    stdin=prompt,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=errors,
                    # Native JSONL tool results can contain the entire ledger.
                    limit=sys.maxsize,
                )
                assert proc.stdout is not None
                result: dict[str, Any] | None = None
                try:
                    async for line in proc.stdout:
                        message = json.loads(line)
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
                            result = message
                except asyncio.CancelledError:
                    # Only an explicit replacement cancels accepted work, not HTTP disconnects.
                    if proc.returncode is None:
                        proc.terminate()
                    raise
                finally:
                    await asyncio.shield(proc.communicate())
                if proc.returncode or result is None or result.get("is_error"):
                    errors.seek(0)
                    raise RuntimeError(
                        f"claude CLI exited {proc.returncode}\n"
                        f"{errors.read().decode()}\n{json.dumps(result, ensure_ascii=False)}"
                    )
