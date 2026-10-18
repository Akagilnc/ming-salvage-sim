"""中间层往外的口：一句皇帝原话进、已落事实出。

模型回话全部是真实 claude CLI 后端录下的原样回话（recorded/*.json，含出处）；
观察只走 Court.facts，不碰账本、不开 SQLite。
"""

import json
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ming.middle.court import Court
from ming.middle.view import Identity

RECORDED = Path(__file__).parent / "recorded"


class Recorded(NamedTuple):
    emperor_words: str
    scene: str
    replies: list[str]


def load(name: str) -> Recorded:
    raw = json.loads((RECORDED / f"{name}.json").read_text())
    return Recorded(raw["emperor_words"], raw["scene"], raw["replies"])


def replaying(replies: list[str]) -> tuple[FunctionModel, list[int]]:
    """按序吐出录下的回话；返回模型与调用计数。"""
    calls: list[int] = []

    def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return ModelResponse(parts=[TextPart(replies[len(calls) - 1])])

    return FunctionModel(reply), calls


def court_for(tmp_path: Path, replies: list[str]) -> tuple[Court, list[int]]:
    model, calls = replaying(replies)
    return Court(tmp_path / "game.sqlite", model), calls


def declared(name: str) -> dict[str, list[dict[str, object]]]:
    """录下的最后一条回话里模型所声明的全部交办与拨款。"""
    return json.loads(replies_of(name)[-1])


def handle_recorded(court: Court, name: str) -> None:
    case = load(name)
    court.handle(case.emperor_words, case.scene)


def replies_of(name: str) -> list[str]:
    return load(name).replies


def test_every_declared_assign_lands_with_the_emperors_own_words(tmp_path: Path) -> None:
    court, _ = court_for(tmp_path, replies_of("assign"))
    handle_recorded(court, "assign")
    facts = court.facts("emperor")
    assigns = declared("assign")["assigns"]
    assert len(assigns) == len(facts) > 0
    assert [(f.kind, f.detail["assignees"], f.detail["task"]) for f in facts] == [
        ("affair", a["assignees"], a["task"]) for a in assigns
    ]
    assert {f.emperor_words for f in facts} == {load("assign").emperor_words}


def test_one_sentence_with_a_grant_and_an_assignment_lands_both(tmp_path: Path) -> None:
    court, _ = court_for(tmp_path, replies_of("grant"))
    handle_recorded(court, "grant")
    facts = court.facts("emperor")
    data = declared("grant")
    (grant,) = [f for f in facts if f.kind == "grant_nominal"]
    assert grant.detail == {
        "amount": 500000,
        "recipient": data["grants"][0]["recipient"],
        "purpose": data["grants"][0]["purpose"],
    }
    (affair,) = [f for f in facts if f.kind == "affair"]
    assert affair.detail["assignees"] == data["assigns"][0]["assignees"]
    assert {f.emperor_words for f in facts} == {load("grant").emperor_words}


def test_a_line_that_is_no_order_lands_nothing(tmp_path: Path) -> None:
    court, _ = court_for(tmp_path, replies_of("none"))
    handle_recorded(court, "none")
    assert court.facts("emperor") == []
    assert court.facts("audit") == []


def test_facts_accumulate_in_one_game_file(tmp_path: Path) -> None:
    court, _ = court_for(tmp_path, replies_of("assign") + replies_of("grant"))
    handle_recorded(court, "assign")
    handle_recorded(court, "grant")
    kinds = Counter(f.kind for f in court.facts("emperor"))
    assert kinds == {"affair": len(declared("assign")["assigns"]) + 1, "grant_nominal": 1}


def test_rewrite_after_bad_format_leaves_no_trace_of_the_retry(tmp_path: Path) -> None:
    replies = replies_of("bad_recovered")
    court, calls = court_for(tmp_path, replies)
    handle_recorded(court, "bad_recovered")
    assert len(calls) == 2
    identities: list[Identity] = ["emperor", "audit"]
    for identity in identities:
        (fact,) = court.facts(identity)
        assert fact.kind == "affair"
        assert fact.detail["assignees"] == declared("bad_recovered")["assigns"][0]["assignees"]


def test_exhausted_retry_is_one_unhandled_fact_and_play_goes_on(tmp_path: Path) -> None:
    bad = replies_of("bad_recovered")[0]
    court, calls = court_for(tmp_path, [bad, bad] + replies_of("assign"))
    handle_recorded(court, "bad_recovered")
    assert len(calls) == 2
    (seen_by_emperor,) = court.facts("emperor")
    assert seen_by_emperor.kind == "unhandled"
    assert seen_by_emperor.emperor_words == load("bad_recovered").emperor_words
    assert seen_by_emperor.detail == {}
    (audited,) = court.facts("audit")
    assert audited.detail["model_text"] == bad
    assert audited.detail["failure_point"]
    handle_recorded(court, "assign")
    kinds = Counter(f.kind for f in court.facts("emperor"))
    assert kinds == {"affair": len(declared("assign")["assigns"]), "unhandled": 1}


def test_transport_failure_is_not_turned_into_unhandled(tmp_path: Path) -> None:
    def broken(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise ConnectionError("host did not answer")

    court = Court(tmp_path / "game.sqlite", FunctionModel(broken))
    with pytest.raises(ConnectionError):
        court.handle("拨银五万两给海瑞。", "")
    assert court.facts("audit") == []
