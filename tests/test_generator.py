from __future__ import annotations

from datetime import date, timedelta

from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.generator import generate_catalog, generate_store_sales, store_sales_csv


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


def test_same_seed_gives_identical_output() -> None:
    day = date(2026, 5, 4)
    first = generate_catalog(7)
    second = generate_catalog(7)

    assert first == second
    assert store_sales_csv(generate_store_sales(first, "ST01", day)) == store_sales_csv(
        generate_store_sales(second, "ST01", day)
    )


def test_different_seed_gives_different_output() -> None:
    day = date(2026, 5, 4)
    first = generate_catalog(7)
    second = generate_catalog(8)

    assert first != second
    assert store_sales_csv(generate_store_sales(first, "ST01", day)) != store_sales_csv(
        generate_store_sales(second, "ST01", day)
    )


def test_store_sales_have_one_row_per_sku_for_the_store_and_day() -> None:
    catalog = generate_catalog(3)
    day = date(2026, 6, 1)

    rows = generate_store_sales(catalog, "ST02", day)

    assert sorted(r.sku for r in rows) == sorted(s.code for s in catalog.skus)
    assert {(r.day, r.store_code) for r in rows} == {(day, "ST02")}
    assert all(r.quantity_sold >= 0 for r in rows)
    assert sum(r.quantity_sold for r in rows) > 0


def _units(seed: int, start: date, days: int) -> int:
    catalog = generate_catalog(seed)
    return sum(
        row.quantity_sold
        for offset in range(days)
        for store in catalog.stores
        for row in generate_store_sales(catalog, store.code, start + timedelta(days=offset))
    )


def test_sales_peak_before_christmas() -> None:
    december = _units(5, date(2026, 12, 7), 14)
    february = _units(5, date(2026, 2, 2), 14)

    assert december > 1.2 * february


def test_weekends_sell_more_than_midweek() -> None:
    catalog = generate_catalog(5)
    saturdays = [date(2026, 3, 7) + timedelta(weeks=w) for w in range(4)]
    tuesdays = [date(2026, 3, 3) + timedelta(weeks=w) for w in range(4)]

    def total(days: list[date]) -> int:
        return sum(
            r.quantity_sold
            for d in days
            for store in catalog.stores
            for r in generate_store_sales(catalog, store.code, d)
        )

    assert total(saturdays) > 1.2 * total(tuesdays)
