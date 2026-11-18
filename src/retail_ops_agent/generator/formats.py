"""Renders generated truth as Uploads in each Sales Channel's own format."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from retail_ops_agent.catalog import Catalog, SalesChannelKind
from retail_ops_agent.generator.history import CLOSING_TIME, History, InventoryRow, OrderLine, SalesRow
from retail_ops_agent.upload_formats import (
    COLUMNS,
    UploadFormat,
    format_for,
)
from retail_ops_agent.uploads import UploadKind


def store_sales_csv(rows: list[SalesRow]) -> str:
    return _csv(
        UploadFormat.STORE_SALES,
        [[r.day.isoformat(), r.sales_channel, r.sku, r.quantity_sold, f"{r.net_sales:.2f}"] for r in rows],
    )


def store_inventory_csv(rows: list[InventoryRow]) -> str:
    return _csv(
        UploadFormat.STORE_INVENTORY,
        [[r.day.isoformat(), r.sales_channel, r.sku, r.on_hand] for r in rows],
    )


def online_shop_order_lines_csv(lines: list[OrderLine]) -> str:
    return _csv(
        UploadFormat.ONLINE_SHOP_ORDER_LINES,
        [
            [
                line.order_id,
                line.created_at.isoformat(),
                line.sku,
                line.quantity,
                f"{line.line_total:.2f}",
                line.status.value,
            ]
            for line in lines
        ],
    )


def online_shop_stock_snapshot_csv(rows: list[InventoryRow]) -> str:
    return _csv(
        UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT,
        [[r.sku, r.on_hand, _snapshot_time(r.day)] for r in rows],
    )


def upload_csv(history: History, sales_channel: str, day: date, kind: UploadKind) -> str:
    """The clean Upload a Sales Channel sends for the day and kind, in its own format."""
    upload_format = format_for(_channel_kind(history.catalog, sales_channel), kind)
    match upload_format:
        case UploadFormat.STORE_SALES:
            return store_sales_csv(history.sales(sales_channel, day))
        case UploadFormat.STORE_INVENTORY:
            return store_inventory_csv(history.inventory(sales_channel, day))
        case UploadFormat.ONLINE_SHOP_ORDER_LINES:
            return online_shop_order_lines_csv(history.order_lines(day))
        case UploadFormat.ONLINE_SHOP_STOCK_SNAPSHOT:
            return online_shop_stock_snapshot_csv(history.inventory(sales_channel, day))


def _channel_kind(catalog: Catalog, sales_channel: str) -> SalesChannelKind:
    for channel in catalog.sales_channels:
        if channel.code == sales_channel:
            return channel.kind
    raise ValueError(f"{sales_channel!r} is not a Sales Channel in the catalog")


def _snapshot_time(day: date) -> str:
    return datetime.combine(day, CLOSING_TIME).isoformat()


def _csv(upload_format: UploadFormat, rows: list[list[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS[upload_format])
    writer.writerows(rows)
    return buffer.getvalue()
