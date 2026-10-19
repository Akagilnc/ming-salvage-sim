"""Real recorded model replies enter Court; assertions use structured audit results."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ming.middle.court import Court

RECORDED = Path(__file__).parent / "recorded"


def load(name: str) -> dict[str, Any]:
    return json.loads((RECORDED / f"{name}.json").read_text())


def replaying(replies: list[str]) -> FunctionModel:
    remaining = iter(replies)

    def reply(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(next(remaining))])

    return FunctionModel(reply)


def handle_recorded(court: Court, name: str) -> None:
    case = load(name)
    court.handle(case["emperor_words"], case["scene"])


def test_joint_assignment_is_an_affair_event_and_each_persons_history(
    tmp_path: Path,
) -> None:
    case = load("assign")
    court = Court.new_game(tmp_path, replaying(case["replies"]))
    court.handle(case["emperor_words"], load("assign")["scene"])
    facts = court.facts("audit")
    (affair,) = [e for e in court.entities("audit") if e.kind == "affair"]
    (assigned,) = [f for f in facts if f.entity_id == affair.id]
    assert assigned.kind == "assigned"
    assert set(assigned.detail["assignees"]) == {"倪元璐", "黄道周"}
    people = {e.key: e.id for e in court.entities("audit") if e.kind == "person"}
    histories = [f for f in facts if f.entity_id != affair.id]
    assert {f.entity_id for f in histories} == {people["倪元璐"], people["黄道周"]}
    assert all(f.detail["affair_id"] == str(affair.id) for f in histories)
    assert {f.emperor_words for f in facts} == {case["emperor_words"]}
    assert court.facts("emperor") == []
    court.close()


def test_unknown_person_rejects_the_whole_declaration_and_next_order_still_lands(
    tmp_path: Path,
) -> None:
    bad = load("unknown")
    good = load("assign")
    court = Court.new_game(tmp_path, replaying(bad["replies"] + good["replies"]))
    before = court.entities("audit")
    handle_recorded(court, "unknown")
    (failure,) = court.facts("audit")
    assert failure.kind == "unhandled"
    assert failure.detail["model_text"] == bad["replies"][-1]
    assert failure.detail["failure_point"]
    (visible,) = court.facts("emperor")
    assert visible.kind == "unhandled"
    assert visible.detail == {}
    assert all(e in court.entities("audit") for e in before)
    assert not [e for e in court.entities("audit") if e.kind == "affair"]
    court.handle(good["emperor_words"], load("assign")["scene"])
    assert [f.kind for f in court.facts("audit")].count("assigned") == 3
    assert not [f for f in court.facts("audit") if f.kind == "grant_nominal"]
    court.close()


def test_grant_is_nominal_and_reopening_preserves_rows_and_event_replay(
    tmp_path: Path,
) -> None:
    case = load("grant")
    model = replaying(case["replies"] * 2)
    court = Court.new_game(tmp_path, model)
    before_accounts = [e for e in court.entities("audit") if e.kind == "account"]
    handle_recorded(court, "grant")
    (grant,) = [f for f in court.facts("audit") if f.kind == "grant_nominal"]
    treasury = next(e for e in before_accounts if e.key == "国库")
    assert grant.entity_id == treasury.id
    assert grant.detail["amount_taels"] == 500000
    assert grant.emperor_words == case["emperor_words"]
    assert [
        e for e in court.entities("audit") if e.kind == "account"
    ] == before_accounts
    assert [f.kind for f in court.facts("audit")].count("assigned") == 2
    path = court.db_path
    before = court.entities("audit")
    facts = court.facts("audit")
    court.close()
    court = Court(path, model)
    assert court.entities("audit") == before == court.entities("audit", replay=True)
    assert court.facts("audit") == facts == court.facts("audit", replay=True)
    handle_recorded(court, "grant")
    assert [f.kind for f in court.facts("audit")].count("grant_nominal") == 2
    court.close()


@pytest.mark.parametrize("name", ["alias", "format_retry"])
def test_model_can_correct_name_or_structure_without_leaving_partial_facts(
    tmp_path: Path, name: str
) -> None:
    case = load(name)
    court = Court.new_game(tmp_path, replaying(case["replies"]))
    handle_recorded(court, name)
    assert not [f for f in court.facts("audit") if f.kind == "unhandled"]
    declaration = json.loads(case["replies"][-1])
    people = {e.key: e.id for e in court.entities("audit") if e.kind == "person"}
    expected_people = {
        people[p] for a in declaration["assigns"] for p in a["assignees"]
    }
    actual_people = {
        f.entity_id for f in court.facts("audit") if f.entity_id in set(people.values())
    }
    assert actual_people == expected_people
    assert len([e for e in court.entities("audit") if e.kind == "affair"]) == len(
        declaration["assigns"]
    )
    assert court.facts("emperor") == []
    court.close()


@pytest.mark.parametrize("name", ["format_retry", "missing_account"])
def test_missing_or_malformed_field_exhaustion_is_retained_and_next_sentence_is_accepted(
    tmp_path: Path, name: str
) -> None:
    bad = load(name)
    empty = load("none")
    court = Court.new_game(
        tmp_path, replaying([bad["replies"][0]] * 2 + empty["replies"])
    )
    handle_recorded(court, name)
    (fact,) = court.facts("audit")
    assert fact.kind == "unhandled"
    assert fact.detail["model_text"] == bad["replies"][0]
    assert fact.detail["failure_point"]
    assert court.facts("emperor")[0].detail == {}
    handle_recorded(court, "none")
    assert court.facts("audit") == [fact]
    court.close()


@pytest.mark.parametrize(
    "failure", [ConnectionError, UnexpectedModelBehavior, RuntimeError]
)
def test_call_failures_are_not_disguised_as_bad_declarations(
    tmp_path: Path, failure: type[Exception]
) -> None:
    def broken(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise failure("backend did not supply a declaration")

    court = Court.new_game(tmp_path, FunctionModel(broken))
    before = court.entities("audit")
    with pytest.raises(failure):
        court.handle("拨银五万两给徐光启。")
    assert court.facts("audit") == []
    assert court.entities("audit") == before
    court.close()
