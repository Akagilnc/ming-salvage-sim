"""转译：皇帝一句话 → 声明；重试只在这一层，用尽在这里接住成「接不住」。"""

import json

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, PromptedOutput, capture_run_messages
from pydantic_ai.exceptions import ToolRetryError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from ming.ledger import Ledger
from ming.middle.declaration import Declaration

INSTRUCTIONS = (
    "你是明朝皇帝的转译官。把皇帝说的这句话转成声明：皇帝把事交给某些人办是交办，"
    "拨银子是拨款。一句话里有几道交办、几笔拨款，就各声明几项；都没有则两个列表皆空。"
    "承办人、收款人写账本正名，不写衙门；这句话里指代的人，照上文写出姓名。"
    "按皇帝当前这一句划分交办，两人共同办理同一件事时只写一项，把两人同列承办人；"
    "不要把上文里的建议当作本句的交办。拨款必须写出钱的账户。"
)


class Unhandled(BaseModel):
    """转译重试用尽：模型最后一次的原文，与最后一次不合格的失败点。"""

    model_text: str
    failure_point: str


def catalogue(ledger: Ledger) -> dict[str, dict[str, list[str]]]:
    return {
        kind: {
            e["key"]: e["data"].get("aliases", [])
            for e in ledger.entities()
            if e["kind"] == kind
        }
        for kind in ("person", "account")
    }


def build_agent(model: Model, ledger: Ledger) -> Agent[None, Declaration]:
    agent = Agent(
        model,
        output_type=PromptedOutput(Declaration),
        instructions=INSTRUCTIONS,
        retries=1,
    )

    @agent.instructions
    def names() -> str:
        return "账本正名与别名（别名只供核对，声明必须用正名）：" + json.dumps(
            catalogue(ledger), ensure_ascii=False
        )

    @agent.output_validator
    def check(out: Declaration) -> Declaration:
        known = catalogue(ledger)
        references = [
            (f"assigns[{i}].assignees[{j}]", "person", name)
            for i, assign in enumerate(out.assigns)
            for j, name in enumerate(assign.assignees)
        ]
        references.extend(
            (f"grants[{i}].{field}", kind, getattr(grant, field))
            for i, grant in enumerate(out.grants)
            for field, kind in (("account", "account"), ("recipient", "person"))
        )
        for field, kind, value in references:
            if value not in known[kind]:
                raise ModelRetry(
                    json.dumps(
                        {
                            "field": field,
                            "current": value,
                            "expected": known[kind],
                            "action": "按账本正名改正后重交整份；确无此人或账户则原样重交，不得换成另一人。",
                        },
                        ensure_ascii=False,
                    )
                )
        return out

    return agent


def translate(
    agent: Agent[None, Declaration], emperor_words: str, scene: str
) -> Declaration | Unhandled:
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
