"""Claude's native MCP and stream-json transport; Pydantic AI owns declarations.

No SDK shutdown, signals, host-session persistence or second validation retry.
"""

import asyncio
import json
import socket
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel


class ClaudeCliModel(FunctionModel):
    def __init__(
        self, name: str = "haiku", tools: Sequence[Callable[..., Any]] = ()
    ) -> None:
        self.tools = tools
        super().__init__(
            function=self._request, stream_function=self._stream, model_name=name
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
        for tool in self.tools:
            mcp.add_tool(tool)
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
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError("MCP server exited before startup")
                    await asyncio.sleep(0.01)
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
                    "--model",
                    self.model_name,
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
                            *[f"mcp__court__{tool.__name__}" for tool in self.tools],
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
                finally:
                    # Even on a reader/consumer error, drain pipes and wait naturally.
                    # Browser disconnects never cancel this accepted scene action.
                    await asyncio.shield(proc.communicate())
                if proc.returncode or result is None or result.get("is_error"):
                    errors.seek(0)
                    raise RuntimeError(
                        f"claude CLI exited {proc.returncode}\n"
                        f"{errors.read().decode()}\n{json.dumps(result, ensure_ascii=False)}"
                    )
