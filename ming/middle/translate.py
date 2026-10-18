"""转译：皇帝一句话 → 声明；重试只在这一层，用尽在这里接住成「接不住」。"""

from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import Agent, PromptedOutput, capture_run_messages
from pydantic_ai.exceptions import ToolRetryError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from ming.middle.declaration import Assign, Grant, NoOrder

Declaration = Annotated[Assign | Grant | NoOrder, Field(discriminator="kind")]

INSTRUCTIONS = (
    "你是明朝皇帝的转译官。把皇帝说的这句话转成声明：皇帝把事交给某些人办是交办，"
    "拨银子是拨款，二者都不是则为 none。承办人、收款人写姓名，不写衙门；"
    "这句话里指代的人，照上文写出姓名。"
)


class Unhandled(BaseModel):
    """转译重试用尽：模型最后一次的原文，与最后一次不合格的失败点。"""

    model_text: str
    failure_point: str


def build_agent(model: Model) -> Agent[None, Declaration]:
    return Agent(model, output_type=PromptedOutput(Declaration), instructions=INSTRUCTIONS, retries=1)


def translate(agent: Agent[None, Declaration], emperor_words: str, scene: str) -> Declaration | Unhandled:
    prompt = f"{scene}\n\n皇帝这一句：{emperor_words}" if scene else emperor_words
    with capture_run_messages() as messages:
        try:
            return agent.run_sync(prompt).output
        except UnexpectedModelBehavior as exhausted:
            if not isinstance(exhausted.__cause__, ToolRetryError):
                raise
            last = [m for m in messages if isinstance(m, ModelResponse)][-1]
            return Unhandled(
                model_text=last.text or "",
                failure_point=exhausted.__cause__.tool_retry.model_response(),
            )
