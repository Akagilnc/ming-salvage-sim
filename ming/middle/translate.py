"""One retry owner for declarations. Exhaustion alone becomes an unhandled fact."""

import json
from typing import Any, TypeVar, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select, true
from pydantic_ai import (
    Agent,
    PromptedOutput,
    RunContext,
    Tool,
    capture_run_messages,
)
from pydantic_ai.exceptions import ToolRetryError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse

from ming.ledger import ENTITY_COLUMNS as E, ENTITY_ROWS, Item, Ledger
from ming.middle.fiscal import OUTPUT_METRICS, levers, payable_army, settling
from ming.middle.declaration import (
    Declaration,
    DecreeEvent,
    Fact,
    NightDeclaration,
    PaymentPolicy,
    Unhandled,
)
from ming.middle.queries import CATALOGUE
from ming.middle.night import read_night
from ming.middle.opening import REFERENCES
from ming.middle.appointments import CATALOGUE_KINDS, incumbency_record, office_pairs, reference_key
from ming.middle.rules import Names, check_rules, fail
from ming.middle.invoke import ModelSource, build_agent, invoke

T = TypeVar("T", bound=Declaration)
INSTRUCTIONS = """你是御前召对的转译官。退朝后通读整夜已落账的全部轮次，一夜只交一次声明。
decrees 只记成了的旨意：领旨的人已经把皇帝的话拟成正式圣旨念出，皇帝认可了那份定稿。
认可按意思认，不限于“准”字；皇帝没表态的就是默拒，驳了的也不成旨。认可须对应当时已经拟就的具体旨稿，不预认本轮回话后续新增的拟稿，也不追认更早搁置的请示。不要把问话、大臣请示或未认可的拟稿记成旨。
text 保留皇帝认可的圣旨定稿全文，不改写、不摘要。origin 记原本是皇帝所下还是大臣所请，people、endorsements、interim 按字段说明填写。
旨意按字段声明 secret 与成旨 turn，记背书与中旨标记：中旨是明发、经外廷议处，密令不明发、不经外廷；不带交办或拨款载荷，不预先执行待月末办理的后果。
当场已经发生的事实用 facts：哪个实体、是否新建、字段变更列表、一段文字。不分类，不设动作枚举。
只记今夜新发生的实况，不把邸报旧事、档案履历或大臣奏报中的说法当成今夜已经发生的事实。
是待执行旨意还是当场实况，照整夜戏文判断；未认可的拟旨不能当成已经执行的事实。
名字用账本正名或所列别名。任免写 entity_type=incumbency，entity 写史书官名（如户部右侍郎、南京户部尚书、陕西巡抚、西安知府），create=false。changes 的 holders 写变更后完整人名名单；一员最多一人，空名单为免职。首次任职由引擎创建在任记录；人物不存任职字段。一人可兼多职，任免不改变状态、所在、在场或行程。尚书现任只算掌部的一员；阁臣的尚书兼衔只记身份与履历文字，不写入在任记录。
戏文已经宣布任命生效、受命者当场领受的，记在任记录；赴任、查账、造炮等尚待办理，不等于已经生效的任命也要等到月末。尚未获准的任命不提前记。
人在外地也可以当场起复或任职，不核在任与否，location 不因此改变。新建实体明确 create=true，已有实体用 false。
无字段变化可以只记文字；对象模型之外的伤情等记入所涉实体履历，不长新字段。
奏报与公开说法单列 reports，只交实体、文字和 audience；facts 只记物理实况。
在场进出归场景名单工具，退朝归场景退朝工具；不声明进出、退朝、说话人分段、可闻性或御前主角。
没有的项目交空列表，不凭空增添。
"""


def catalogue(ledger: Ledger, exclude: tuple[str, ...] = ()) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for row in ledger.read(CATALOGUE.with_only_columns(
        E.kind, E.key, E.data["aliases"].label("aliases"), E.data["name"].as_string().label("name"),
    ).where(E.kind.not_in(exclude))):
        aliases: list[str] = row["aliases"] or []
        name = row["name"]
        if name and name != row["key"]:
            aliases = [*aliases, name]
        result.setdefault(row["kind"], {})[row["key"]] = aliases
    return result


# Content catalogues the month accounts and levy timeline iterate: only the
# imported rows exist, so a declaration may change them but never add one.
CATALOGUES = {"historical_event", "fiscal", "account", "office", "territory", "incumbency"}


def allowed_fields(ledger: Ledger) -> dict[str, set[str]]:
    fields: dict[str, set[str]] = {
        "affair": {"text"},
        "decree": {"text", "origin", "people"},
    }
    keys = func.json_each(E.data).table_valued("key")
    for row in ledger.read(select(E.kind, keys.c.key.label("field")).select_from(
        E.id.table.join(keys, true())
    ).where(E.source != "", E.kind != "calendar").distinct()):
        fields.setdefault(row["kind"], set()).add(row["field"])
    fields["incumbency"] = {"holders"}
    # Fiscal settlement, arrears and the content catalogues are engine-owned;
    # translation writes only the levers the month accounts read.
    fields["region"] = (fields.get("region", set()) - {"fiscal"}) | {"fiscal_surcharge"}
    fields["historical_event"] = {"terminal_reason"}
    fields["account"] = {"taels", "payment_order", "army_order"}
    fields["fiscal"] = {"value", "payment_policy"}
    fields["army"] = (fields.get("army", set()) - {"arrears", "month_paid"}) | {
        "payment_policy"
    }
    fields.setdefault("person", set()).add("travel_speed")
    fields["person"].difference_update(
        {"transit_to", "remaining_distance", "waiting_audience"}
    )
    return fields


def check(ledger: Ledger, out: Declaration, source: UUID) -> None:
    names, fields = catalogue(ledger), allowed_fields(ledger)
    for i, fact in enumerate(out.facts):
        path = f"facts[{i}]"
        if fact.entity_type != "incumbency":
            fact.entity = reference_key(ledger, fact.entity_type, fact.entity)
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
                {"create": False, "entities": list(known)},
                names,
                "这类实体不能新建。create 改 false，entity 用 expected 里的正名，重交整份。",
            )
        if fact.entity_type == "incumbency":
            check_appointment(ledger, fact, path, names)
        elif (fact.entity in known) == fact.create:
            fail(
                path + ".entity",
                fact.entity,
                {"names_and_aliases": known, "create": fact.entity not in known},
                names,
                "entity 用 names_and_aliases 里的正名；没有就 create=true。确无该实体不得换成另一实体。重交整份。",
            )
        if fact.create or fact.entity_type == "incumbency":
            known[fact.entity] = []
        for j, change in enumerate(fact.changes):
            if change.counterpart:
                change.counterpart.entity = reference_key(ledger, change.counterpart.entity_type, change.counterpart.entity)
            if change.field not in fields[fact.entity_type]:
                fail(
                    f"{path}.changes[{j}].field",
                    change.field,
                    sorted(fields[fact.entity_type]),
                    names,
                    "field 改成 expected 里的字段名，重交整份。",
                )
    check_fiscal(ledger, out, names)
    check_rules(out, set(names.get("affair", {})), names)
    check_references(ledger, out, names)
    check_decrees(ledger, out, source, names)


def check_decrees(
    ledger: Ledger,
    out: Declaration,
    source: UUID,
    names: dict[str, dict[str, list[str]]],
) -> None:
    # Only a night has a decrees list to index. Month shares omit the source.
    labeled = (("facts", out.facts), ("decree_events", out.decree_events))
    for label, items in labeled:
        for i, item in enumerate(items):
            ref = item.decree
            path = f"{label}[{i}].decree"
            if isinstance(out, NightDeclaration):
                if ref is not None and not 0 <= ref < len(out.decrees):
                    fail(
                        path,
                        ref,
                        "本份 decrees 的零基下标",
                        names,
                        "decree 改成 expected，重交整份。",
                    )
                elif ref is None and (isinstance(item, DecreeEvent) or item.discovered):
                    fail(
                        path,
                        ref,
                        "指定所属旨意；只有月末本旨声明可省略来源",
                        names,
                        "补上所属旨意的下标，重交整份。只有月末本旨可省略。",
                    )
            elif ref is not None:
                fail(path, ref, "省略 decree", names, "省略 decree，重交整份。")
    if isinstance(out, NightDeclaration) and out.decrees:
        turns = read_night(ledger, source).turns
        for i, decree in enumerate(out.decrees):
            if decree.turn > len(turns):
                fail(
                    f"decrees[{i}].turn",
                    decree.turn,
                    list(range(1, len(turns) + 1)),
                    names,
                    "turn 改成 expected 里的本夜轮次，重交整份。",
                )
    if isinstance(out, NightDeclaration):
        check_endorsements(ledger, out, source, names)


def check_endorsements(
    ledger: Ledger,
    out: NightDeclaration,
    source: UUID,
    names: dict[str, dict[str, list[str]]],
) -> None:
    turn_ids = {f["detail"]["id"] for f in ledger.facts(entity_id=source, kind="turn")}
    for i, decree in enumerate(out.decrees):
        for j, endorsement in enumerate(decree.endorsements):
            path = f"decrees[{i}].endorsements[{j}]"
            if endorsement.source_chat_turn_id not in turn_ids:
                fail(
                    path + ".source_chat_turn_id",
                    endorsement.source_chat_turn_id,
                    sorted(turn_ids),
                    names,
                    "source_chat_turn_id 改成 expected 里的本夜轮次 id，重交整份。",
                )
            if endorsement.form != "御笔手敕":
                endorsement.endorser = reference_key(ledger, "person", endorsement.endorser)
            expected = ["御笔"] if endorsement.form == "御笔手敕" else names.get("person", {})
            if endorsement.endorser not in expected:
                fail(
                    path + ".endorser",
                    endorsement.endorser,
                    expected,
                    names,
                    "endorser 改成 expected 里的正名，重交整份。",
                )


def check_fiscal(ledger: Ledger, out: Declaration, names: Names) -> None:
    config = ledger.entities(kind="fiscal")
    expenses = {
        r["key"]: r["data"]["account"]
        for r in config
        if r["data"].get("direction") == "expense"
    }
    # A fiscal lever only on an entity the month accounts read it from.
    targets = {
        ("fiscal", "value"): levers(config),
        ("fiscal", "payment_policy"): list(expenses),
        ("account", "army_order"): ["国库"],
        ("region", "fiscal_surcharge"): [
            r["key"]
            for r in ledger.entities(kind="region")
            if settling(r["data"])
        ],
    }
    for i, fact in enumerate(out.facts):
        for j, change in enumerate(fact.changes):
            path = f"facts[{i}].changes[{j}]"
            allowed = targets.get((fact.entity_type, change.field))
            if allowed is not None and fact.entity not in allowed:
                fail(
                    path + ".entity",
                    fact.entity,
                    allowed,
                    names,
                    "对象改成 expected 里的正名，重交整份。",
                )
            if change.field == "payment_policy":
                try:
                    PaymentPolicy.model_validate(change.value)
                except ValidationError:
                    fail(
                        path + ".value",
                        change.value,
                        PaymentPolicy.model_json_schema(),
                        names,
                        "按 expected 的 schema 修正 payment_policy，重交整份。",
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
                labels = [
                    label
                    for row in ledger.entities(kind="historical_event", key=fact.entity)
                    for label in row["data"].get("terminal_reason_labels", [])
                ]
                if change.value not in labels:
                    fail(
                        path + ".value",
                        change.value,
                        labels,
                        names,
                        "terminal_reason 改成 expected 里的结局标签，重交整份。",
                    )
            if fact.entity_type == "account" and change.field in {
                "payment_order",
                "army_order",
            }:
                choices = (
                    [
                        r["key"]
                        for r in ledger.entities(kind="army")
                        if payable_army(r["data"])
                    ]
                    if change.field == "army_order"
                    else [
                        key
                        for key, account in expenses.items()
                        if account == fact.entity
                    ]
                    + (["军饷"] if fact.entity == "国库" else [])
                )
                # A complete order: every choice exactly once.
                value = change.value
                if not (
                    isinstance(value, list)
                    and all(isinstance(v, str) for v in cast(list[Any], value))
                    and sorted(cast(list[str], value)) == sorted(choices)
                ):
                    fail(
                        path + ".value",
                        change.value,
                        choices,
                        names,
                        "按 expected 的正名交完整顺序，每个一次，重交整份。",
                    )


def check_appointment(ledger: Ledger, fact: Fact, path: str, names: Names) -> None:
    pairs = office_pairs(ledger, fact.entity)
    if len(pairs) != 1:
        fail(path + ".entity", fact.entity,
             [{"office": office, "territory": territory} for office, territory in pairs]
             if pairs else {"office": names.get("office", {}), "territory": names.get("territory", {})},
             names, "写出能唯一对上两表的官名；歧义时用候选属地全名。重交整份。")
    office = ledger.entities(kind="office", key=pairs[0][0])[0]
    fact.entity = incumbency_record(pairs[0], [])[0]
    for j, change in enumerate(fact.changes):
        if change.field != "holders":
            continue
        field = f"{path}.changes[{j}].value"
        value: Any = change.value
        if not isinstance(value, list) or not all(isinstance(p, str) for p in cast(list[Any], value)):
            fail(field, change.value, {"type": "array", "items": {"type": "string"}}, names, "holders 写完整人名名单，重交整份。")
        holders = [reference_key(ledger, "person", person) for person in cast(list[str], value)]
        change.value = holders
        if not office["data"]["multiple"] and len(holders) > 1:
            fail(field, holders, {"maxItems": 1}, names, "一员只能任一人，重交整份。")
        for k, person in enumerate(holders):
            if person not in names.get("person", {}):
                fail(f"{field}[{k}]", person, names.get("person", {}), names, "在任者用人物正名，重交整份。")


def check_references(ledger: Ledger, out: Declaration, names: Names) -> None:
    people: list[tuple[str, Any]] = []
    for i, fact in enumerate(out.facts):
        for j, change in enumerate(fact.changes):
            kind = REFERENCES.get((fact.entity_type, change.field))
            if kind is not None and (change.field == "location" or change.value != ""):
                change.value = reference_key(ledger, kind, change.value) if isinstance(change.value, str) else change.value
                known = isinstance(change.value, str) and (
                    change.value in names.get(kind, {})
                )
                if not known:
                    fail(
                        f"facts[{i}].changes[{j}].value",
                        change.value,
                        names.get(kind, {}),
                        names,
                        "value 改成 expected 里的账本正名，重交整份。确无该实体不得换成另一实体。",
                    )
            if (fact.entity_type, change.field) == ("decree", "people"):
                people.append((f"facts[{i}].changes[{j}].value", change.value))
    for i, report in enumerate(out.reports):
        report.entity = reference_key(ledger, report.entity_type, report.entity)
        if report.entity not in names.get(report.entity_type, {}):
            fail(
                f"reports[{i}].entity",
                report.entity,
                names.get(report.entity_type, {}),
                names,
                "entity 改成 expected 里的正名，重交整份。确无该实体不得换成另一实体。",
            )
    if isinstance(out, NightDeclaration):
        people.extend((f"decrees[{i}].people", decree.people) for i, decree in enumerate(out.decrees))
    for path, value in people:
        if not isinstance(value, list):
            fail(
                path,
                value,
                names.get("person", {}),
                names,
                "people 改成名单，成员用 expected 里的人名正名，重交整份。",
            )
        members = cast(list[Any], value)
        for i, person in enumerate(members):
            members[i] = person = reference_key(ledger, "person", person) if isinstance(person, str) else person
            if not isinstance(person, str) or person not in names.get("person", {}):
                fail(f"{path}[{i}]", person, names.get("person", {}), names,
                     "people 里的名字改成 expected 里的人名正名，重交整份。确无此人不得换成另一人。")


def declaration_agent(
    model: ModelSource,
    ledger: Ledger,
    output_type: type[T],
    instructions: str = INSTRUCTIONS,
) -> Agent[UUID, T]:
    async def read_catalogues() -> Item:
        """需要核对官职、属地时取两张目录；含正名、别名、衙门及员额。"""
        tables: Item = {kind: {} for kind in CATALOGUE_KINDS}
        for row in ledger.read(ENTITY_ROWS.with_only_columns(
            E.kind, E.key, E.data["aliases"].label("aliases"),
            E.data["department"].as_string().label("department"),
            E.data["multiple"].as_boolean().label("multiple"),
            E.data["region"].as_string().label("region"),
        ).where(E.kind.in_(tables))):
            tables[row["kind"]][row["key"]] = {k: v for k, v in row.items() if k not in {"kind", "key"} and v is not None}
        return tables

    agent = build_agent(
        model,
        tools=[Tool(read_catalogues, takes_ctx=False)],
        name=output_type.__name__,
        deps_type=UUID,
        output_type=PromptedOutput(output_type),
        instructions=instructions + "\n官职和属地不混在实况名册里；需要核对官名、地名、别名、所属衙门或员额时，用 read_catalogues 取两张目录。",
        retries=1,
    )

    @agent.instructions
    async def names() -> str:
        # Queries and JSON encoding stay on the caller's loop, like tools;
        # only model I/O yields.
        return json.dumps(
            {
                "names_and_aliases": catalogue(ledger, exclude=CATALOGUE_KINDS),
                "field_schemas": {"payment_policy": PaymentPolicy.model_json_schema()},
                "allowed_fields": {
                    k: sorted(v) for k, v in allowed_fields(ledger).items()
                },
            },
            ensure_ascii=False,
        )

    @agent.output_validator
    def validate(ctx: RunContext[UUID], out: T) -> T:
        check(ledger, out, ctx.deps)
        return out

    return agent


async def translate(
    agent: Agent[UUID, T],
    prompt: str,
    source: UUID,
) -> T | Unhandled:
    with capture_run_messages() as messages:
        try:
            return (
                await invoke(
                    agent, "请按 JSON schema 提交完整声明。\n" + prompt, deps=source
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
