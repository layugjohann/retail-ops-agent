from __future__ import annotations

from datetime import date

import pytest

from retail_ops_agent.catalog import Catalog
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import History, generate_history, upload_csv
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus

DAY = date(2026, 3, 2)


@pytest.fixture
def history(catalog: Catalog) -> History:
    return generate_history(catalog, DAY, 2)


def _submit(ops_day: OpsDay, history: History, sales_channel: str, kind: UploadKind, day: date = DAY) -> str:
    return _submit_content(ops_day, sales_channel, kind, upload_csv(history, sales_channel, day, kind), day)


def _submit_content(
    ops_day: OpsDay, sales_channel: str, kind: UploadKind, content: str, day: date = DAY
) -> str:
    return ops_day.submit_upload(
        sales_channel=sales_channel,
        day=day,
        kind=kind,
        content=content,
        uploader="uploader@cobalthome.example",
    )


def test_a_clean_store_sales_upload_is_accepted(
    ops_day: OpsDay, history: History, notifier: LogNotifier
) -> None:
    upload_id = _submit(ops_day, history, "ST01", UploadKind.SALES)

    outcome = ops_day.run_ops_day(DAY)

    assert outcome.day == DAY
    assert [(u.upload_id, u.status, u.defects) for u in outcome.uploads] == [
        (upload_id, UploadStatus.ACCEPTED, [])
    ]
    assert notifier.sent == []


def test_clean_uploads_of_all_four_formats_are_accepted(
    ops_day: OpsDay, catalog: Catalog, history: History, notifier: LogNotifier
) -> None:
    expected: set[tuple[str, UploadKind]] = set()
    for channel in catalog.sales_channels:
        for kind in UploadKind:
            _submit(ops_day, history, channel.code, kind)
            expected.add((channel.code, kind))

    outcome = ops_day.run_ops_day(DAY)

    assert {(u.sales_channel, u.kind) for u in outcome.uploads} == expected
    assert {u.status for u in outcome.uploads} == {UploadStatus.ACCEPTED}
    assert all(u.defects == [] for u in outcome.uploads)
    assert notifier.sent == []


def test_upload_status_distinguishes_sales_from_inventory(ops_day: OpsDay, history: History) -> None:
    sales_id = _submit(ops_day, history, "ONLINE", UploadKind.SALES)
    inventory_id = _submit(ops_day, history, "ONLINE", UploadKind.INVENTORY)
    ops_day.run_ops_day(DAY)

    statuses = {u.upload_id: (u.sales_channel, u.kind, u.status) for u in ops_day.upload_statuses()}

    assert statuses == {
        sales_id: ("ONLINE", UploadKind.SALES, UploadStatus.ACCEPTED),
        inventory_id: ("ONLINE", UploadKind.INVENTORY, UploadStatus.ACCEPTED),
    }


def test_accepted_sales_are_queryable_by_sales_channel(
    ops_day: OpsDay, catalog: Catalog, history: History
) -> None:
    for channel in catalog.sales_channels:
        _submit(ops_day, history, channel.code, UploadKind.SALES)

    ops_day.run_ops_day(DAY)

    sales = {row.sales_channel: row for row in ops_day.sales_by_sales_channel()}
    assert set(sales) == {c.code for c in catalog.sales_channels}
    for channel in catalog.sales_channels:
        truth = history.sales(channel.code, DAY)
        assert sales[channel.code].day == DAY
        assert sales[channel.code].sales_channel_name == channel.name
        assert sales[channel.code].quantity_sold == sum(r.quantity_sold for r in truth)
        assert sales[channel.code].net_sales == pytest.approx(sum(r.net_sales for r in truth))


def test_online_shop_sales_match_the_generators_daily_totals(
    ops_day: OpsDay, catalog: Catalog, history: History
) -> None:
    for day in history.days:
        _submit(ops_day, history, "ONLINE", UploadKind.SALES, day)
        ops_day.run_ops_day(day)

    loaded = {row.day: row for row in ops_day.sales_by_sales_channel()}
    for day in history.days:
        truth = history.sales("ONLINE", day)
        assert loaded[day].quantity_sold == sum(r.quantity_sold for r in truth)
        assert loaded[day].net_sales == pytest.approx(sum(r.net_sales for r in truth))


ORDER_LINES = """\
order_id,created_at,sku,quantity,line_total,status
WEB-1,2026-03-02T09:15:00,{a},2,20.00,paid
WEB-1,2026-03-02T09:15:00,{b},1,5.50,paid
WEB-2,2026-03-02T11:40:00,{a},3,30.00,cancelled
WEB-3,2026-03-02T14:05:00,{a},1,10.00,paid
WEB-4,2026-03-02T16:30:00,{b},4,22.00,refunded
"""


def test_online_shop_sales_leave_out_cancelled_and_refunded_order_lines(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    a, b = catalog.skus[0].code, catalog.skus[1].code
    _submit_content(ops_day, "ONLINE", UploadKind.SALES, ORDER_LINES.format(a=a, b=b))

    outcome = ops_day.run_ops_day(DAY)

    assert [u.status for u in outcome.uploads] == [UploadStatus.ACCEPTED]
    [online] = ops_day.sales_by_sales_channel()
    assert (online.sales_channel, online.quantity_sold) == ("ONLINE", 4)
    assert online.net_sales == pytest.approx(35.50)


def test_an_order_line_with_an_unknown_status_is_quarantined(ops_day: OpsDay, catalog: Catalog) -> None:
    a, b = catalog.skus[0].code, catalog.skus[1].code
    content = ORDER_LINES.format(a=a, b=b).replace("refunded", "returned")
    _submit_content(ops_day, "ONLINE", UploadKind.SALES, content)

    [upload] = ops_day.run_ops_day(DAY).uploads

    assert upload.status is UploadStatus.QUARANTINED
    assert [(d.kind, d.row, d.column) for d in upload.defects] == [(DefectKind.UNREADABLE_VALUE, 6, "status")]
    assert ops_day.sales_by_sales_channel() == []


def test_inventory_is_queryable_by_sales_channel_and_sku(
    ops_day: OpsDay, catalog: Catalog, history: History
) -> None:
    for channel in catalog.sales_channels:
        _submit(ops_day, history, channel.code, UploadKind.INVENTORY)

    ops_day.run_ops_day(DAY)

    by_sku = {(row.sales_channel, row.sku): row for row in ops_day.inventory_by_sku()}
    for channel in catalog.sales_channels:
        for truth in history.inventory(channel.code, DAY):
            row = by_sku[(channel.code, truth.sku)]
            assert (row.day, row.on_hand, row.sales_channel_name) == (DAY, truth.on_hand, channel.name)
    sku = catalog.skus[0]
    assert (by_sku[("ST01", sku.code)].sku_name, by_sku[("ST01", sku.code)].category) == (
        sku.name,
        sku.category,
    )

    by_channel = {row.sales_channel: row for row in ops_day.inventory_by_sales_channel()}
    for channel in catalog.sales_channels:
        truth = history.inventory(channel.code, DAY)
        assert by_channel[channel.code].on_hand == sum(r.on_hand for r in truth)
        assert by_channel[channel.code].skus_in_stock == sum(1 for r in truth if r.on_hand > 0)


def test_inventory_by_sku_shows_the_latest_day_unless_asked(ops_day: OpsDay, history: History) -> None:
    for day in history.days:
        _submit(ops_day, history, "ST01", UploadKind.INVENTORY, day)
        ops_day.run_ops_day(day)

    assert {row.day for row in ops_day.inventory_by_sku()} == {history.days[-1]}
    assert {row.day for row in ops_day.inventory_by_sku(DAY)} == {DAY}


def test_negative_stock_is_quarantined_and_kept_out_of_inventory(ops_day: OpsDay, catalog: Catalog) -> None:
    sku = catalog.skus[0].code
    content = f"date,store_code,sku,on_hand\n{DAY.isoformat()},ST01,{sku},-4\n"
    _submit_content(ops_day, "ST01", UploadKind.INVENTORY, content)

    [upload] = ops_day.run_ops_day(DAY).uploads

    assert upload.status is UploadStatus.QUARANTINED
    assert [(d.kind, d.row, d.column) for d in upload.defects] == [
        (DefectKind.IMPOSSIBLE_QUANTITY, 2, "on_hand")
    ]
    assert ops_day.inventory_by_sku() == []


def test_a_stock_snapshot_in_the_store_format_is_quarantined(
    ops_day: OpsDay, catalog: Catalog, history: History
) -> None:
    store_format = upload_csv(history, "ST01", DAY, UploadKind.INVENTORY).replace("ST01", "ONLINE")
    _submit_content(ops_day, "ONLINE", UploadKind.INVENTORY, store_format)

    [upload] = ops_day.run_ops_day(DAY).uploads

    assert upload.status is UploadStatus.QUARANTINED
    assert {(d.kind, d.column) for d in upload.defects} == {
        (DefectKind.MISSING_COLUMN, "SKU Code"),
        (DefectKind.MISSING_COLUMN, "Available Quantity"),
        (DefectKind.MISSING_COLUMN, "Snapshot Time"),
    }


def test_a_stock_snapshot_from_another_day_is_quarantined(ops_day: OpsDay, history: History) -> None:
    next_day = history.days[1]
    _submit_content(
        ops_day, "ONLINE", UploadKind.INVENTORY, upload_csv(history, "ONLINE", next_day, UploadKind.INVENTORY)
    )

    [upload] = ops_day.run_ops_day(DAY).uploads

    assert upload.status is UploadStatus.QUARANTINED
    assert {(d.kind, d.column) for d in upload.defects} == {(DefectKind.DATE_MISMATCH, "Snapshot Time")}


def test_an_upload_is_processed_only_once(ops_day: OpsDay, history: History) -> None:
    _submit(ops_day, history, "ST01", UploadKind.SALES)
    ops_day.run_ops_day(DAY)

    second = ops_day.run_ops_day(DAY)

    assert second.uploads == []
    assert len(ops_day.sales_by_sales_channel()) == 1


def test_uploads_for_other_days_wait_for_their_own_ops_day(ops_day: OpsDay, history: History) -> None:
    _submit(ops_day, history, "ST01", UploadKind.SALES, history.days[1])

    outcome = ops_day.run_ops_day(DAY)

    assert outcome.uploads == []
    assert ops_day.sales_by_sales_channel() == []


def test_submitting_for_an_unknown_sales_channel_is_refused(ops_day: OpsDay) -> None:
    with pytest.raises(ValueError, match="unknown Sales Channel"):
        ops_day.submit_upload(
            sales_channel="ST99", day=DAY, kind=UploadKind.SALES, content="", uploader="someone"
        )
