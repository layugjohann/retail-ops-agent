from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"


def _live_app() -> AppTest:
    """The dashboard switched from its default, Replay Mode, to Live Mode."""
    app = AppTest.from_file(str(APP), default_timeout=120).run()
    return app.radio(key="mode").set_value("Live Mode").run()


@pytest.fixture
def fresh_sandbox() -> None:
    """The sandbox is cached for the whole process; a test that decides the Approval Queue's one
    Reorder needs it undecided."""
    st.cache_resource.clear()


def test_dashboard_renders_sales_inventory_and_upload_status_offline() -> None:
    app = _live_app()

    assert not app.exception
    headers = [h.value for h in app.header]
    assert "Sales by Sales Channel" in headers
    assert "Inventory" in headers
    assert "Upload status" in headers
    assert "Uploader messages" in headers
    assert "Investigations" in headers
    assert "Approval Queue" in headers
    assert "Hours Saved" in headers
    assert "Audit Log" in headers
    assert len(app.dataframe) == 8
    assert "quarantined" in set(app.dataframe[2].value["status"])


def test_dashboard_shows_each_quarantined_uploads_message() -> None:
    app = _live_app()

    statuses = app.dataframe[2].value
    ever_quarantined = set(statuses[statuses["history"].str.startswith("quarantined")]["Upload"])
    assert len(ever_quarantined) == 3
    assert set(app.dataframe[3].value["Upload"]) == ever_quarantined
    assert all("What to do:" in t.value for t in app.text)


def test_dashboard_shows_superseded_uploads_and_their_history() -> None:
    app = _live_app()

    statuses = app.dataframe[2].value
    superseded = statuses[statuses["status"] == "superseded"]
    assert set(superseded["Upload"]) == {"ST03-2026-11-06-sales-001", "ST01-2026-11-10-inventory-001"}
    corrected = superseded[superseded["Upload"] == "ST03-2026-11-06-sales-001"].iloc[0]
    assert corrected["superseded by"] == "ST03-2026-11-06-sales-002"
    assert corrected["history"] == "quarantined → superseded"
    replacement = statuses[statuses["Upload"] == "ST03-2026-11-06-sales-002"].iloc[0]
    assert replacement["status"] == "accepted"


def test_dashboard_audit_log_lists_safe_fixes_and_can_undo_one() -> None:
    app = _live_app()
    before = len(app.dataframe[-1].value)
    assert before > 0
    assert set(app.dataframe[-1].value["Action"]) == {"safe_fix", "quarantine"}

    app.button(key="undo").click().run()

    assert not app.exception
    log = app.dataframe[-1].value
    assert len(log) == before + 1
    assert log["Action"].iloc[0] == "undo"


def test_dashboard_shows_hours_saved_with_its_assumptions() -> None:
    app = _live_app()

    assumptions = app.dataframe[-2].value
    log = app.dataframe[-1].value
    assert set(assumptions["Action"]) == {"safe_fix", "quarantine", "alert", "reorder"}
    assert set(assumptions["basis"]) == {"assumption"}
    assert all(assumptions["source or assumption"].str.len() > 0)
    for row in assumptions.to_dict("records"):
        standing = (log["Action"] == row["Action"]) & log["undone by entry"].isna()
        assert row["entries"] == standing.sum()
        assert row["minutes saved"] == row["entries"] * row["minutes each"]
    [metric] = [m for m in app.metric if m.label == "Hours Saved"]
    assert metric.value == f"{assumptions['minutes saved'].sum() / 60:.2f} h"
    assert any("SIMULATED" in c.value for c in app.caption)


def test_dashboard_shows_investigations_with_their_evidence() -> None:
    app = _live_app()

    investigations = app.dataframe[4].value
    assert list(investigations["Anomaly"]) == ["stockout_risk"]
    assert list(investigations["Sales Channel"]) == ["ST02"]
    [expander] = app.expander[-1:]
    assert "Stockout risk" in expander.label
    shown = " ".join(m.value for m in expander.markdown)
    assert "Evidence:" in shown and "days of cover" in shown and "Likely cause:" in shown


@pytest.mark.usefixtures("fresh_sandbox")
def test_dashboard_approval_queue_shows_the_reorder_and_approving_places_it() -> None:
    app = _live_app()

    investigations = app.dataframe[4].value
    queue = app.dataframe[5].value
    [action_id] = list(queue["Action"])
    assert list(queue["Investigation"]) == list(investigations["Investigation"])
    assert list(queue["Sales Channel"]) == ["ST02"]
    assert list(queue["quantity"]) == [48]
    [supplier] = list(queue["Supplier"])
    assert supplier
    [cost] = list(queue["cost"])
    assert cost == round(48 * queue["unit cost"].iloc[0], 2)
    assert not [b for b in app.button if b.label == "Approve" and b.key != f"approve-{action_id}"]
    assert "reorder" not in set(app.dataframe[-1].value["Action"])

    app.button(key=f"approve-{action_id}").click().run()

    assert not app.exception
    assert any("Nothing waiting for Approval" in i.value for i in app.info)
    decided = app.dataframe[5].value
    assert list(decided["decision"]) == ["approved"]
    assert decided["ERP Reorder"].iloc[0].startswith("RO-")
    log = app.dataframe[-1].value
    [reorder] = log[log["Action"] == "reorder"].to_dict("records")
    assert reorder["Tier"] == 2
    assert reorder["taken by"] == "inventory planner (dashboard)"
    assert reorder["Investigation"] == investigations["Investigation"].iloc[0]


@pytest.mark.usefixtures("fresh_sandbox")
def test_dashboard_approval_queue_can_reject_a_reorder() -> None:
    app = _live_app()
    [action_id] = list(app.dataframe[5].value["Action"])

    app.button(key=f"reject-{action_id}").click().run()

    assert not app.exception
    assert list(app.dataframe[5].value["decision"]) == ["rejected"]
    assert "reorder" not in set(app.dataframe[-1].value["Action"])


@pytest.mark.usefixtures("fresh_sandbox")
def test_dashboard_advancing_simulated_time_expires_the_pending_reorder() -> None:
    app = _live_app()
    [action_id] = list(app.dataframe[5].value["Action"])

    app.button(key="advance-time").click().run()
    assert list(app.dataframe[5].value["Action"]) == [action_id]
    app.button(key="advance-time").click().run()

    assert not app.exception
    assert any("Nothing waiting for Approval" in i.value for i in app.info)
    assert list(app.dataframe[5].value["decision"]) == ["expired"]
    assert "reorder" not in set(app.dataframe[-1].value["Action"])
