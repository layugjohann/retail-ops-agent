from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from streamlit.testing.v1 import AppTest

from retail_ops_agent import live
from retail_ops_agent.evals.throttle import Throttle, ThrottledModel
from retail_ops_agent.ops_day import Models
from retail_ops_agent.sandbox import Sandbox

APP = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"


def _live_app() -> AppTest:
    """The dashboard switched from its default, Replay Mode, to Live Mode."""
    app = AppTest.from_file(str(APP), default_timeout=120).run()
    return app.radio(key="mode").set_value("Live Mode").run()


@pytest.fixture(autouse=True)
def _seeded_copies(  # pyright: ignore[reportUnusedFunction]
    seeded_live_sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each Visitor's sandbox, and each one built again on reset, is a copy of the session's seeded
    sandbox rather than seeded again, which takes seconds."""

    def seeded_copy() -> Sandbox:
        return deepcopy(seeded_live_sandbox)

    monkeypatch.setattr(live, "new_live_sandbox", seeded_copy)


@pytest.fixture
def fresh_sandbox() -> None:
    """Each Visitor's sandbox lives in their own session, but the shared key's limiter is cached for
    the whole process; start every test that runs a day with it unused."""
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

    assert not app.exception
    assert _expired_warnings(app) == [f"Expired: {action_id}"]
    assert any("Nothing waiting for Approval" in i.value for i in app.info)
    assert list(app.dataframe[5].value["decision"]) == ["expired"]
    assert "reorder" not in set(app.dataframe[-1].value["Action"])
    # The warning is shown once, not again on the next advance.
    app.button(key="advance-time").click().run()
    assert _expired_warnings(app) == []


def _expired_warnings(app: AppTest) -> list[str]:
    return [w.value for w in app.warning if w.value.startswith("Expired")]


NEXT_DAY = "2026-11-14"


def _statuses(app: AppTest) -> pd.DataFrame:
    [statuses] = [d.value for d in app.dataframe if "history" in d.value.columns]
    return statuses


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_run_day_processes_the_next_days_uploads() -> None:
    app = _live_app()
    assert app.button(key="run-day").label == f"Run day ({NEXT_DAY})"
    assert NEXT_DAY not in {str(d) for d in _statuses(app)["day"]}

    app.button(key="run-day").click().run()

    assert not app.exception
    assert any(f"Ran the Ops Day for {NEXT_DAY}" in s.value for s in app.success)
    assert NEXT_DAY in {str(d) for d in _statuses(app)["day"]}
    assert app.button(key="run-day").label == "Run day (2026-11-15)"


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_an_uploaded_csv_of_ones_own_goes_through_intake() -> None:
    app = _live_app()
    app.selectbox(key="own-channel").set_value("ST01").run()
    [editor] = [t for t in app.text_area if t.key and t.key.startswith("own-csv-ST01-2026-11-14-sales")]
    broken = "\n".join(",".join(line.split(",")[:-1]) for line in (editor.value or "").splitlines())
    editor.input(broken).run()

    app.button(key="submit-own-upload").click().run()
    assert any("Submitted ST01-2026-11-14-sales-001" in s.value for s in app.success)
    app.button(key="run-day").click().run()

    assert not app.exception
    statuses = _statuses(app)
    [mine] = statuses[statuses["Upload"] == "ST01-2026-11-14-sales-001"].to_dict("records")
    assert mine["status"] == "quarantined"
    ours = statuses[(statuses["Sales Channel"] == "ST01") & (statuses["kind"] == "sales")]
    assert len(ours[ours["day"].astype(str) == NEXT_DAY]) == 1


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_reset_starts_the_sandbox_again() -> None:
    app = _live_app()
    [action_id] = list(app.dataframe[5].value["Action"])
    app.button(key=f"approve-{action_id}").click().run()
    app.button(key="run-day").click().run()
    assert app.button(key="run-day").label == "Run day (2026-11-15)"

    app.button(key="reset").click().run()

    assert not app.exception
    assert app.button(key="run-day").label == f"Run day ({NEXT_DAY})"
    assert list(app.dataframe[5].value["Action"]) == [action_id]


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_each_visitor_has_their_own_sandbox() -> None:
    mine, theirs = _live_app(), _live_app()
    [action_id] = list(mine.dataframe[5].value["Action"])

    mine.button(key=f"approve-{action_id}").click().run()
    mine.button(key="run-day").click().run()
    theirs.run()

    assert list(mine.dataframe[5].value["decision"]) == ["approved"]
    assert list(theirs.dataframe[5].value["Action"]) == [action_id]
    assert theirs.button(key="run-day").label == f"Run day ({NEXT_DAY})"


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_asks_for_the_visitors_own_key_once_the_shared_limit_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_SHARED_RUNS", "1")
    app = _live_app()
    assert not [t for t in app.text_input if t.key == "visitor-key"]

    app.button(key="run-day").click().run()

    assert not app.exception
    assert any("limit of 1 Ops Day every 24 hours is reached" in w.value for w in app.warning)
    assert app.text_input(key="visitor-key").value == ""
    assert app.button(key="run-day").disabled

    app.text_input(key="visitor-key").input("gsk-visitor-secret").run()

    assert not app.button(key="run-day").disabled
    shown = " ".join(str(e.value) for e in [*app.markdown, *app.caption, *app.success, *app.warning])
    assert "gsk-visitor-secret" not in shown


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_a_model_that_misbehaves_shows_a_message_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def misbehaving(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise UnexpectedModelBehavior("Tool 'json' exceeded max retries count of 1")

    model = FunctionModel(misbehaving)

    def shared_models(_env: Mapping[str, str]) -> tuple[Models, str]:
        return Models(intake=model, analyst=model, ops=model), "shared"

    monkeypatch.setattr(live, "models_from_environment", shared_models)
    app = _live_app()

    app.button(key="run-day").click().run()

    assert not app.exception
    assert any("UnexpectedModelBehavior" in e.value and "run the day again" in e.value for e in app.error)


@pytest.mark.usefixtures("fresh_sandbox")
def test_live_mode_a_provider_wait_over_the_cap_shows_a_message_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def quota_spent(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(
            429, "llama-free", {"error": {"message": "try again in 2h24m"}}, retry_after=8640.0
        )

    model = ThrottledModel(FunctionModel(quota_spent), Throttle(0))

    def shared_models(_env: Mapping[str, str]) -> tuple[Models, str]:
        return Models(intake=model, analyst=model, ops=model), "shared"

    monkeypatch.setattr(live, "models_from_environment", shared_models)
    app = _live_app()

    app.button(key="run-day").click().run()

    assert not app.exception
    assert any("ProviderWaitTooLong" in e.value and "run the day again" in e.value for e in app.error)
