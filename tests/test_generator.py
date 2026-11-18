from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import pytest

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.catalog import SalesChannelKind
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import (
    PLANTABLE_DEFECTS,
    AnomalyCause,
    AnomalyPlan,
    DefectPlan,
    GroundTruth,
    History,
    ResubmissionKind,
    ResubmissionPlan,
    generate_catalog,
    generate_history,
    generate_opening_stock,
    generate_uploads,
    upload_csv,
)
from retail_ops_agent.upload_formats import OrderLineStatus
from retail_ops_agent.uploads import UploadKind, UploadStatus


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


def test_opening_stock_is_what_every_history_opens_with_whatever_its_first_day() -> None:
    catalog = generate_catalog(11)
    opening = generate_opening_stock(catalog)
    assert set(opening) == {c.code for c in catalog.sales_channels}
    for first_day in (date(2026, 3, 2), date(2026, 11, 30)):
        history = generate_history(catalog, first_day, 1)
        for channel in catalog.sales_channels:
            assert history.opening_stock(channel.code) == opening[channel.code]


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


_PLAN_DAY = date(2026, 6, 1)


def _plans() -> list[DefectPlan]:
    return [
        DefectPlan(sales_channel=channel, day=_PLAN_DAY, upload_kind=kind, defect_kind=defect)
        for channel, kind, defect in [
            ("ST01", UploadKind.SALES, DefectKind.RENAMED_COLUMN),
            ("ST02", UploadKind.INVENTORY, DefectKind.STRAY_WHITESPACE),
            ("ONLINE", UploadKind.SALES, DefectKind.WRONG_DELIMITER),
            ("ONLINE", UploadKind.INVENTORY, DefectKind.BYTE_ORDER_MARK),
        ]
    ]


def test_planting_is_deterministic_and_leaves_other_uploads_clean() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)

    first = generate_uploads(history, _plans())
    second = generate_uploads(history, _plans())

    assert first.ground_truth == second.ground_truth
    planted = {(p.sales_channel, p.upload_kind) for p in _plans()}
    for channel in history.catalog.sales_channels:
        for kind in UploadKind:
            content = first.content(channel.code, _PLAN_DAY, kind)
            assert content == second.content(channel.code, _PLAN_DAY, kind)
            clean = upload_csv(history, channel.code, _PLAN_DAY, kind)
            assert (content != clean) == ((channel.code, kind) in planted)


def test_the_ground_truth_record_matches_the_planted_uploads(tmp_path: Path) -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    generated = generate_uploads(history, _plans())
    truth = {(p.sales_channel, p.upload_kind): p for p in generated.ground_truth.defects}

    assert len(truth) == len(_plans())
    assert all(p.has_safe_fix and p.expected_status is UploadStatus.SAFE_FIXED for p in truth.values())

    renamed = truth[("ST01", UploadKind.SALES)]
    header = generated.content("ST01", _PLAN_DAY, UploadKind.SALES).split("\n", 1)[0].split(",")
    assert renamed.row == 1
    assert renamed.column not in header
    assert len(header) == 5

    padded = truth[("ST02", UploadKind.INVENTORY)]
    columns, rows = _rows(generated.content("ST02", _PLAN_DAY, UploadKind.INVENTORY))
    assert padded.row is not None and padded.column in columns
    value = rows[padded.row - 2][padded.column]
    assert value != value.strip()

    assert "," not in generated.content("ONLINE", _PLAN_DAY, UploadKind.SALES)
    assert generated.content("ONLINE", _PLAN_DAY, UploadKind.INVENTORY).startswith("\ufeff")

    path = tmp_path / "ground_truth.json"
    generated.ground_truth.write(path)
    assert GroundTruth.read(path) == generated.ground_truth


def test_each_plantable_defect_kind_can_be_planted_on_its_own() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    for kind in PLANTABLE_DEFECTS:
        plan = DefectPlan(sales_channel="ST03", day=_PLAN_DAY, upload_kind=UploadKind.SALES, defect_kind=kind)
        [planted] = generate_uploads(history, [plan]).ground_truth.defects
        assert planted.defect_kind is kind


def test_defect_kinds_that_cannot_be_planted_yet_are_refused() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    plan = DefectPlan(
        sales_channel="ST01",
        day=_PLAN_DAY,
        upload_kind=UploadKind.SALES,
        defect_kind=DefectKind.SALES_CHANNEL_MISMATCH,
    )

    with pytest.raises(ValueError, match="cannot be planted"):
        generate_uploads(history, [plan])


def test_unfixable_defects_are_recorded_as_expecting_quarantine_for_their_whole_upload() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    plans = [
        DefectPlan(sales_channel="ST04", day=_PLAN_DAY, upload_kind=UploadKind.INVENTORY, defect_kind=kind)
        for kind in (DefectKind.STRAY_WHITESPACE, DefectKind.UNKNOWN_SKU)
    ]

    generated = generate_uploads(history, plans)

    truth = {p.defect_kind: p for p in generated.ground_truth.defects}
    assert truth[DefectKind.STRAY_WHITESPACE].has_safe_fix
    assert not truth[DefectKind.UNKNOWN_SKU].has_safe_fix
    assert {p.expected_status for p in truth.values()} == {UploadStatus.QUARANTINED}
    unknown = truth[DefectKind.UNKNOWN_SKU]
    columns, rows = _rows(generated.content("ST04", _PLAN_DAY, UploadKind.INVENTORY))
    assert unknown.row is not None and unknown.column in columns
    assert rows[unknown.row - 2][unknown.column] not in {s.code for s in history.catalog.skus}


def test_a_duplicated_day_repeats_every_row_after_the_last() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    plan = DefectPlan(
        sales_channel="ST01",
        day=_PLAN_DAY,
        upload_kind=UploadKind.SALES,
        defect_kind=DefectKind.DUPLICATE_DAY,
    )

    generated = generate_uploads(history, [plan])

    clean = upload_csv(history, "ST01", _PLAN_DAY, UploadKind.SALES)
    header, body = clean.split("\n", 1)
    assert generated.content("ST01", _PLAN_DAY, UploadKind.SALES) == f"{header}\n{body}{body}"
    [planted] = generated.ground_truth.defects
    assert planted.row == len(body.splitlines()) + 2


def _resubmission(channel: str, kind: UploadKind, change: ResubmissionKind) -> ResubmissionPlan:
    return ResubmissionPlan(sales_channel=channel, day=_PLAN_DAY, upload_kind=kind, resubmission_kind=change)


def test_a_corrected_resubmission_is_the_clean_upload_without_its_planted_defects() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    plan = DefectPlan(
        sales_channel="ST01",
        day=_PLAN_DAY,
        upload_kind=UploadKind.SALES,
        defect_kind=DefectKind.MISSING_COLUMN,
    )

    generated = generate_uploads(
        history, [plan], [_resubmission("ST01", UploadKind.SALES, ResubmissionKind.CORRECTED)]
    )

    clean = upload_csv(history, "ST01", _PLAN_DAY, UploadKind.SALES)
    assert generated.content("ST01", _PLAN_DAY, UploadKind.SALES) != clean
    assert generated.resubmission("ST01", _PLAN_DAY, UploadKind.SALES) == clean
    [truth] = generated.ground_truth.resubmissions
    assert truth.changed_rows == () and truth.unit_change == 0
    assert truth.expected_status is UploadStatus.ACCEPTED
    assert truth.replaced_status is UploadStatus.SUPERSEDED


@pytest.mark.parametrize("channel", ["ST02", "ONLINE"])
@pytest.mark.parametrize("kind", list(UploadKind))
def test_a_changed_resubmission_revises_the_rows_its_ground_truth_records(
    channel: str, kind: UploadKind, tmp_path: Path
) -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    plans = [_resubmission(channel, kind, ResubmissionKind.CHANGED)]

    generated = generate_uploads(history, (), plans)

    assert generated.resubmission(channel, _PLAN_DAY, kind) == generate_uploads(
        history, (), plans
    ).resubmission(channel, _PLAN_DAY, kind)
    [truth] = generated.ground_truth.resubmissions
    columns, before = _rows(generated.content(channel, _PLAN_DAY, kind))
    after_columns, after = _rows(generated.resubmission(channel, _PLAN_DAY, kind))
    assert after_columns == columns and len(after) == len(before)
    differing = tuple(i + 2 for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b)
    assert differing == truth.changed_rows and len(differing) > 0
    quantity = {
        ("ST02", UploadKind.SALES): "quantity_sold",
        ("ST02", UploadKind.INVENTORY): "on_hand",
        ("ONLINE", UploadKind.SALES): "quantity",
        ("ONLINE", UploadKind.INVENTORY): "Available Quantity",
    }[(channel, kind)]
    assert sum(int(r[quantity]) for r in after) - sum(int(r[quantity]) for r in before) == truth.unit_change
    if channel == "ONLINE" and kind is UploadKind.SALES:
        assert all(after[row - 2]["status"] == OrderLineStatus.PAID.value for row in truth.changed_rows)

    path = tmp_path / "ground_truth.json"
    generated.ground_truth.write(path)
    assert GroundTruth.read(path) == generated.ground_truth


def test_resubmissions_are_only_available_where_planned() -> None:
    history = generate_history(generate_catalog(3), _PLAN_DAY, 1)
    plan = _resubmission("ST01", UploadKind.SALES, ResubmissionKind.CHANGED)
    generated = generate_uploads(history, (), [plan])

    with pytest.raises(KeyError, match="no resubmission planned"):
        generated.resubmission("ST02", _PLAN_DAY, UploadKind.SALES)
    with pytest.raises(ValueError, match="more than one resubmission"):
        generate_uploads(history, (), [plan, plan])


_RISK_FIRST_DAY = date(2026, 5, 4)
_RISK_DAY = date(2026, 5, 15)


def _stockout_risk(sales_channel: str, day: date = _RISK_DAY) -> AnomalyPlan:
    return AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel=sales_channel, day=day)


@pytest.mark.parametrize("sales_channel", ["ST01", "ONLINE"])
def test_a_planted_stockout_risk_is_a_demand_surge_the_sales_reveal(sales_channel: str) -> None:
    catalog = generate_catalog(11)
    history = generate_history(catalog, _RISK_FIRST_DAY, 12, [_stockout_risk(sales_channel)])
    generated = generate_uploads(history)

    [planted] = generated.ground_truth.anomalies
    assert (planted.kind, planted.cause, planted.sales_channel, planted.day) == (
        AnomalyKind.STOCKOUT_RISK,
        AnomalyCause.DEMAND_SURGE,
        sales_channel,
        _RISK_DAY,
    )
    surge = [d for d in history.days if planted.cause_starts_on <= d <= planted.day]
    before = [d for d in history.days if d < planted.cause_starts_on]

    def sold(day: date) -> int:
        return next(r.quantity_sold for r in history.sales(sales_channel, day) if r.sku == planted.sku)

    assert planted.units_sold == tuple(sold(d) for d in surge)
    usual = sum(sold(d) for d in before) / len(before)
    assert all(units > 3 * max(usual, 1) for units in planted.units_sold)
    on_hand = next(r.on_hand for r in history.inventory(sales_channel, _RISK_DAY) if r.sku == planted.sku)
    assert on_hand < planted.units_sold[-1]
    # Stock still equals the previous day's plus arrivals minus sales.
    assert all(r.on_hand >= 0 for d in history.days for r in history.inventory(sales_channel, d))


def test_planting_a_stockout_risk_leaves_other_skus_and_sales_channels_alone() -> None:
    catalog = generate_catalog(11)
    clean = generate_history(catalog, _RISK_FIRST_DAY, 12)
    planted = generate_history(catalog, _RISK_FIRST_DAY, 12, [_stockout_risk("ST03")])
    [anomaly] = planted.planted_anomalies

    for channel in catalog.sales_channels:
        for day in clean.days:
            for a, b in zip(clean.sales(channel.code, day), planted.sales(channel.code, day), strict=True):
                if (channel.code, a.sku) != ("ST03", anomaly.sku):
                    assert a == b


def test_planted_stockout_risks_are_deterministic_and_vary_with_the_plan() -> None:
    catalog = generate_catalog(11)

    def truth(plan: AnomalyPlan) -> GroundTruth:
        return generate_uploads(generate_history(catalog, _RISK_FIRST_DAY, 12, [plan])).ground_truth

    assert truth(_stockout_risk("ST01")) == truth(_stockout_risk("ST01"))
    assert truth(_stockout_risk("ST01")).anomalies != truth(_stockout_risk("ST04")).anomalies


@pytest.mark.parametrize(
    "plan",
    [
        _stockout_risk("ST01", _RISK_FIRST_DAY + timedelta(days=5)),
        _stockout_risk("ST01", _RISK_FIRST_DAY + timedelta(days=30)),
        _stockout_risk("NOPE"),
    ],
)
def test_a_stockout_risk_that_cannot_be_planted_is_refused(plan: AnomalyPlan) -> None:
    with pytest.raises(ValueError):
        generate_history(generate_catalog(11), _RISK_FIRST_DAY, 12, [plan])
