"""声明：转译模型把皇帝一句话说成的结构。只定义声明，不含皇帝原话。"""

from typing import Literal

from pydantic import BaseModel, Field


class Assign(BaseModel):
    """交办：皇帝把一件事交给某些人。"""

    kind: Literal["assign"]
    assignees: list[str] = Field(description="承办人的姓名列表，一人一项")
    task: str = Field(description="所交办的事")


class Grant(BaseModel):
    """拨款：皇帝拨一笔银子。"""

    kind: Literal["grant"]
    recipient: str = Field(description="收款人姓名，不是经办衙门")
    amount_taels: int = Field(description="两数，整数，照皇帝说的数")
    purpose: str = Field(description="用途")


class NoOrder(BaseModel):
    """这句话既不是交办，也不是拨款。"""

    kind: Literal["none"]
