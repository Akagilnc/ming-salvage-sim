"""The physical hall tool's structured result."""

from typing import Any

from pydantic import BaseModel, Field


class HallResult(BaseModel):
    ok: bool
    hall: list[str]
    failures: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
