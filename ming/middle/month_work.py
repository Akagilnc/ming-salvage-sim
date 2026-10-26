"""Shared model input and persisted product types, not a second month driver."""

import json
from typing import Any, Literal

from pydantic import Field

from ming.middle.court import Court
from ming.middle.declaration import Petition, StrictModel
from ming.middle.view import Identity, Officials, character_input


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


def prompt(court: Court, identity: Identity, context: Any) -> str:
    return json.dumps(
        character_input(
            {
                "date": court.calendar().data,
                "context": context,
                "catalogue": court.record_catalogue(identity),
                **({"speakers": [e.model_dump(mode="json") for name in identity.people
                                   for e in court.entities(identity, kind="person", key=name)]}
                   if isinstance(identity, Officials) else {}),
            }
        ),
        ensure_ascii=False,
    )
