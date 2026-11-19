"""Plans and ground truth for Anomalies and lookalikes planted in the generated history (ADR 0005).

Each Anomaly kind is planted with a cause the data reveals:

- A stockout risk is planted as a demand surge: for a few days running up to the planned day, one
  comfortably stocked SKU at one Sales Channel sells far beyond its usual rate and drains its stock
  faster than a Restock can arrive. Its sales over those days stand far above its own history.
- A sales drop at one Sales Channel is planted as a footfall drop: for a few days, fewer shoppers
  come, so every SKU at that Sales Channel sells well under its usual rate while stock stays on hand
  and the other Sales Channels sell as usual.
- A sales spike is planted as a local price cut: one well-stocked SKU at one Sales Channel is sold
  at a discount for a few days and sells several times its usual rate. The net sales a unit show the
  lower price, and the other Sales Channels sell it as usual at the full price.
- A slow mover is planted as fading demand: one SKU that sold steadily at one Sales Channel all but
  stops selling there while its stock stays on hand and Restocks already ordered still arrive.

A lookalike is something that looks like an Anomaly at one Sales Channel but is shared by the whole
chain, so must not be blamed on one Sales Channel:

- a chain-wide dip, in which every Sales Channel sells well under its usual rate for a few days;
- a chain-wide promotion, in which one SKU is sold at a discount at every Sales Channel and sells
  several times its usual rate everywhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, model_validator

from retail_ops_agent.anomalies import AnomalyKind

# Demand surge (stockout risk).
# How many days a planted demand surge lasts, ending on the planned day.
SURGE_DAYS = 3
# Of the units on hand each morning of the surge, the share the surge sells on top of usual demand.
SURGE_SHARES = (0.3, 0.5, 0.9)
# A surged SKU's Lead Time is longer than this, so no Restock ordered during the surge arrives in it.
MIN_SURGED_LEAD_TIME_DAYS = SURGE_DAYS + 3
# Stock a surged SKU must have the morning the surge begins, so the risk is the surge's doing and
# every day's sales stay plausible.
MIN_SURGED_ON_HAND = 30
MAX_SURGED_ON_HAND = 600
# Days of trading before the surge, so detection has a history to compare the surge with.
MIN_DAYS_BEFORE_SURGE = 7

# Footfall drop (sales drop) and chain-wide dip.
DROP_DAYS = 3
# The share of usual demand still bought on each day of a footfall drop or a chain-wide dip.
FOOTFALL_DROP_SHARE = 0.35
CHAIN_WIDE_DIP_SHARE = 0.4

# Price cut (sales spike) and chain-wide promotion.
SPIKE_DAYS = 3
# The discount on the retail price while the price cut or promotion lasts.
PRICE_CUT = 0.3
# Units bought each day of the price cut on top of usual demand, as a multiple of expected demand.
SPIKE_EXTRA_DEMAND = 3.0
# Only a SKU expected to sell at least this many units a day at the Sales Channel is price cut, so
# the spike stands out from day-to-day noise.
MIN_SPIKED_EXPECTED_UNITS = 3.0
# A chain-wide promotion is on a SKU expected to sell that much at this many Sales Channels or more.
MIN_PROMOTED_SALES_CHANNELS = 3
# A price-cut SKU keeps enough stock to cover its Lead Time and these days more at its average rate,
# raised by the spike, so the spike does not also become a stockout risk.
SPIKED_COVER_MARGIN_DAYS = 2
# How far the spike can raise the average rate stockout risk is judged on, as a multiple of expected
# demand, with a busy weekend and as little as a week of history before the spike.
SPIKED_AVERAGE_FACTOR = 1.9
# The busiest weekday, as a multiple of expected demand.
BUSIEST_WEEKDAY_FACTOR = 1.35

# Fading demand (slow mover).
FADE_DAYS = 8
# The share of usual demand still bought while demand has faded.
FADED_DEMAND_SHARE = 0.02
MIN_FADED_EXPECTED_UNITS = 3.0
MIN_FADED_ON_HAND = 40

# Days of trading before any other planted cause, so detection has a week of usual sales to compare
# with; two weeks before fading demand, since a slow seller's usual rate needs longer to settle.
MIN_DAYS_BEFORE_CAUSE = 7
MIN_DAYS_BEFORE_FADE = 14


class AnomalyCause(StrEnum):
    DEMAND_SURGE = "demand_surge"
    FOOTFALL_DROP = "footfall_drop"
    PRICE_CUT = "price_cut"
    FADING_DEMAND = "fading_demand"


class LookalikeCause(StrEnum):
    CHAIN_WIDE_DIP = "chain_wide_dip"
    CHAIN_WIDE_PROMOTION = "chain_wide_promotion"


# The cause each Anomaly kind is planted with.
PLANTED_CAUSES: dict[AnomalyKind, AnomalyCause] = {
    AnomalyKind.STOCKOUT_RISK: AnomalyCause.DEMAND_SURGE,
    AnomalyKind.SALES_DROP: AnomalyCause.FOOTFALL_DROP,
    AnomalyKind.SALES_SPIKE: AnomalyCause.PRICE_CUT,
    AnomalyKind.SLOW_MOVER: AnomalyCause.FADING_DEMAND,
}

# The Anomaly kind each lookalike resembles, and the cause it is planted with.
LOOKALIKE_CAUSES: dict[AnomalyKind, LookalikeCause] = {
    AnomalyKind.SALES_DROP: LookalikeCause.CHAIN_WIDE_DIP,
    AnomalyKind.SALES_SPIKE: LookalikeCause.CHAIN_WIDE_PROMOTION,
}


def _with_cause(data: object, causes: Mapping[AnomalyKind, StrEnum], what: str) -> object:
    """Fill in a plan's cause from its kind, refusing a kind with none or a cause that does not match."""
    if not isinstance(data, dict):
        return data
    fields = cast(dict[str, object], data)
    if "kind" not in fields:
        return fields
    kind = AnomalyKind(str(fields["kind"]))
    if kind not in causes:
        raise ValueError(f"no {what} of kind {kind.value} can be planted")
    expected = causes[kind]
    given = fields.get("cause")
    if given is not None and given != expected:
        raise ValueError(f"a planted {what} of kind {kind.value} has the cause {expected.value}")
    return {**fields, "cause": expected}


class AnomalyPlan(BaseModel):
    """An Anomaly to plant at a Sales Channel, showing by the given day. Its cause follows its kind."""

    model_config = ConfigDict(frozen=True)

    kind: AnomalyKind
    sales_channel: str
    day: date
    cause: AnomalyCause = AnomalyCause.DEMAND_SURGE

    @model_validator(mode="before")
    @classmethod
    def _cause_of_kind(cls, data: object) -> object:
        return _with_cause(data, PLANTED_CAUSES, "Anomaly")


class LookalikePlan(BaseModel):
    """A chain-wide pattern to plant, looking like an Anomaly of the given kind at every Sales Channel
    and showing by the given day. Its cause follows its kind."""

    model_config = ConfigDict(frozen=True)

    kind: AnomalyKind
    day: date
    cause: LookalikeCause = LookalikeCause.CHAIN_WIDE_DIP

    @model_validator(mode="before")
    @classmethod
    def _cause_of_kind(cls, data: object) -> object:
        return _with_cause(data, LOOKALIKE_CAUSES, "lookalike")


class PlantedAnomaly(BaseModel):
    """Ground truth for one planted Anomaly: where it is, what caused it and when it should be flagged.

    Detection should flag it for the Sales Channel and SKU (None for a sales drop, which is about the
    whole Sales Channel) on a day from cause_starts_on to day.
    """

    model_config = ConfigDict(frozen=True)

    kind: AnomalyKind
    cause: AnomalyCause
    sales_channel: str
    sku: str | None
    cause_starts_on: date
    day: date
    # Units sold on each day of the cause, oldest first: of the SKU at the Sales Channel, or of every
    # SKU together at the Sales Channel for a sales drop.
    units_sold: tuple[int, ...]


class PlantedLookalike(BaseModel):
    """Ground truth for one planted lookalike: what it resembles and what caused it.

    Detection should flag no Anomaly of its kind (for its SKU, if it has one) at any Sales Channel on
    any day from cause_starts_on to day: it is chain-wide, not a problem at one Sales Channel.
    """

    model_config = ConfigDict(frozen=True)

    kind: AnomalyKind
    cause: LookalikeCause
    sku: str | None
    cause_starts_on: date
    day: date
    # Units sold at every Sales Channel together on each day of the cause, oldest first: of the SKU,
    # or of every SKU for a chain-wide dip.
    units_sold: tuple[int, ...]
