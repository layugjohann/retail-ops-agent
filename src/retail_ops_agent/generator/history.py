"""Simulates the Client's trading over a run of days: sales, inventory and restocks.

Every Sales Channel starts each SKU at its order-up-to level. Each day, restocks due that day
arrive first, then demand is met from what is on hand (a SKU that runs out sells only what it
has), and when on hand plus on order falls to the reorder point a restock is ordered in whole case
packs; it arrives after the SKU's lead time. So inventory always equals the previous day's
inventory plus arrivals minus sales. The Client plans stock for the season's expected demand and
keeps enough on hand to cover well over a lead time, so clean data shows no stockout risk; planted
Anomalies (see anomalies.py) are what bring one about.

Online Shop sales are also broken into Order Lines. Paid lines add up to the day's sales;
cancelled and refunded lines are extra and never touched stock.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.catalog import Catalog, SalesChannelKind
from retail_ops_agent.generator.anomalies import (
    MAX_SURGED_ON_HAND,
    MIN_DAYS_BEFORE_SURGE,
    MIN_SURGED_LEAD_TIME_DAYS,
    MIN_SURGED_ON_HAND,
    SURGE_DAYS,
    SURGE_SHARES,
    AnomalyPlan,
    PlantedAnomaly,
)
from retail_ops_agent.generator.demand import DemandModel
from retail_ops_agent.upload_formats import OrderLineStatus

# Inventory is counted when Sales Channels close; Online Shop orders before then count for the day.
CLOSING_TIME = time(20, 45)

# The reorder point covers this many lead times of demand plus safety days, and the order-up-to
# level review days beyond that.
_LEAD_TIMES_COVERED = 2
_SAFETY_DAYS = 7
_REVIEW_DAYS = 14
# Plan stock for a little more than average demand, to ride out busy days.
_PLANNING_FACTOR = 1.2

_CANCELLED_SHARE = 0.05
_REFUNDED_SHARE = 0.03


@dataclass(frozen=True)
class SalesRow:
    day: date
    sales_channel: str
    sku: str
    quantity_sold: int
    net_sales: float


@dataclass(frozen=True)
class InventoryRow:
    """Units on hand at closing time."""

    day: date
    sales_channel: str
    sku: str
    on_hand: int


@dataclass(frozen=True)
class Restock:
    """Stock ordered from the SKU's Supplier, arriving before trading on arrives_on."""

    sales_channel: str
    sku: str
    ordered_on: date
    arrives_on: date
    quantity: int


@dataclass(frozen=True)
class OrderLine:
    order_id: str
    created_at: datetime
    sku: str
    quantity: int
    line_total: float
    status: OrderLineStatus


class History:
    """The generator's internal truth for a run of days."""

    def __init__(
        self,
        *,
        catalog: Catalog,
        days: tuple[date, ...],
        opening_stock: dict[str, dict[str, int]],
        sales: dict[tuple[str, date], list[SalesRow]],
        inventory: dict[tuple[str, date], list[InventoryRow]],
        restocks: tuple[Restock, ...],
        order_lines: dict[date, list[OrderLine]],
        planted_anomalies: tuple[PlantedAnomaly, ...] = (),
    ) -> None:
        self.catalog = catalog
        self.days = days
        self._opening_stock = opening_stock
        self._sales = sales
        self._inventory = inventory
        self.restocks = restocks
        self._order_lines = order_lines
        self.planted_anomalies = planted_anomalies

    def opening_stock(self, sales_channel: str) -> dict[str, int]:
        """Units of each SKU on hand before the first day."""
        return dict(self._opening_stock[sales_channel])

    def sales(self, sales_channel: str, day: date) -> list[SalesRow]:
        """One row per SKU, including SKUs that sold nothing."""
        return list(self._sales[(sales_channel, day)])

    def inventory(self, sales_channel: str, day: date) -> list[InventoryRow]:
        return list(self._inventory[(sales_channel, day)])

    def order_lines(self, day: date) -> list[OrderLine]:
        """The Online Shop's Order Lines for the day, in order of creation."""
        return list(self._order_lines[day])


def generate_history(
    catalog: Catalog, first_day: date, days: int, anomalies: Sequence[AnomalyPlan] = ()
) -> History:
    """Simulate trading from first_day for the given number of days, with each planned Anomaly
    planted. Deterministic for the seed and the plans."""
    if days < 1:
        raise ValueError("days must be at least 1")
    demand = DemandModel(catalog)
    run = tuple(first_day + timedelta(days=offset) for offset in range(days))
    surges = _plan_surges(catalog, run, anomalies)

    policies = _stock_policies(catalog, demand)
    opening = _opening_stock(catalog, policies)
    on_hand = {(code, sku): units for code, stock in opening.items() for sku, units in stock.items()}
    on_order: dict[tuple[str, str], list[Restock]] = {key: [] for key in on_hand}

    sales: dict[tuple[str, date], list[SalesRow]] = {}
    inventory: dict[tuple[str, date], list[InventoryRow]] = {}
    restocks: list[Restock] = []
    order_lines: dict[date, list[OrderLine]] = {}

    for day in run:
        for channel in catalog.sales_channels:
            wanted = demand.draw(channel.code, day)
            sold: dict[str, int] = {}
            surge = surges.get((channel.code, day))
            if surge is not None and surge.sku is None:
                surge.choose_sku(catalog, on_hand, on_order)
            for sku in catalog.skus:
                key = (channel.code, sku.code)
                arriving = [r for r in on_order[key] if r.arrives_on == day]
                on_order[key] = [r for r in on_order[key] if r.arrives_on != day]
                on_hand[key] += sum(r.quantity for r in arriving)

                surging = surge is not None and surge.sku == sku.code
                extra = surge.extra_demand(day, on_hand[key]) if surge is not None and surging else 0
                sold[sku.code] = min(wanted[sku.code] + extra, on_hand[key])
                on_hand[key] -= sold[sku.code]
                if surge is not None and surging:
                    surge.units_sold.append(sold[sku.code])

                quantity = policies[key].restock_quantity(
                    on_hand[key] + sum(r.quantity for r in on_order[key]),
                    demand.expected_units(channel.code, sku, day),
                )
                if quantity:
                    restock = Restock(
                        sales_channel=channel.code,
                        sku=sku.code,
                        ordered_on=day,
                        arrives_on=day + timedelta(days=sku.lead_time_days),
                        quantity=quantity,
                    )
                    on_order[key].append(restock)
                    restocks.append(restock)

            inventory[(channel.code, day)] = [
                InventoryRow(
                    day=day,
                    sales_channel=channel.code,
                    sku=sku.code,
                    on_hand=on_hand[(channel.code, sku.code)],
                )
                for sku in catalog.skus
            ]
            if channel.kind is SalesChannelKind.ONLINE_SHOP:
                lines = _order_lines(catalog, day, sold)
                order_lines[day] = lines
                paid_totals = _paid_totals(lines)
                sales[(channel.code, day)] = [
                    SalesRow(
                        day=day,
                        sales_channel=channel.code,
                        sku=sku.code,
                        quantity_sold=sold[sku.code],
                        net_sales=paid_totals.get(sku.code, 0.0),
                    )
                    for sku in catalog.skus
                ]
            else:
                sales[(channel.code, day)] = [
                    SalesRow(
                        day=day,
                        sales_channel=channel.code,
                        sku=sku.code,
                        quantity_sold=sold[sku.code],
                        net_sales=round(sold[sku.code] * sku.retail_price, 2),
                    )
                    for sku in catalog.skus
                ]

    return History(
        catalog=catalog,
        days=run,
        opening_stock=opening,
        sales=sales,
        inventory=inventory,
        restocks=tuple(restocks),
        order_lines=order_lines,
        planted_anomalies=tuple(surge.planted() for surge in dict.fromkeys(surges.values())),
    )


class _Surge:
    """A planted demand surge at one Sales Channel, on the SKU chosen the morning it begins."""

    def __init__(self, catalog: Catalog, plan: AnomalyPlan, days: tuple[date, ...]) -> None:
        self.plan = plan
        self.days = days
        self.sku: str | None = None
        self.units_sold: list[int] = []
        self._rng = random.Random(
            f"anomaly:{catalog.seed}:{plan.kind.value}:{plan.sales_channel}:{plan.day.isoformat()}"
        )

    def choose_sku(
        self,
        catalog: Catalog,
        on_hand: dict[tuple[str, str], int],
        on_order: dict[tuple[str, str], list[Restock]],
    ) -> None:
        """Pick a SKU that is comfortably stocked with nothing on order, so the surge alone drains it."""
        channel = self.plan.sales_channel
        candidates = [
            sku.code
            for sku in catalog.skus
            if sku.lead_time_days > MIN_SURGED_LEAD_TIME_DAYS
            and MIN_SURGED_ON_HAND <= on_hand[(channel, sku.code)] <= MAX_SURGED_ON_HAND
            and not on_order[(channel, sku.code)]
        ]
        if not candidates:
            raise ValueError(f"no SKU at {channel} can take a demand surge on {self.days[0].isoformat()}")
        self.sku = self._rng.choice(candidates)

    def extra_demand(self, day: date, on_hand: int) -> int:
        return math.ceil(on_hand * SURGE_SHARES[self.days.index(day)])

    def planted(self) -> PlantedAnomaly:
        assert self.sku is not None
        return PlantedAnomaly(
            kind=self.plan.kind,
            cause=self.plan.cause,
            sales_channel=self.plan.sales_channel,
            sku=self.sku,
            cause_starts_on=self.days[0],
            day=self.plan.day,
            units_sold=tuple(self.units_sold),
        )


def _plan_surges(
    catalog: Catalog, run: tuple[date, ...], plans: Sequence[AnomalyPlan]
) -> dict[tuple[str, date], _Surge]:
    channels = {c.code for c in catalog.sales_channels}
    surges: dict[tuple[str, date], _Surge] = {}
    for plan in plans:
        if plan.kind is not AnomalyKind.STOCKOUT_RISK:
            raise ValueError(f"Anomaly kind {plan.kind} cannot be planted yet")
        if plan.sales_channel not in channels:
            raise ValueError(f"{plan.sales_channel!r} is not a Sales Channel in the catalog")
        days = tuple(plan.day - timedelta(days=offset) for offset in reversed(range(SURGE_DAYS)))
        if days[-1] not in run or days[0] - timedelta(days=MIN_DAYS_BEFORE_SURGE) < run[0]:
            raise ValueError(
                f"a stockout risk on {plan.day.isoformat()} needs {MIN_DAYS_BEFORE_SURGE} days of trading "
                f"before its {SURGE_DAYS}-day surge, all within the generated days"
            )
        surge = _Surge(catalog, plan, days)
        for day in days:
            if (plan.sales_channel, day) in surges:
                raise ValueError(f"demand surges overlap at {plan.sales_channel} on {day.isoformat()}")
            surges[(plan.sales_channel, day)] = surge
    return surges


def generate_opening_stock(catalog: Catalog) -> dict[str, dict[str, int]]:
    """Units of each SKU on hand at each Sales Channel before trading starts, by Sales Channel code.

    The same stock generate_history opens with, whatever its first day. Deterministic for the seed.
    """
    return _opening_stock(catalog, _stock_policies(catalog, DemandModel(catalog)))


def _stock_policies(catalog: Catalog, demand: DemandModel) -> dict[tuple[str, str], _StockPolicy]:
    return {
        (channel.code, sku.code): _StockPolicy(
            base_units=demand.base_units(channel.code, sku),
            lead_time_days=sku.lead_time_days,
            case_pack=sku.case_pack,
        )
        for channel in catalog.sales_channels
        for sku in catalog.skus
    }


def _opening_stock(
    catalog: Catalog, policies: dict[tuple[str, str], _StockPolicy]
) -> dict[str, dict[str, int]]:
    """Every Sales Channel starts each SKU at its order-up-to level."""
    return {
        channel.code: {
            sku.code: policies[(channel.code, sku.code)].order_up_to(
                policies[(channel.code, sku.code)].base_units
            )
            for sku in catalog.skus
        }
        for channel in catalog.sales_channels
    }


@dataclass(frozen=True)
class _StockPolicy:
    """Reorder point and order-up-to level, planned for the expected daily demand of the season."""

    base_units: float
    lead_time_days: int
    case_pack: int

    def reorder_point(self, expected_units: float) -> int:
        days = _LEAD_TIMES_COVERED * self.lead_time_days + _SAFETY_DAYS
        return max(1, math.ceil(expected_units * _PLANNING_FACTOR * days))

    def order_up_to(self, expected_units: float) -> int:
        days = _LEAD_TIMES_COVERED * self.lead_time_days + _SAFETY_DAYS + _REVIEW_DAYS
        return math.ceil(expected_units * _PLANNING_FACTOR * days) + self.case_pack

    def restock_quantity(self, position: int, expected_units: float) -> int:
        """Whole case packs that bring on hand plus on order back up to the order-up-to level."""
        if position > self.reorder_point(expected_units):
            return 0
        return math.ceil((self.order_up_to(expected_units) - position) / self.case_pack) * self.case_pack


def _order_lines(catalog: Catalog, day: date, sold: dict[str, int]) -> list[OrderLine]:
    rng = random.Random(f"order-lines:{catalog.seed}:{day.isoformat()}")
    prices = {sku.code: sku.retail_price for sku in catalog.skus}

    pieces: list[tuple[str, int, OrderLineStatus]] = []
    for sku in catalog.skus:
        remaining = sold[sku.code]
        while remaining > 0:
            quantity = min(remaining, rng.choice((1, 1, 1, 2, 2, 3)))
            pieces.append((sku.code, quantity, OrderLineStatus.PAID))
            remaining -= quantity
            roll = rng.random()
            if roll < _CANCELLED_SHARE:
                pieces.append((sku.code, rng.randint(1, 2), OrderLineStatus.CANCELLED))
            elif roll < _CANCELLED_SHARE + _REFUNDED_SHARE:
                pieces.append((sku.code, rng.randint(1, 2), OrderLineStatus.REFUNDED))
    rng.shuffle(pieces)

    seconds_open = CLOSING_TIME.hour * 3600 + CLOSING_TIME.minute * 60
    orders: list[tuple[datetime, list[tuple[str, int, OrderLineStatus]]]] = []
    start = 0
    while start < len(pieces):
        size = rng.randint(1, 3)
        created_at = datetime.combine(day, time()) + timedelta(seconds=rng.randrange(seconds_open))
        orders.append((created_at, pieces[start : start + size]))
        start += size
    orders.sort(key=lambda order: order[0])

    lines: list[OrderLine] = []
    for number, (created_at, order_pieces) in enumerate(orders, start=1):
        order_id = f"WEB-{day:%Y%m%d}-{number:04d}"
        for sku_code, quantity, status in order_pieces:
            lines.append(
                OrderLine(
                    order_id=order_id,
                    created_at=created_at,
                    sku=sku_code,
                    quantity=quantity,
                    line_total=round(quantity * prices[sku_code], 2),
                    status=status,
                )
            )
    return lines


def _paid_totals(lines: list[OrderLine]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for line in lines:
        if line.status is OrderLineStatus.PAID:
            totals[line.sku] = totals.get(line.sku, 0.0) + line.line_total
    return {sku: round(total, 2) for sku, total in totals.items()}
