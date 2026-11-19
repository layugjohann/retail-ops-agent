"""Simulates the Client's trading over a run of days: sales, inventory and restocks.

Every Sales Channel starts each SKU at its order-up-to level. Each day, restocks due that day
arrive first, then demand is met from what is on hand (a SKU that runs out sells only what it
has), and when on hand plus on order falls to the reorder point a restock is ordered in whole case
packs; it arrives after the SKU's lead time. So inventory always equals the previous day's
inventory plus arrivals minus sales. The Client plans stock for the season's expected demand and
keeps enough on hand to cover well over a lead time, so clean data shows no Anomaly; planted
Anomalies and lookalikes (see anomalies.py) are what bring them about.

Online Shop sales are also broken into Order Lines. Paid lines add up to the day's sales;
cancelled and refunded lines are extra and never touched stock.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.catalog import Catalog, SalesChannelKind, Sku
from retail_ops_agent.generator.anomalies import (
    BUSIEST_WEEKDAY_FACTOR,
    CHAIN_WIDE_DIP_SHARE,
    DROP_DAYS,
    FADE_DAYS,
    FADED_DEMAND_SHARE,
    FOOTFALL_DROP_SHARE,
    MAX_SURGED_ON_HAND,
    MIN_DAYS_BEFORE_CAUSE,
    MIN_DAYS_BEFORE_FADE,
    MIN_DAYS_BEFORE_SURGE,
    MIN_FADED_EXPECTED_UNITS,
    MIN_FADED_ON_HAND,
    MIN_PROMOTED_SALES_CHANNELS,
    MIN_SPIKED_EXPECTED_UNITS,
    MIN_SURGED_LEAD_TIME_DAYS,
    MIN_SURGED_ON_HAND,
    PRICE_CUT,
    SPIKE_DAYS,
    SPIKE_EXTRA_DEMAND,
    SPIKED_AVERAGE_FACTOR,
    SPIKED_COVER_MARGIN_DAYS,
    SURGE_DAYS,
    SURGE_SHARES,
    AnomalyPlan,
    LookalikePlan,
    PlantedAnomaly,
    PlantedLookalike,
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
        planted_lookalikes: tuple[PlantedLookalike, ...] = (),
    ) -> None:
        self.catalog = catalog
        self.days = days
        self._opening_stock = opening_stock
        self._sales = sales
        self._inventory = inventory
        self.restocks = restocks
        self._order_lines = order_lines
        self.planted_anomalies = planted_anomalies
        self.planted_lookalikes = planted_lookalikes

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
    catalog: Catalog,
    first_day: date,
    days: int,
    anomalies: Sequence[AnomalyPlan] = (),
    lookalikes: Sequence[LookalikePlan] = (),
) -> History:
    """Simulate trading from first_day for the given number of days, with each planned Anomaly and
    lookalike planted. Deterministic for the seed and the plans."""
    if days < 1:
        raise ValueError("days must be at least 1")
    demand = DemandModel(catalog)
    run = tuple(first_day + timedelta(days=offset) for offset in range(days))
    plants = _plan_plants(catalog, demand, run, anomalies, lookalikes)

    policies = _stock_policies(catalog, demand)
    opening = _opening_stock(catalog, policies)
    on_hand = {(code, sku): units for code, stock in opening.items() for sku, units in stock.items()}
    on_order: dict[tuple[str, str], list[Restock]] = {key: [] for key in on_hand}

    sales: dict[tuple[str, date], list[SalesRow]] = {}
    inventory: dict[tuple[str, date], list[InventoryRow]] = {}
    restocks: list[Restock] = []
    order_lines: dict[date, list[OrderLine]] = {}
    sku_index = {sku.code: index for index, sku in enumerate(catalog.skus)}

    for day in run:
        today = [p for p in plants if day in p.days]
        for plant in today:
            if day == plant.days[0]:
                plant.start(
                    on_hand,
                    on_order,
                    lambda channel, sku, day=day: _usual(sales, sku_index, channel, sku, day),
                )
        for channel in catalog.sales_channels:
            wanted = demand.draw(channel.code, day)
            sold: dict[str, int] = {}
            prices: dict[str, float] = {}
            here = [p for p in today if channel.code in p.sales_channels]
            for sku in catalog.skus:
                key = (channel.code, sku.code)
                arriving = [r for r in on_order[key] if r.arrives_on == day]
                on_order[key] = [r for r in on_order[key] if r.arrives_on != day]
                on_hand[key] += sum(r.quantity for r in arriving)

                asked = wanted[sku.code]
                price = sku.retail_price
                for plant in here:
                    if plant.touches(sku.code):
                        asked = plant.demand(channel.code, sku, day, asked, on_hand[key])
                        price = round(price * plant.price_factor, 2)
                prices[sku.code] = price
                sold[sku.code] = min(asked, on_hand[key])
                on_hand[key] -= sold[sku.code]
                for plant in here:
                    if plant.touches(sku.code):
                        plant.record(day, sold[sku.code])

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
                lines = _order_lines(catalog, day, sold, prices)
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
                        net_sales=round(sold[sku.code] * prices[sku.code], 2),
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
        planted_anomalies=tuple(p.planted_anomaly() for p in plants if p.lookalike is None),
        planted_lookalikes=tuple(p.planted_lookalike() for p in plants if p.lookalike is not None),
    )


class _Plant:
    """A planted cause: for some days it changes demand, and maybe the price, at some Sales Channels.

    Each kind of cause overrides the parts it changes. A cause about one SKU chooses it the morning
    it begins, from the stock on hand then.
    """

    price_factor = 1.0

    def __init__(
        self,
        catalog: Catalog,
        demand: DemandModel,
        *,
        kind: AnomalyKind,
        day: date,
        days: int,
        sales_channels: tuple[str, ...],
        anomaly: AnomalyPlan | None = None,
        lookalike: LookalikePlan | None = None,
    ) -> None:
        self.catalog = catalog
        self._demand = demand
        self.kind = kind
        self.anomaly = anomaly
        self.lookalike = lookalike
        self.days = tuple(day - timedelta(days=offset) for offset in reversed(range(days)))
        self.sales_channels = sales_channels
        self.sku: str | None = None
        self._units: dict[date, int] = {}
        place = anomaly.sales_channel if anomaly is not None else "chain"
        self.rng = random.Random(f"anomaly:{catalog.seed}:{kind.value}:{place}:{day.isoformat()}")

    def start(
        self,
        on_hand: dict[tuple[str, str], int],
        on_order: dict[tuple[str, str], list[Restock]],
        usual: Callable[[str, str], float],
    ) -> None:
        """Called the morning the cause begins, before any Sales Channel trades. usual gives a SKU's
        average daily units sold at a Sales Channel over the days before."""

    def touches(self, sku: str) -> bool:
        return self.sku is None or self.sku == sku

    def demand(self, sales_channel: str, sku: Sku, day: date, asked: int, on_hand: int) -> int:
        return asked

    def record(self, day: date, sold: int) -> None:
        self._units[day] = self._units.get(day, 0) + sold

    def _thin(self, asked: int, share: float) -> int:
        """Each unit asked for is still bought with the given chance."""
        return sum(1 for _ in range(asked) if self.rng.random() < share)

    def _expected(self, sales_channel: str, sku: Sku) -> float:
        return self._demand.expected_units(sales_channel, sku, self.days[0])

    def _choose(self, candidates: list[str], what: str) -> None:
        if not candidates:
            where = self.anomaly.sales_channel if self.anomaly is not None else "every Sales Channel"
            raise ValueError(f"no SKU at {where} can take {what} on {self.days[0].isoformat()}")
        self.sku = self.rng.choice(candidates)

    def planted_anomaly(self) -> PlantedAnomaly:
        assert self.anomaly is not None
        return PlantedAnomaly(
            kind=self.kind,
            cause=self.anomaly.cause,
            sales_channel=self.anomaly.sales_channel,
            sku=self.sku,
            cause_starts_on=self.days[0],
            day=self.days[-1],
            units_sold=tuple(self._units.get(d, 0) for d in self.days),
        )

    def planted_lookalike(self) -> PlantedLookalike:
        assert self.lookalike is not None
        return PlantedLookalike(
            kind=self.kind,
            cause=self.lookalike.cause,
            sku=self.sku,
            cause_starts_on=self.days[0],
            day=self.days[-1],
            units_sold=tuple(self._units.get(d, 0) for d in self.days),
        )


class _Surge(_Plant):
    """A demand surge on one comfortably stocked SKU with nothing on order, so it alone drains it."""

    def start(
        self,
        on_hand: dict[tuple[str, str], int],
        on_order: dict[tuple[str, str], list[Restock]],
        usual: Callable[[str, str], float],
    ) -> None:
        channel = self.sales_channels[0]
        self._choose(
            [
                sku.code
                for sku in self.catalog.skus
                if sku.lead_time_days > MIN_SURGED_LEAD_TIME_DAYS
                and MIN_SURGED_ON_HAND <= on_hand[(channel, sku.code)] <= MAX_SURGED_ON_HAND
                and not on_order[(channel, sku.code)]
            ],
            "a demand surge",
        )

    def demand(self, sales_channel: str, sku: Sku, day: date, asked: int, on_hand: int) -> int:
        return asked + math.ceil(on_hand * SURGE_SHARES[self.days.index(day)])


class _FootfallDrop(_Plant):
    """Fewer shoppers: every SKU is bought less, at one Sales Channel or, for a dip, at all of them."""

    def __init__(self, *args: Any, share: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._share = share

    def demand(self, sales_channel: str, sku: Sku, day: date, asked: int, on_hand: int) -> int:
        return self._thin(asked, self._share)


class _PriceCut(_Plant):
    """One SKU sold at a discount, at one Sales Channel or, for a promotion, at all of them, and
    bought several times as much as it usually sells. It is chosen well stocked wherever it usually
    sells well, so the spike there does not also become a stockout risk."""

    price_factor = 1.0 - PRICE_CUT

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rates: dict[str, float] = {}

    def start(
        self,
        on_hand: dict[tuple[str, str], int],
        on_order: dict[tuple[str, str], list[Restock]],
        usual: Callable[[str, str], float],
    ) -> None:
        candidates: list[str] = []
        rates: dict[str, dict[str, float]] = {}
        for sku in self.catalog.skus:
            # The rate the spike is measured against: the higher of what the SKU is expected to sell
            # and what it has been selling.
            rate = {c: max(self._expected(c, sku), usual(c, sku.code)) for c in self.sales_channels}
            busy = [c for c in self.sales_channels if self._expected(c, sku) >= MIN_SPIKED_EXPECTED_UNITS]
            needed = len(self.sales_channels) if self.lookalike is None else MIN_PROMOTED_SALES_CHANNELS
            if len(busy) < needed:
                continue
            if all(on_hand[(c, sku.code)] >= self._stock_needed(sku, rate[c]) for c in busy):
                candidates.append(sku.code)
                rates[sku.code] = rate
        self._choose(candidates, "a price cut")
        assert self.sku is not None
        self._rates = rates[self.sku]

    def _stock_needed(self, sku: Sku, rate: float) -> float:
        spike = SPIKE_DAYS * (rate * (BUSIEST_WEEKDAY_FACTOR + SPIKE_EXTRA_DEMAND) + 1)
        cover = rate * SPIKED_AVERAGE_FACTOR * (sku.lead_time_days + SPIKED_COVER_MARGIN_DAYS)
        return spike + cover

    def demand(self, sales_channel: str, sku: Sku, day: date, asked: int, on_hand: int) -> int:
        return asked + math.ceil(SPIKE_EXTRA_DEMAND * self._rates[sales_channel])


class _FadingDemand(_Plant):
    """One steadily selling SKU all but stops selling while stock stays on hand. A SKU with a Restock
    on its way is chosen where there is one, so the stock builds up while sales fade."""

    def start(
        self,
        on_hand: dict[tuple[str, str], int],
        on_order: dict[tuple[str, str], list[Restock]],
        usual: Callable[[str, str], float],
    ) -> None:
        channel = self.sales_channels[0]
        candidates = [
            sku
            for sku in self.catalog.skus
            if min(self._expected(channel, sku), usual(channel, sku.code)) >= MIN_FADED_EXPECTED_UNITS
            and on_hand[(channel, sku.code)] >= MIN_FADED_ON_HAND
        ]
        arriving = [
            sku.code
            for sku in candidates
            if any(r.arrives_on in self.days[1:] for r in on_order[(channel, sku.code)])
        ]
        self._choose(arriving or [sku.code for sku in candidates], "fading demand")

    def demand(self, sales_channel: str, sku: Sku, day: date, asked: int, on_hand: int) -> int:
        return self._thin(asked, FADED_DEMAND_SHARE)


def _usual(
    sales: dict[tuple[str, date], list[SalesRow]],
    sku_index: dict[str, int],
    channel: str,
    sku: str,
    day: date,
) -> float:
    """Average daily units of the SKU sold at the Sales Channel over the two weeks before the day."""
    days = [day - timedelta(days=offset) for offset in range(1, 15)]
    sold = [sales[(channel, d)][sku_index[sku]].quantity_sold for d in days if (channel, d) in sales]
    return sum(sold) / len(sold) if sold else 0.0


def _plan_plants(
    catalog: Catalog,
    demand: DemandModel,
    run: tuple[date, ...],
    anomalies: Sequence[AnomalyPlan],
    lookalikes: Sequence[LookalikePlan],
) -> list[_Plant]:
    channels = tuple(c.code for c in catalog.sales_channels)
    plants: list[_Plant] = []
    for plan in anomalies:
        if plan.sales_channel not in channels:
            raise ValueError(f"{plan.sales_channel!r} is not a Sales Channel in the catalog")
        common: dict[str, Any] = {"kind": plan.kind, "day": plan.day, "sales_channels": (plan.sales_channel,)}
        if plan.kind is AnomalyKind.STOCKOUT_RISK:
            plant: _Plant = _Surge(catalog, demand, days=SURGE_DAYS, anomaly=plan, **common)
        elif plan.kind is AnomalyKind.SALES_DROP:
            plant = _FootfallDrop(
                catalog, demand, days=DROP_DAYS, anomaly=plan, share=FOOTFALL_DROP_SHARE, **common
            )
        elif plan.kind is AnomalyKind.SALES_SPIKE:
            plant = _PriceCut(catalog, demand, days=SPIKE_DAYS, anomaly=plan, **common)
        else:
            plant = _FadingDemand(catalog, demand, days=FADE_DAYS, anomaly=plan, **common)
        plants.append(plant)
    for lookalike in lookalikes:
        common = {"kind": lookalike.kind, "day": lookalike.day, "sales_channels": channels}
        if lookalike.kind is AnomalyKind.SALES_DROP:
            plant = _FootfallDrop(
                catalog, demand, days=DROP_DAYS, lookalike=lookalike, share=CHAIN_WIDE_DIP_SHARE, **common
            )
        else:
            plant = _PriceCut(catalog, demand, days=SPIKE_DAYS, lookalike=lookalike, **common)
        plants.append(plant)

    taken: set[tuple[str, date]] = set()
    for plant in plants:
        before = {
            AnomalyKind.STOCKOUT_RISK: MIN_DAYS_BEFORE_SURGE,
            AnomalyKind.SLOW_MOVER: MIN_DAYS_BEFORE_FADE,
        }.get(plant.kind, MIN_DAYS_BEFORE_CAUSE)
        what = f"a planted {plant.kind.value} on {plant.days[-1].isoformat()}"
        if plant.days[-1] not in run or plant.days[0] - timedelta(days=before) < run[0]:
            raise ValueError(
                f"{what} needs {before} days of trading before its {len(plant.days)}-day cause, "
                "all within the generated days"
            )
        for channel in plant.sales_channels:
            for day in plant.days:
                if (channel, day) in taken:
                    raise ValueError(f"planted causes overlap at {channel} on {day.isoformat()}")
                taken.add((channel, day))
    return plants


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


def _order_lines(
    catalog: Catalog, day: date, sold: dict[str, int], prices: dict[str, float]
) -> list[OrderLine]:
    """The day's Order Lines, each SKU at the day's price."""
    rng = random.Random(f"order-lines:{catalog.seed}:{day.isoformat()}")

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
