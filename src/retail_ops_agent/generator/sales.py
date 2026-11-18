"""Generates clean Store sales Uploads with plausible seasonality."""

from __future__ import annotations

import csv
import io
import math
import random
from dataclasses import dataclass
from datetime import date

from retail_ops_agent.catalog import Catalog, SalesChannelKind

STORE_SALES_COLUMNS = ("date", "store_code", "sku", "quantity_sold", "net_sales")

# Monday .. Sunday
_WEEKDAY_FACTOR = (0.85, 0.85, 0.9, 0.95, 1.1, 1.35, 1.2)

# Categories whose demand peaks in summer rather than in the winter gifting season.
_SUMMER_CATEGORIES = frozenset({"Garden"})


@dataclass(frozen=True)
class StoreSalesRow:
    day: date
    store_code: str
    sku: str
    quantity_sold: int
    net_sales: float


def generate_store_sales(catalog: Catalog, store_code: str, day: date) -> list[StoreSalesRow]:
    """The true sales for one Store and day: one row per SKU. Deterministic for the catalog seed."""
    store = next((c for c in catalog.stores if c.code == store_code), None)
    if store is None or store.kind is not SalesChannelKind.STORE:
        raise ValueError(f"{store_code!r} is not a Store in the catalog")

    store_rng = random.Random(f"store-size:{catalog.seed}:{store_code}")
    store_size = store_rng.uniform(0.6, 1.4)
    day_rng = random.Random(f"store-sales:{catalog.seed}:{store_code}:{day.isoformat()}")

    rows: list[StoreSalesRow] = []
    for sku in catalog.skus:
        popularity = random.Random(f"popularity:{catalog.seed}:{sku.code}").lognormvariate(0, 0.8)
        # Cheaper SKUs sell more units.
        price_factor = 20.0 / (20.0 + sku.retail_price)
        expected = (
            1.5
            * store_size
            * popularity
            * price_factor
            * _WEEKDAY_FACTOR[day.weekday()]
            * _season_factor(day, sku.category)
        )
        quantity = _poisson(day_rng, expected)
        rows.append(
            StoreSalesRow(
                day=day,
                store_code=store_code,
                sku=sku.code,
                quantity_sold=quantity,
                net_sales=round(quantity * sku.retail_price, 2),
            )
        )
    return rows


def store_sales_csv(rows: list[StoreSalesRow]) -> str:
    """Render Store sales rows in the Stores' Upload format."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(STORE_SALES_COLUMNS)
    for row in rows:
        writer.writerow(
            [row.day.isoformat(), row.store_code, row.sku, row.quantity_sold, f"{row.net_sales:.2f}"]
        )
    return buffer.getvalue()


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
