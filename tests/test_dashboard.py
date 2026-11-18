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
    assert "Investigations" in headers
    assert "Audit Log" in headers
    assert len(app.dataframe) == 6
    assert "quarantined" in set(app.dataframe[2].value["status"])


def test_dashboard_shows_each_quarantined_uploads_message() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()

    statuses = app.dataframe[2].value
    ever_quarantined = set(statuses[statuses["history"].str.startswith("quarantined")]["Upload"])
    assert len(ever_quarantined) == 3
    assert set(app.dataframe[3].value["Upload"]) == ever_quarantined
    assert all("What to do:" in t.value for t in app.text)


def test_dashboard_shows_superseded_uploads_and_their_history() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()

    statuses = app.dataframe[2].value
    superseded = statuses[statuses["status"] == "superseded"]
    assert set(superseded["Upload"]) == {"ST03-2026-11-06-sales-001", "ST01-2026-11-10-inventory-001"}
    corrected = superseded[superseded["Upload"] == "ST03-2026-11-06-sales-001"].iloc[0]
    assert corrected["superseded by"] == "ST03-2026-11-06-sales-002"
    assert corrected["history"] == "quarantined → superseded"
    replacement = statuses[statuses["Upload"] == "ST03-2026-11-06-sales-002"].iloc[0]
    assert replacement["status"] == "accepted"


def test_dashboard_audit_log_lists_safe_fixes_and_can_undo_one() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()
    before = len(app.dataframe[5].value)
    assert before > 0
    assert set(app.dataframe[5].value["Action"]) == {"safe_fix", "quarantine", "alert"}

    app.button[0].click().run()

    assert not app.exception
    log = app.dataframe[5].value
    assert len(log) == before + 1
    assert log["Action"].iloc[0] == "undo"


def test_dashboard_shows_investigations_with_their_evidence() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120).run()

    investigations = app.dataframe[4].value
    assert list(investigations["Anomaly"]) == ["stockout_risk"]
    assert list(investigations["Sales Channel"]) == ["ST02"]
    [expander] = app.expander[-1:]
    assert "Stockout risk" in expander.label
    shown = " ".join(m.value for m in expander.markdown)
    assert "Evidence:" in shown and "days of cover" in shown and "Likely cause:" in shown
    alerts = app.dataframe[5].value
    alerts = alerts[alerts["Action"] == "alert"]
    assert list(alerts["Tier"]) == [1]
    assert list(alerts["Investigation"]) == list(investigations["Investigation"])
