"""Simulates the Client's trading over a run of days: sales, inventory and restocks.

Every Sales Channel starts each SKU at its order-up-to level. Each day, restocks due that day
arrive first, then demand is met from what is on hand (a SKU that runs out sells only what it
has), and when on hand plus on order falls to the reorder point a restock is ordered in whole case
packs; it arrives after the SKU's lead time. So inventory always equals the previous day's
inventory plus arrivals minus sales.

Online Shop sales are also broken into Order Lines. Paid lines add up to the day's sales;
cancelled and refunded lines are extra and never touched stock.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from retail_ops_agent.catalog import Catalog, SalesChannelKind, Sku
from retail_ops_agent.generator.demand import DemandModel
from retail_ops_agent.upload_formats import OrderLineStatus

# Inventory is counted when Sales Channels close; Online Shop orders before then count for the day.
CLOSING_TIME = time(20, 45)

# How many days of demand the reorder point and the order-up-to level cover beyond the lead time.
_SAFETY_DAYS = 3
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
    ) -> None:
        self.catalog = catalog
        self.days = days
        self._opening_stock = opening_stock
        self._sales = sales
        self._inventory = inventory
        self.restocks = restocks
        self._order_lines = order_lines

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


def generate_history(catalog: Catalog, first_day: date, days: int) -> History:
    """Simulate trading from first_day for the given number of days. Deterministic for the seed."""
    if days < 1:
        raise ValueError("days must be at least 1")
    demand = DemandModel(catalog)
    run = tuple(first_day + timedelta(days=offset) for offset in range(days))

    policies = {
        (channel.code, sku.code): _StockPolicy.for_sku(demand.base_units(channel.code, sku), sku)
        for channel in catalog.sales_channels
        for sku in catalog.skus
    }
    opening = {
        channel.code: {sku.code: policies[(channel.code, sku.code)].order_up_to for sku in catalog.skus}
        for channel in catalog.sales_channels
    }
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
            for sku in catalog.skus:
                key = (channel.code, sku.code)
                arriving = [r for r in on_order[key] if r.arrives_on == day]
                on_order[key] = [r for r in on_order[key] if r.arrives_on != day]
                on_hand[key] += sum(r.quantity for r in arriving)

                sold[sku.code] = min(wanted[sku.code], on_hand[key])
                on_hand[key] -= sold[sku.code]

                quantity = policies[key].restock_quantity(
                    on_hand[key] + sum(r.quantity for r in on_order[key])
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
    )


@dataclass(frozen=True)
class _StockPolicy:
    reorder_point: int
    order_up_to: int
    case_pack: int

    @classmethod
    def for_sku(cls, base_units: float, sku: Sku) -> _StockPolicy:
        daily = base_units * _PLANNING_FACTOR
        reorder_point = max(1, math.ceil(daily * (sku.lead_time_days + _SAFETY_DAYS)))
        order_up_to = math.ceil(daily * (sku.lead_time_days + _REVIEW_DAYS)) + sku.case_pack
        return cls(reorder_point=reorder_point, order_up_to=order_up_to, case_pack=sku.case_pack)

    def restock_quantity(self, position: int) -> int:
        """Whole case packs that bring on hand plus on order back up to the order-up-to level."""
        if position > self.reorder_point:
            return 0
        return math.ceil((self.order_up_to - position) / self.case_pack) * self.case_pack


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
