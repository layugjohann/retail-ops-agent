from __future__ import annotations

from datetime import date, timedelta

import pytest

from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import (
    DefectPlan,
    GeneratedUploads,
    ResubmissionKind,
    ResubmissionPlan,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus
from retail_ops_agent.views import UploadOutcome

DAY = date(2026, 3, 2)
UPLOADER = "manager.st01@cobalthome.example"
LATER = timedelta(hours=1)


def _generate(
    catalog: Catalog,
    sales_channel: str,
    kind: UploadKind,
    resubmission: ResubmissionKind,
    defect: DefectKind | None = None,
) -> GeneratedUploads:
    return generate_uploads(
        generate_history(catalog, DAY, 2),
        [DefectPlan(sales_channel=sales_channel, day=DAY, upload_kind=kind, defect_kind=defect)]
        if defect
        else [],
        [
            ResubmissionPlan(
                sales_channel=sales_channel, day=DAY, upload_kind=kind, resubmission_kind=resubmission
            )
        ],
    )


def _submit(ops_day: OpsDay, sales_channel: str, kind: UploadKind, content: str, day: date = DAY) -> str:
    return ops_day.submit_upload(
        sales_channel=sales_channel, day=day, kind=kind, content=content, uploader=UPLOADER
    )


def _status(ops_day: OpsDay, upload_id: str) -> UploadOutcome:
    [outcome] = [u for u in ops_day.upload_statuses() if u.upload_id == upload_id]
    return outcome


def _sales(ops_day: OpsDay, sales_channel: str) -> tuple[int, float]:
    [row] = [r for r in ops_day.sales_by_sales_channel() if r.sales_channel == sales_channel and r.day == DAY]
    return row.quantity_sold, row.net_sales


@pytest.mark.parametrize("sales_channel", ["ST01", "ONLINE"])
def test_a_resubmitted_sales_upload_replaces_the_earlier_one_and_nothing_is_double_counted(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock, sales_channel: str
) -> None:
    generated = _generate(catalog, sales_channel, UploadKind.SALES, ResubmissionKind.CHANGED)
    first = _submit(
        ops_day, sales_channel, UploadKind.SALES, generated.content(sales_channel, DAY, UploadKind.SALES)
    )
    ops_day.run_ops_day(DAY)
    units_before, net_before = _sales(ops_day, sales_channel)

    clock.advance(LATER)
    second = _submit(
        ops_day, sales_channel, UploadKind.SALES, generated.resubmission(sales_channel, DAY, UploadKind.SALES)
    )
    ops_day.run_ops_day(DAY)

    [truth] = generated.ground_truth.resubmissions
    assert truth.unit_change > 0
    units_after, net_after = _sales(ops_day, sales_channel)
    assert units_after == units_before + truth.unit_change
    assert net_after == pytest.approx(net_before + truth.net_sales_change)
    assert _status(ops_day, first).status is truth.replaced_status is UploadStatus.SUPERSEDED
    assert _status(ops_day, second).status is truth.expected_status is UploadStatus.ACCEPTED


def test_a_resubmitted_inventory_upload_replaces_the_earlier_one(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated = _generate(catalog, "ST02", UploadKind.INVENTORY, ResubmissionKind.CHANGED)
    _submit(ops_day, "ST02", UploadKind.INVENTORY, generated.content("ST02", DAY, UploadKind.INVENTORY))
    ops_day.run_ops_day(DAY)
    [before] = [r for r in ops_day.inventory_by_sales_channel() if r.sales_channel == "ST02"]

    clock.advance(LATER)
    _submit(ops_day, "ST02", UploadKind.INVENTORY, generated.resubmission("ST02", DAY, UploadKind.INVENTORY))
    ops_day.run_ops_day(DAY)

    [truth] = generated.ground_truth.resubmissions
    [after] = [r for r in ops_day.inventory_by_sales_channel() if r.sales_channel == "ST02"]
    assert after.on_hand == before.on_hand + truth.unit_change
    rows = [r for r in ops_day.inventory_by_sku(DAY) if r.sales_channel == "ST02"]
    assert len(rows) == len({r.sku for r in rows}) == len(catalog.skus)


def test_the_superseded_upload_names_its_replacement_and_keeps_its_history(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated = _generate(catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED)
    first = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)
    clock.advance(LATER)
    second = _submit(ops_day, "ST01", UploadKind.SALES, generated.resubmission("ST01", DAY, UploadKind.SALES))

    outcome = ops_day.run_ops_day(DAY)

    assert {u.upload_id: u.status for u in outcome.uploads} == {
        first: UploadStatus.SUPERSEDED,
        second: UploadStatus.ACCEPTED,
    }
    earlier = _status(ops_day, first)
    assert earlier.superseded_by == second
    assert [c.status for c in earlier.history] == [UploadStatus.ACCEPTED, UploadStatus.SUPERSEDED]
    assert earlier.history[1].changed_at == clock.now()
    assert _status(ops_day, second).superseded_by is None
    # Both stay in the status view, oldest first.
    assert [u.upload_id for u in ops_day.upload_statuses()] == [first, second]


def test_a_corrected_resubmission_of_a_quarantined_upload_is_accepted(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock, notifier: LogNotifier
) -> None:
    generated = _generate(
        catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED, DefectKind.IMPOSSIBLE_QUANTITY
    )
    first = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)
    assert _status(ops_day, first).status is UploadStatus.QUARANTINED
    assert ops_day.sales_by_sales_channel() == []

    clock.advance(LATER)
    second = _submit(ops_day, "ST01", UploadKind.SALES, generated.resubmission("ST01", DAY, UploadKind.SALES))
    outcome = ops_day.run_ops_day(DAY)

    assert _status(ops_day, second).status is UploadStatus.ACCEPTED
    earlier = _status(ops_day, first)
    assert earlier.status is UploadStatus.SUPERSEDED
    assert [c.status for c in earlier.history] == [UploadStatus.QUARANTINED, UploadStatus.SUPERSEDED]
    clean = generated.history.sales("ST01", DAY)
    assert _sales(ops_day, "ST01") == (
        sum(r.quantity_sold for r in clean),
        pytest.approx(sum(r.net_sales for r in clean)),
    )
    assert outcome.audit_entries == [] and outcome.uploader_messages == []
    assert len(notifier.sent) == 1


def test_a_quarantined_resubmission_still_replaces_the_earlier_upload(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    clean = _generate(catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED)
    broken = _generate(catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED, DefectKind.UNKNOWN_SKU)
    first = _submit(ops_day, "ST01", UploadKind.SALES, clean.content("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)

    clock.advance(LATER)
    second = _submit(ops_day, "ST01", UploadKind.SALES, broken.content("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)

    assert _status(ops_day, first).status is UploadStatus.SUPERSEDED
    assert _status(ops_day, second).status is UploadStatus.QUARANTINED
    assert ops_day.sales_by_sales_channel() == []


def test_a_duplicate_day_inside_one_file_is_still_a_defect(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated = _generate(
        catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED, DefectKind.DUPLICATE_DAY
    )
    first = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))

    outcome = ops_day.run_ops_day(DAY)

    [upload] = outcome.uploads
    assert upload.upload_id == first
    assert upload.status is UploadStatus.QUARANTINED
    assert {d.kind for d in upload.defects} == {DefectKind.DUPLICATE_DAY}
    assert upload.superseded_by is None


def test_an_upload_replaced_before_its_ops_day_is_superseded_without_intake(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock, notifier: LogNotifier
) -> None:
    generated = _generate(
        catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED, DefectKind.MISSING_COLUMN
    )
    first = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))
    clock.advance(LATER)
    second = _submit(ops_day, "ST01", UploadKind.SALES, generated.resubmission("ST01", DAY, UploadKind.SALES))

    outcome = ops_day.run_ops_day(DAY)

    assert {u.upload_id: u.status for u in outcome.uploads} == {
        first: UploadStatus.SUPERSEDED,
        second: UploadStatus.ACCEPTED,
    }
    assert _status(ops_day, first).superseded_by == second
    assert [c.status for c in _status(ops_day, first).history] == [UploadStatus.SUPERSEDED]
    assert outcome.audit_entries == [] and notifier.sent == []
    assert len(ops_day.sales_by_sales_channel()) == 1


def test_a_resubmission_for_an_earlier_day_is_picked_up_by_the_next_ops_day(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated = _generate(catalog, "ST01", UploadKind.SALES, ResubmissionKind.CHANGED)
    next_day = DAY + timedelta(days=1)
    first = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)
    units_before, _ = _sales(ops_day, "ST01")

    clock.advance(timedelta(days=1))
    second = _submit(ops_day, "ST01", UploadKind.SALES, generated.resubmission("ST01", DAY, UploadKind.SALES))
    _submit(
        ops_day, "ST01", UploadKind.SALES, generated.content("ST01", next_day, UploadKind.SALES), next_day
    )
    outcome = ops_day.run_ops_day(next_day)

    statuses = {u.upload_id: u.status for u in outcome.uploads}
    assert statuses[first] is UploadStatus.SUPERSEDED
    assert statuses[second] is UploadStatus.ACCEPTED
    [truth] = generated.ground_truth.resubmissions
    assert _sales(ops_day, "ST01")[0] == units_before + truth.unit_change


def test_the_superseded_uploads_audit_log_entries_can_no_longer_be_undone(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated = _generate(
        catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED, DefectKind.UNKNOWN_SKU
    )
    first = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))
    [quarantine] = ops_day.run_ops_day(DAY).audit_entries
    clock.advance(LATER)
    _submit(ops_day, "ST01", UploadKind.SALES, generated.resubmission("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)
    before = _sales(ops_day, "ST01")

    with pytest.raises(ValueError, match="Superseded"):
        ops_day.undo(quarantine.entry_id, taken_by="bi.analyst@cobalthome.example")

    assert _status(ops_day, first).status is UploadStatus.SUPERSEDED
    assert _sales(ops_day, "ST01") == before
    assert len(ops_day.audit_log()) == 1


def test_resubmissions_of_other_sales_channels_and_kinds_are_left_alone(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated = _generate(catalog, "ST01", UploadKind.SALES, ResubmissionKind.CORRECTED)
    for channel in ("ST01", "ST02"):
        for kind in UploadKind:
            _submit(ops_day, channel, kind, generated.content(channel, DAY, kind))
    ops_day.run_ops_day(DAY)

    clock.advance(LATER)
    _submit(ops_day, "ST01", UploadKind.SALES, generated.resubmission("ST01", DAY, UploadKind.SALES))
    ops_day.run_ops_day(DAY)

    superseded = [u.upload_id for u in ops_day.upload_statuses() if u.status is UploadStatus.SUPERSEDED]
    assert superseded == ["ST01-2026-03-02-sales-001"]
