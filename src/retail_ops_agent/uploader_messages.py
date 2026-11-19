"""The plain-language message Intake writes an Uploader when their Upload is Quarantined.

Each Defect is named, located and paired with the correction to make, from fixed tables, so the
message always says what is wrong, where, and what to do, whatever the model adds to it.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from retail_ops_agent.defects import Defect, DefectKind, defect_location
from retail_ops_agent.uploads import Upload

# At most this many Defects are listed one by one; the rest are counted.
MAX_LISTED_DEFECTS = 10

DEFECT_NAMES: Mapping[DefectKind, str] = MappingProxyType(
    {
        DefectKind.MISSING_COLUMN: "Missing column",
        DefectKind.UNREADABLE_VALUE: "Unreadable value",
        DefectKind.UNKNOWN_SKU: "Unknown SKU",
        DefectKind.SALES_CHANNEL_MISMATCH: "Wrong store code",
        DefectKind.DATE_MISMATCH: "Wrong date",
        DefectKind.IMPOSSIBLE_QUANTITY: "Impossible quantity",
        DefectKind.SWAPPED_COLUMNS: "Swapped columns",
        DefectKind.DUPLICATE_DAY: "Day reported twice",
        DefectKind.RENAMED_COLUMN: "Renamed column",
        DefectKind.STRAY_WHITESPACE: "Spaces around a value",
        DefectKind.WRONG_DELIMITER: "Values not separated by commas",
        DefectKind.BYTE_ORDER_MARK: "Byte order mark",
        DefectKind.UNITS_IN_CASES: "Quantity not in units",
    }
)

FIXES: Mapping[DefectKind, str] = MappingProxyType(
    {
        DefectKind.MISSING_COLUMN: (
            "Add this column to the header and fill it in on every row, as in your usual export."
        ),
        DefectKind.UNREADABLE_VALUE: (
            "Replace the value with one in the usual format, for example 12 or 2026-03-02."
        ),
        DefectKind.UNKNOWN_SKU: (
            "Check the SKU against the catalog and correct the typo; if it is a new SKU, ask the BI "
            "analyst to add it to the catalog before you resend."
        ),
        DefectKind.SALES_CHANNEL_MISMATCH: (
            "Make sure the file is for this Sales Channel and every row has its store code."
        ),
        DefectKind.DATE_MISMATCH: (
            "Export the data for the day the Upload is for, or submit this file for the day it covers."
        ),
        DefectKind.IMPOSSIBLE_QUANTITY: (
            "Enter the real quantity in units: stock cannot be negative and sales cannot be negative "
            "or absurdly large."
        ),
        DefectKind.SWAPPED_COLUMNS: (
            "Put each value back under its own header (or the headers back over their values) so "
            "every column holds what its name says."
        ),
        DefectKind.DUPLICATE_DAY: (
            "Remove the repeated rows so the day's data appears only once, keeping the copy that is correct."
        ),
        DefectKind.RENAMED_COLUMN: "Use the usual column name.",
        DefectKind.STRAY_WHITESPACE: "Remove the spaces around the value.",
        DefectKind.WRONG_DELIMITER: "Save the file as a comma-separated CSV.",
        DefectKind.BYTE_ORDER_MARK: "Save the file as UTF-8 without a byte order mark.",
        DefectKind.UNITS_IN_CASES: (
            "Report every quantity as the number of single units, as your usual export does, with no "
            "conversion to or from cases or case packs, and check any other day sent the same way."
        ),
    }
)


def quarantine_subject(upload: Upload) -> str:
    return f"Upload {upload.upload_id} is Quarantined: please correct it and resend"


def quarantine_message(upload: Upload, defects: list[Defect], note: str | None = None) -> str:
    """The message to the Uploader of a Quarantined Upload, listing each Defect with its fix.

    The Intake agent's own note, if any, is included as written but never replaces the list.
    """
    return _message(
        upload,
        f"Your {upload.kind.value} Upload for {upload.sales_channel} on {upload.day.isoformat()} "
        f"({upload.upload_id}) is in Quarantine, so none of its rows are in the BI data yet.",
        defects,
        note,
    )


def data_problem_message(upload: Upload, defects: list[Defect]) -> str:
    """The message to the Uploader of an Upload sent back to Intake by a Data Problem: it passed
    validation and was loaded, but an Investigation found it wrong, so it is now in Quarantine."""
    return _message(
        upload,
        f"Your {upload.kind.value} Upload for {upload.sales_channel} on {upload.day.isoformat()} "
        f"({upload.upload_id}) passed our checks, but looking into an unusual pattern in the figures "
        "showed it is not right. It is now in Quarantine, and its rows have been taken out of the BI "
        "data.",
        defects,
        None,
    )


def _message(upload: Upload, opening: str, defects: list[Defect], note: str | None) -> str:
    lines = [
        opening,
        "",
        "Please correct the following and resend the whole file for the same day; it will replace this one.",
        "",
    ]
    for number, defect in enumerate(defects[:MAX_LISTED_DEFECTS], start=1):
        lines.append(
            f"{number}. {DEFECT_NAMES[defect.kind]} at {defect_location(defect)}: {defect.detail}. "
            f"What to do: {FIXES[defect.kind]}"
        )
    if len(defects) > MAX_LISTED_DEFECTS:
        lines.append(
            f"... and {len(defects) - MAX_LISTED_DEFECTS} more Defects. "
            "The Upload status view lists them all."
        )
    if note and note.strip():
        lines.extend(["", f"Note from the Intake agent: {note.strip()}"])
    return "\n".join(lines)
