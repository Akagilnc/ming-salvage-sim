"""Codex subscription credentials, shared with the Codex CLI's own auth file."""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic_ai.models.openai_codex import OpenAICodexModel
from pydantic_ai.exceptions import UserError
from pydantic_ai.providers.openai_codex import (
    OpenAICodexCredentialSource,
    OpenAICodexCredentials,
    OpenAICodexProvider,
)

_PROVIDERS: dict[tuple[str, int], OpenAICodexProvider] = {}


def auth_path() -> Path:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    return home / "auth.json"


def write_auth(path: Path, data: dict[str, Any]) -> None:
    payload = (json.dumps(data, indent=2) + "\n").encode()
    mode = path.stat().st_mode & 0o777
    temporary = path.with_name(f".{path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, mode)


class CodexAuthFile(OpenAICodexCredentialSource):
    """Read and write the CLI's auth.json so a refresh stays on one chain."""

    def __init__(self, path: Path) -> None:
        self.path = path

    async def load(self) -> OpenAICodexCredentials:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            raise UserError(f"{self.path}: {error}") from error
        return OpenAICodexCredentials.from_codex_cli_auth(data)

    async def save(self, credentials: OpenAICodexCredentials) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            raise UserError(
                f"Malformed Codex CLI credentials at `{self.path}`. Run `codex login` first."
            )
        tokens["access_token"] = credentials.access_token
        tokens["refresh_token"] = credentials.refresh_token
        tokens["account_id"] = credentials.account_id
        data["last_refresh"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        write_auth(self.path, data)


def codex_model(name: str) -> OpenAICodexModel:
    path = auth_path()
    key = (str(path), id(asyncio.get_running_loop()))
    provider = _PROVIDERS.get(key)
    if provider is None:
        provider = OpenAICodexProvider(credential_source=CodexAuthFile(path))
        _PROVIDERS[key] = provider
    return OpenAICodexModel(name, provider=provider)
