"""Cobalt Home dashboard. Reads only from the Ops Day boundary; holds no business logic."""

# Streamlit's chart and table signatures include an untyped optional dataframe library, which
# strict pyright reports as partially unknown on every call.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

from retail_ops_agent.models import models_from_environment
from retail_ops_agent.ops_day import OpsDay
from retail_ops_agent.sandbox import build_sandbox

SEED = 7
FIRST_DAY = date(2026, 11, 1)
DAYS = 14


@st.cache_resource
def _sandbox() -> tuple[OpsDay, str]:
    models, label = models_from_environment(os.environ)
    return build_sandbox(seed=SEED, models=models, first_day=FIRST_DAY, days=DAYS), label


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
