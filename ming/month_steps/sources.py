"""Month-end urgent drafting and faction petitions; choices act next month."""

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4
from collections.abc import Awaitable, Callable

from pydantic import Field
from pydantic_ai import Agent, PromptedOutput, RunContext
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.concepts import ACTING
from ming.middle.declaration import StrictModel
from ming.middle.invoke import gather_or_raise, invoke
from ming.month_steps.materials import Petition, PendingPetition, next_month, petition_officials, prompt
from ming.middle.records import Materials, read_records
from ming.middle.view import EntityView, Officials, character_input
from ming.middle.rules import Names, fail, name_expected
from ming.month_steps.products import record_product


@dataclass
class SourceMaterials(Materials):
    """One month-end run's name catalogue, shared by every source's validation."""
    catalogue: Names


class UrgentPetition(Petition):
    signer: str = Field(description="署名人的账本正名")
    revision_of: UUID | None = Field(default=None, description="改票所指原奏疏 id")


class ImpeachmentPetition(Petition):
    signer: str = Field(description="发难者的账本正名")
    target: str = Field(description="被劾人的账本正名")
    options: list[str] = Field(
        min_length=3,
        max_length=3,
        description="依次为顺水推舟办人、压下、查实再办，三项措辞由发难者写",
    )


class Urgencies(StrictModel):
    petitions: list[UrgentPetition]


class Impeachments(StrictModel):
    petitions: list[ImpeachmentPetition]


class Sources:
    urgent, impeachment = (
        Agent(
            name=kind, output_type=PromptedOutput(output),
            deps_type=SourceMaterials, tools=[read_records], retries=1,
            instructions="你演上奏的官员。按输入 catalogue 用 read_records 按需查本人所知见闻；按输入人物立场写下月开局的奏折。正文与选项用奏报口吻，人物才具、操守以言行呈现。" + "\n" + ACTING,
        ) for kind, output in (("urgent", Urgencies), ("impeachment", Impeachments))
    )

    def __init__(self, court: Court, model: Callable[[], Model]) -> None:
        self.court, self.model = court, model

    async def run(self, calendar: EntityView) -> None:
        pending: dict[tuple[str, ...], list[tuple[int, EntityView, str, dict[str, object]]]] = {}
        for index, (source, kind, faction) in enumerate([
            (calendar, "urgent", None),
            *((f, "impeachment", f.key) for f in self.court.read.entities("audit", kind="faction")),
        ]):
            if self.court.read.has_facts(source.id, kind, date=calendar.data):
                continue
            people = list(petition_officials(self.court, faction))
            if kind == "urgent" and not people:
                record_product(self.court, source.id, kind, {"petitions": [], "date": calendar.data})
                continue
            context: dict[str, object] = {
                "returned": [f.detail for f in self.court.returned_petitions()],
                "instruction": "以在职首辅、司礼监掌印的立场择本月急务、排先后，按各人立场与利害拟旨成奏折。署名由你定，不以首辅优先。可以交空；发回原案由在职者改票并填写 revision_of，不复述原案充作新案。选项由你拟，不附发回改票按钮。",
            } if kind == "urgent" else {
                "faction": faction,
                "people": people,
                "instruction": "以本派在朝人物的身份看本月见闻和本派、对手势力，自行决定劾不劾、劾谁、如何归因，可以交空。灾难真而归因可夹私货。署名人及被劾人用账本正名。每折三项：顺水推舟办人、压下、查实再办，措辞自拟。",
            }
            pending.setdefault(tuple(people), []).append((index, source, kind, context))
        if not pending:
            return
        catalogue = self.court.read.catalogue()
        calls: dict[int, Awaitable[None]] = {}
        for names, requests in pending.items():
            identity = Officials(people=list(names))
            inputs = prompt(self.court, identity, {}, date=calendar.data)
            calls.update((index, self.call(source, kind, identity, {**inputs, "context": character_input(context)}, catalogue))
                         for index, source, kind, context in requests)
        await gather_or_raise(*(calls[index] for index in sorted(calls)))

    async def call(
        self,
        source: EntityView,
        kind: str,
        identity: Officials,
        inputs: dict[str, Any],
        catalogue: Names,
    ) -> None:
        result = await invoke(
            self.urgent if kind == "urgent" else self.impeachment,
            inputs,
            deps=SourceMaterials(self.court, identity, catalogue), model=self.model(),
        )
        self.court.log.info("%s output: %s", kind, result.output.model_dump_json())
        date = inputs["date"]
        available = {**date, **next_month(date)}
        people = {e.key: e.id for e in self.court.read.entities(
            "audit", kind="person", key=[p.signer for p in result.output.petitions],
        )} if result.output.petitions else {}
        petitions = [
            PendingPetition(
                **item.model_dump(exclude={"options"}),
                options=[*item.options, "发回改票"]
                if kind == "urgent"
                else item.options,
                id=uuid4(),
                entity_id=people[item.signer],
                available=available,
                blocking=False,
                source=kind,
                ordinal=index,
            )
            for index, item in enumerate(result.output.petitions)
        ]
        record_product(
            self.court, source.id, kind,
            {"petitions": [str(p.id) for p in petitions], "date": date},
            petitions=petitions,
        )


@Sources.urgent.output_validator
@Sources.impeachment.output_validator
def names(ctx: RunContext[SourceMaterials], output: Urgencies | Impeachments):
    if not output.petitions:
        return output
    catalogue = ctx.deps.catalogue
    allowed: dict[str, list[str]] | list[str] = catalogue["person"]
    if isinstance(output, Urgencies):
        allowed = cast(Officials, ctx.deps.identity).people
    originals: set[str] = ctx.deps.court.returned_petition_ids() if isinstance(output, Urgencies) and any(p.revision_of is not None for p in output.petitions) else set()
    for index, item in enumerate(output.petitions):
        refs = {"signer": item.signer}
        if isinstance(item, ImpeachmentPetition):
            refs["target"] = item.target
        for field, name in refs.items():
            if name not in allowed:
                fail(
                    f"petitions[{index}].{field}", name,
                    allowed if isinstance(output, Urgencies) else name_expected("person", "", catalogue), catalogue,
                    "参照 expected 的正名清单或输入目录指针核对人名，重交整份。确无此人不得换成另一人。",
                )
        if isinstance(item, UrgentPetition) and item.revision_of is not None:
            if str(item.revision_of) not in originals:
                fail(
                    f"petitions[{index}].revision_of", str(item.revision_of),
                    sorted(originals), catalogue,
                    "revision_of 改成 expected 里的原奏疏 id，或省略，重交整份。",
                )
    return output
