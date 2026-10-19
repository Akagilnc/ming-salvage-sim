"""声明：转译模型把皇帝一句话说成的结构。只定义声明，不含皇帝原话。

一句话可以含多道交办、多笔拨款：两个列表各装各的，都空即这句话既非交办也非拨款。
"""

from pydantic import BaseModel, Field


class Assign(BaseModel):
    """交办：皇帝把一件事交给某些人。"""

    assignees: list[str] = Field(description="承办人的姓名列表，一人一项")
    task: str = Field(description="所交办的事")


class Grant(BaseModel):
    """拨款：皇帝拨一笔银子。"""

    account: str = Field(description="出钱账户的账本正名，如国库或内库；不得省略")
    recipient: str = Field(description="收款人账本正名，不是经办衙门")
    amount_taels: int = Field(description="两数，整数，照皇帝说的数")
    purpose: str = Field(description="用途")


class Declaration(BaseModel):
    """这句话里的全部声明。"""

    assigns: list[Assign] = Field(description="这句话里的每一道交办，一道一项")
    grants: list[Grant] = Field(description="这句话里的每一笔拨款，一笔一项")
