"""Anomaly detection: plain, reproducible statistics over the accepted BI data. No model is involved.

A stockout risk is flagged when a SKU's days of cover at a Sales Channel (units on hand divided by
its average daily units sold) drop below the Lead Time of the SKU from its Supplier: stock would run
out before a Reorder placed today could arrive.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.catalog import Sku

# Average daily units sold are taken over the trailing window of days up to and including the day.
SALES_WINDOW_DAYS = 14
# Fewer days of accepted sales than this in the window is too little history to judge cover on.
MIN_SALES_DAYS = 7
# Below this many units a day, days of cover swing with every single sale, so slow sellers are left
# to the slow-mover statistics.
MIN_AVERAGE_DAILY_UNITS = 1.0


class AnomalyKind(StrEnum):
    STOCKOUT_RISK = "stockout_risk"


class Anomaly(BaseModel):
    """A statistically unusual pattern in valid data, with the statistics that flagged it."""

    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    kind: AnomalyKind
    day: date
    sales_channel: str
    sku: str
    on_hand: int
    average_daily_units: float
    sales_days: int
    days_of_cover: float
    lead_time_days: int

    @property
    def summary(self) -> str:
        return (
            f"Stockout risk for {self.sku} at {self.sales_channel} on {self.day.isoformat()}: "
            f"{self.on_hand} on hand at {self.average_daily_units:.2f} units a day is "
            f"{self.days_of_cover:.1f} days of cover, below the {self.lead_time_days}-day Lead Time"
        )


class SalesAndStock(Protocol):
    """The read-only BI queries detection needs."""

    def stock_on(self, day: date) -> dict[tuple[str, str], int]:
        """Accepted units on hand by (Sales Channel, SKU) at the end of the day."""
        ...

    def units_sold_between(self, first: date, last: date) -> dict[tuple[str, str], int]:
        """Accepted units sold by (Sales Channel, SKU) over the days, both included."""
        ...

    def sales_days_between(self, first: date, last: date) -> dict[str, int]:
        """By Sales Channel: how many of the days have accepted sales."""
        ...

    def inventory_days_before(self, day: date) -> dict[str, date]:
        """By Sales Channel: the latest day before the given one with accepted inventory."""
        ...


def anomaly_id(kind: AnomalyKind, sales_channel: str, sku: str, day: date) -> str:
    return f"{kind.value}:{sales_channel}:{sku}:{day.isoformat()}"


def detect_stockout_risks(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> list[Anomaly]:
    """Every SKU and Sales Channel whose days of cover fell below the Lead Time on the day.

    Only a new risk is flagged: one that was not already below the Lead Time on the Sales Channel's
    previous day of accepted inventory, so a risk that lasts is flagged once.
    """
    today = _at_risk(bi, day, skus)
    previous_days = bi.inventory_days_before(day)
    previous: dict[date, dict[tuple[str, str], Anomaly]] = {}
    flagged: list[Anomaly] = []
    for key, anomaly in sorted(today.items()):
        before = previous_days.get(key[0])
        if before is not None:
            if before not in previous:
                previous[before] = _at_risk(bi, before, skus)
            if key in previous[before]:
                continue
        flagged.append(anomaly)
    return flagged


def _at_risk(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> dict[tuple[str, str], Anomaly]:
    first = day - timedelta(days=SALES_WINDOW_DAYS - 1)
    sold = bi.units_sold_between(first, day)
    sales_days = bi.sales_days_between(first, day)
    at_risk: dict[tuple[str, str], Anomaly] = {}
    for (channel, code), on_hand in bi.stock_on(day).items():
        sku = skus.get(code)
        days = sales_days.get(channel, 0)
        if sku is None or days < MIN_SALES_DAYS:
            continue
        average = sold.get((channel, code), 0) / days
        if average < MIN_AVERAGE_DAILY_UNITS:
            continue
        cover = on_hand / average
        if cover < sku.lead_time_days:
            at_risk[(channel, code)] = Anomaly(
                anomaly_id=anomaly_id(AnomalyKind.STOCKOUT_RISK, channel, code, day),
                kind=AnomalyKind.STOCKOUT_RISK,
                day=day,
                sales_channel=channel,
                sku=code,
                on_hand=on_hand,
                average_daily_units=round(average, 2),
                sales_days=days,
                days_of_cover=round(cover, 1),
                lead_time_days=sku.lead_time_days,
            )
    return at_risk
