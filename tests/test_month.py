"""Medium: month products and landing through HTTP, read through the CLI."""

import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.models.test import TestModel
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from ming.middle.declaration import PendingPetition
from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"
GUOKU_ORDER = [
    "军饷",
    "官俸_base",
    "宗室禄米_base",
    "赈灾_base",
    "工程_base",
    "建筑维护_base",
]
ARMY_ORDER = [
    "京营",
    "关宁军 / 宁锦防线",
    "山海关守军",
    "宣大边军",
    "蓟镇兵",
    "登莱兵与水师",
    "东江镇",
    "陕西边军",
    "南京守备军",
    "福建水师",
    "广东水师",
    "西南土司兵",
]
BORDER_ORDER = [
    "军饷",
    "宗室禄米_base",
    "官俸_base",
    "赈灾_base",
    "建筑维护_base",
    "工程_base",
]
BORDER_ARMIES = [
    "关宁军 / 宁锦防线",
    "宣大边军",
    "蓟镇兵",
    "山海关守军",
    "陕西边军",
    "登莱兵与水师",
    "东江镇",
    "京营",
    "南京守备军",
    "福建水师",
    "广东水师",
    "西南土司兵",
]
# Event log, read rows, and tracking: one landing commit lands all three.
LANDING = (
    "SELECT max(id) FROM ledger_events",
    "SELECT count(*) FROM facts WHERE kind = 'landed'",
    "SELECT max(notification_id) FROM readmodel_tracking",
)


@pytest.mark.parametrize(
    ("first", "extra"),
    [
        ("simulation.txt", 0),
        ("month_deferred.txt", 0),
        ("month_zero.txt", 1),
        ("sources", 0),
    ],
)
def test_month_without_decrees_advances_after_reopening(
    game_db: Path, steps, audit, first: str, extra: int
) -> None:
    received = []
    if first == "sources":
        for name in ("urgent", "impeachment"):
            steps[name] = TestModel(
                call_tools=[],
                custom_output_text=(RECORDED / f"sources_{name}.txt").read_text(),
            )
    steps["simulation"] = replaying(
        [
            (
                RECORDED / ("simulation.txt" if first == "sources" else first)
            ).read_text(),
            *[(RECORDED / "simulation.txt").read_text()] * (2 + extra),
        ],
        received,
    )
    with TestClient(create_app(game_db.parent)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        for year, month in [(1627, 11), (1627, 12), (1628, 1)]:
            assert client.post("/actions", json={"action": "month"}).status_code == 204
            state = client.get("/state").json()["game"]
            assert state["date"] == {"id": "world", "year": year, "month": month}
            assert (state["running"], state["pending"], state["failure"]) == (
                False,
                None,
                None,
            )
            if first == "sources":
                urgent = [p for p in state["petitions"] if p["source"] == "urgent"]
                assert [p["signer"] for p in urgent] == ["王体乾", "黄立极"]
                assert all(not p["blocking"] for p in state["petitions"])
                people = {
                    e["key"]: e["id"]
                    for e in audit(game_db)["entities"]
                    if e["kind"] == "person"
                }
                assert all(
                    p["entity_id"] == people[p["signer"]] for p in state["petitions"]
                )
                assert all(
                    p["target"] in people
                    for p in state["petitions"]
                    if p["source"] == "impeachment"
                )
            for petition in state["petitions"]:
                calls = len(received)
                assert (
                    client.post(
                        "/actions",
                        json={
                            "action": "choose",
                            "petition": petition["id"],
                            "option": 2 if petition["source"] == "impeachment" else 0,
                        },
                    ).status_code
                    == 204
                )
                assert len(received) == calls
                assert client.get("/state").json()["game"]["date"] == state["date"]
            ledger = audit(game_db.parent / save)
            months = (year - 1627) * 12 + month - 10
            assert len([f for f in ledger["facts"] if f["kind"] == "urgent"]) == months
            assert len(
                [f for f in ledger["facts"] if f["kind"] == "impeachment"]
            ) == months * len([e for e in ledger["entities"] if e["kind"] == "faction"])
            budgets = [f for f in ledger["facts"] if f["kind"] == "month_accounts"]
            assert len(budgets) == months
            assert [
                f["kind"]
                for f in ledger["facts"]
                if f["kind"] in {"month_accounts", "gazette"}
            ] == ["month_accounts", "gazette"] * len(budgets)
            assert (
                next(
                    e["data"]["arrears"]
                    for e in ledger["entities"]
                    if e["kind"] == "army" and e["key"] == "关宁军 / 宁锦防线"
                )
                == 60
            )
            assert not [e for e in ledger["entities"] if e["kind"] == "affair"]
            assert not [f for f in ledger["facts"] if f["kind"] == "forecast"]
            assert (
                len([f for f in ledger["facts"] if f["kind"] == "simulation"])
                == (year - 1627) * 12 + month - 10 + extra
            )
            material = json.loads(
                received[0 if month == 11 and extra else -1].parts[0].content
            )
            assert {c["petition_id"] for c in material["context"]["prior_choices"]} == {
                f["detail"]["petition_id"]
                for f in ledger["facts"]
                if f["kind"] == "choice" and f["detail"]["date"] == material["date"]
            }
            assert all(
                c["petition"]["id"] == c["petition_id"]
                for c in material["context"]["prior_choices"]
            )
            calendar = next(
                e["id"] for e in ledger["entities"] if e["kind"] == "calendar"
            )
            assert all(
                f["entity_id"] == calendar
                for f in ledger["facts"]
                if f["kind"] == "simulation"
            )
            state = client.get("/state").json()["game"]
            client.post("/actions", json={"action": "load", "save": save})
            assert client.get("/state").json()["game"] == state


@pytest.mark.parametrize("valid_revision", [True, False])
def test_returned_urgent_waits_through_vacancy(
    game_db: Path, steps, monkeypatch, valid_revision: bool
) -> None:
    revision = (RECORDED / "sources_revision.txt").read_text()
    received = []
    steps["simulation"] = replaying(
        [(RECORDED / "simulation.txt").read_text()] * 5, received
    )
    steps["urgent"] = replaying([(RECORDED / "sources_urgent.txt").read_text()])
    drafting = []
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        if valid_revision:

            def identify_original(**fields):
                # Align only this original's generated ID, regardless of scheduling.
                if fields["source"] == "urgent" and fields["ordinal"] == 0:
                    fields["id"] = UUID(
                        json.loads(revision)["petitions"][0]["revision_of"]
                    )
                return PendingPetition(**fields)

            monkeypatch.setattr(
                "ming.month_steps.sources.PendingPetition", identify_original
            )
        client.post("/actions", json={"action": "month"})
        monkeypatch.undo()
        petitions = client.get("/state").json()["game"]["petitions"]
        original = petitions[0]
        for index, petition in enumerate(petitions):
            client.post(
                "/actions",
                json={
                    "action": "choose",
                    "petition": petition["id"],
                    "option": len(petition["options"]) - 1 if index == 0 else 0,
                },
            ).raise_for_status()
        assert client.get("/state").json()["game"]["returned_petitions"] == []
        for phase, month in (("vacancy", 12), ("appointment", 1)):
            case = json.loads((RECORDED / f"sources_{phase}.json").read_text())
            steps["scene"] = replaying(case["scenes"])
            steps["NightDeclaration"] = replaying([case["declaration"]])
            if phase == "appointment":
                steps["urgent"] = replaying([revision] * 2, drafting)
            client.post("/actions", json={"action": "open"})
            for words in case["words"]:
                client.post("/actions", json={"action": "say", "words": words})
            client.post("/actions", json={"action": "dismiss"})
            client.post("/actions", json={"action": "month"})
            state = client.get("/state").json()["game"]
            if phase == "appointment" and not valid_revision:
                assert state["failure"] is not None
                assert state["failure"]["payload"]["type"] == "UnexpectedModelBehavior"
                assert state["date"]["month"] == 12
                assert state["petitions"] == []
                assert [p["petition"]["id"] for p in state["returned_petitions"]] == [
                    original["id"]
                ]
                assert [
                    (json.loads(p.content)["field"], json.loads(p.content)["expected"])
                    for m in drafting
                    for p in m.parts
                    if isinstance(p, RetryPromptPart)
                ] == [("revision_of", [original["id"]])]
            else:
                assert state["failure"] is None
                assert state["date"]["month"] == month
                if phase == "vacancy":
                    assert state["petitions"] == []
                    assert [
                        (p["petition"]["id"], p["awaiting_drafter"])
                        for p in state["returned_petitions"]
                    ] == [(original["id"], True)]
                else:
                    assert [
                        (p["signer"], p["revision_of"])
                        for p in state["petitions"]
                        if p["revision_of"]
                    ] == [("曹化淳", original["id"])]
                    assert state["returned_petitions"] == []
            material = json.loads(received[-1].parts[0].content)["context"]
            assert {p["petition_id"] for p in material["prior_choices"]} == (
                {petitions[1]["id"]} if phase == "vacancy" else set()
            )
            client.post("/actions", json={"action": "load", "save": game_db.name})
            assert client.get("/state").json()["game"] == state
        material = json.loads(drafting[0].parts[0].content)["context"]
        assert [p["name"] for p in material["drafters"]] == ["曹化淳"]
        assert [p["id"] for p in material["returned"]] == [original["id"]]


@pytest.mark.parametrize(
    "case",
    [
        (300000, 300000, False),
        (3200000, 3200000, False),
        (5000000, 3200000, False),
        (5000000, 3200000, "write"),
        (5000000, 3200000, "commit"),
    ],
)
def test_month_lands_both_sides_at_source_stock_and_preserves_nominal(
    tmp_path: Path, game_db: Path, case, steps, audit
) -> None:
    nominal, actual, interrupt = case
    steps["Declaration"] = TestModel(
        call_tools=[],
        custom_output_text=(RECORDED / f"month_money_{nominal}.txt").read_text(),
    )
    observed = []

    def before_commit(session):
        # Outer SQLAlchemy commit: policy rows and tracking exist, none durable.
        current = tuple(session.execute(text(q)).scalar_one() for q in LANDING)
        if current[1] and not observed:
            observed.append(current)
            raise RuntimeError("injected pre-commit failure")

    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        db = tmp_path / save
        if interrupt == "write":
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "CREATE TRIGGER interrupt BEFORE UPDATE ON entities WHEN NEW.key='内库' BEGIN SELECT RAISE(ABORT, 'injected'); END"
                )
        if interrupt == "commit":
            event.listen(Session, "before_commit", before_commit)
        try:
            client.post("/actions", json={"action": "month"})
        finally:
            if interrupt == "commit":
                event.remove(Session, "before_commit", before_commit)
        with sqlite3.connect(db) as connection:
            durable = tuple(connection.execute(q).fetchone()[0] for q in LANDING)
        assert durable[0] == durable[2] and bool(durable[1]) != bool(interrupt)
        if interrupt == "commit":
            assert observed[0][0] == observed[0][2] > durable[0]
        if interrupt:
            ledger = audit(db)
            assert {
                e["key"]: e["data"]["taels"]
                for e in ledger["entities"]
                if e["kind"] == "account"
            } == {"国库": 3200000, "内库": 4400000}
            assert not [
                f for f in ledger["facts"] if f["kind"] in {"changed", "landed"}
            ]
            with sqlite3.connect(db) as connection:
                connection.execute("DROP TRIGGER IF EXISTS interrupt")
            client.post("/actions", json={"action": "load", "save": save})
            assert client.get("/state").json()["game"]["failure"] is not None
            client.post("/actions", json={"action": "retry"})
        ledger = audit(db)
        assert {
            e["key"]: e["data"]["taels"]
            for e in ledger["entities"]
            if e["kind"] == "account"
        } == pytest.approx(
            {"国库": 11940269.2869425 - actual, "内库": 7657600 + actual}
        )
        transfers = [
            f["detail"]
            for f in ledger["facts"]
            if f["kind"] == "changed" and "taels" in f["detail"]["nominal"]
        ]
        assert [(t["nominal"]["taels"], t["actual"]["taels"]) for t in transfers] == [
            (-nominal, -actual),
            (nominal, actual),
        ]
        public = audit(db, identity="public")
        assert not [e for e in public["entities"] if e["kind"] == "account"]
        assert all(
            "nominal" not in f["detail"] and "actual" not in f["detail"]
            for f in public["facts"]
        )
        if nominal == 5000000:
            reports = [f for f in public["facts"] if f["kind"] == "reported"]
            assert reports
            assert all(set(f["detail"]) == {"text"} for f in reports)
            treasury = next(e["id"] for e in ledger["entities"] if e["key"] == "国库")
            assert all(f["entity_id"] == treasury for f in reports)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 11


DEBT = {
    "recording": "month_fiscal_payments.txt",
    "army_arrears": 60,
    "salary_arrears": (0,),
    "dues": (66,),
    "receipts": [],
    "quota": 2.1969011325,
    "prior_paid": 0,
    "stipend_arrears": 0,
    "court_arrears": 0,
    "payment_order": GUOKU_ORDER,
    "army_order": ARMY_ORDER,
}


@pytest.mark.parametrize(
    ("opening_db", "case"),
    [
        (
            None,
            {
                "recording": "month_fiscal_policy.txt",
                "army_arrears": 40,
                "salary_arrears": (25, 25, 25, 25),
                "dues": (33, 33, 33, 66),
                "receipts": [("补欠", 200000, 200000, None)],
                "quota": 5.1969011325,
            },
        ),
        (
            None,
            {
                "army_arrears": 0,
                "salary_arrears": (0, 0),
                "dues": (66, 66),
                "receipts": [
                    ("补欠", 5000000, 600000, "obligation"),
                    ("当月饷", 5000000, 144000, "obligation"),
                    ("犒赏", 50000, 50000, None),
                    ("专项", 60000, 60000, None),
                ],
                "prior_paid": 14.4,
            },
        ),
        (
            "shortage",
            {
                "salary_arrears": (992.97307130575, 1985.9461426115),
                "dues": (66, 66),
                "receipts": [
                    ("补欠", 5000000, 0, "balance"),
                    ("当月饷", 5000000, 0, "balance"),
                    ("犒赏", 50000, 0, "balance"),
                    ("专项", 60000, 0, "balance"),
                ],
                "stipend_arrears": 66,
                "court_arrears": 667.24,
            },
        ),
        pytest.param(
            None,
            {
                "recording": "month_fiscal_reorder.txt",
                "payment_order": BORDER_ORDER,
                "army_order": BORDER_ARMIES,
            },
            id="reorder",
        ),
        pytest.param(
            None,
            {
                "recording": "month_fiscal_building.txt",
                "building": "钦定银矿",
            },
            id="building",
        ),
        pytest.param(
            "prestige",
            {
                "recording": "month_empty.txt",
                "prestige": 100,
            },
            id="prestige",
        ),
    ],
    indirect=["opening_db"],
)
def test_month_keeps_debt_separate_from_reduction_and_temporary_deferral(
    opening_db, game_db: Path, steps, audit, case
) -> None:
    case = {**DEBT, **case}
    steps["Declaration"] = replaying([(RECORDED / case["recording"]).read_text()])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        for index, due in enumerate(case["dues"]):
            assert client.post("/actions", json={"action": "month"}).status_code == 204
            assert client.get("/state").json()["game"]["failure"] is None
            ledger = audit(game_db)
            rows = {(e["kind"], e["key"]): e["data"] for e in ledger["entities"]}
            assert rows[("army", "关宁军 / 宁锦防线")]["arrears"] == case["army_arrears"]
            assert rows[("fiscal", "官俸_base")]["arrears"] == pytest.approx(
                case["salary_arrears"][index]
            )
            assert rows[("fiscal", "宗室禄米_base")]["arrears"] == case["stipend_arrears"] * (index + 1)
            assert rows[("fiscal", "宫廷_base")]["arrears"] == pytest.approx(
                case["court_arrears"] * (index + 1)
            )
            assert (
                rows[("fiscal", "内廷俸_base")]["arrears"]
                == rows[("fiscal", "妃嫔_base")]["arrears"]
                == 0
            )
            assert all(
                e["data"]["taels"] >= 0
                for e in ledger["entities"]
                if e["kind"] == "account"
            )
            assert rows[("region", "陕西")]["fiscal"]["settle"]["p"][
                "起运定额"
            ] == pytest.approx(case["quota"])
            stipends = [
                f["detail"]
                for f in ledger["facts"]
                if f["kind"] == "monthly_payment"
                and f["detail"]["recipient"] == "宗室禄米_base"
            ]
            assert (stipends[-1]["due"], stipends[-1]["paid"]) == (due, due - case["stipend_arrears"])
            receipts = [f["detail"] for f in ledger["facts"] if f["kind"] == "received"]
            assert [
                (r["purpose"], r["nominal"], r["actual"], r["limit_reason"])
                for r in receipts
            ] == case["receipts"]
            army_payments = [
                f["detail"]
                for f in ledger["facts"]
                if f["kind"] == "monthly_payment"
                and f["detail"]["recipient"] == "关宁军 / 宁锦防线"
            ]
            assert army_payments[-1]["prior_paid"] == (case["prior_paid"] if index == 0 else 0)
            assert army_payments[-1]["paid"] + army_payments[-1][
                "prior_paid"
            ] == pytest.approx(14.4)
            account = rows[("account", "国库")]
            assert account["payment_order"] == case["payment_order"]
            assert account["army_order"] == case["army_order"]
            paid = [
                f["detail"]["recipient"]
                for f in ledger["facts"]
                if f["kind"] == "monthly_payment"
                and f["entity_id"]
                == next(e["id"] for e in ledger["entities"] if e["key"] == "国库")
            ]
            expected = [
                name
                for category in case["payment_order"]
                for name in (case["army_order"] if category == "军饷" else (category,))
            ]
            assert paid[-len(expected) :] == expected
            if case.get("building"):
                building = rows[("building", case["building"])]
                assert next(
                    f["detail"]["amount"]
                    for f in ledger["facts"]
                    if f["kind"] == "monthly_income"
                    and f["detail"].get("source") == case["building"]
                ) == pytest.approx(
                    building["output_amount"] * building["condition"] / 100
                )
                assert building["condition"] != 100
            if "prestige" in case:
                assert (
                    rows[("world", "天下")]["imperial_prestige"] == case["prestige"]
                )
                assert (
                    next(
                        f["detail"]["actual"]
                        for f in ledger["facts"]
                        if f["kind"] == "monthly_output"
                        and f["detail"]["source"] == "帝国航空"
                    )
                    == 0
                )
            steps["Declaration"] = TestModel(
                call_tools=[],
                custom_output_text=(RECORDED / "month_empty.txt").read_text(),
            )


@pytest.mark.parametrize(
    ("opening_db", "case"),
    [
        (
            1631,
            (
                "month_fiscal_1631-haiku.json",
                "辽饷升至一分二厘",
                None,
                51.79786519425,
                0,
                None,
            ),
        ),
        (
            1631,
            ("month_fiscal_1631.json", "辽饷升至一分二厘", "已准", 69.063820259, 0, None),
        ),
        (
            1640,
            ("month_fiscal_1640.json", "剿饷议停", "已停", 51.79786519425, 0, None),
        ),
        pytest.param(
            1631,
            (
                "month_fiscal_1631.json",
                "辽饷升至一分二厘",
                None,
                51.79786519425,
                2,
                "month_empty.txt",
            ),
            id="retained",
        ),
        pytest.param(
            1631,
            (
                "month_fiscal_1631.json",
                "辽饷升至一分二厘",
                "已驳",
                51.79786519425,
                1,
                "month_fiscal_reject.txt",
            ),
            id="rejected",
        ),
    ],
    indirect=["opening_db"],
)
def test_fiscal_petition_lands_only_declared_outcome_without_readding_levies(
    opening_db, game_db: Path, steps, audit, case: tuple
) -> None:
    recording = json.loads((RECORDED / case[0]).read_text())
    for name, replies in recording.items():
        steps[name] = replaying(replies)
    if case[5] is not None:
        steps["Declaration"] = replaying([(RECORDED / case[5]).read_text()])
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name})
        client.post("/actions", json={"action": "month"})
        client.portal.call(client.app.state.web.game.drain)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 1
        assert state["petitions"][0]["blocking"] is True
        client.post(
            "/actions",
            json={
                "action": "choose",
                "petition": state["petitions"][0]["id"],
                "option": case[4],
            },
        )
        client.portal.call(client.app.state.web.game.drain)
        for month in (2, 3, 4):
            state = client.get("/state").json()["game"]
            assert state["failure"] is None
            assert state["date"]["month"] == month
            ledger = audit(game_db)
            assert (
                next(
                    e["data"].get("terminal_reason")
                    for e in ledger["entities"]
                    if (e["kind"], e["key"]) == ("event", case[1])
                )
                == case[2]
            )
            assert sum(
                e["data"]["fiscal"]["settle"]["p"]["三饷应征"]
                for e in ledger["entities"]
                if e["kind"] == "region" and "settle" in e["data"].get("fiscal", {})
            ) == pytest.approx(case[3])
            if month < 4:
                received = []
                for name, filename in (
                    ("simulation", "simulation.txt"),
                    ("Declaration", "month_empty.txt"),
                ):
                    steps[name] = replaying(
                        [(RECORDED / filename).read_text()],
                        received if name == "simulation" else None,
                    )
                client.post("/actions", json={"action": "month"})
                assert (
                    json.loads(received[-1].parts[0].content)["context"][
                        "fiscal_events"
                    ]
                    == []
                )


@pytest.mark.parametrize(
    "declared",
    [
        pytest.param((RECORDED / "month_invalid.txt").read_text(), id="invalid_shape"),
        pytest.param(
            [
                {
                    "entity_type": "event",
                    "entity": "辽饷升至一分二厘",
                    "create": False,
                    "changes": [{"field": "terminal_reason", "value": "不准"}],
                    "text": "结局不在该事件的闭集里",
                }
            ],
            id="terminal_reason",
        ),
        pytest.param(
            [
                {
                    "entity_type": "region",
                    "entity": "陕西",
                    "create": False,
                    "changes": [{"field": "fiscal_surcharge", "value": "三"}],
                    "text": "加派额不是数字",
                }
            ],
            id="surcharge_type",
        ),
        pytest.param(
            [
                {
                    "entity_type": "region",
                    "entity": "不存在省",
                    "create": True,
                    "changes": [{"field": "fiscal_surcharge", "value": 3}],
                    "text": "加派写到账本里没有的地区",
                }
            ],
            id="surcharge_region",
        ),
        pytest.param(
            [
                {
                    "entity_type": "account",
                    "entity": "国库",
                    "create": False,
                    "changes": [
                        {
                            "field": "payment_order",
                            "value": [
                                "军饷",
                                "官俸_base",
                                "宗室禄米_base",
                                "赈灾_base",
                                "工程_base",
                                "边饷",
                            ],
                        }
                    ],
                    "text": "改序写入不在科目里的名字",
                }
            ],
            id="payment_order",
        ),
        pytest.param(
            [
                {
                    "entity_type": "fiscal",
                    "entity": "宗室禄米_base",
                    "create": False,
                    "changes": [
                        {
                            "field": "payment_policy",
                            "value": {"factor": -0.5, "defer": 0.0},
                        }
                    ],
                    "text": "减额比例为负",
                }
            ],
            id="factor_negative",
        ),
        pytest.param(
            [
                {
                    "entity_type": "fiscal",
                    "entity": "宗室禄米_base",
                    "create": False,
                    "changes": [
                        {
                            "field": "payment_policy",
                            "value": {"factor": 1.5, "defer": 0.0},
                        }
                    ],
                    "text": "减额比例大于一",
                }
            ],
            id="factor_high",
        ),
        pytest.param(
            [
                {
                    "entity_type": "account",
                    "entity": "国库",
                    "create": False,
                    "changes": [
                        {
                            "field": "taels",
                            "value": -10000,
                            "counterpart": {
                                "entity_type": "army",
                                "entity": "关宁军 / 宁锦防线",
                            },
                        }
                    ],
                    "text": "付给军队的款没写名目",
                },
                {
                    "entity_type": "army",
                    "entity": "关宁军 / 宁锦防线",
                    "create": False,
                    "changes": [],
                    "text": "收到没写名目的拨付",
                },
            ],
            id="purpose_missing",
        ),
        pytest.param(
            [
                {
                    "entity_type": "account",
                    "entity": "国库",
                    "create": False,
                    "changes": [
                        {
                            "field": "taels",
                            "value": -10000,
                            "purpose": "赏赐",
                            "counterpart": {
                                "entity_type": "army",
                                "entity": "关宁军 / 宁锦防线",
                            },
                        }
                    ],
                    "text": "名目不在四类之内",
                },
                {
                    "entity_type": "army",
                    "entity": "关宁军 / 宁锦防线",
                    "create": False,
                    "changes": [],
                    "text": "收到名目不在四类的拨付",
                },
            ],
            id="purpose_unknown",
        ),
        pytest.param(
            [
                {
                    "entity_type": "account",
                    "entity": "国库",
                    "create": False,
                    "changes": [
                        {
                            "field": "taels",
                            "value": 10000,
                            "purpose": "犒赏",
                        }
                    ],
                    "text": "名目用在非军队非科目的款上",
                }
            ],
            id="purpose_misplaced",
        ),
        pytest.param(
            [
                {
                    "entity_type": "army",
                    "entity": "关宁军 / 宁锦防线",
                    "create": False,
                    "changes": [{"field": "arrears", "value": 0}],
                    "text": "直接声明欠额",
                }
            ],
            id="arrears",
        ),
    ],
)
def test_exhausted_month_declaration_is_unhandled_not_a_stopped_month(
    tmp_path: Path, game_db: Path, steps, audit, declared
) -> None:
    reply = (
        declared
        if isinstance(declared, str)
        else json.dumps({"facts": declared}, ensure_ascii=False)
    )
    steps["Declaration"] = replaying([reply, reply])
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        client.post("/actions", json={"action": "month"})
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["running"], state["failure"]) == (
            11,
            False,
            None,
        )
        facts = client.get("/records").json()["facts"]
        assert {f["kind"] for f in facts if f["kind"] != "interaction"} == {
            "unhandled",
            "gazette",
        }
        assert all(not f["detail"] for f in facts if f["kind"] == "unhandled")
        ledger = audit(tmp_path / save)
        assert {
            e["key"]: e["data"]["taels"]
            for e in ledger["entities"]
            if e["kind"] == "account"
        } == pytest.approx({"国库": 11940269.2869425, "内库": 7657600})
        rows = {(e["kind"], e["key"]): e["data"] for e in ledger["entities"]}
        assert rows[("event", "辽饷升至一分二厘")].get("terminal_reason") is None
        assert rows[("army", "关宁军 / 宁锦防线")]["arrears"] == 60
        assert rows[("account", "国库")]["payment_order"] == GUOKU_ORDER
        assert "fiscal_surcharge" not in rows[("region", "陕西")]
        assert "payment_policy" not in rows[("fiscal", "宗室禄米_base")]
        assert not any(e["key"] == "不存在省" for e in ledger["entities"])
        assert not any(f["kind"] == "received" for f in ledger["facts"])
        settled = [f for f in ledger["facts"] if f["kind"] == "month_accounts"]
        assert settled[-1]["detail"]["date"]["year"] == 1627
        assert settled[-1]["detail"]["date"]["month"] == 10
