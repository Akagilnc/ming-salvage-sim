"""Shared immutable read models; JSON serialization remains an outward copy."""

from typing import Annotated

from frozendict import deepfreeze
from pydantic import AfterValidator, BaseModel, ConfigDict

type ReadData[T] = Annotated[dict[str, T], AfterValidator(deepfreeze)]


class ReadView(BaseModel):
    model_config = ConfigDict(frozen=True)
