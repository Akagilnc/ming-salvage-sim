"""One retry owner for declarations. Exhaustion alone becomes an unhandled fact."""

import json
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel
from pydantic_ai import (
    Agent,
    ModelRetry,
    PromptedOutput,
    RunContext,
    capture_run_messages,
)
from pydantic_ai.exceptions import ToolRetryError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model

from ming.ledger import Ledger
from ming.middle.declaration import Declaration, TurnDeclaration
from ming.middle.night import read_night

T = TypeVar("T", bound=Declaration)
INSTRUCTIONS = """你是御前召对的转译官。只声明这一轮，不重落前轮。
旨意当场建：皇帝所下或大臣所请，注明皇帝此刻已允、已驳、未表态；只保留原话，不预先执行后果。
decrees 不是皇帝说过的所有话的清单。只记需要外廷、过月办理的决定或奏请；单纯询问事实不建旨。
殿内即时传宣、入殿和退下全归名单工具，不建旨；即使今夜没能宣来，也不能自行把它改成入京旨意。明确命远人赴京才是需要办理的传召旨意。
对本夜已有旨意的应允或驳回用 assents，引已有旨意 id；未表态的奏请收夜后默认同意，不另补默认事件。
当场已经发生的事实用 facts：哪个实体、是否新建、字段变更列表、一段文字。不分类，不设动作枚举。
待执行旨意不是已经发生的后果；是旨意还是当场实况照戏文判断。
人名、账户、官衔、地区都写账本正名。官职只写官衔，任职地区另写 office_region；人在外地也可以起复或任职，location 不因此改变。
当场起复不核在任与否。新建实体明确 create=true，已有实体用 false。无字段变化可只记文字。
转译不声明进出殿，在场以场景工具维护的名单为准。
segments 的 start/end 只针对 this_turn.scene 原文，0 起算，终点不含；不要把皇帝原话、JSON 外壳或历史算进去。scene_length 给出本轮戏文字数。
按戏文原文字符区间声明说话人分段、可闻性与御前主角，不重写戏文；低语不等于人人可闻，皇帝听者统一用 emperor。
皇帝打字说退朝时声明 dismiss=true。没有的项目交空列表，不凭空增添。
"""


class Unhandled(BaseModel):
    model_text: str
    failure_point: str


def catalogue(ledger: Ledger) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for row in ledger.entities():
        result.setdefault(row["kind"], {})[row["key"]] = row["data"].get("aliases", [])
    return result


def allowed_fields(ledger: Ledger) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {
        "affair": {"text"},
        "decree": {"emperor_words", "origin", "stance"},
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
    if isinstance(out, TurnDeclaration):
        for decree in out.decrees:
            for person in decree.people:
                if person not in names["person"]:
                    fail("decrees.people", person, names["person"])


def check_turn(ledger: Ledger, out: TurnDeclaration, turn: tuple[UUID, str]) -> None:
    night = read_night(ledger, turn[0])
    scene = next(t.scene for t in night.turns if t.id == turn[1])
    decrees = [
        e["key"]
        for e in ledger.entities()
        if e["kind"] == "decree" and e["data"].get("night_id") == str(turn[0])
    ]
    for assent in out.assents:
        if assent.decree_id not in decrees:
            fail("assents.decree_id", assent.decree_id, decrees)
    for segment in out.segments:
        if not 0 <= segment.start <= segment.end <= len(scene):
            fail("segments", segment.model_dump(), {"min": 0, "max": len(scene)})


def build_agent(
    model: Model, ledger: Ledger, output_type: type[T]
) -> Agent[tuple[UUID, str] | None, T]:
    agent = Agent(
        model,
        deps_type=tuple[UUID, str] | None,
        output_type=PromptedOutput(output_type),
        instructions=INSTRUCTIONS,
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
    def validate(ctx: RunContext[tuple[UUID, str] | None], out: T) -> T:
        check(ledger, out)
        if isinstance(out, TurnDeclaration) and ctx.deps is not None:
            check_turn(ledger, out, ctx.deps)
        return out

    return agent


async def translate(
    agent: Agent[tuple[UUID, str] | None, T],
    prompt: str,
    turn: tuple[UUID, str] | None = None,
) -> T | Unhandled:
    with capture_run_messages() as messages:
        try:
            return (
                await agent.run("请按 JSON schema 提交完整声明。\n" + prompt, deps=turn)
            ).output
        except UnexpectedModelBehavior as exhausted:
            if not isinstance(exhausted.__cause__, ToolRetryError):
                raise
            last = [m for m in messages if isinstance(m, ModelResponse)][-1]
            return Unhandled(
                model_text=last.text or "",
                failure_point=exhausted.__cause__.tool_retry.model_response(),
            )
