"""Shared model input and persisted product types, not a second month driver."""

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from ming.middle.declaration import Petition, StrictModel
from ming.middle.view import EntityView, Officials, character_input
from ming.middle.records import Materials


COST_RULES = """背书（含御笔手敕、御笔强推）本身不走代价轨。
强颁与预先中旨共用代价轨：实际颁出才付皇威；相关派系／阶级满意度反应可正可负可零。
预先中旨被驳也有满意度反应与中旨名声，但不执行旨意、不扣皇威；收回、留中不抹去已经发生的中旨尝试反应。
同旨背书与中旨并存只计一份代价。prior_interim 是本旨已记的中旨历史，重议不重复已付反应；后来获准或强颁只补实际颁出的皇威代价。
撤回成命交皇威、当事大臣与相关派系反应；收权罢差零毁约代价。正规被驳旨收回、留中中性。民心不是这些动作的固定代价。"""


class Deliberation(StrictModel):
    text: str = Field(description="外廷议处原文。")
    verdict: Literal["准", "驳", "中旨亦不可颁"] = Field(description="议处结局，含义见外廷判词。")


class MonthText(StrictModel):
    text: str = Field(description="本月推演正文，含义见月草稿、月定稿。")


class Simulation(MonthText):
    petitions: list[Petition] = Field(default_factory=list[Petition], description="本月岔路口奏疏列表，无岔路可省略；含义见岔路口。")


@dataclass
class MonthMaterials(Materials):
    calendar: EntityView
    catalogue: list[dict[str, Any]] = field(init=False)
    speakers: list[dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        self.catalogue = self.court.record_catalogue(self.identity)
        speakers = {e.key: e.model_dump(mode="json") for e in self.court.entities(
            self.identity, kind="person", key=self.identity.people,
        )} if isinstance(self.identity, Officials) and self.identity.people else {}
        self.speakers = [speakers[name] for name in self.identity.people if name in speakers
                         ] if isinstance(self.identity, Officials) else []


def prompt(materials: MonthMaterials, context: Any) -> str:
    return json.dumps(
        character_input(
            {
                "date": materials.calendar.data,
                "context": context,
                "catalogue": materials.catalogue,
                **({"speakers": materials.speakers} if isinstance(materials.identity, Officials) else {}),
            }
        ),
        ensure_ascii=False,
    )
