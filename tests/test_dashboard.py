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
    assert len(app.dataframe) == 3
