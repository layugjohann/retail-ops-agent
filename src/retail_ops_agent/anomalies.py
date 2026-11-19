"""Anomaly detection: plain, reproducible statistics over the accepted BI data. No model is involved.

Four kinds of Anomaly are flagged:

- A stockout risk, when a SKU's days of cover at a Sales Channel (units on hand divided by its
  average daily units sold) drop below the Lead Time of the SKU from its Supplier: stock would run
  out before a Reorder placed today could arrive.
- A sales drop at one Sales Channel, when its units sold a day over the last few days fall far below
  its own usual rate *and* far below how the other Sales Channels moved over the same days. A drop
  every Sales Channel shares (a seasonal dip, a chain-wide quiet spell) is not blamed on one of them.
- A sales spike, when a SKU sells several times its usual rate at one Sales Channel on every one of
  the last few days while the other Sales Channels sell it as usual. A spike the whole chain shares
  is not blamed on one Sales Channel, and a spike that already threatens the stock is the stockout
  risk it causes, not a second Anomaly.
- A slow mover, when a SKU that used to sell steadily at a Sales Channel all but stops selling there
  while plenty of stock sits on hand, so further Reorders would only build it up.

Each is flagged once: on the first day it shows, not again while it lasts.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from retail_ops_agent.catalog import Sku

# Stockout risk.
# Average daily units sold are taken over the trailing window of days up to and including the day.
SALES_WINDOW_DAYS = 14
# Fewer days of accepted sales than this in the window is too little history to judge cover on.
MIN_SALES_DAYS = 7
# Below this many units a day, days of cover swing with every single sale, so slow sellers are left
# to the slow-mover statistics.
MIN_AVERAGE_DAILY_UNITS = 1.0

# A Sales Channel's usual rate is its average over this many days before the recent days compared
# with it, two whole weeks so busy weekends and quiet weekdays even out ...
USUAL_WINDOW_DAYS = 14
# ... and needs at least this many days of accepted sales among them.
MIN_USUAL_SALES_DAYS = 7
# A Sales Channel is compared with the others only when at least this many others have sales on the
# same days.
MIN_OTHER_SALES_CHANNELS = 2

# Sales drop at one Sales Channel.
# The recent days compared with the usual rate; every one needs accepted sales.
DROP_WINDOW_DAYS = 3
# Flagged when units a day fall to this share of the Sales Channel's own usual rate or less ...
DROP_SHARE = 0.6
# ... and to this share or less of the change the other Sales Channels saw over the same days.
DROP_SHARE_OF_OTHERS = 0.6

# Sales spike.
# Every one of this many recent days must be a spike day, with accepted sales.
SPIKE_WINDOW_DAYS = 3
# A spike day sells at least this many times the SKU's usual rate at the Sales Channel ...
SPIKE_RATIO = 2.5
# ... and at least this many units, so a slow seller's lucky day is not a spike.
SPIKE_MIN_DAILY_UNITS = 8
# The spike is local only while the other Sales Channels together sell the SKU at less than this many
# times their own usual rate over the same days; when they sell more than usual too, the spike must
# be SPIKE_RATIO times their rise.
SPIKE_MAX_OTHERS_RATIO = 1.5

# Slow mover.
# The recent days compared with the usual rate, of which at least MIN_SLOW_SALES_DAYS need accepted
# sales.
SLOW_WINDOW_DAYS = 7
MIN_SLOW_SALES_DAYS = 5
# A slow seller's usual rate swings a lot from week to week, so it is taken over a whole usual window.
SLOW_MIN_USUAL_SALES_DAYS = USUAL_WINDOW_DAYS
# Only a SKU that usually sells at least this many units a day can be seen to slow down.
SLOW_MIN_USUAL_DAILY_UNITS = 2.5
# Flagged when units a day fall to this share of the usual rate or less ...
SLOW_SHARE = 0.1
# ... with at least this many units on hand, lasting at least this many days at the recent rate.
SLOW_MIN_ON_HAND = 20
SLOW_MIN_DAYS_OF_COVER = 60.0


class AnomalyKind(StrEnum):
    STOCKOUT_RISK = "stockout_risk"
    SALES_DROP = "sales_drop"
    SALES_SPIKE = "sales_spike"
    SLOW_MOVER = "slow_mover"


class _AnomalyBase(BaseModel):
    """What every Anomaly has: its id, the day it was flagged and the Sales Channel it is at."""

    model_config = ConfigDict(frozen=True)

    anomaly_id: str
    day: date
    sales_channel: str


class StockoutRisk(_AnomalyBase):
    """Days of cover of a SKU at a Sales Channel below its Lead Time."""

    kind: Literal[AnomalyKind.STOCKOUT_RISK] = AnomalyKind.STOCKOUT_RISK
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


class SalesDrop(_AnomalyBase):
    """Units sold a day at one Sales Channel, every SKU together, far below its usual rate while the
    other Sales Channels held up.

    change and others_change are recent units a day as a share of the usual rate, for this Sales
    Channel and for the other Sales Channels together.
    """

    kind: Literal[AnomalyKind.SALES_DROP] = AnomalyKind.SALES_DROP
    sku: None = None
    recent_days: int
    recent_daily_units: float
    usual_days: int
    usual_daily_units: float
    change: float
    others_change: float
    other_sales_channels: int

    @property
    def summary(self) -> str:
        return (
            f"Sales drop at {self.sales_channel} on {self.day.isoformat()}: {self.recent_daily_units:.1f} "
            f"units a day over the last {self.recent_days} days, {self.change:.0%} of its usual "
            f"{self.usual_daily_units:.1f}, while the other {self.other_sales_channels} Sales Channels "
            f"sold {self.others_change:.0%} of their usual"
        )


class SalesSpike(_AnomalyBase):
    """A SKU selling several times its usual rate at one Sales Channel on each recent day, while the
    other Sales Channels sold it as usual.

    others_ratio is the other Sales Channels' recent units a day of the SKU, together, over their
    usual rate; None when they do not usually sell it.
    """

    kind: Literal[AnomalyKind.SALES_SPIKE] = AnomalyKind.SALES_SPIKE
    sku: str
    daily_units: tuple[int, ...]
    usual_days: int
    usual_daily_units: float
    lowest_ratio: float
    others_ratio: float | None
    other_sales_channels: int

    @property
    def summary(self) -> str:
        units = ", ".join(str(u) for u in self.daily_units)
        others = (
            f"the other {self.other_sales_channels} Sales Channels sold it at {self.others_ratio:.1f} times "
            "their usual rate"
            if self.others_ratio is not None
            else f"the other {self.other_sales_channels} Sales Channels do not usually sell it"
        )
        return (
            f"Sales spike for {self.sku} at {self.sales_channel} on {self.day.isoformat()}: {units} units "
            f"on the last {len(self.daily_units)} days, at least {self.lowest_ratio:.1f} times its usual "
            f"{self.usual_daily_units:.2f} a day, while {others}"
        )


class SlowMover(_AnomalyBase):
    """A SKU that all but stopped selling at a Sales Channel while plenty of stock sits on hand.

    days_of_cover is how long the stock on hand lasts at the recent rate; None if nothing sold.
    """

    kind: Literal[AnomalyKind.SLOW_MOVER] = AnomalyKind.SLOW_MOVER
    sku: str
    recent_days: int
    recent_daily_units: float
    usual_days: int
    usual_daily_units: float
    on_hand: int
    days_of_cover: float | None

    @property
    def summary(self) -> str:
        cover = (
            f"{self.days_of_cover:.0f} days of cover" if self.days_of_cover is not None else "no sales at all"
        )
        return (
            f"Slow mover {self.sku} at {self.sales_channel} on {self.day.isoformat()}: "
            f"{self.recent_daily_units:.2f} units a day over the last {self.recent_days} days of sales, "
            f"down from its usual {self.usual_daily_units:.2f}, with {self.on_hand} on hand ({cover})"
        )


type Anomaly = Annotated[StockoutRisk | SalesDrop | SalesSpike | SlowMover, Field(discriminator="kind")]

# The Anomaly kinds that are about one SKU; the others are about a whole Sales Channel.
SKU_KINDS = frozenset({AnomalyKind.STOCKOUT_RISK, AnomalyKind.SALES_SPIKE, AnomalyKind.SLOW_MOVER})


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


def anomaly_id(kind: AnomalyKind, sales_channel: str, sku: str | None, day: date) -> str:
    return f"{kind.value}:{sales_channel}:{sku or 'all'}:{day.isoformat()}"


type _Key = tuple[str, str | None]


def detect_anomalies(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> list[Anomaly]:
    """Every Anomaly that first shows on the day, in a fixed order: by kind, Sales Channel and SKU."""
    previous_sales_day = day - timedelta(days=1)
    return [
        *detect_stockout_risks(bi, day, skus),
        *_new(lambda d: _sales_drops(bi, d), day, previous_sales_day),
        *_new(lambda d: _sales_spikes(bi, d, skus), day, previous_sales_day),
        *_new_by_inventory_day(bi, lambda d: _slow_movers(bi, d, skus), day),
    ]


def _new[A: _AnomalyBase](flag: Callable[[date], dict[_Key, A]], day: date, previous: date | None) -> list[A]:
    """The day's Anomalies that were not already showing on the previous day."""
    today = flag(day)
    before = flag(previous) if previous is not None and today else {}
    return [anomaly for key, anomaly in sorted(today.items(), key=_order) if key not in before]


def _order(item: tuple[_Key, object]) -> tuple[str, str]:
    channel, sku = item[0]
    return (channel, sku or "")


def _new_by_inventory_day[A: _AnomalyBase](
    bi: SalesAndStock, flag: Callable[[date], dict[_Key, A]], day: date
) -> list[A]:
    """Like _new, comparing each Sales Channel with its own previous day of accepted inventory."""
    today = flag(day)
    previous_days = bi.inventory_days_before(day)
    previous: dict[date, dict[_Key, A]] = {}
    flagged: list[A] = []
    for key, anomaly in sorted(today.items(), key=_order):
        before = previous_days.get(key[0])
        if before is not None:
            if before not in previous:
                previous[before] = flag(before)
            if key in previous[before]:
                continue
        flagged.append(anomaly)
    return flagged


def detect_stockout_risks(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> list[StockoutRisk]:
    """Every SKU and Sales Channel whose days of cover fell below the Lead Time on the day.

    Only a new risk is flagged: one that was not already below the Lead Time on the Sales Channel's
    previous day of accepted inventory, so a risk that lasts is flagged once.
    """
    return _new_by_inventory_day(bi, lambda d: _at_risk(bi, d, skus), day)


def _at_risk(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> dict[_Key, StockoutRisk]:
    first = day - timedelta(days=SALES_WINDOW_DAYS - 1)
    sold = bi.units_sold_between(first, day)
    sales_days = bi.sales_days_between(first, day)
    at_risk: dict[_Key, StockoutRisk] = {}
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
            at_risk[(channel, code)] = StockoutRisk(
                anomaly_id=anomaly_id(AnomalyKind.STOCKOUT_RISK, channel, code, day),
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


class _Rates:
    """Units a day by (Sales Channel, SKU) over a run of days, averaged over each Sales Channel's days
    of accepted sales among them."""

    def __init__(self, bi: SalesAndStock, first: date, last: date) -> None:
        self.days = bi.sales_days_between(first, last)
        self.units = bi.units_sold_between(first, last)

    def of(self, channel: str, sku: str) -> float:
        return self.units.get((channel, sku), 0) / self.days[channel]

    def total(self, channel: str) -> float:
        return sum(u for (c, _), u in self.units.items() if c == channel) / self.days[channel]


def _usual_window(recent_first: date) -> tuple[date, date]:
    last = recent_first - timedelta(days=1)
    return last - timedelta(days=USUAL_WINDOW_DAYS - 1), last


def _sales_drops(bi: SalesAndStock, day: date) -> dict[_Key, SalesDrop]:
    recent_first = day - timedelta(days=DROP_WINDOW_DAYS - 1)
    recent = _Rates(bi, recent_first, day)
    usual = _Rates(bi, *_usual_window(recent_first))
    rates = {
        channel: (recent.total(channel), usual.total(channel))
        for channel, days in recent.days.items()
        if days == DROP_WINDOW_DAYS and usual.days.get(channel, 0) >= MIN_USUAL_SALES_DAYS
    }
    drops: dict[_Key, SalesDrop] = {}
    for channel, (now, before) in rates.items():
        others = [rate for other, rate in rates.items() if other != channel]
        others_before = sum(b for _, b in others)
        if before <= 0 or len(others) < MIN_OTHER_SALES_CHANNELS or others_before <= 0:
            continue
        change = now / before
        others_change = sum(n for n, _ in others) / others_before
        if change <= DROP_SHARE and change <= DROP_SHARE_OF_OTHERS * others_change:
            drops[(channel, None)] = SalesDrop(
                anomaly_id=anomaly_id(AnomalyKind.SALES_DROP, channel, None, day),
                day=day,
                sales_channel=channel,
                recent_days=DROP_WINDOW_DAYS,
                recent_daily_units=round(now, 2),
                usual_days=usual.days[channel],
                usual_daily_units=round(before, 2),
                change=round(change, 3),
                others_change=round(others_change, 3),
                other_sales_channels=len(others),
            )
    return drops


def _sales_spikes(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> dict[_Key, SalesSpike]:
    days = [day - timedelta(days=offset) for offset in reversed(range(SPIKE_WINDOW_DAYS))]
    recent = _Rates(bi, days[0], day)
    usual = _Rates(bi, *_usual_window(days[0]))
    channels = [
        c
        for c, n in recent.days.items()
        if n == SPIKE_WINDOW_DAYS and usual.days.get(c, 0) >= MIN_USUAL_SALES_DAYS
    ]
    by_day = [bi.units_sold_between(d, d) for d in days]
    at_risk: dict[_Key, StockoutRisk] | None = None
    spikes: dict[_Key, SalesSpike] = {}
    for channel in channels:
        others = [c for c in channels if c != channel]
        if len(others) < MIN_OTHER_SALES_CHANNELS:
            continue
        for code in skus:
            units = tuple(sold.get((channel, code), 0) for sold in by_day)
            if min(units) < SPIKE_MIN_DAILY_UNITS:
                continue
            before = usual.of(channel, code)
            lowest_ratio = min(units) / before if before > 0 else float("inf")
            if lowest_ratio < SPIKE_RATIO:
                continue
            others_before = sum(usual.of(c, code) for c in others)
            others_now = sum(recent.of(c, code) for c in others)
            others_ratio = others_now / others_before if others_before > 0 else None
            if others_ratio is None:
                if others_now > 0:
                    continue
            elif others_ratio >= SPIKE_MAX_OTHERS_RATIO or lowest_ratio < SPIKE_RATIO * max(
                1.0, others_ratio
            ):
                # Shared by the other Sales Channels, or no more than the chain-wide rise.
                continue
            if at_risk is None:
                at_risk = _at_risk(bi, day, skus)
            if (channel, code) in at_risk:
                # A spike that already threatens the stock is flagged as the stockout risk it causes.
                continue
            spikes[(channel, code)] = SalesSpike(
                anomaly_id=anomaly_id(AnomalyKind.SALES_SPIKE, channel, code, day),
                day=day,
                sales_channel=channel,
                sku=code,
                daily_units=units,
                usual_days=usual.days[channel],
                usual_daily_units=round(before, 2),
                lowest_ratio=round(min(lowest_ratio, 999.0), 1),
                others_ratio=round(others_ratio, 2) if others_ratio is not None else None,
                other_sales_channels=len(others),
            )
    return spikes


def _slow_movers(bi: SalesAndStock, day: date, skus: Mapping[str, Sku]) -> dict[_Key, SlowMover]:
    recent_first = day - timedelta(days=SLOW_WINDOW_DAYS - 1)
    recent = _Rates(bi, recent_first, day)
    usual = _Rates(bi, *_usual_window(recent_first))
    slow: dict[_Key, SlowMover] = {}
    for (channel, code), on_hand in bi.stock_on(day).items():
        if code not in skus or on_hand < SLOW_MIN_ON_HAND:
            continue
        if recent.days.get(channel, 0) < MIN_SLOW_SALES_DAYS:
            continue
        if usual.days.get(channel, 0) < SLOW_MIN_USUAL_SALES_DAYS:
            continue
        before = usual.of(channel, code)
        now = recent.of(channel, code)
        if before < SLOW_MIN_USUAL_DAILY_UNITS or now > SLOW_SHARE * before:
            continue
        cover = on_hand / now if now > 0 else None
        if cover is not None and cover < SLOW_MIN_DAYS_OF_COVER:
            continue
        slow[(channel, code)] = SlowMover(
            anomaly_id=anomaly_id(AnomalyKind.SLOW_MOVER, channel, code, day),
            day=day,
            sales_channel=channel,
            sku=code,
            recent_days=recent.days[channel],
            recent_daily_units=round(now, 2),
            usual_days=usual.days[channel],
            usual_daily_units=round(before, 2),
            on_hand=on_hand,
            days_of_cover=round(cover, 1) if cover is not None else None,
        )
    return slow
