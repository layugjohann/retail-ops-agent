from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"


def test_dashboard_renders_sales_inventory_and_upload_status_offline() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()

    assert not app.exception
    headers = [h.value for h in app.header]
    assert "Sales by Sales Channel" in headers
    assert "Inventory" in headers
    assert "Upload status" in headers
    assert "Uploader messages" in headers
    assert "Audit Log" in headers
    assert len(app.dataframe) == 5
    assert "quarantined" in set(app.dataframe[2].value["status"])


def test_dashboard_shows_each_quarantined_uploads_message() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()

    statuses = app.dataframe[2].value
    quarantined = set(statuses[statuses["status"] == "quarantined"]["Upload"])
    assert len(quarantined) == 3
    assert set(app.dataframe[3].value["Upload"]) == quarantined
    assert all("What to do:" in t.value for t in app.text)


def test_dashboard_audit_log_lists_safe_fixes_and_can_undo_one() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()
    before = len(app.dataframe[4].value)
    assert before > 0
    assert set(app.dataframe[4].value["Action"]) == {"safe_fix", "quarantine"}

    app.button[0].click().run()

    assert not app.exception
    log = app.dataframe[4].value
    assert len(log) == before + 1
    assert log["Action"].iloc[0] == "undo"
