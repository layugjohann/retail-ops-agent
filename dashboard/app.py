"""Cobalt Home dashboard. Reads only from the Ops Day boundary; holds no business logic."""

# Streamlit's chart and table signatures include an untyped optional dataframe library, which
# strict pyright reports as partially unknown on every call.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

from retail_ops_agent.defects import DefectKind
from retail_ops_agent.generator import DefectPlan
from retail_ops_agent.models import models_from_environment
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.sandbox import build_sandbox
from retail_ops_agent.uploads import UploadKind

SEED = 7
FIRST_DAY = date(2026, 11, 1)
DAYS = 14
# Safe-fixable Defects planted in the sandbox's Uploads, so the Audit Log has Safe Fixes to show.
PLANTED_DEFECTS = [
    DefectPlan(sales_channel=channel, day=date(2026, 11, day), upload_kind=kind, defect_kind=defect)
    for channel, day, kind, defect in [
        ("ST02", 3, UploadKind.SALES, DefectKind.RENAMED_COLUMN),
        ("ONLINE", 5, UploadKind.INVENTORY, DefectKind.WRONG_DELIMITER),
        ("ST04", 8, UploadKind.INVENTORY, DefectKind.STRAY_WHITESPACE),
        ("ONLINE", 11, UploadKind.SALES, DefectKind.BYTE_ORDER_MARK),
    ]
]
UNDO_TAKEN_BY = "BI analyst (dashboard)"


@st.cache_resource
def _sandbox() -> tuple[OpsDay, str]:
    models, label = models_from_environment(os.environ)
    return build_sandbox(
        seed=SEED, models=models, first_day=FIRST_DAY, days=DAYS, defects=PLANTED_DEFECTS
    ), label


ops_day, model_label = _sandbox()

st.set_page_config(page_title="Cobalt Home: retail ops", layout="wide")
st.title("Cobalt Home")
st.caption(f"Fictional Client. Simulated data, seed {SEED}. Intake model: {model_label}.")

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
        }
        for u in ops_day.upload_statuses()
    ]
)
if statuses.empty:
    st.info("No Uploads processed yet.")
else:
    st.dataframe(statuses, hide_index=True)

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
        if st.button("Undo"):
            undo = ops_day.undo(chosen, taken_by=UNDO_TAKEN_BY)
            st.success(f"Recorded entry {undo.entry_id}: {undo.summary}")
            st.rerun()
