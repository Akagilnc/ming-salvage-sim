"""Shared model input and persisted product types, not a second month driver."""

import json
from typing import Any, Literal

from ming.middle.court import Court
from ming.middle.declaration import Petition, StrictModel
from ming.middle.view import Identity, character_input


COST_RULES = """背书（含御笔手敕、御笔强推）本身不走代价轨，不等于中旨。
强颁与预先中旨共用代价轨：实际颁出才付皇威；相关派系／阶级满意度反应可正可负可零，中旨名声记在本旨。
预先中旨被驳也有满意度反应与中旨名声，但不执行旨意、不扣皇威；收回、留中不抹去已经发生的中旨尝试反应。
同旨背书与中旨并存只计一份代价。prior_interim 是本旨已记的中旨历史，重议不重复已付反应；后来获准或强颁只补实际颁出的皇威代价。
撤回成命交皇威、当事大臣与相关派系反应；收权罢差零毁约代价。正规被驳旨收回、留中中性。民心不是这些动作的固定代价。"""


class Deliberation(StrictModel):
    text: str
    verdict: Literal["准", "驳", "中旨亦不可颁"]


class Simulation(StrictModel):
    text: str
    petitions: list[Petition]
    month_end: bool


def prompt(court: Court, identity: Identity, context: Any) -> str:
    return json.dumps(
        character_input(
            {
                "date": court.calendar().data,
                "context": context,
                "catalogue": court.record_catalogue(identity),
            }
        ),
        ensure_ascii=False,
    )
