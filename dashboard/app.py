"""Cobalt Home dashboard. Reads only from the Ops Day boundary; holds no business logic."""

# Streamlit's chart and table signatures include an untyped optional dataframe library, which
# strict pyright reports as partially unknown on every call.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

from retail_ops_agent.anomalies import AnomalyKind
from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import AnomalyPlan, DefectPlan, ResubmissionKind, ResubmissionPlan
from retail_ops_agent.models import models_from_environment
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.sandbox import build_sandbox
from retail_ops_agent.uploads import UploadKind

SEED = 7
FIRST_DAY = date(2026, 11, 1)
DAYS = 14
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
# A demand surge planted at one Store, so there is a stockout risk to investigate and alert on.
PLANTED_ANOMALIES = [
    AnomalyPlan(kind=AnomalyKind.STOCKOUT_RISK, sales_channel="ST02", day=date(2026, 11, 12)),
]
UNDO_TAKEN_BY = "BI analyst (dashboard)"
APPROVER = "inventory planner (dashboard)"


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
    ), label


ops_day, model_label = _sandbox()

st.set_page_config(page_title="Cobalt Home: retail ops", layout="wide")
st.title("Cobalt Home")
st.caption(f"Fictional Client. Simulated data, seed {SEED}. Agent model: {model_label}.")

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
        "tools. A stockout risk is flagged when days of cover fall below the SKU's Lead Time."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "day": i.anomaly.day,
                    "Anomaly": i.anomaly.kind.value,
                    "Sales Channel": i.anomaly.sales_channel,
                    "SKU": i.anomaly.sku,
                    "days of cover": i.anomaly.days_of_cover,
                    "Lead Time (days)": i.anomaly.lead_time_days,
                    "cause": i.cause,
                    "recommended Action": i.recommended_action.kind.value,
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
            st.markdown(
                f"**Statistics that flagged it:** {i.anomaly.on_hand} units on hand; "
                f"{i.anomaly.average_daily_units:.2f} units a day over {i.anomaly.sales_days} days of sales; "
                f"{i.anomaly.days_of_cover:.1f} days of cover against a {i.anomaly.lead_time_days}-day "
                "Lead Time."
            )
            st.markdown(
                f"**Recommended Action ({i.recommended_action.kind.value}):** "
                f"{i.recommended_action.description}"
            )
            st.caption(f"Investigated by the {i.investigated_by} at {i.investigated_at:%Y-%m-%d %H:%M}.")

st.header("Approval Queue")
st.caption(
    "Reorders are Tier 2: each waits here for the inventory planner's yes or no and reaches the ERP "
    "only once approved. A Reorder costing under the Auto-approval Limit of "
    f"{ops_day.auto_approval_limit:.2f} is approved by rule and recorded in the Audit Log."
)
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
decided = [r for r in ops_day.reorders() if r.status.value != "pending"]
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
                }
                for r in decided
            ]
        ),
        hide_index=True,
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
