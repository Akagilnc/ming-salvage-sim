"""One retry owner for declarations. Exhaustion alone becomes an unhandled fact."""

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import JSON, case, func, type_coerce
from pydantic_ai.models import Model
from pydantic_ai import (
    Agent,
    PromptedOutput,
    RunContext,
    capture_run_messages,
)
from pydantic_ai.exceptions import ToolRetryError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse

from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, Item, Ledger
from ming.middle.fiscal import OUTPUT_METRICS, levers, payable_army, settling
from ming.middle.declaration import (
    Declaration,
    EntityRef,
    Fact,
    NightDeclaration,
    MonthlyFunding,
    PaymentPolicy,
    Unhandled,
)
from ming.middle.queries import CATALOGUE
from ming.middle.opening import REFERENCES
from ming.middle.appointments import ALIASES, APPOINTMENT_ROLES, incumbency_record, office_pairs, reference_key
from ming.middle.rules import Names, check_rules, fail, name_expected
from ming.middle.dispatch import Translation, prepare
from ming.middle.records import TranslationMaterials, read_records
from ming.middle.invoke import invoke
from ming.middle.fields import FIELDS_BY_KIND

APPOINTMENT_RULES = """任免只声明 incumbency：entity 用史书官名（京官如户部右侍郎、南京户部尚书；外官如陕西巡抚、保定府新城县知县），create=false。官职、属地由目录正名或别名精确解析，同名属地须带上级全名。holders、acting 按字段表填写。外官须带属地。首次任职由引擎创建在任记录；人物不存 office、office_region、office_type 等任职字段。
升转新实职即离原任；旨里写明兼领、仍管的才保留旧职。没有兼领、仍管时，在同份声明里从原任 holders 去掉此人；旧职本来无在任记录不必声明。新官替换同官同地原任，不动同官别地。任免不改变人物状态、所在、在场或行程。罢去全部官职时，在同份声明中把罢官原因写进此人的 identity_description 作为处境。
尚书现任只算掌部的一员；阁臣的尚书兼衔只记身份与履历文字，不写入在任记录。内阁首辅为单员职务，须为在任阁臣；同份声明可先任大学士再任首辅。离开全部阁职时同时卸首辅，新首辅只替原首辅这一职、不免其大学士。次辅只记身份。"""

INSTRUCTIONS = """你是御前召对的转译官。退朝后通读整夜已落账的全部轮次，一夜只交一次声明。
decrees 只记成了的旨意，含义见成旨。
text 保留圣旨定稿全文，不改写、不摘要。origin、people、endorsements、interim 按字段说明填写。
旨意按字段声明 secret 与成旨 turn，记背书与 interim；不带交办或拨款载荷，不预先执行待月末办理的后果。
当场已经发生的事实用 facts：哪个实体、是否新建、字段变更列表、一段文字。不分类，不设动作枚举。
只记今夜新发生的实况，不把邸报旧事、档案履历或大臣奏报中的说法当成今夜已经发生的事实。
是待执行旨意还是当场实况，照整夜戏文判断；未认可的拟旨不能当成已经执行的事实。
名字用账本正名或所列别名。
戏文已经宣布任命生效、受命者当场领受的，记在任记录；赴任、查账、造炮等尚待办理，不等于已经生效的任命也要等到月末。尚未获准的任命不提前记。
人在外地也可以当场起复或任职；除首辅须在任阁臣外，不以在任与否限制任命，location 不因此改变。新建实体明确 create=true，已有实体用 false。
无字段变化可以只记文字；对象模型之外的伤情等记入所涉实体履历，不长新字段。
奏报与公开说法单列 reports，只交实体、文字和 audience；facts 只记物理实况。
在场进出归场景名单工具，退朝归场景退朝工具；不声明进出、退朝、说话人分段、可闻性或御前主角。
没有的项目交空列表，不凭空增添。
"""


def catalogue(records: Iterable[Item]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for row in records:
        result.setdefault(row["kind"], {})[row["key"]] = row["aliases"]
    return result


# Content catalogues the month accounts and levy timeline iterate: only the
# imported rows exist, so a declaration may change them but never add one.
CATALOGUES = {"historical_event", "fiscal", "account", "office", "territory", "incumbency"}


def declaration_records(ledger: Ledger, out: Declaration | Unhandled) -> dict[tuple[str, str], Item]:
    if isinstance(out, Unhandled) or not (out.facts or out.reports or out.decree_events or isinstance(out, NightDeclaration) and out.decrees):
        return {}
    appointment_kinds = ("office", "incumbency") if any(f.entity_type == "incumbency" for f in out.facts) else ()
    records = ledger.read(CATALOGUE.with_only_columns(
        E.id, E.kind, E.key, ALIASES, E.data["external"].as_boolean().label("external"),
        type_coerce(case((E.kind.in_(appointment_kinds), func.json_object(
            "multiple", E.data["multiple"].as_boolean(), "department", E.data["department"].as_string(),
            "office", E.data["office"].as_string(), "territory", E.data["territory"].as_string(),
            "holders", E.data["holders"], "acting", E.data["acting"],
        )), else_="{}"), JSON).label("data"),
    ))
    return {(row["kind"], row["key"]): row for row in records}


def check(ledger: Ledger, out: Declaration, records: dict[tuple[str, str], Item], names: Names) -> None:
    fields = FIELDS_BY_KIND
    appointments = {pair: row for pair, row in records.items()
                    if pair[0] in {"office", "territory", "incumbency"}}
    for i, fact in enumerate(out.facts):
        path = f"facts[{i}]"
        if fact.entity_type != "incumbency":
            fact.entity = reference_key(ledger, fact.entity_type, fact.entity, names)
        known = names.setdefault(fact.entity_type, {})
        if fact.entity_type not in fields:
            fail(
                path + ".entity_type",
                fact.entity_type,
                list(fields),
                names,
                "entity_type 改成 expected 里的类型，重交整份。",
            )
        if fact.create and fact.entity_type in CATALOGUES:
            fail(
                path + ".create",
                True,
                {"create": False, **name_expected(fact.entity_type, fact.entity, names)},
                names,
                "这类实体不能新建。create 改 false，参照 expected 的输入目录指针或候选核对 entity，重交整份。",
            )
        if fact.entity_type == "incumbency":
            check_appointment(ledger, fact, path, names, appointments)
        elif (fact.entity in known) == fact.create:
            fail(
                path + ".entity",
                fact.entity,
                {"create": fact.entity not in known, **name_expected(fact.entity_type, fact.entity, names)},
                names,
                "参照 expected 的输入目录指针或候选核对 entity 与 create；确无该实体不得换成另一实体，重交整份。",
            )
        if fact.create or fact.entity_type == "incumbency":
            known[fact.entity] = []
        for j, change in enumerate(fact.changes):
            if change.counterpart:
                change.counterpart.entity = reference_key(ledger, change.counterpart.entity_type, change.counterpart.entity, names)
            if change.field not in fields[fact.entity_type]:
                fail(
                    f"{path}.changes[{j}].field",
                    change.field,
                    sorted(fields[fact.entity_type]),
                    names,
                    "field 改成 expected 里的字段名，重交整份。",
                )
    check_fiscal(ledger, out, names)
    check_references(ledger, out, names)
    check_rules(out, names)


def check_funding(ledger: Ledger, out: Declaration, names: Names) -> dict[str, Item]:
    accounts = {f.entity for f in out.facts if f.entity_type == "account"
                and any(c.field == "payment_order" for c in f.changes)}
    funding = {r["key"]: r["funding"] for r in ledger.entities(kind="affair", query=ENTITY_ROWS.with_only_columns(
        E.key, E.data["monthly_funding"].label("funding"),
    ).where(E.data["monthly_funding"]["account"].as_string().in_(accounts)))} if accounts else {}
    for i, fact in enumerate(out.facts):
        if fact.entity_type != "affair":
            continue
        for j, change in enumerate(fact.changes):
            if change.field != "monthly_funding":
                continue
            account = change.value["account"]
            if account not in names["account"]:
                fail(f"facts[{i}].changes[{j}].value.account", account, name_expected("account", account, names), names, "出款库用账本正名，重交整份。")
            funding[fact.entity] = change.value
    return funding


def check_fiscal(ledger: Ledger, out: Declaration, names: Names) -> None:
    schemas = {"payment_policy": PaymentPolicy, "monthly_funding": MonthlyFunding}
    for i, j, change in (
        (i, j, change) for i, fact in enumerate(out.facts)
        for j, change in enumerate(fact.changes) if change.field in schemas
    ):
        try:
            schemas[change.field].model_validate(change.value)
        except ValidationError:
            fail(f"facts[{i}].changes[{j}].value", change.value, schemas[change.field].model_json_schema(), names,
                 f"按 expected 的 schema 修正 {change.field}，重交整份。")
    fields = {(f.entity_type, c.field) for f in out.facts for c in f.changes}
    config: Sequence[Item] = ledger.entities(kind="fiscal", query=ENTITY_ROWS.with_only_columns(E.key, type_coerce(func.json_object(
        "budget_role", E.data["budget_role"].as_string(),
        "direction", E.data["direction"].as_string(), "account", E.data["account"].as_string(),
    ), JSON).label("data"))) if fields & {("fiscal", "value"), ("fiscal", "payment_policy"), ("account", "payment_order")} else []
    expenses = {
        r["key"]: r["data"]["account"]
        for r in config
        if r["data"].get("direction") == "expense"
    }
    funding = check_funding(ledger, out, names)
    # A fiscal lever only on an entity the month accounts read it from.
    targets = {
        ("fiscal", "value"): levers(config) if ("fiscal", "value") in fields else [],
        ("fiscal", "payment_policy"): list(expenses),
        ("account", "army_order"): ["国库"],
        ("region", "fiscal_surcharge"): [
            r["key"] for r in ledger.entities(kind="region", query=ENTITY_ROWS.with_only_columns(E.key, E.data))
            if settling(r["data"])
        ] if ("region", "fiscal_surcharge") in fields else [],
    }
    armies = [
        r["key"] for r in ledger.entities(kind="army", query=ENTITY_ROWS.with_only_columns(E.key, E.data))
        if payable_army(r["data"])
    ] if ("account", "army_order") in fields else []
    endings: dict[str, list[str]] = {r["key"]: r["labels"] or [] for r in ledger.entities(kind="historical_event", query=ENTITY_ROWS.with_only_columns(
        E.key, E.data["terminal_reason_labels"].label("labels"),
    ).where(E.key.in_([f.entity for f in out.facts if f.entity_type == "historical_event"
                      and any(c.field == "terminal_reason" for c in f.changes)])))} if ("historical_event", "terminal_reason") in fields else {}
    for i, fact in enumerate(out.facts):
        for j, change in enumerate(fact.changes):
            path = f"facts[{i}].changes[{j}]"
            allowed = targets.get((fact.entity_type, change.field))
            if allowed is not None and fact.entity not in allowed:
                fail(
                    f"facts[{i}].entity",
                    fact.entity,
                    allowed,
                    names,
                    "对象改成 expected 里的正名，重交整份。",
                )
            if (fact.entity_type, change.field) == ("building", "output_metric"):
                if change.value not in OUTPUT_METRICS:
                    fail(
                        path + ".value",
                        change.value,
                        OUTPUT_METRICS,
                        names,
                        "output_metric 改成 expected 里的计量，重交整份。",
                    )
            if (fact.entity_type, change.field) == ("historical_event", "terminal_reason"):
                allowed = endings.get(fact.entity, [])
                if change.value not in allowed:
                    fail(
                        path + ".value",
                        change.value,
                        allowed,
                        names,
                        "terminal_reason 改成 expected 里的结局标签，重交整份。",
                    )
            if fact.entity_type == "account" and change.field in {
                "payment_order",
                "army_order",
            }:
                choices = (
                    armies if change.field == "army_order"
                    else [
                        key
                        for key, account in expenses.items()
                        if account == fact.entity
                    ]
                    + (["军饷"] if fact.entity == "国库" else [])
                    + [EntityRef(entity_type="affair", entity=key).model_dump()
                       for key, grant in funding.items() if grant["account"] == fact.entity]
                )
                # A complete order: every choice exactly once.
                value = change.value
                if not (
                    isinstance(value, list)
                    and len(cast(list[Any], value)) == len(choices)
                    and all(cast(list[Any], value).count(choice) == 1 for choice in choices)
                ):
                    fail(
                        path + ".value",
                        change.value,
                        choices,
                        names,
                        "按 expected 的项目引用交完整顺序，每个一次，重交整份。",
                    )


def check_appointment(
    ledger: Ledger, fact: Fact, path: str, names: Names,
    appointments: dict[tuple[str, str], Item],
) -> None:
    pairs, resolution = office_pairs(ledger, fact.entity, records=appointments)
    if resolution["status"] != "resolved":
        fail(path + ".entity", fact.entity, resolution,
             names, "按 expected 核对官名与属地；用 read_records 查询，须带属地时写候选属地全名，重交整份。")
    office = appointments["office", pairs[0][0]]
    fact.entity = incumbency_record(pairs[0], [])[0]
    for j, change in enumerate(fact.changes):
        if change.field not in APPOINTMENT_ROLES:
            continue
        field = f"{path}.changes[{j}].value"
        value: Any = change.value
        if not isinstance(value, list) or not all(isinstance(p, str) for p in cast(list[Any], value)):
            fail(field, change.value, {"type": "array", "items": {"type": "string"}}, names, "holders 写完整人名名单，重交整份。")
        holders = [reference_key(ledger, "person", person, names) for person in cast(list[str], value)]
        change.value = holders
        if not office["data"]["multiple"] and len(holders) > 1:
            fail(field, holders, {"maxItems": 1}, names, "一员只能任一人，重交整份。")
        for k, person in enumerate(holders):
            if person not in names.get("person", {}):
                fail(f"{field}[{k}]", person, name_expected("person", person, names), names, "在任者用 expected 指向的输入人物目录中的正名，重交整份。")


def check_references(ledger: Ledger, out: Declaration, names: Names) -> None:
    people: list[tuple[str, Any]] = []
    for i, fact in enumerate(out.facts):
        for j, change in enumerate(fact.changes):
            kind = REFERENCES.get((fact.entity_type, change.field))
            if kind is not None and (change.field == "location" or change.value != ""):
                change.value = reference_key(ledger, kind, change.value, names) if isinstance(change.value, str) else change.value
                known = isinstance(change.value, str) and (
                    change.value in names.get(kind, {})
                )
                if not known:
                    fail(
                        f"facts[{i}].changes[{j}].value",
                        change.value,
                        name_expected(kind, str(change.value), names),
                        names,
                        "参照 expected 的输入目录指针或候选填写 value，重交整份。确无该实体不得换成另一实体。",
                    )
            if (fact.entity_type, change.field) == ("decree", "people"):
                people.append((f"facts[{i}].changes[{j}].value", change.value))
    for i, report in enumerate(out.reports):
        report.entity = reference_key(ledger, report.entity_type, report.entity, names)
        if report.entity not in names.get(report.entity_type, {}):
            fail(
                f"reports[{i}].entity",
                report.entity,
                name_expected(report.entity_type, report.entity, names),
                names,
                "参照 expected 的输入目录指针或候选填写 entity，重交整份。确无该实体不得换成另一实体。",
            )
    if isinstance(out, NightDeclaration):
        people.extend((f"decrees[{i}].people", decree.people) for i, decree in enumerate(out.decrees))
    for path, value in people:
        if not isinstance(value, list):
            fail(
                path,
                value,
                name_expected("person", "", names),
                names,
                "people 改成名单，成员用 expected 指向的输入人物目录中的正名，重交整份。",
            )
        members = cast(list[Any], value)
        for i, person in enumerate(members):
            members[i] = person = reference_key(ledger, "person", person, names) if isinstance(person, str) else person
            if not isinstance(person, str) or person not in names.get("person", {}):
                fail(f"{path}[{i}]", person, name_expected("person", str(person), names), names,
                     "people 里的名字用 expected 指向的输入人物目录中的正名，重交整份。确无此人不得换成另一人。")


def declaration_agent(
    output_type: type[Declaration],
    instructions: str,
) -> Agent[TranslationMaterials, Translation]:
    def accept(ctx: RunContext[TranslationMaterials], out: Declaration):
        ledger = ctx.deps.ledger
        records = declaration_records(ledger, out)
        names = catalogue(records.values())
        check(ledger, out, records, names)
        return prepare(ledger, out, ledger.get(ctx.deps.source), records, names)

    # The same output function accepts this call's specific declaration schema.
    accept.__annotations__["out"] = output_type

    agent = Agent(
        tools=[read_records],
        name=output_type.__name__,
        deps_type=TranslationMaterials,
        output_type=PromptedOutput(accept),
        instructions=instructions + "\n" + APPOINTMENT_RULES + "\n官职和属地不混在实况名册里；需要核对官名、地名、别名、所属衙门或员额时，用 read_records 带类 office、territory 或正名查询；空参不返回目录。",
        retries=1,
    )

    @agent.instructions
    async def names(ctx: RunContext[TranslationMaterials]) -> str:
        # Queries and JSON encoding stay on the caller's loop, like tools;
        # only model I/O yields.
        return json.dumps(
            {
                "catalogue": ctx.deps.court.record_catalogue(ctx.deps.identity),
                "field_schemas": {"payment_policy": PaymentPolicy.model_json_schema(), "monthly_funding": MonthlyFunding.model_json_schema()},
                "allowed_fields": {
                    kind: {field: asdict(rule) for field, rule in rules.items()}
                    for kind, rules in FIELDS_BY_KIND.items()
                },
            },
            ensure_ascii=False,
        )

    return agent


async def translate(
    agent: Agent[TranslationMaterials, Translation],
    prompt: str,
    materials: TranslationMaterials,
    model: Model,
) -> Translation | Unhandled:
    with capture_run_messages() as messages:
        try:
            return (
                await invoke(
                    agent, "请按 JSON schema 提交完整声明。\n" + prompt,
                    deps=materials, model=model,
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
