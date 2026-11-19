"""Cobalt Home dashboard. Holds no business logic.

Replay Mode, the default, plays back recorded Ops Day outcomes with no model, key or network call.
Live Mode reads from and calls the Ops Day boundary of a seeded sandbox.
"""

# Streamlit's chart and table signatures include an untyped optional dataframe library, which
# strict pyright reports as partially unknown on every call.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.approval_queue import QueuedReorder
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import AnomalyPlan, DefectPlan, ResubmissionKind, ResubmissionPlan
from retail_ops_agent.models import models_from_environment
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.replay import (
    STAGE_TITLES,
    Recording,
    ReplayStage,
    ReplayStep,
    load_recordings,
    replay_step,
    step_count,
)
from retail_ops_agent.sandbox import build_sandbox
from retail_ops_agent.uploads import UploadKind

SEED = 7
FIRST_DAY = date(2026, 11, 1)
DAYS = 14
RUN_DAYS = 13
# Defects planted in the sandbox's Uploads: some with a Safe Fix, so the Audit Log has Safe Fixes to
# show, and some without, so there are Quarantined Uploads and Uploader messages.
PLANTED_DEFECTS = [
    DefectPlan(sales_channel=channel, day=date(2026, 11, day), upload_kind=kind, defect_kind=defect)
    for channel, day, kind, defect in [
        ("ST02", 3, UploadKind.SALES, DefectKind.RENAMED_COLUMN),
        ("ONLINE", 5, UploadKind.INVENTORY, DefectKind.WRONG_DELIMITER),
        ("ST04", 8, UploadKind.INVENTORY, DefectKind.STRAY_WHITESPACE),
        ("ONLINE", 11, UploadKind.SALES, DefectKind.BYTE_ORDER_MARK),
        ("ST03", 6, UploadKind.SALES, DefectKind.MISSING_COLUMN),
        ("ST05", 9, UploadKind.INVENTORY, DefectKind.UNKNOWN_SKU),
        ("ONLINE", 12, UploadKind.SALES, DefectKind.DUPLICATE_DAY),
    ]
]
# Resubmissions in the sandbox: a corrected one gets a Quarantined Upload accepted, and a changed one
# revises figures, so the Upload status view has Superseded Uploads to show.
RESUBMISSIONS = [
    ResubmissionPlan(
        sales_channel=channel, day=date(2026, 11, day), upload_kind=kind, resubmission_kind=change
    )
    for channel, day, kind, change in [
        ("ST03", 6, UploadKind.SALES, ResubmissionKind.CORRECTED),
        ("ST01", 10, UploadKind.INVENTORY, ResubmissionKind.CHANGED),
    ]
]
# A demand surge planted at one Store, so there is a stockout risk to investigate and alert on. The
# risk is flagged before the planted day (on Nov 13); the sandbox runs only through that day, so its
# Reorder is still in the Approval Queue, not Expired, when the dashboard opens.
PLANTED_ANOMALIES = [
    AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST02", day=date(2026, 11, 14)),
]
UNDO_TAKEN_BY = "BI analyst (dashboard)"
APPROVER = "inventory planner (dashboard)"
TIME_STEP = timedelta(hours=24)


@st.cache_resource
def _sandbox() -> tuple[OpsDay, str]:
    models, label = models_from_environment(os.environ)
    return build_sandbox(
        seed=SEED,
        models=models,
        first_day=FIRST_DAY,
        days=DAYS,
        defects=PLANTED_DEFECTS,
        resubmissions=RESUBMISSIONS,
        anomalies=PLANTED_ANOMALIES,
        run_days=RUN_DAYS,
    ), label


def _live_mode() -> None:
    """A seeded sandbox run through the Ops Day boundary, with approve, reject, advance and undo."""
    ops_day, model_label = _sandbox()
    st.caption(f"Live Mode: a seeded sandbox, seed {SEED}. Agent model: {model_label}.")

    st.header("Sales by Sales Channel")
    sales = pd.DataFrame([row.model_dump() for row in ops_day.sales_by_sales_channel()])
    if sales.empty:
        st.info("No accepted sales yet.")
    else:
        by_channel = sales.pivot_table(
            index="day", columns="sales_channel_name", values="net_sales", aggfunc="sum"
        )
        st.line_chart(by_channel)
        st.dataframe(sales, hide_index=True)

    st.header("Inventory")
    inventory_by_channel = pd.DataFrame([row.model_dump() for row in ops_day.inventory_by_sales_channel()])
    inventory_by_sku = pd.DataFrame([row.model_dump() for row in ops_day.inventory_by_sku()])
    if inventory_by_channel.empty or inventory_by_sku.empty:
        st.info("No accepted inventory yet.")
    else:
        st.subheader("Units on hand by Sales Channel")
        st.line_chart(
            inventory_by_channel.pivot_table(
                index="day", columns="sales_channel_name", values="on_hand", aggfunc="sum"
            )
        )
        latest = inventory_by_sku["day"].max()
        st.subheader(f"Units on hand by SKU and Sales Channel, {latest}")
        st.dataframe(
            inventory_by_sku.pivot_table(
                index=["sku", "sku_name", "category"],
                columns="sales_channel_name",
                values="on_hand",
                aggfunc="sum",
            ).reset_index(),
            hide_index=True,
        )

    st.header("Upload status")
    statuses = pd.DataFrame(
        [
            {
                "day": u.day,
                "Sales Channel": u.sales_channel,
                "kind": u.kind.value,
                "status": u.status.value,
                "Defects": len(u.defects),
                "Upload": u.upload_id,
                "superseded by": u.superseded_by or "",
                "history": " → ".join(c.status.value for c in u.history),
            }
            for u in ops_day.upload_statuses()
        ]
    )
    if statuses.empty:
        st.info("No Uploads processed yet.")
    else:
        quarantined = int((statuses["status"] == "quarantined").sum())
        superseded = int((statuses["status"] == "superseded").sum())
        st.caption(
            f"{quarantined} Upload{'s' if quarantined != 1 else ''} in Quarantine: held out of the BI data "
            "until the Uploader resends a corrected file. "
            f"{superseded} Upload{'s' if superseded != 1 else ''} Superseded: replaced by a later Upload "
            "for the same Sales Channel, day and kind, and kept out of the BI data."
        )
        st.dataframe(statuses, hide_index=True)

    st.header("Uploader messages")
    messages = ops_day.uploader_messages()
    if not messages:
        st.info("No messages sent to Uploaders.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "sent at": m.sent_at,
                        "to": m.recipient,
                        "Upload": m.upload_id,
                        "subject": m.subject,
                    }
                    for m in messages
                ]
            ),
            hide_index=True,
        )
        for m in messages:
            with st.expander(f"{m.sent_at:%Y-%m-%d %H:%M} to {m.recipient}: {m.subject}"):
                st.text(m.body)

    st.header("Investigations")
    investigations = ops_day.investigations()
    if not investigations:
        st.info("No Anomalies investigated yet.")
    else:
        st.caption(
            "Anomalies are flagged by plain statistics; the Analyst agent investigates each with read-only "
            "tools. A stockout risk is flagged when days of cover fall below the SKU's Lead Time; a sales "
            "drop when one Sales Channel sells far below its usual rate while the others do not; a sales "
            "spike when a SKU sells several times its usual rate at one Sales Channel only; a slow mover "
            "when a SKU all but stops selling while plenty of stock sits on hand. A drop or spike the "
            "whole chain shares is not blamed on one Sales Channel. An Investigation that finds the "
            "Anomaly came from Uploads that are wrong concludes Data Problem: no Action is taken, and the "
            "Uploads go back to Intake, which Quarantines them and messages their Uploaders."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "day": i.anomaly.day,
                        "Anomaly": i.anomaly.kind.value,
                        "Sales Channel": i.anomaly.sales_channel,
                        "SKU": i.anomaly.sku or "every SKU",
                        "cause": i.cause,
                        "conclusion": i.conclusion,
                        "Investigation": i.investigation_id,
                    }
                    for i in investigations
                ]
            ),
            hide_index=True,
        )
        for i in investigations:
            with st.expander(f"{i.anomaly.day}: {i.anomaly.summary}"):
                st.markdown(f"**Likely cause:** {i.cause}")
                st.markdown("**Evidence:**\n" + "\n".join(f"- {item}" for item in i.evidence))
                st.markdown(f"**Statistics that flagged it:** {i.anomaly.summary}.")
                if i.data_problem is not None:
                    days = ", ".join(d.isoformat() for d in i.data_problem.days)
                    sent_back = ", ".join(i.data_problem.upload_ids) or "none still loaded"
                    st.markdown(
                        f"**Data Problem** in the {i.data_problem.upload_kind.value} Uploads of {days}: "
                        f"{i.data_problem.what_is_wrong} Sent back to Intake: {sent_back}. No Action taken."
                    )
                elif i.recommended_action is not None:
                    st.markdown(
                        f"**Recommended Action ({i.recommended_action.kind.value}):** "
                        f"{i.recommended_action.description}"
                    )
                st.caption(f"Investigated by the {i.investigated_by} at {i.investigated_at:%Y-%m-%d %H:%M}.")

    st.header("Approval Queue")
    st.caption(
        "Reorders are Tier 2: each waits here for the inventory planner's yes or no and reaches the ERP "
        "only once approved. A Reorder costing under the Auto-approval Limit of "
        f"{ops_day.auto_approval_limit:.2f} is approved by rule and recorded in the Audit Log. There is at "
        "most one pending Reorder per SKU and Sales Channel: a newer Investigation's Reorder replaces it. "
        "A pending Action Expires 48 simulated hours after it was queued."
    )
    time_column, advance_column = st.columns(2)
    time_column.markdown(f"**Simulated time:** {ops_day.now():%Y-%m-%d %H:%M}")
    if advance_column.button("Advance simulated time 24 hours", key="advance-time"):
        expired = ops_day.advance_time(TIME_STEP)
        if expired:
            st.warning("Expired: " + ", ".join(e.action_id for e in expired))
        st.rerun()
    causes = {i.investigation_id: i.cause for i in investigations}
    queue = ops_day.approval_queue()
    if not queue:
        st.info("Nothing waiting for Approval.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Action": q.action_id,
                        "queued at": q.queued_at,
                        "expires at": q.expires_at,
                        "Investigation": q.investigation_id,
                        "cause": causes.get(q.investigation_id, ""),
                        "Sales Channel": q.sales_channel,
                        "SKU": q.sku,
                        "SKU name": q.sku_name,
                        "quantity": q.quantity,
                        "Supplier": q.supplier_name,
                        "unit cost": q.unit_cost,
                        "cost": q.cost,
                    }
                    for q in queue
                ]
            ),
            hide_index=True,
        )
        for q in queue:
            with st.container(border=True):
                st.markdown(
                    f"**{q.action_id}: Reorder {q.quantity} units of {q.sku} ({q.sku_name}) "
                    f"for {q.sales_channel}** "
                    f"from {q.supplier_name}, cost {q.cost:.2f} ({q.quantity} at {q.unit_cost:.2f})"
                )
                st.markdown(f"From Investigation {q.investigation_id}: {causes.get(q.investigation_id, '')}")
                st.caption(q.reason)
                approve_column, reject_column = st.columns(2)
                if approve_column.button("Approve", key=f"approve-{q.action_id}"):
                    approved = ops_day.approve(q.action_id, approved_by=APPROVER)
                    st.success(f"Approved {q.action_id}: placed Reorder {approved.reorder_id} in the ERP")
                    st.rerun()
                if reject_column.button("Reject", key=f"reject-{q.action_id}"):
                    ops_day.reject(q.action_id, rejected_by=APPROVER)
                    st.rerun()
    decided = ops_day.decided_reorders()
    st.subheader("Decided Reorders")
    if not decided:
        st.info("No Reorders decided yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Action": r.action_id,
                        "Investigation": r.investigation_id,
                        "Sales Channel": r.sales_channel,
                        "SKU": r.sku,
                        "quantity": r.quantity,
                        "Supplier": r.supplier_name,
                        "cost": r.cost,
                        "decision": r.status.value,
                        "decided by": r.decided_by,
                        "decided at": r.decided_at,
                        "ERP Reorder": r.reorder_id or "",
                        "replaced by": r.replaced_by or "",
                    }
                    for r in decided
                ]
            ),
            hide_index=True,
        )
    flagged = ops_day.flagged_reorders()
    st.subheader("Flagged after a Supersede")
    st.caption(
        "When a resent Upload replaces one an Anomaly was built on, the Anomaly is checked again. If it no "
        "longer holds, its Tier 1 Actions are undone through the Audit Log and its pending Reorder is "
        "withdrawn from the Approval Queue. A Reorder already placed with the Supplier is never undone "
        "automatically: it is flagged here for the inventory planner, who can cancel it by undoing its "
        "Audit Log entry."
    )
    if not flagged:
        st.info("No placed Reorders flagged.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Action": f.action_id,
                        "ERP Reorder": f.reorder_id,
                        "Audit Log entry": f.audit_entry_id,
                        "Sales Channel": f.sales_channel,
                        "SKU": f.sku,
                        "quantity": f.quantity,
                        "Supplier": f.supplier_name,
                        "cost": f.cost,
                        "flagged at": f.flagged_at,
                        "Superseded Upload": f.superseded_upload_id,
                        "replaced by": f.replaced_by,
                        "why": f.reason,
                    }
                    for f in flagged
                ]
            ),
            hide_index=True,
        )
    for c in ops_day.cleared_anomalies():
        st.markdown(
            f"Cleared {c.cleared_at:%Y-%m-%d %H:%M}: {c.summary} ({c.superseded_upload_id} was replaced by "
            f"{c.replaced_by}, and it no longer holds)."
        )

    st.header("Audit Log")
    entries = ops_day.audit_log()
    if not entries:
        st.info("No Actions recorded yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "entry": e.entry_id,
                        "recorded at": e.recorded_at,
                        "Action": e.action.value,
                        "Tier": int(e.tier),
                        "taken by": e.taken_by,
                        "triggered by": e.triggered_by,
                        "summary": e.summary,
                        "Investigation": e.investigation_id or "",
                        "how to undo": e.undo.description,
                        "undone by entry": e.undone_by,
                    }
                    for e in entries
                ]
            ),
            hide_index=True,
        )
        undoable = {e.entry_id: e for e in entries if e.undone_by is None}
        if undoable:
            chosen = st.selectbox(
                "Entry to undo",
                list(undoable),
                format_func=lambda entry_id: f"{entry_id}: {undoable[entry_id].summary}",
            )
            if st.button("Undo", key="undo"):
                try:
                    undo = ops_day.undo(chosen, taken_by=UNDO_TAKEN_BY)
                except ValueError as refused:
                    st.error(str(refused))
                else:
                    st.success(f"Recorded entry {undo.entry_id}: {undo.summary}")
                    st.rerun()


@st.cache_resource
def _recordings() -> list[Recording]:
    return load_recordings()


def _table(rows: list[dict[str, object]], empty: str) -> None:
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True)
    else:
        st.info(empty)


def _go_to(key: str, position: int) -> None:
    st.session_state[key] = position


def _replay_mode() -> None:
    """Recorded Ops Days, stepped through stage by stage. Reads only recorded JSON: no model, no key."""
    recordings = {r.recording_id: r for r in _recordings()}
    st.caption(
        "Replay Mode plays back recorded Ops Days: no model, no key and no network calls. Step through "
        "each Ops Day stage by stage: Intake, Load, Detection, Investigation and Actions."
    )
    chosen = st.selectbox(
        "Recorded Ops Days",
        list(recordings),
        format_func=lambda recording_id: recordings[recording_id].title,
        key="recording",
    )
    recording = recordings[chosen]
    st.markdown(recording.description)
    st.caption(
        f"Recorded with the agent model {recording.model}; seed {recording.seed}; Auto-approval Limit "
        f"{recording.auto_approval_limit:.2f}."
    )
    key = f"replay-step-{recording.recording_id}"
    total = step_count(recording)
    position = min(int(st.session_state.get(key, 0)), total - 1)
    back, forward, restart = st.columns(3)
    back.button(
        "Previous step",
        key="replay-previous",
        disabled=position == 0,
        on_click=_go_to,
        args=(key, position - 1),
    )
    forward.button(
        "Next step",
        key="replay-next",
        disabled=position == total - 1,
        on_click=_go_to,
        args=(key, position + 1),
    )
    restart.button("Start over", key="replay-restart", on_click=_go_to, args=(key, 0))
    step = replay_step(recording, position)
    st.progress((position + 1) / total, text=f"Step {position + 1} of {total}")
    st.markdown(
        " → ".join(f"**{STAGE_TITLES[s]}**" if s is step.stage else STAGE_TITLES[s] for s in STAGE_TITLES)
    )
    st.header(step.title)
    st.info(step.narration)
    match step.stage:
        case ReplayStage.INTAKE:
            _replay_intake(step)
        case ReplayStage.LOAD:
            _replay_load(step)
        case ReplayStage.DETECTION:
            _replay_detection(step)
        case ReplayStage.INVESTIGATION:
            _replay_investigation(step)
        case ReplayStage.ACTIONS:
            _replay_actions(step)


def _audit_rows(step: ReplayStep) -> list[dict[str, object]]:
    return [
        {
            "entry": e.entry_id,
            "recorded at": e.recorded_at,
            "Action": e.action.value,
            "Tier": int(e.tier),
            "taken by": e.taken_by,
            "triggered by": e.triggered_by,
            "summary": e.summary,
            "how to undo": e.undo.description,
        }
        for e in step.audit_entries
    ]


def _replay_intake(step: ReplayStep) -> None:
    st.subheader("Uploads")
    _table(
        [
            {
                "Sales Channel": u.sales_channel,
                "day": u.day,
                "kind": u.kind.value,
                "status": u.status.value,
                "Defects": ", ".join(d.kind.value for d in u.defects),
                "Upload": u.upload_id,
                "superseded by": u.superseded_by or "",
            }
            for u in step.uploads
        ],
        "No Uploads arrived.",
    )
    st.subheader("Safe Fixes and Quarantines")
    _table(_audit_rows(step), "No Safe Fixes or Quarantines.")
    st.subheader("Uploader messages")
    if not step.uploader_messages:
        st.info("No messages sent to Uploaders.")
    for m in step.uploader_messages:
        with st.expander(f"To {m.recipient}: {m.subject}"):
            st.text(m.body)


def _replay_load(step: ReplayStep) -> None:
    st.subheader("Uploads loaded into the BI data")
    _table(
        [
            {"Sales Channel": u.sales_channel, "day": u.day, "kind": u.kind.value, "Upload": u.upload_id}
            for u in step.uploads
        ],
        "Nothing loaded.",
    )
    st.subheader("Accepted sales by Sales Channel")
    _table([s.model_dump() for s in step.sales], "No accepted sales.")
    st.subheader("Accepted inventory by Sales Channel")
    _table([i.model_dump() for i in step.inventory], "No accepted inventory.")


def _replay_detection(step: ReplayStep) -> None:
    st.subheader("Anomalies flagged")
    _table(
        [
            {
                "Anomaly": a.kind.value,
                "Sales Channel": a.sales_channel,
                "SKU": getattr(a, "sku", None) or "every SKU",
                "statistics": a.summary,
            }
            for a in step.anomalies
        ],
        "No Anomalies flagged.",
    )
    for c in step.cleared_anomalies:
        st.markdown(f"Cleared: {c.summary} ({c.superseded_upload_id} was replaced by {c.replaced_by}).")


def _replay_investigation(step: ReplayStep) -> None:
    if not step.investigations:
        st.info("No Investigations.")
    for i in step.investigations:
        with st.container(border=True):
            st.markdown(f"**{i.anomaly.summary}**")
            st.markdown(f"**Likely cause:** {i.cause}")
            st.markdown("**Evidence:**\n" + "\n".join(f"- {item}" for item in i.evidence))
            if i.data_problem is not None:
                st.markdown(
                    f"**Data Problem:** {i.data_problem.what_is_wrong} Sent back to Intake: "
                    f"{', '.join(i.data_problem.upload_ids) or 'none still loaded'}."
                )
            elif i.recommended_action is not None:
                st.markdown(
                    f"**Recommended Action ({i.recommended_action.kind.value}):** "
                    f"{i.recommended_action.description}"
                )
            st.caption(f"Investigated by the {i.investigated_by} at {i.investigated_at:%Y-%m-%d %H:%M}.")


def _reorder_rows(reorders: list[QueuedReorder]) -> list[dict[str, object]]:
    return [
        {
            "Action": r.action_id,
            "Sales Channel": r.sales_channel,
            "SKU": r.sku,
            "SKU name": r.sku_name,
            "quantity": r.quantity,
            "Supplier": r.supplier_name,
            "cost": r.cost,
            "status": r.status.value,
            "decided by": r.decided_by or "",
            "ERP Reorder": r.reorder_id or "",
        }
        for r in reorders
    ]


def _replay_actions(step: ReplayStep) -> None:
    st.subheader("Reorders proposed")
    _table(_reorder_rows(step.reorders), "No Reorders proposed.")
    st.subheader("Approval Queue")
    _table(_reorder_rows(step.approval_queue), "Nothing waiting for Approval.")
    st.subheader("Approval decisions")
    _table(_reorder_rows([d.reorder for d in step.decisions]), "No Approval decisions taken.")
    if step.flagged_reorders:
        st.subheader("Flagged after a Supersede")
        _table([f.model_dump() for f in step.flagged_reorders], "")
    st.subheader("Audit Log entries")
    _table(_audit_rows(step), "No Actions recorded.")


REPLAY_MODE = "Replay Mode"
LIVE_MODE = "Live Mode"

st.set_page_config(page_title="Cobalt Home: retail ops", layout="wide")
st.title("Cobalt Home")
st.caption("Fictional Client. Simulated data.")
mode = st.sidebar.radio("Mode", [REPLAY_MODE, LIVE_MODE], key="mode")
if mode == LIVE_MODE:
    _live_mode()
else:
    _replay_mode()
