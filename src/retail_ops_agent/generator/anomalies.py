"""Plans and ground truth for Anomalies planted in the generated history (ADR 0005).

A stockout risk is planted as a demand surge: for a few days running up to the planned day, one
comfortably stocked SKU at one Sales Channel sells far beyond its usual rate and drains its stock
faster than a Restock can arrive. The cause is in the data: the SKU's sales over those days stand
far above its own history.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.anomalies import AnomalyKind

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


class AnomalyCause(StrEnum):
    DEMAND_SURGE = "demand_surge"


class AnomalyPlan(BaseModel):
    """An Anomaly to plant at a Sales Channel, showing by the given day."""

    model_config = ConfigDict(frozen=True)

    kind: AnomalyKind
    sales_channel: str
    day: date
    cause: AnomalyCause = AnomalyCause.DEMAND_SURGE


class PlantedAnomaly(BaseModel):
    """Ground truth for one planted Anomaly: where it is, what caused it and when it should be flagged.

    Detection should flag it for the Sales Channel and SKU on a day from cause_starts_on to day.
    """

    model_config = ConfigDict(frozen=True)

    kind: AnomalyKind
    cause: AnomalyCause
    sales_channel: str
    sku: str
    cause_starts_on: date
    day: date
    # Units the SKU sold at the Sales Channel on each day of the cause, oldest first.
    units_sold: tuple[int, ...]
