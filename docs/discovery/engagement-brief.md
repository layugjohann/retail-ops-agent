# Engagement brief

> **SIMULATED.** Written as if by an engineer embedded at Cobalt Home, a fictional Client. The responsibilities come from a public job posting for a "Forward Deployed Engineer (AI Enhanced)" at a retail and e-commerce company, which is not named here.

## The Client

Cobalt Home sells home and lifestyle goods through 6 Stores and an Online Shop: about 300 SKUs,
bought from a handful of Suppliers. Each Sales Channel uploads a sales CSV and an inventory CSV
every day. A BI analyst cleans them and loads them into the dashboards that store managers, the
inventory planner and leadership read. Reorders are placed by hand in the ERP.

## Why we are here

Leadership's question: *"Where are our people losing hours to manual work, and what is it worth to
fix?"* Nobody measures that time today, so nobody can answer it.

## What the engagement covers

Mapped to the responsibilities in the posting:

| Responsibility in the posting | What it means at Cobalt Home |
| --- | --- |
| Embed with the teams and discover manual bottlenecks | Shadow the four people in [Personas](personas.md), write down each manual process step by step ([Current manual processes](manual-processes.md)), and time it ([Baseline](baseline.md)). |
| Build multi-agent, tool-calling workflows that save measurable hours | An Intake agent for Uploads, an Analyst agent for Anomalies and an Ops agent for Actions, run every Ops Day by a deterministic pipeline. Hours Saved is computed from what they actually did (the Audit Log) and the baseline. |
| Maintain the BI system: CSV uploads, ETL, validation, dashboards | Validate each Upload, apply Safe Fixes, Quarantine what cannot be fixed without asking, load accepted data, and keep the dashboard trustworthy. |
| Act as the go-between with ERP and API vendors | Reach the ERP only through an MCP server and keep the Data Source and Notifier behind seams, so the prototype can be pointed at the Client's real systems in week one. |

## Constraints

- Nothing external or costly happens without a person: Reorders and Supplier messages wait for
  Approval unless a Reorder is under the Auto-approval Limit.
- Every Action is recorded in the Audit Log and can be undone or accounted for.
- Text inside an Upload is data, never an instruction.
- The prototype costs nothing to run: free-tier models by default.

## What success looks like

- Uploads with small Defects no longer reach a person; Uploads with real Defects reach the Uploader
  with a message that says what to fix.
- A stockout risk or a Sales Drop is investigated the same evening, not days later.
- Hours Saved on the dashboard, with every assumption behind it shown next to the number, that
  leadership can question and the team can correct.

## Open questions for the Client

- How long do the tasks in the baseline really take? (Every timing is an assumption until timed
  with the people who do them.)
- What Auto-approval Limit is the inventory planner comfortable with?
- Which chat tool do Uploaders read, so the Notifier can post there?
