"""命令行宿主（claude -p）的 pydantic-ai Model 适配。

不传 --json-schema：宿主不自带 schema 重试，重试只有 pydantic-ai 这一层。
"""

import asyncio

from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    TextPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings


class ClaudeCliModel(Model):
    @property
    def model_name(self) -> str:
        return "haiku"

    @property
    def system(self) -> str:
        return "claude-cli"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        model_settings, model_request_parameters = self.prepare_request(
            model_settings, model_request_parameters
        )
        parts = self._get_instruction_parts(messages, model_request_parameters) or []
        system_prompt = "\n\n".join(part.content for part in parts)
        prompt = ModelMessagesTypeAdapter.dump_json(messages, indent=2).decode()
        proc = await asyncio.create_subprocess_exec(
            *(
                "claude",
                "-p",
                "--model",
                self.model_name,
                "--tools",
                "",
                "--no-session-persistence",
            ),
            *("--setting-sources", "", "--system-prompt", system_prompt, prompt),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}\n{stderr.decode()}\n{stdout.decode()}"
            )
        return ModelResponse(
            parts=[TextPart(stdout.decode())], model_name=self.model_name
        )
