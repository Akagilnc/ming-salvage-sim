"""Deterministic monthly obligations and cash flows, in the ledger transaction."""

from copy import deepcopy

from ming.ledger import Entity, Item, Ledger
from ming.middle.calendar import calendar_row
from ming.middle.declaration import EntityRef, FiscalEnd, MonthlyFunding, PaymentPolicy
from ming.middle.queries import FUNDED_AFFAIRS

WAN = 10_000
# Building output goes to an account or a 0-100 world scale; "" yields nothing.
OUTPUT_SCALES = {"皇威": "imperial_prestige", "民心": "public_support"}
OUTPUT_METRICS = ["国库", "内库", *OUTPUT_SCALES, ""]
# Provincial taxes collected at a national rate, and the estate's own route.
REGION_TAXES = {"salt_tax": "盐税", "commerce_tax": "商税"}
ESTATE = "皇庄"
# Imported power name. The content id "ming" is rewritten at import and never stored.
MING = "大明"


def remitting_region(data: Item) -> bool:
    """Land, salt and commerce remit only from a region 大明 still holds."""
    return data.get("controlled_by") == MING


def settling(data: Item) -> bool:
    """A region the month accounts settle, not every region row."""
    return "settle" in data.get("fiscal", {})


def clamp_scale(value: float) -> float:
    return min(100, max(0, value))


def payable_army(data: Item) -> bool:
    """Pay an army only when 大明 owns it and it already has a salary rate."""
    return data.get("owner_power") == MING and "salary_rate" in data


def has_obligation(purpose: str, kind: str, data: Item) -> bool:
    """Whether this recipient actually carries the named obligation."""
    if purpose == "补欠":
        return "arrears" in data
    if purpose == "当月饷" and kind == "army":
        return payable_army(data)
    return purpose == "当月饷" and kind == "fiscal" and data.get("direction") == "expense"


def levers(config: list[Item]) -> list[str]:
    """Fiscal values the month accounts read; no other value is a decree lever."""
    return [
        *(row["key"] for row in config if row["data"]["budget_role"] == "fixed"),
        *(f"{category}_rate" for category in REGION_TAXES.values()),
        f"{ESTATE}_base",
        f"{ESTATE}_rate",
    ]


def past_end(date: Item, until: FiscalEnd | None) -> bool:
    return until is not None and (date["year"], date["month"]) > (until.year, until.month)


def active_policy(data: Item, date: Item) -> PaymentPolicy:
    policy = PaymentPolicy.model_validate(data.get("payment_policy", {}))
    if past_end(date, policy.until):
        return PaymentPolicy()
    return policy


def current_paid(data: Item, date: Item) -> float:
    payment = data.get("month_paid", {})
    return payment.get("amount", 0) if payment.get("date") == date else 0


def obligation(pair: tuple[str, str], existing: dict[tuple[str, str], Item]) -> float:
    """The same monthly obligation caps appropriations and monthly payment."""
    data = existing[pair]["data"]
    if pair[0] == "army":
        if not payable_army(data):
            return 0
        base = data.get("manpower", 0) * data.get("salary_rate", 0) / WAN
    elif pair[0] == "affair":
        funding = MonthlyFunding.model_validate(data["monthly_funding"])
        date = existing[("calendar", "world")]["data"]
        if past_end(date, funding.until):
            return 0
        base = funding.amount / WAN
    elif pair[1] == "建筑维护_base":
        base = sum(
            row["data"].get("maintenance", 0)
            for (kind, _), row in existing.items()
            if kind == "building"
        )
    else:
        rate = existing[("fiscal", pair[1].removesuffix("_base") + "_rate")]["data"][
            "value"
        ]
        base = data["value"] * rate / 100
    return base * active_policy(data, existing[("calendar", "world")]["data"]).factor


def due_levies(ledger: Ledger) -> list[Item]:
    date = calendar_row(ledger)["data"]
    events = {row["data"]["id"]: row for row in ledger.entities(kind="historical_event")}
    return [
        {"entity": row["key"], "data": row["data"]}
        for row in events.values()
        if row["data"].get("category") == "fiscal_levy"
        and (row["data"]["trigger_year"], row["data"]["trigger_month"])
        == (date["year"], date["month"])
        and row["data"].get("terminal_reason") is None
        and all(
            events[subject.split(".")[1]]["data"].get("terminal_reason")
            == required.removeprefix("==")
            for subject, required in row["data"]["trigger_gate"].items()
        )
    ]


class Accounts:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.rows = [
            ledger.get(row["id"])
            for row in [*ledger.read(FUNDED_AFFAIRS), *ledger.entities(
                kind=(
                    "calendar",
                    "account",
                    "fiscal",
                    "army",
                    "region",
                    "building",
                    "world",
                    "historical_event",
                )
            )]
        ]
        self.calendar = next(e for e in self.rows if e.kind == "calendar")
        self.date = self.calendar.data
        self.accounts = {e.key: e for e in self.rows if e.kind == "account"}
        self.config = {e.key: e for e in self.rows if e.kind == "fiscal"}
        self.buildings = [e for e in self.rows if e.kind == "building"]
        self.existing = {(e.kind, e.key): e.snapshot() for e in self.rows}

    def income(
        self, source: Entity, account: str, amount: float, category: str
    ) -> None:
        target = self.accounts[account]
        detail = {
            "date": self.date,
            "category": category,
            "source": source.key,
            "account": account,
            "amount": amount,
            "unit": "万两",
        }
        # One flow row on the receiving account; the detail names the source.
        target.record(
            "monthly_income", "", detail, {"taels": target.data["taels"] + amount * WAN}
        )

    def taxes(self) -> None:
        events = {
            e.key: e.data.get("terminal_reason") for e in self.rows if e.kind == "historical_event"
        }
        regions = [
            e
            for e in self.rows
            if e.kind == "region" and settling(e.data)
        ]
        land = sum(e.data["fiscal"]["settle"]["st"]["官民田"] for e in regions)
        jiao = events["剿饷开征"] == "已准" and events["剿饷议停"] != "已停"
        lian = events["练饷开征"] == "已准"
        liao_rate = 4 / 3 if events["辽饷升至一分二厘"] == "已准" else 1
        for region in regions:
            fiscal = deepcopy(region.data["fiscal"])
            settle = fiscal["settle"]
            settle["_meta"].setdefault(
                "正赋起运基线",
                max(0, settle["p"]["起运定额"] - settle["p"]["三饷应征"]),
            )
            settle["_meta"].setdefault("辽饷九厘基线", settle["p"]["三饷应征"])
            if "剿饷基线" not in settle["_meta"]:
                settle["_meta"].update(
                    {
                        "剿饷基线": settle["st"]["官民田"] / land * 280 / 12,
                        "练饷基线": settle["st"]["官民田"] / land * 730 / 12,
                    }
                )
            components = {
                "辽饷": settle["_meta"]["辽饷九厘基线"] * liao_rate,
                "剿饷": settle["_meta"]["剿饷基线"] if jiao else 0,
                "练饷": settle["_meta"]["练饷基线"] if lian else 0,
            }
            levies = sum(components.values())
            settle["p"].update(
                {
                    "三饷应征": levies,
                    "起运定额": max(
                        0,
                        settle["_meta"]["正赋起运基线"]
                        + levies
                        + region.data.get("fiscal_surcharge", 0),
                    ),
                }
            )
            region.record(
                "monthly_assessment",
                "",
                {
                    "date": self.date,
                    "levies": levies,
                    "components": components,
                    "surcharge": region.data.get("fiscal_surcharge", 0),
                    "remittance": settle["p"]["起运定额"],
                    "unit": "万两",
                },
                {"fiscal": fiscal},
            )

    def revenues(self) -> None:
        for region in (
            e for e in self.rows if e.kind == "region" and remitting_region(e.data)
        ):
            fiscal = region.data.get("fiscal", {})
            if settling(region.data):
                self.income(region, "国库", fiscal["settle"]["p"]["起运定额"], "起运")
            for field, category in REGION_TAXES.items():
                if field in fiscal:
                    self.income(
                        region,
                        "国库",
                        fiscal[field]
                        * self.config[category + "_rate"].data["value"]
                        / 100,
                        category,
                    )
        self.income(
            self.config[f"{ESTATE}_base"],
            "内库",
            obligation(("fiscal", f"{ESTATE}_base"), self.existing),
            ESTATE,
        )
        for item in self.config.values():
            if (
                item.data.get("direction") == "income"
                and item.data["budget_role"] == "fixed"
            ):
                self.income(
                    item,
                    item.data["account"],
                    obligation((item.kind, item.key), self.existing),
                    item.key,
                )

    def production(self) -> None:
        world = next(e for e in self.rows if e.kind == "world")
        for building in self.buildings:
            metric = building.data.get("output_metric", "")
            amount = (
                building.data.get("output_amount", 0)
                * building.data.get("condition", 100)
                / 100
            )
            if metric in self.accounts:
                self.income(building, metric, amount, "建筑产出")
            elif metric:
                field = OUTPUT_SCALES[metric]
                actual = clamp_scale(world.data[field] + amount)
                detail = {
                    "date": self.date,
                    "source": building.key,
                    "field": field,
                    "nominal": amount,
                    "actual": actual - world.data[field],
                }
                world.record("monthly_output", "", detail, {field: actual})

    def expenses(self) -> None:
        armies = {
            e.key: e for e in self.rows if e.kind == "army" and payable_army(e.data)
        }
        recipients = {(e.kind, e.key): e for e in self.rows}
        for account in self.accounts.values():
            for item in account.data.get("payment_order", []):
                if isinstance(item, dict):
                    ref = EntityRef.model_validate(item)
                    category = ref.entity
                    targets = [recipients[ref.entity_type, ref.entity]]
                elif item == "军饷":
                    category = item
                    order = dict.fromkeys([*account.data["army_order"], *armies])
                    targets = [armies[name] for name in order if name in armies]
                else:
                    category = item
                    targets = [self.config[category]]
                for target in targets:
                    self.pay(target, account, category)

    def pay(self, target: Entity, account: Entity, category: str) -> None:
        due = obligation((target.kind, target.key), self.existing)
        prior = current_paid(target.data, self.date)
        remaining = max(0, due - prior)
        policy = active_policy(target.data, self.date)
        paid = min(
            max(0, due * (1 - policy.defer) - prior), account.data["taels"] / WAN
        )
        detail: Item = {
            "date": self.date,
            "category": category,
            "recipient": target.key,
            "account": account.key,
            "due": due,
            "prior_paid": prior,
            "paid": paid,
            "unpaid": remaining - paid,
            "unit": "万两",
        }
        account.record(
            "monthly_payment",
            "",
            detail,
            {"taels": max(0, account.data["taels"] - paid * WAN)},
        )
        target.record(
            "monthly_payment",
            "",
            detail,
            {
                "arrears": target.data.get("arrears", 0) + (remaining - paid),
                "month_paid": {"date": self.date, "amount": prior + paid},
            },
        )

    def run(self) -> None:
        if self.ledger.facts(
            entity_id=self.calendar.id, kind="month_accounts", date=self.date
        ):
            return
        self.taxes()
        self.revenues()
        self.production()
        self.expenses()
        self.calendar.record("month_accounts", "", {"date": self.date})
        self.ledger.commit(self.rows)
