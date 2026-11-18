from __future__ import annotations

from datetime import date, timedelta

import pytest

from retail_ops_agent.audit_log import ActionTier, AuditAction, UndoOperation
from retail_ops_agent.catalog import Catalog
from retail_ops_agent.clock import SimulatedClock
from retail_ops_agent.defects import SAFE_FIX_TABLE, DefectKind
from retail_ops_agent.generator import (
    PLANTABLE_DEFECTS,
    DefectPlan,
    GeneratedUploads,
    generate_history,
    generate_uploads,
    upload_csv,
)
from retail_ops_agent.notifier import LogNotifier
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.uploads import UploadKind, UploadStatus

DAY = date(2026, 3, 2)
UPLOADER = "uploader@cobalthome.example"
ANALYST = "bi.analyst@cobalthome.example"


def _generate(catalog: Catalog, *plans: tuple[str, UploadKind, DefectKind]) -> GeneratedUploads:
    return generate_uploads(
        generate_history(catalog, DAY, 1),
        [
            DefectPlan(sales_channel=channel, day=DAY, upload_kind=kind, defect_kind=defect)
            for channel, kind, defect in plans
        ],
    )


def _submit(ops_day: OpsDay, sales_channel: str, kind: UploadKind, content: str) -> str:
    return ops_day.submit_upload(
        sales_channel=sales_channel, day=DAY, kind=kind, content=content, uploader=UPLOADER
    )


def _loaded(ops_day: OpsDay, kind: UploadKind) -> dict[str, int]:
    """Units loaded into the BI data per Sales Channel."""
    if kind is UploadKind.SALES:
        return {r.sales_channel: r.quantity_sold for r in ops_day.sales_by_sales_channel()}
    return {r.sales_channel: r.on_hand for r in ops_day.inventory_by_sales_channel()}


def _truth(generated: GeneratedUploads, sales_channel: str, kind: UploadKind) -> int:
    if kind is UploadKind.SALES:
        return sum(r.quantity_sold for r in generated.history.sales(sales_channel, DAY))
    return sum(r.on_hand for r in generated.history.inventory(sales_channel, DAY))


def test_the_safe_fix_table_covers_every_defect_kind_and_marks_the_planted_ones_safe() -> None:
    assert set(SAFE_FIX_TABLE) == set(DefectKind)
    assert {k for k, safe in SAFE_FIX_TABLE.items() if safe} == PLANTABLE_DEFECTS


@pytest.mark.parametrize("defect_kind", sorted(PLANTABLE_DEFECTS))
@pytest.mark.parametrize("sales_channel", ["ST01", "ONLINE"])
@pytest.mark.parametrize("kind", list(UploadKind))
def test_each_planted_safe_fixable_defect_is_detected_fixed_and_logged(
    ops_day: OpsDay,
    catalog: Catalog,
    notifier: LogNotifier,
    defect_kind: DefectKind,
    sales_channel: str,
    kind: UploadKind,
) -> None:
    generated = _generate(catalog, (sales_channel, kind, defect_kind))
    [planted] = generated.ground_truth.defects
    upload_id = _submit(ops_day, sales_channel, kind, generated.content(sales_channel, DAY, kind))

    outcome = ops_day.run_ops_day(DAY)

    [upload] = outcome.uploads
    assert upload.status is planted.expected_status is UploadStatus.SAFE_FIXED
    assert [(d.kind, d.row, d.column) for d in upload.defects] == [
        (planted.defect_kind, planted.row, planted.column)
    ]
    assert _loaded(ops_day, kind) == {sales_channel: _truth(generated, sales_channel, kind)}
    assert notifier.sent == []

    [entry] = outcome.audit_entries
    assert ops_day.audit_log() == [entry]
    assert entry.action is AuditAction.SAFE_FIX
    assert entry.tier is ActionTier.INTERNAL
    assert entry.taken_by == "Intake agent"
    assert upload_id in entry.triggered_by
    assert defect_kind.value in entry.triggered_by
    assert entry.defect == upload.defects[0]
    assert (entry.undo.operation, entry.undo.upload_id) == (UndoOperation.RESTORE_ORIGINAL_UPLOAD, upload_id)
    assert entry.undone_by is None


def test_several_safe_fixes_in_one_upload_each_get_an_audit_log_entry(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    generated = _generate(
        catalog,
        ("ST02", UploadKind.SALES, DefectKind.BYTE_ORDER_MARK),
        ("ST02", UploadKind.SALES, DefectKind.WRONG_DELIMITER),
        ("ST02", UploadKind.SALES, DefectKind.RENAMED_COLUMN),
        ("ST02", UploadKind.SALES, DefectKind.STRAY_WHITESPACE),
    )
    _submit(ops_day, "ST02", UploadKind.SALES, generated.content("ST02", DAY, UploadKind.SALES))

    outcome = ops_day.run_ops_day(DAY)

    assert [u.status for u in outcome.uploads] == [UploadStatus.SAFE_FIXED]
    expected = {(p.defect_kind, p.row, p.column) for p in generated.ground_truth.defects}
    assert {(d.kind, d.row, d.column) for d in outcome.uploads[0].defects} == expected
    assert {(e.defect.kind, e.defect.row, e.defect.column) for e in outcome.audit_entries if e.defect} == (
        expected
    )
    assert _loaded(ops_day, UploadKind.SALES) == {"ST02": _truth(generated, "ST02", UploadKind.SALES)}


def test_clean_uploads_produce_no_safe_fixes(ops_day: OpsDay, catalog: Catalog) -> None:
    generated = _generate(catalog)
    for channel in catalog.sales_channels:
        for kind in UploadKind:
            _submit(ops_day, channel.code, kind, generated.content(channel.code, DAY, kind))

    outcome = ops_day.run_ops_day(DAY)

    assert {u.status for u in outcome.uploads} == {UploadStatus.ACCEPTED}
    assert outcome.audit_entries == []
    assert ops_day.audit_log() == []
    assert generated.ground_truth.defects == ()


def _safe_fixed_upload(ops_day: OpsDay, catalog: Catalog) -> tuple[str, int]:
    generated = _generate(catalog, ("ST01", UploadKind.SALES, DefectKind.RENAMED_COLUMN))
    upload_id = _submit(ops_day, "ST01", UploadKind.SALES, generated.content("ST01", DAY, UploadKind.SALES))
    [entry] = ops_day.run_ops_day(DAY).audit_entries
    return upload_id, entry.entry_id


def _status(ops_day: OpsDay, upload_id: str) -> UploadStatus:
    return next(u.status for u in ops_day.upload_statuses() if u.upload_id == upload_id)


def test_undoing_a_safe_fix_restores_the_upload_as_it_arrived_and_is_a_new_entry(
    ops_day: OpsDay, catalog: Catalog, clock: SimulatedClock
) -> None:
    upload_id, fix_id = _safe_fixed_upload(ops_day, catalog)
    [before] = ops_day.audit_log()
    clock.advance(timedelta(hours=2))

    undo = ops_day.undo(fix_id, taken_by=ANALYST)

    assert undo.action is AuditAction.UNDO
    assert undo.tier is ActionTier.INTERNAL
    assert undo.taken_by == ANALYST
    assert undo.undoes == fix_id
    assert undo.recorded_at == clock.now()
    assert (undo.undo.operation, undo.undo.entry_id) == (UndoOperation.REINSTATE_ENTRY, fix_id)
    newest, original = ops_day.audit_log()
    assert newest == undo
    assert original == before.model_copy(update={"undone_by": undo.entry_id})
    assert _status(ops_day, upload_id) is UploadStatus.QUARANTINED
    assert ops_day.sales_by_sales_channel() == []


def test_undoing_an_undo_reinstates_the_safe_fix(ops_day: OpsDay, catalog: Catalog) -> None:
    upload_id, fix_id = _safe_fixed_upload(ops_day, catalog)
    loaded = _loaded(ops_day, UploadKind.SALES)
    undo = ops_day.undo(fix_id, taken_by=ANALYST)

    redo = ops_day.undo(undo.entry_id, taken_by=ANALYST)

    assert redo.undoes == undo.entry_id
    assert [e.entry_id for e in ops_day.audit_log()] == [redo.entry_id, undo.entry_id, fix_id]
    assert ops_day.audit_log()[-1].undone_by is None
    assert _status(ops_day, upload_id) is UploadStatus.SAFE_FIXED
    assert _loaded(ops_day, UploadKind.SALES) == loaded


def test_an_entry_cannot_be_undone_twice_or_if_it_does_not_exist(ops_day: OpsDay, catalog: Catalog) -> None:
    _, fix_id = _safe_fixed_upload(ops_day, catalog)
    ops_day.undo(fix_id, taken_by=ANALYST)

    with pytest.raises(ValueError, match="already undone"):
        ops_day.undo(fix_id, taken_by=ANALYST)
    with pytest.raises(ValueError, match="no Audit Log entry"):
        ops_day.undo(999, taken_by=ANALYST)
    assert len(ops_day.audit_log()) == 2


def test_a_safe_fixable_defect_beside_an_unfixable_one_is_quarantined_without_a_safe_fix(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    sku = catalog.skus[0].code
    content = f"date,store_code,sku,on_hand\n{DAY.isoformat()}, ST01 ,{sku},-4\n"
    _submit(ops_day, "ST01", UploadKind.INVENTORY, content)

    outcome = ops_day.run_ops_day(DAY)

    [upload] = outcome.uploads
    assert upload.status is UploadStatus.QUARANTINED
    assert {(d.kind, d.column) for d in upload.defects} == {
        (DefectKind.STRAY_WHITESPACE, "store_code"),
        (DefectKind.IMPOSSIBLE_QUANTITY, "on_hand"),
    }
    assert outcome.audit_entries == []
    assert ops_day.inventory_by_sku() == []


def test_a_header_that_could_be_either_of_two_columns_is_not_renamed(
    ops_day: OpsDay, catalog: Catalog
) -> None:
    history = generate_history(catalog, DAY, 1)
    content = upload_csv(history, "ST01", DAY, UploadKind.SALES).replace(
        "quantity_sold,net_sales", "Quantity Sold,qty_sold", 1
    )
    _submit(ops_day, "ST01", UploadKind.SALES, content)

    outcome = ops_day.run_ops_day(DAY)

    [upload] = outcome.uploads
    assert upload.status is UploadStatus.QUARANTINED
    assert {d.kind for d in upload.defects} == {DefectKind.MISSING_COLUMN}
    assert outcome.audit_entries == []


def test_semicolons_with_decimal_commas_are_not_guessed_at(ops_day: OpsDay, catalog: Catalog) -> None:
    sku = catalog.skus[0].code
    content = f"date;store_code;sku;quantity_sold;net_sales\n{DAY.isoformat()};ST01;{sku};2;12,50\n"
    _submit(ops_day, "ST01", UploadKind.SALES, content)

    outcome = ops_day.run_ops_day(DAY)

    assert [u.status for u in outcome.uploads] == [UploadStatus.QUARANTINED]
    assert outcome.audit_entries == []
