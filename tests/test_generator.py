from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.generator import History, generate_catalog, generate_history, upload_csv
from retail_ops_agent.upload_formats import OrderLineStatus
from retail_ops_agent.uploads import UploadKind


def test_catalog_has_the_clients_shape() -> None:
    catalog = generate_catalog(1)

    kinds = [c.kind for c in catalog.sales_channels]
    assert kinds.count(SalesChannelKind.STORE) == 6
    assert kinds.count(SalesChannelKind.ONLINE_SHOP) == 1
    assert 280 <= len(catalog.skus) <= 320
    assert 4 <= len(catalog.suppliers) <= 6
    assert len({s.code for s in catalog.skus}) == len(catalog.skus)


def test_every_sku_has_a_supplier_cost_price_case_pack_and_lead_time() -> None:
    catalog = generate_catalog(1)
    supplier_codes = {s.code for s in catalog.suppliers}

    for sku in catalog.skus:
        assert sku.supplier_code in supplier_codes
        assert 0 < sku.unit_cost < sku.retail_price
        assert sku.case_pack >= 1
        assert sku.lead_time_days >= 1


def _all_uploads(history: History) -> list[str]:
    return [
        upload_csv(history, channel.code, day, kind)
        for day in history.days
        for channel in history.catalog.sales_channels
        for kind in UploadKind
    ]


def test_same_seed_gives_identical_output() -> None:
    first = generate_catalog(7)
    second = generate_catalog(7)

    assert first == second
    assert _all_uploads(generate_history(first, date(2026, 5, 4), 2)) == _all_uploads(
        generate_history(second, date(2026, 5, 4), 2)
    )


def test_different_seed_gives_different_output() -> None:
    first = generate_catalog(7)
    second = generate_catalog(8)

    assert first != second
    first_uploads = _all_uploads(generate_history(first, date(2026, 5, 4), 1))
    second_uploads = _all_uploads(generate_history(second, date(2026, 5, 4), 1))
    assert all(a != b for a, b in zip(first_uploads, second_uploads, strict=True))


def _rows(content: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content))
    return list(reader.fieldnames or []), list(reader)


def test_each_sales_channel_sends_both_kinds_in_its_own_format() -> None:
    catalog = generate_catalog(3)
    day = date(2026, 6, 1)
    history = generate_history(catalog, day, 1)
    sku_codes = sorted(s.code for s in catalog.skus)

    columns, rows = _rows(upload_csv(history, "ST02", day, UploadKind.SALES))
    assert columns == ["date", "store_code", "sku", "quantity_sold", "net_sales"]
    assert sorted(r["sku"] for r in rows) == sku_codes
    assert {(r["date"], r["store_code"]) for r in rows} == {(day.isoformat(), "ST02")}

    columns, rows = _rows(upload_csv(history, "ST02", day, UploadKind.INVENTORY))
    assert columns == ["date", "store_code", "sku", "on_hand"]
    assert sorted(r["sku"] for r in rows) == sku_codes

    columns, rows = _rows(upload_csv(history, "ONLINE", day, UploadKind.SALES))
    assert columns == ["order_id", "created_at", "sku", "quantity", "line_total", "status"]
    assert {r["status"] for r in rows} == {"paid", "cancelled", "refunded"}
    assert {r["created_at"][:10] for r in rows} == {day.isoformat()}

    columns, rows = _rows(upload_csv(history, "ONLINE", day, UploadKind.INVENTORY))
    assert columns == ["SKU Code", "Available Quantity", "Snapshot Time"]
    assert sorted(r["SKU Code"] for r in rows) == sku_codes
    assert {r["Snapshot Time"][:10] for r in rows} == {day.isoformat()}


def test_online_shop_paid_order_lines_add_up_to_its_daily_sales() -> None:
    catalog = generate_catalog(3)
    day = date(2026, 6, 1)
    history = generate_history(catalog, day, 1)

    paid_units: defaultdict[str, int] = defaultdict(int)
    paid_totals: defaultdict[str, float] = defaultdict(float)
    for line in history.order_lines(day):
        if line.status is OrderLineStatus.PAID:
            paid_units[line.sku] += line.quantity
            paid_totals[line.sku] += line.line_total

    for row in history.sales("ONLINE", day):
        assert row.quantity_sold == paid_units[row.sku]
        assert abs(row.net_sales - paid_totals[row.sku]) < 0.005
    assert sum(r.quantity_sold for r in history.sales("ONLINE", day)) > 0


def test_inventory_follows_sales_and_restocks_arriving_after_the_lead_time() -> None:
    catalog = generate_catalog(11)
    history = generate_history(catalog, date(2026, 3, 2), 28)
    skus = {s.code: s for s in catalog.skus}

    arrivals: defaultdict[tuple[str, str, date], int] = defaultdict(int)
    for restock in history.restocks:
        sku = skus[restock.sku]
        assert restock.arrives_on - restock.ordered_on == timedelta(days=sku.lead_time_days)
        assert restock.quantity > 0
        assert restock.quantity % sku.case_pack == 0
        arrivals[(restock.sales_channel, restock.sku, restock.arrives_on)] += restock.quantity
    assert any(r.arrives_on <= history.days[-1] for r in history.restocks)

    for channel in catalog.sales_channels:
        on_hand = history.opening_stock(channel.code)
        for day in history.days:
            sold = {r.sku: r.quantity_sold for r in history.sales(channel.code, day)}
            for row in history.inventory(channel.code, day):
                expected = on_hand[row.sku] + arrivals[(channel.code, row.sku, day)] - sold[row.sku]
                assert row.on_hand == expected >= 0
                on_hand[row.sku] = row.on_hand


def _store_units(seed: int, start: date, days: int) -> int:
    history = generate_history(generate_catalog(seed), start, days)
    return sum(
        row.quantity_sold
        for day in history.days
        for store in history.catalog.stores
        for row in history.sales(store.code, day)
    )


def test_sales_peak_before_christmas() -> None:
    december = _store_units(5, date(2026, 12, 7), 14)
    february = _store_units(5, date(2026, 2, 2), 14)

    assert december > 1.2 * february


def test_weekends_sell_more_than_midweek() -> None:
    history = generate_history(generate_catalog(5), date(2026, 3, 2), 28)

    def total(weekday: int) -> int:
        return sum(
            r.quantity_sold
            for day in history.days
            if day.weekday() == weekday
            for store in history.catalog.stores
            for r in history.sales(store.code, day)
        )

    assert total(5) > 1.2 * total(1)
