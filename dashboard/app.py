"""Cobalt Home dashboard. Holds no business logic.

Replay Mode, the default, plays back recorded Ops Day outcomes with no model, key or network call.
Live Mode gives each Visitor their own in-memory sandbox and reads from and calls only its Ops Day
boundary.
"""

# Streamlit's chart and table signatures include an untyped optional dataframe library, which
# strict pyright reports as partially unknown on every call.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import os
from datetime import timedelta

import pandas as pd
import streamlit as st
from pydantic_ai.exceptions import AgentRunError

from retail_ops_agent.approval_queue import QueuedReorder
from retail_ops_agent.hours_saved import HoursSaved
from retail_ops_agent.live import (
    DEFAULT_VISITOR_MODELS,
    SEED,
    KeyProvider,
    OwnKeyNeeded,
    SharedKeyLimit,
    SharedKeyLimiter,
    VisitorKey,
    new_live_sandbox,
    run_live_day,
)
from retail_ops_agent.replay import (
    STAGE_TITLES,
    Recording,
    ReplayStage,
    ReplayStep,
    load_recordings,
    replay_step,
    step_count,
)
from retail_ops_agent.sandbox import Sandbox
from retail_ops_agent.uploads import UploadKind

UNDO_TAKEN_BY = "BI analyst (dashboard)"
APPROVER = "inventory planner (dashboard)"
TIME_STEP = timedelta(hours=24)
SANDBOX_KEY = "live-sandbox"
OWN_KEY_NEEDED = "live-own-key-needed"
LAST_RUN = "live-last-run"
# The Actions that Expired when simulated time last advanced, shown once after the rerun.
EXPIRED_NOTICE = "live-expired-notice"


@st.cache_resource
def _shared_key_limiter(limit: SharedKeyLimit) -> SharedKeyLimiter:
    """One limiter for the whole server, so the shared key's limit holds across every Visitor."""
    return SharedKeyLimiter(limit)


def _sandbox() -> Sandbox:
    """This Visitor's own sandbox, kept in their session's memory only."""
    if SANDBOX_KEY not in st.session_state:
        with st.spinner("Seeding your sandbox of Cobalt Home…"):
            st.session_state[SANDBOX_KEY] = new_live_sandbox()
    sandbox: Sandbox = st.session_state[SANDBOX_KEY]
    return sandbox


def _reset() -> None:
    for key in (SANDBOX_KEY, OWN_KEY_NEEDED, LAST_RUN, EXPIRED_NOTICE):
        st.session_state.pop(key, None)


def _visitor_key(reason: str) -> VisitorKey | None:
    """Ask for the Visitor's own key. It stays in this browser session's widgets only: it is never
    written to disk, logged, cached or recorded in the Audit Log."""
    st.warning(
        f"{reason} Your key is used only for the Ops Days you run in this session and is never stored."
    )
    provider_column, model_column = st.columns(2)
    provider = provider_column.selectbox("Provider", list(KeyProvider), key="visitor-provider")
    model_name = model_column.text_input(
        "Model", value=DEFAULT_VISITOR_MODELS[provider], key=f"visitor-model-{provider.name}"
    )
    api_key = st.text_input("Your API key", type="password", key="visitor-key")
    if not api_key.strip():
        return None
    return VisitorKey(provider=provider, api_key=api_key.strip(), model_name=model_name.strip() or None)


def _sandbox_controls(sandbox: Sandbox) -> None:
    """Run day, uploading one's own CSV and reset, all through the sandbox's Ops Day boundary."""
    limiter = _shared_key_limiter(SharedKeyLimit.from_environment(os.environ))
    st.header("Your sandbox")
    st.caption(
        f"Your own copy of Cobalt Home (seed {SEED}), held only in this session's memory: nothing you do "
        f"is stored on the server or seen by anyone else. Its first {len(sandbox.days_run)} Ops Days were "
        "run with the offline scripted model; each Ops Day you run uses a real model, first the shared "
        f"free-tier key (limited to {limiter.limit.describe()} across every Visitor; "
        f"{limiter.remaining()} left now), then your own key."
    )
    last_run = st.session_state.get(LAST_RUN)
    if last_run:
        st.success(last_run)
    reason: str | None = st.session_state.get(OWN_KEY_NEEDED)
    if reason is None and limiter.remaining() == 0:
        reason = limiter.limit_reached()
    needs_own_key = reason is not None
    visitor_key = _visitor_key(reason) if reason is not None else None
    next_day = sandbox.next_day
    run_column, reset_column = st.columns(2)
    run_label = f"Run day ({next_day})" if next_day else "Every day has run"
    run = run_column.button(
        run_label, key="run-day", disabled=next_day is None or (needs_own_key and visitor_key is None)
    )
    if reset_column.button("Reset sandbox", key="reset"):
        _reset()
        st.rerun()
    if run:
        try:
            with st.spinner(f"Running the Ops Day for {next_day}…"):
                result = run_live_day(sandbox, env=os.environ, limiter=limiter, visitor_key=visitor_key)
        except OwnKeyNeeded as needed:
            st.session_state[OWN_KEY_NEEDED] = str(needed)
            st.session_state[LAST_RUN] = None
            st.rerun()
        except AgentRunError as failed:
            st.error(
                f"The model could not run the Ops Day ({type(failed).__name__}). Check the key and model, "
                "then run the day again; its Uploads are kept."
            )
        else:
            outcome = result.outcome
            st.session_state[LAST_RUN] = (
                f"Ran the Ops Day for {outcome.day} with {result.model_label}: "
                f"{len(outcome.uploads)} Uploads, {len(outcome.anomalies)} Anomalies, "
                f"{len(outcome.reorders)} Reorders proposed, {len(outcome.audit_entries)} Audit Log entries."
            )
            st.rerun()

    st.subheader("Upload a CSV of your own")
    st.caption(
        "Edit the generated Upload or paste your own, broken or malicious ones included. For the next day "
        "it takes the place of the generated Upload; for a day already run it is a resubmission that "
        "Supersedes the earlier Upload when the next Ops Day runs."
    )
    days = [*sandbox.days_run, *([next_day] if next_day else [])]
    channel_column, day_column, kind_column = st.columns(3)
    channel = channel_column.selectbox("Sales Channel", sandbox.sales_channels, key="own-channel")
    day = day_column.selectbox("Day", days, index=len(days) - 1, key="own-day")
    kind = kind_column.selectbox("Kind", list(UploadKind), format_func=lambda k: k.value, key="own-kind")
    chosen_file = st.file_uploader("CSV file", type=["csv", "txt"], key="own-file")
    starting = (
        chosen_file.getvalue().decode("utf-8", errors="replace")
        if chosen_file is not None
        else sandbox.generated_upload(channel, day, kind)
    )
    file_tag = chosen_file.file_id if chosen_file is not None else "generated"
    content = st.text_area(
        "Upload contents", value=starting, height=200, key=f"own-csv-{channel}-{day}-{kind.value}-{file_tag}"
    )
    if st.button("Submit Upload", key="submit-own-upload"):
        try:
            upload_id = sandbox.submit_own_upload(sales_channel=channel, day=day, kind=kind, content=content)
        except ValueError as refused:
            st.error(str(refused))
        else:
            st.session_state[LAST_RUN] = f"Submitted {upload_id}; the next Ops Day you run processes it."
            st.rerun()


def _live_mode() -> None:
    """The Visitor's own seeded sandbox run through the Ops Day boundary: Run day, approve, reject,
    advance, undo, their own CSV and reset."""
    sandbox = _sandbox()
    ops_day = sandbox.ops_day
    _sandbox_controls(sandbox)

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
            # A warning shown now would be wiped by the rerun, so the next render shows it.
            st.session_state[EXPIRED_NOTICE] = "Expired: " + ", ".join(e.action_id for e in expired)
        st.rerun()
    notice: str | None = st.session_state.pop(EXPIRED_NOTICE, None)
    if notice:
        st.warning(notice)
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
                        "cancelled by": r.cancelled_by or "",
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

    st.header("Hours Saved")
    _hours_saved(ops_day.hours_saved())

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


def _hours_saved(saved: HoursSaved) -> None:
    """Hours Saved, with every assumption behind it next to the figure."""
    st.metric("Hours Saved", f"{saved.hours:.2f} h")
    st.caption(
        "Hours Saved = Audit Log entries of each task's Action that still stand (not undone) times the "
        f"baseline's minutes for that task. {saved.label}"
    )
    if saved.undone_entries:
        st.caption(f"{saved.undone_entries} undone entries are left out.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "task done by hand": line.task.task,
                    "persona": line.task.persona,
                    "Action": line.task.audit_action.value,
                    "entries": line.matching_entries,
                    "minutes each": line.task.minutes_each,
                    "minutes saved": line.minutes_saved,
                    "how often": line.task.how_often,
                    "basis": line.task.basis.value,
                    "source or assumption": line.task.source or line.task.reasoning,
                }
                for line in saved.lines
            ]
        ),
        hide_index=True,
    )


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
    if step.hours_saved is not None:
        st.header("Hours Saved so far")
        _hours_saved(step.hours_saved)


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
    _table(
        [
            {
                "day": s.day,
                "Sales Channel": s.sales_channel,
                "name": s.sales_channel_name,
                "units sold": s.quantity_sold,
                "net sales": s.net_sales,
            }
            for s in step.sales
        ],
        "No accepted sales.",
    )
    st.subheader("Accepted inventory by Sales Channel")
    _table(
        [
            {
                "day": i.day,
                "Sales Channel": i.sales_channel,
                "name": i.sales_channel_name,
                "SKUs in stock": i.skus_in_stock,
                "units on hand": i.on_hand,
            }
            for i in step.inventory
        ],
        "No accepted inventory.",
    )


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
