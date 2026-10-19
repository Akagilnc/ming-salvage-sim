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


GRANT = load("grant")


@pytest.mark.parametrize(
    "name,assignees",
    [
        ("assign", {"倪元璐", "黄道周"}),
        ("alias", {"史可法"}),
        ("format_retry", {"史可法"}),
    ],
)
def test_assignment_is_an_affair_event_and_each_persons_history(
    tmp_path: Path, name: str, assignees: set[str]
) -> None:
    case = load(name)
    court = Court.new_game(tmp_path, replaying(case["replies"]))
    court.handle(case["emperor_words"], case["scene"])
    facts = court.facts("audit")
    (affair,) = [e for e in court.entities("audit") if e.kind == "affair"]
    (assigned,) = [f for f in facts if f.entity_id == affair.id]
    assert {f.kind for f in facts} == {"assigned"}
    assert set(assigned.detail["assignees"]) == assignees
    people = {e.key: e.id for e in court.entities("audit") if e.kind == "person"}
    histories = [f for f in facts if f.entity_id != affair.id]
    assert len(histories) == len(assignees)
    assert {f.entity_id for f in histories} == {people[p] for p in assignees}
    assert all(f.detail["affair_id"] == str(affair.id) for f in histories)
    assert {f.emperor_words for f in facts} == {case["emperor_words"]}
    assert court.facts("emperor") == []
    court.close()


@pytest.mark.parametrize(
    "bad,next_name",
    [
        pytest.param(load("unknown"), "assign", id="unknown"),
        pytest.param(load("format_retry"), "none", id="format_retry"),
        pytest.param(GRANT | GRANT["missing_account"], "none", id="missing_account"),
    ],
)
def test_exhaustion_rejects_the_whole_declaration_and_accepts_the_next_sentence(
    tmp_path: Path, bad: dict[str, Any], next_name: str
) -> None:
    following = load(next_name)
    court = Court.new_game(
        tmp_path, replaying([bad["replies"][0]] * 2 + following["replies"])
    )
    before = court.entities("audit")
    court.handle(bad["emperor_words"], bad["scene"])
    (failure,) = court.facts("audit")
    assert failure.kind == "unhandled"
    assert failure.detail["model_text"] == bad["replies"][0]
    assert failure.detail["failure_point"]
    assert failure.emperor_words == bad["emperor_words"]
    (visible,) = court.facts("emperor")
    assert visible.kind == "unhandled"
    assert visible.detail == {}
    assert all(e in court.entities("audit") for e in before)
    assert not [e for e in court.entities("audit") if e.kind == "affair"]
    court.handle(following["emperor_words"], following["scene"])
    if next_name == "assign":
        assert [f.kind for f in court.facts("audit")].count("assigned") == 3
        assert not [f for f in court.facts("audit") if f.kind == "grant_nominal"]
    else:
        assert court.facts("audit") == [failure]
    court.close()


def test_grant_is_nominal_and_reopening_preserves_rows_and_event_replay(
    tmp_path: Path,
) -> None:
    case = GRANT
    model = replaying(case["replies"] * 2)
    court = Court.new_game(tmp_path, model)
    before_accounts = [e for e in court.entities("audit") if e.kind == "account"]
    court.handle(case["emperor_words"], case["scene"])
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
    court.handle(case["emperor_words"], case["scene"])
    assert [f.kind for f in court.facts("audit")].count("grant_nominal") == 2
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
