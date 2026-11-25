"""Daily demand per Sales Channel and SKU, with weekday and seasonal patterns."""

from __future__ import annotations

import math
import random
from datetime import date
from functools import cache

from retail_ops_agent.catalog import Catalog, SalesChannelKind, Sku

# Monday .. Sunday
_STORE_WEEKDAY_FACTOR = (0.85, 0.85, 0.9, 0.95, 1.1, 1.35, 1.2)
# The Online Shop is flatter through the week, with a Sunday-evening bump.
_ONLINE_SHOP_WEEKDAY_FACTOR = (1.05, 1.0, 0.95, 0.95, 0.9, 0.95, 1.2)

# Categories whose demand peaks in summer rather than in the winter gifting season.
_SUMMER_CATEGORIES = frozenset({"Garden"})


class DemandModel:
    """Expected and drawn daily demand. Deterministic for the catalog seed."""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._popularity = {
            sku.code: random.Random(f"popularity:{catalog.seed}:{sku.code}").lognormvariate(0, 0.8)
            for sku in catalog.skus
        }
        self._size: dict[str, float] = {}
        self._weekday: dict[str, tuple[float, ...]] = {}
        for channel in catalog.sales_channels:
            rng = random.Random(f"sales-channel-size:{catalog.seed}:{channel.code}")
            if channel.kind is SalesChannelKind.STORE:
                self._size[channel.code] = rng.uniform(0.6, 1.4)
                self._weekday[channel.code] = _STORE_WEEKDAY_FACTOR
            else:
                self._size[channel.code] = rng.uniform(1.6, 2.4)
                self._weekday[channel.code] = _ONLINE_SHOP_WEEKDAY_FACTOR

    def base_units(self, sales_channel: str, sku: Sku) -> float:
        """Average daily units ignoring weekday and season."""
        # Cheaper SKUs sell more units.
        price_factor = 20.0 / (20.0 + sku.retail_price)
        return 1.5 * self._size[sales_channel] * self._popularity[sku.code] * price_factor

    def expected_units(self, sales_channel: str, sku: Sku, day: date) -> float:
        """Average daily units expected in the day's season, ignoring the weekday."""
        return self.base_units(sales_channel, sku) * _season_factor(day, sku.category)

    def draw(self, sales_channel: str, day: date) -> dict[str, int]:
        """Units each SKU is asked for at the Sales Channel on the day."""
        rng = random.Random(f"demand:{self._catalog.seed}:{sales_channel}:{day.isoformat()}")
        weekday = self._weekday[sales_channel][day.weekday()]
        return {
            sku.code: _poisson(
                rng, self.base_units(sales_channel, sku) * weekday * _season_factor(day, sku.category)
            )
            for sku in self._catalog.skus
        }


@cache
def _season_factor(day: date, category: str) -> float:
    day_of_year = day.timetuple().tm_yday
    if category in _SUMMER_CATEGORIES:
        # Peak around late June.
        return 1.0 + 0.6 * math.cos(2 * math.pi * (day_of_year - 175) / 365)
    # Gentle winter peak plus a sharp run-up to the gifting season in December.
    base = 1.0 + 0.15 * math.cos(2 * math.pi * (day_of_year - 355) / 365)
    gifting = 0.8 * math.exp(-(((day_of_year - 352) / 12) ** 2)) if day.month == 12 else 0.0
    return base + gifting


def _poisson(rng: random.Random, mean: float) -> int:
    """Knuth's algorithm; fine for the small means used here."""
    if mean <= 0:
        return 0
    limit = math.exp(-mean)
    k = 0
    p = 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1
