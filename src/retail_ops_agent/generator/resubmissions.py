"""Resubmissions: a later Upload for the same Sales Channel, day and kind, replacing the first.

A corrected resubmission is the Upload as it should have been sent: the clean one, without any
planted Defects. A changed resubmission is clean too, but the Uploader has revised some figures,
so its totals differ from the first Upload's by an amount the ground truth records.
"""

from __future__ import annotations

import csv
import io
import random
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.generator.formats import upload_csv
from retail_ops_agent.generator.history import History
from retail_ops_agent.upload_formats import OrderLineStatus, UploadFormat, format_for
from retail_ops_agent.uploads import UploadKind, UploadStatus

# How many rows a changed resubmission revises, and by how many units each.
_CHANGED_ROWS = 3
_MAX_UNIT_CHANGE = 4


class ResubmissionKind(StrEnum):
    CORRECTED = "corrected"
    CHANGED = "changed"


class ResubmissionPlan(BaseModel):
    """A resubmission of the Upload a Sales Channel sends for a day and kind."""

    model_config = ConfigDict(frozen=True)

    sales_channel: str
    day: date
    upload_kind: UploadKind
    resubmission_kind: ResubmissionKind


class PlantedResubmission(BaseModel):
    """Ground truth for one resubmission: what changed and what should happen to both Uploads."""

    model_config = ConfigDict(frozen=True)

    sales_channel: str
    day: date
    upload_kind: UploadKind
    resubmission_kind: ResubmissionKind
    # Rows revised from the clean Upload (row 1 is the header); none for a corrected resubmission.
    changed_rows: tuple[int, ...]
    # How far the resubmission's counted units (sold, or on hand) and net sales differ from the
    # clean Upload's. Cancelled and refunded Order Lines are never revised, so every change counts.
    unit_change: int
    net_sales_change: float
    expected_status: UploadStatus
    replaced_status: UploadStatus


# Per format: the quantity column a revision changes, and the money column that follows it.
_REVISED_COLUMNS: dict[UploadFormat, tuple[str, str | None]] = {
    UploadFormat.STORE_SALES: ("quantity_sold", "net_sales"),
    UploadFormat.STORE_INVENTORY: ("on_hand", None),
    UploadFormat.ONLINE_SHOP_ORDER_LINES: ("quantity", "line_total"),
    UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT: ("Available Quantity", None),
}


def resubmission_csv(history: History, plan: ResubmissionPlan) -> tuple[str, PlantedResubmission]:
    """The resubmitted Upload and its ground truth. Deterministic for the catalog seed and plan."""
    if plan.day not in history.days:
        raise ValueError(f"{plan.day} is not one of the generated days")
    clean = upload_csv(history, plan.sales_channel, plan.day, plan.upload_kind)
    content, changed_rows, unit_change, net_sales_change = clean, (), 0, 0.0
    if plan.resubmission_kind is ResubmissionKind.CHANGED:
        content, changed_rows, unit_change, net_sales_change = _revise(history, plan, clean)
    return content, PlantedResubmission(
        sales_channel=plan.sales_channel,
        day=plan.day,
        upload_kind=plan.upload_kind,
        resubmission_kind=plan.resubmission_kind,
        changed_rows=changed_rows,
        unit_change=unit_change,
        net_sales_change=net_sales_change,
        expected_status=UploadStatus.ACCEPTED,
        replaced_status=UploadStatus.SUPERSEDED,
    )


def _revise(history: History, plan: ResubmissionPlan, clean: str) -> tuple[str, tuple[int, ...], int, float]:
    upload_format = format_for(_channel_kind(history, plan.sales_channel), plan.upload_kind)
    quantity_column, money_column = _REVISED_COLUMNS[upload_format]
    header, *rows = list(csv.reader(io.StringIO(clean)))
    quantity_at = header.index(quantity_column)
    money_at = header.index(money_column) if money_column else None
    sku_at = header.index("SKU Code" if upload_format is UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT else "sku")
    revisable = [
        i
        for i, row in enumerate(rows)
        if upload_format is not UploadFormat.ONLINE_SHOP_ORDER_LINES
        or row[header.index("status")] == OrderLineStatus.PAID.value
    ]
    if not revisable:
        raise ValueError("the Upload has no rows to revise")
    rng = random.Random(
        f"resubmission:{history.catalog.seed}:{plan.sales_channel}:{plan.day.isoformat()}:"
        f"{plan.upload_kind.value}"
    )
    chosen = sorted(rng.sample(revisable, min(_CHANGED_ROWS, len(revisable))))
    prices = {sku.code: sku.retail_price for sku in history.catalog.skus}
    unit_change = 0
    net_sales_change = 0.0
    for index in chosen:
        row = rows[index]
        change = rng.randint(1, _MAX_UNIT_CHANGE)
        row[quantity_at] = str(int(row[quantity_at]) + change)
        unit_change += change
        if money_at is not None:
            before = float(row[money_at])
            after = round(int(row[quantity_at]) * prices[row[sku_at]], 2)
            row[money_at] = f"{after:.2f}"
            net_sales_change += after - before
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue(), tuple(i + 2 for i in chosen), unit_change, round(net_sales_change, 2)


def _channel_kind(history: History, sales_channel: str) -> SalesChannelKind:
    for channel in history.catalog.sales_channels:
        if channel.code == sales_channel:
            return channel.kind
    raise ValueError(f"{sales_channel!r} is not a Sales Channel in the catalog")
