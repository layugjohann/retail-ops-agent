from __future__ import annotations

from datetime import date

import pytest

from retail_ops_agent.catalog import Catalog
from retail_ops_agent.generator import generate_store_sales, store_sales_csv
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus

DAY = date(2026, 3, 2)


def _submit_clean_store_sales(ops_day: OpsDay, catalog: Catalog, store_code: str, day: date) -> str:
    return ops_day.submit_upload(
        sales_channel=store_code,
        day=day,
        kind=UploadKind.SALES,
        content=store_sales_csv(generate_store_sales(catalog, store_code, day)),
        uploader="manager@cobalthome.example",
    )


def test_a_clean_store_sales_upload_is_accepted(
    ops_day: OpsDay, catalog: Catalog, notifier: LogNotifier
) -> None:
    upload_id = _submit_clean_store_sales(ops_day, catalog, "ST01", DAY)

    outcome = ops_day.run_ops_day(DAY)

    assert outcome.day == DAY
    assert [(u.upload_id, u.status, u.defects) for u in outcome.uploads] == [
        (upload_id, UploadStatus.ACCEPTED, [])
    ]
    assert notifier.sent == []


def test_accepted_sales_are_queryable_by_sales_channel(ops_day: OpsDay, catalog: Catalog) -> None:
    for store in catalog.stores:
        _submit_clean_store_sales(ops_day, catalog, store.code, DAY)

    ops_day.run_ops_day(DAY)

    sales = {row.sales_channel: row for row in ops_day.sales_by_sales_channel()}
    assert set(sales) == {s.code for s in catalog.stores}
    for store in catalog.stores:
        truth = generate_store_sales(catalog, store.code, DAY)
        assert sales[store.code].day == DAY
        assert sales[store.code].sales_channel_name == store.name
        assert sales[store.code].quantity_sold == sum(r.quantity_sold for r in truth)
        assert sales[store.code].net_sales == pytest.approx(sum(r.net_sales for r in truth))


def test_upload_status_view_shows_each_processed_upload(ops_day: OpsDay, catalog: Catalog) -> None:
    upload_id = _submit_clean_store_sales(ops_day, catalog, "ST03", DAY)
    ops_day.run_ops_day(DAY)

    statuses = ops_day.upload_statuses()

    assert [(u.upload_id, u.sales_channel, u.day, u.kind, u.status) for u in statuses] == [
        (upload_id, "ST03", DAY, UploadKind.SALES, UploadStatus.ACCEPTED)
    ]


def test_an_upload_is_processed_only_once(ops_day: OpsDay, catalog: Catalog) -> None:
    _submit_clean_store_sales(ops_day, catalog, "ST01", DAY)
    ops_day.run_ops_day(DAY)

    second = ops_day.run_ops_day(DAY)

    assert second.uploads == []
    assert len(ops_day.sales_by_sales_channel()) == 1


def test_uploads_for_other_days_wait_for_their_own_ops_day(ops_day: OpsDay, catalog: Catalog) -> None:
    _submit_clean_store_sales(ops_day, catalog, "ST01", date(2026, 3, 3))

    outcome = ops_day.run_ops_day(DAY)

    assert outcome.uploads == []
    assert ops_day.sales_by_sales_channel() == []


def test_submitting_for_an_unknown_sales_channel_is_refused(ops_day: OpsDay) -> None:
    with pytest.raises(ValueError, match="unknown Sales Channel"):
        ops_day.submit_upload(
            sales_channel="ST99", day=DAY, kind=UploadKind.SALES, content="", uploader="someone"
        )
