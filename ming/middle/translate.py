"""One retry owner for declarations. Exhaustion alone becomes an unhandled fact."""

import json
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import (
    Agent,
    ModelRetry,
    PromptedOutput,
    capture_run_messages,
)
from pydantic_ai.exceptions import ToolRetryError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from ming.ledger import Ledger
from ming.middle.declaration import Declaration, NightDeclaration
from ming.middle.rules import check_rules
from ming.middle.invoke import invoke, transport_model

T = TypeVar("T", bound=Declaration)
INSTRUCTIONS = """你是御前召对的转译官。退朝后通读整夜已落账的全部轮次，一夜只交一次声明。
decrees 只记成了的旨意：领旨的人已经把皇帝的话拟成正式圣旨念出，皇帝认可了那份定稿。
认可按意思认，不限于“准”字；皇帝没表态的就是默拒，驳了的也不成旨。不要把问话、大臣请示或未认可的拟稿记成旨。
text 保留皇帝认可的圣旨定稿全文，不改写、不摘要。origin 记原本是皇帝所下还是大臣所请，people 按字段说明填写。
旨意只记定稿、来历与涉及的人，不带交办或拨款载荷，不预先执行待月末办理的后果。
当场已经发生的事实用 facts：哪个实体、是否新建、字段变更列表、一段文字。不分类，不设动作枚举。
只记今夜新发生的实况，不把邸报旧事、档案履历或大臣奏报中的说法当成今夜已经发生的事实。
是待执行旨意还是当场实况，照整夜戏文判断；未认可的拟旨不能当成已经执行的事实。
人名、账户、官衔、地区都写账本正名。官职只写官衔，任职地区另写 office_region。
人在外地也可以当场起复或任职，不核在任与否，location 不因此改变。新建实体明确 create=true，已有实体用 false。
无字段变化可以只记文字；对象模型之外的伤情等记入所涉实体履历，不长新字段。
在场进出归场景名单工具，退朝归场景退朝工具；不声明进出、退朝、说话人分段、可闻性或御前主角。
没有的项目交空列表，不凭空增添。
"""


class Unhandled(BaseModel):
    model_text: str
    failure_point: str


def catalogue(ledger: Ledger) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for row in ledger.entities():
        aliases = row["data"].get("aliases", [])
        name = row["data"].get("name")
        if name and name != row["key"]:
            aliases = [*aliases, name]
        result.setdefault(row["kind"], {})[row["key"]] = aliases
    return result


def allowed_fields(ledger: Ledger) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {
        "affair": {"text", "closed", "petition"},
        "decree": {"text", "origin", "people", "petition"},
    }
    for row in ledger.entities():
        if row["source"]:
            fields.setdefault(row["kind"], set()).update(row["data"])
    return fields


def fail(field: str, value: object, expected: object) -> None:
    raise ModelRetry(
        json.dumps(
            {
                "field": field,
                "current": value,
                "expected": expected,
                "action": "按 expected 修正此字段并重交整份；名字必须用账本正名，确无该实体不得换成另一实体。",
            },
            ensure_ascii=False,
        )
    )


def check(ledger: Ledger, out: Declaration) -> None:
    names, fields = catalogue(ledger), allowed_fields(ledger)
    for i, fact in enumerate(out.facts):
        path = f"facts[{i}]"
        known = names.setdefault(fact.entity_type, {})
        if fact.entity_type not in fields:
            fail(path + ".entity_type", fact.entity_type, list(fields))
        if (fact.entity in known) == fact.create:
            fail(
                path + ".entity",
                fact.entity,
                {"names_and_aliases": known, "create": fact.entity not in known},
            )
        if fact.create:
            known[fact.entity] = []
        for j, change in enumerate(fact.changes):
            if change.field not in fields[fact.entity_type]:
                fail(
                    f"{path}.changes[{j}].field",
                    change.field,
                    sorted(fields[fact.entity_type]),
                )
            if fact.entity_type == "person" and change.field in {
                "office",
                "office_region",
                "location",
            }:
                kind = "office" if change.field == "office" else "region"
                if change.value != "" and (
                    not isinstance(change.value, str)
                    or change.value not in names.get(kind, {})
                ):
                    fail(
                        f"{path}.changes[{j}].value", change.value, names.get(kind, {})
                    )
    check_rules(out)
    if isinstance(out, NightDeclaration):
        for decree in out.decrees:
            for person in decree.people:
                if person not in names["person"]:
                    fail("decrees.people", person, names["person"])


def build_agent(
    model: Model, ledger: Ledger, output_type: type[T], instructions: str = INSTRUCTIONS
) -> Agent[None, T]:
    agent = Agent(
        transport_model(model),
        output_type=PromptedOutput(output_type),
        instructions=instructions,
        retries=1,
    )

    @agent.instructions
    def names() -> str:
        return json.dumps(
            {
                "names_and_aliases": catalogue(ledger),
                "allowed_fields": {
                    k: sorted(v) for k, v in allowed_fields(ledger).items()
                },
            },
            ensure_ascii=False,
        )

    @agent.output_validator
    def validate(out: T) -> T:
        check(ledger, out)
        return out

    return agent


async def translate(
    agent: Agent[None, T],
    prompt: str,
    background: bool = False,
) -> T | Unhandled:
    with capture_run_messages() as messages:
        try:
            return (
                await invoke(
                    agent, "请按 JSON schema 提交完整声明。\n" + prompt, background
                )
            ).output
        except UnexpectedModelBehavior as exhausted:
            if not isinstance(exhausted.__cause__, ToolRetryError):
                raise
            last = [m for m in messages if isinstance(m, ModelResponse)][-1]
            return Unhandled(
                model_text=last.text or "",
                failure_point=exhausted.__cause__.tool_retry.model_response(),
            )
