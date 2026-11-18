from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from retail_ops_agent.audit_log import ActionTier, AuditAction, UndoOperation
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.data_source import CsvDataSource
from retail_ops_agent.defects import SAFE_FIX_TABLE, DefectKind
from retail_ops_agent.erp import InMemoryErp
from retail_ops_agent.generator import (
    PLANTABLE_DEFECTS,
    DefectPlan,
    GeneratedUploads,
    generate_catalog,
    generate_history,
    generate_uploads,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus

from .conftest import scripted_intake_model, scripted_models

DAY = date(2026, 3, 2)
UPLOAD_TIME = datetime(2026, 3, 2, 21, 0)
UPLOADER = "manager.st01@cobalthome.example"
ANALYST = "bi.analyst@cobalthome.example"

UNFIXABLE = sorted(k for k in PLANTABLE_DEFECTS if not SAFE_FIX_TABLE[k])

# Words an Uploader would recognise for each planted Defect, and for the correction to make.
NAMES = {
    DefectKind.MISSING_COLUMN: ("Missing column", "Add this column"),
    DefectKind.SWAPPED_COLUMNS: ("Swapped columns", "back under its own header"),
    DefectKind.DUPLICATE_DAY: ("Day reported twice", "Remove the repeated rows"),
    DefectKind.IMPOSSIBLE_QUANTITY: ("Impossible quantity", "Enter the real quantity"),
    DefectKind.UNKNOWN_SKU: ("Unknown SKU", "Check the SKU against the catalog"),
    DefectKind.DATE_MISMATCH: ("Wrong date", "Export the data for the day the Upload is for"),
}


def _generate(
    catalog: Catalog, *plans: tuple[str, UploadKind, DefectKind], days: int = 1
) -> GeneratedUploads:
    return generate_uploads(
        generate_history(catalog, DAY, days),
        [
            DefectPlan(sales_channel=channel, day=DAY, upload_kind=kind, defect_kind=defect)
            for channel, kind, defect in plans
        ],
    )


def _ops_day(catalog: Catalog, directory: Path, notifier: LogNotifier, intake: TestModel) -> OpsDay:
    return OpsDay(
        models=scripted_models(intake),
        erp=InMemoryErp(catalog),
        notifier=notifier,
        data_source=CsvDataSource(directory / "uploads"),
        clock=SimulatedClock(UPLOAD_TIME),
    )


def _submit(ops_day: OpsDay, generated: GeneratedUploads, sales_channel: str, kind: UploadKind) -> str:
    return ops_day.submit_upload(
        sales_channel=sales_channel,
        day=DAY,
        kind=kind,
        content=generated.content(sales_channel, DAY, kind),
        uploader=UPLOADER,
    )


def _loaded(ops_day: OpsDay) -> set[tuple[str, str]]:
    """(Sales Channel, kind) of everything in the BI data."""
    return {(r.sales_channel, "sales") for r in ops_day.sales_by_sales_channel()} | {
        (r.sales_channel, "inventory") for r in ops_day.inventory_by_sales_channel()
    }


def test_every_defect_kind_planted_here_has_no_safe_fix_and_words_for_the_uploader() -> None:
    assert set(UNFIXABLE) == set(NAMES)


@pytest.mark.parametrize("defect_kind", UNFIXABLE)
@pytest.mark.parametrize("sales_channel", ["ST01", "ONLINE"])
@pytest.mark.parametrize("kind", list(UploadKind))
def test_each_planted_unfixable_defect_quarantines_the_upload_and_messages_the_uploader(
    ops_day: OpsDay,
    catalog: Catalog,
    notifier: LogNotifier,
    defect_kind: DefectKind,
    sales_channel: str,
    kind: UploadKind,
) -> None:
    generated = _generate(catalog, (sales_channel, kind, defect_kind))
    [planted] = generated.ground_truth.defects
    upload_id = _submit(ops_day, generated, sales_channel, kind)

    outcome = ops_day.run_ops_day(DAY)

    [upload] = outcome.uploads
    assert upload.status is planted.expected_status is UploadStatus.QUARANTINED
    assert [(d.kind, d.row, d.column) for d in upload.defects] == [
        (planted.defect_kind, planted.row, planted.column)
    ]
    assert _loaded(ops_day) == set()
    assert [u.status for u in ops_day.upload_statuses()] == [UploadStatus.QUARANTINED]

    [entry] = outcome.audit_entries
    assert ops_day.audit_log() == [entry]
    assert (entry.action, entry.tier, entry.taken_by) == (
        AuditAction.QUARANTINE,
        ActionTier.INTERNAL,
        "Intake agent",
    )
    assert upload_id in entry.triggered_by and defect_kind.value in entry.triggered_by
    assert (entry.undo.operation, entry.undo.upload_id) == (UndoOperation.RELEASE_UPLOAD, upload_id)

    [message] = outcome.uploader_messages
    assert ops_day.uploader_messages() == [message]
    assert (message.upload_id, message.recipient) == (upload_id, UPLOADER)
    [sent] = notifier.sent
    assert (sent.recipient, sent.subject, sent.body) == (message.recipient, message.subject, message.body)
    name, fix = NAMES[defect_kind]
    assert name in message.body
    assert fix in message.body
    if planted.row is not None:
        assert f"row {planted.row}" in message.body
    assert f"column {planted.column}" in message.body
    assert upload_id in message.body


def test_a_quarantined_upload_keeps_none_of_its_rows_while_the_others_load(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    # One bad row among hundreds still keeps the whole Upload out.
    generated = _generate(catalog, ("ST03", UploadKind.SALES, DefectKind.IMPOSSIBLE_QUANTITY))
    for channel in catalog.sales_channels:
        for kind in UploadKind:
            _submit(ops_day, generated, channel.code, kind)

    outcome = ops_day.run_ops_day(DAY)

    quarantined = [u for u in outcome.uploads if u.status is UploadStatus.QUARANTINED]
    assert [(u.sales_channel, u.kind) for u in quarantined] == [("ST03", UploadKind.SALES)]
    everything = {(c.code, k.value) for c in catalog.sales_channels for k in UploadKind}
    assert _loaded(ops_day) == everything - {("ST03", "sales")}
    assert len(outcome.uploader_messages) == 1


@pytest.mark.parametrize("seed", [1, 42, 2026])
def test_clean_uploads_are_never_quarantined(seed: int, tmp_path: Path) -> None:
    catalog = generate_catalog(seed)
    notifier = LogNotifier()
    ops_day = _ops_day(catalog, tmp_path, notifier, scripted_intake_model())
    generated = generate_uploads(generate_history(catalog, DAY, 3))
    for day in generated.history.days:
        for channel in catalog.sales_channels:
            for kind in UploadKind:
                ops_day.submit_upload(
                    sales_channel=channel.code,
                    day=day,
                    kind=kind,
                    content=generated.content(channel.code, day, kind),
                    uploader=UPLOADER,
                )
        outcome = ops_day.run_ops_day(day)
        assert {u.status for u in outcome.uploads} == {UploadStatus.ACCEPTED}
        assert outcome.uploader_messages == []

    assert notifier.sent == []
    assert ops_day.audit_log() == []


def test_the_intake_agents_note_is_added_to_the_message_but_never_replaces_the_list(
    catalog: Catalog, tmp_path: Path
) -> None:
    note = "Your till export seems to have picked up yesterday's file."
    ops_day = _ops_day(catalog, tmp_path, LogNotifier(), scripted_intake_model(uploader_message=note))
    generated = _generate(catalog, ("ST01", UploadKind.SALES, DefectKind.DATE_MISMATCH))
    _submit(ops_day, generated, "ST01", UploadKind.SALES)

    [message] = ops_day.run_ops_day(DAY).uploader_messages

    assert note in message.body
    assert "Wrong date at column date" in message.body


def test_a_message_lists_the_first_defects_and_counts_the_rest(ops_day: OpsDay, catalog: Catalog) -> None:
    unknown = "\n".join(f"{DAY.isoformat()},ST01,CH-{9000 + i},1,10.00" for i in range(14))
    upload_id = ops_day.submit_upload(
        sales_channel="ST01",
        day=DAY,
        kind=UploadKind.SALES,
        content=f"date,store_code,sku,quantity_sold,net_sales\n{unknown}\n{DAY.isoformat()},ST01,"
        f"{catalog.skus[0].code},1,10.00\n",
        uploader=UPLOADER,
    )

    [message] = ops_day.run_ops_day(DAY).uploader_messages

    assert message.upload_id == upload_id
    assert "10. Unknown SKU at row 11, column sku" in message.body
    assert "row 12" not in message.body
    assert "and 4 more Defects" in message.body


def _quarantined(ops_day: OpsDay, catalog: Catalog) -> tuple[GeneratedUploads, str, int]:
    generated = _generate(catalog, ("ST01", UploadKind.SALES, DefectKind.UNKNOWN_SKU))
    upload_id = _submit(ops_day, generated, "ST01", UploadKind.SALES)
    [entry] = ops_day.run_ops_day(DAY).audit_entries
    return generated, upload_id, entry.entry_id


def _status(ops_day: OpsDay, upload_id: str) -> UploadStatus:
    return next(u.status for u in ops_day.upload_statuses() if u.upload_id == upload_id)


def test_undoing_a_quarantine_releases_the_rows_that_passed_every_check(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    generated, upload_id, quarantine_id = _quarantined(ops_day, catalog)
    [planted] = generated.ground_truth.defects
    truth = generated.history.sales("ST01", DAY)
    bad_row = truth[(planted.row or 0) - 2]
    clock.advance(timedelta(hours=1))

    undo = ops_day.undo(quarantine_id, taken_by=ANALYST)

    assert (undo.action, undo.tier, undo.undoes, undo.taken_by) == (
        AuditAction.UNDO,
        ActionTier.INTERNAL,
        quarantine_id,
        ANALYST,
    )
    assert [e.entry_id for e in ops_day.audit_log()] == [undo.entry_id, quarantine_id]
    assert ops_day.audit_log()[1].undone_by == undo.entry_id
    assert _status(ops_day, upload_id) is UploadStatus.ACCEPTED
    [sales] = ops_day.sales_by_sales_channel()
    assert sales.quantity_sold == sum(r.quantity_sold for r in truth) - bad_row.quantity_sold


def test_undoing_the_release_quarantines_the_upload_again(ops_day: OpsDay, catalog: Catalog) -> None:
    _, upload_id, quarantine_id = _quarantined(ops_day, catalog)
    release = ops_day.undo(quarantine_id, taken_by=ANALYST)

    again = ops_day.undo(release.entry_id, taken_by=ANALYST)

    assert again.undoes == release.entry_id
    assert ops_day.audit_log()[-1].undone_by is None
    assert _status(ops_day, upload_id) is UploadStatus.QUARANTINED
    assert ops_day.sales_by_sales_channel() == []


def test_releasing_a_duplicated_day_loads_each_row_once(ops_day: OpsDay, catalog: Catalog) -> None:
    generated = _generate(catalog, ("ST02", UploadKind.INVENTORY, DefectKind.DUPLICATE_DAY))
    _submit(ops_day, generated, "ST02", UploadKind.INVENTORY)
    [entry] = ops_day.run_ops_day(DAY).audit_entries

    ops_day.undo(entry.entry_id, taken_by=ANALYST)

    [inventory] = ops_day.inventory_by_sales_channel()
    assert inventory.on_hand == sum(r.on_hand for r in generated.history.inventory("ST02", DAY))


def test_releasing_an_upload_logs_each_safe_fix_behind_its_loaded_rows(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    good, bad = catalog.skus[0].code, catalog.skus[1].code
    upload_id = ops_day.submit_upload(
        sales_channel="ST01",
        day=DAY,
        kind=UploadKind.INVENTORY,
        content=(
            f"date,store_code,sku,on_hand\n{DAY.isoformat()}, ST01 ,{good},4\n"
            f"{DAY.isoformat()},ST01,{bad},-4\n"
        ),
        uploader=UPLOADER,
    )
    [quarantine] = ops_day.run_ops_day(DAY).audit_entries

    ops_day.undo(quarantine.entry_id, taken_by=ANALYST)

    assert _status(ops_day, upload_id) is UploadStatus.SAFE_FIXED
    [fix] = [e for e in ops_day.audit_log() if e.action is AuditAction.SAFE_FIX]
    assert fix.defect is not None and fix.defect.kind is DefectKind.STRAY_WHITESPACE

    ops_day.undo(fix.entry_id, taken_by=ANALYST)

    assert _status(ops_day, upload_id) is UploadStatus.QUARANTINED
    assert ops_day.inventory_by_sku() == []
