# Project Coding Standards

<!--
Rules specific to this codebase. The Review Session checks every change against them, on top of
the Preset layer (shipped with sandcastle-pro) and your Personal layer
(~/.config/sandcastle-pro/CODING_STANDARDS.md). When rules conflict, this file wins.

Write one rule per list item. Delete the headings you don't need, or add your own.
Text inside HTML comments, like this one, is ignored.

Breaking a rule in this file is a Non-critical Finding: it is logged on the Issue for you to decide.
Only rules under the "## Must" heading at the bottom are fixed automatically.

Sources: GLOSSARY.md, docs/adr/0001-0006, .scratch/retail-ops-agent/spec.md.
-->

## Language and tooling

- Python only, packaged with uv; dependencies are added with `uv add`, never by hand-editing a lock file.
- Code passes ruff and the static typechecker with no new ignores; a `# type: ignore` or `# noqa` names the specific code and says why.
- Public functions and every agent's output are fully typed; agent outputs are Pydantic models, never free-form dicts or strings.
- No paid service or paid model is required to build, test, run or demo anything; free-tier models are the default and frontier models are only reached with a user-supplied key (ADR 0001).

## Naming

- Code, comments, docs and UI text use the terms in `GLOSSARY.md` and never their listed _Avoid_ words (e.g. `Upload` not `file`, `Defect` not `error`, `Reorder` not `purchase_order`, `Sales Channel` not `location`, `Ops Day` not `run` or `batch`).
- A new domain concept is added to `GLOSSARY.md` in the same change that introduces it.
- Upload statuses are exactly `accepted`, `safe_fixed`, `quarantined` and `superseded`; Action Tiers are `0`, `1` and `2`.

## Structure

- The Ops Day module is the one public boundary: the dashboard, the n8n trigger, Replay Mode, Live Mode and the evals call only its operations and views.
- The Ops Day boundary receives its dependencies (models, ERP client, Notifier, Data Source, clock) as arguments; nothing behind it constructs them itself or reads global state.
- Handoff between Intake, Load, Detect, Analyst and Ops is a plain deterministic pipeline; no LLM chooses which agent runs next (ADR 0003).
- A Data Problem is a structured outcome returned to Intake, not a free-form message between agents.
- Anomaly detection is deterministic statistics with no model call; the same data always gives the same Anomalies.
- Which Defect kinds have a Safe Fix is decided by a fixed table in code, not by the model.
- Agents and the Action policy reach the ERP only through the ERP client interface; nothing imports the mock ERP's internals (ADR 0006).
- Notifications go only through the Notifier interface and Uploads arrive only through the Data Source interface.
- Agents are built with Pydantic AI; no LangGraph or hand-written provider tool loop (ADR 0004).
- The Analyst agent's tools are read-only.
- The Streamlit dashboard holds no business logic: it reads views and calls operations of the Ops Day boundary only.
- n8n workflows only trigger Ops Days and forward notifications; any rule lives in tested Python.
- Times come from the injected clock, never from `datetime.now()` or `time.time()` behind the boundary.
- Generated data comes from the seeded generator (ADR 0005); any randomness takes an explicit seed.

## Testing

- Tests check behaviour visible at a seam (Ops Day outcome, Audit Log, Approval Queue, ERP state), never which internal function ran or what a prompt says; they keep passing when prompts, agent internals or SQL are rewritten.
- Ops Day tests use Pydantic AI's scripted test models, the in-memory fake ERP, the log Notifier and a controllable clock; unit tests never call a real model or the network.
- A change to ERP behaviour runs the shared ERP contract suite against both the in-memory fake and the MCP server.
- Every new Defect, Anomaly or injection kind in the generator is recorded in the ground-truth record and has an Ops Day test for its expected outcome.
- Every bug fix comes with a test that fails without the fix.
- Evals are not part of the unit test run; they live in the eval harness and are paced for free-tier rate limits.

## Docs

- A decision that is hard to reverse, surprising, or the result of a real trade-off gets an ADR in `docs/adr/`.
- Simulated discovery documents are labelled as simulated, and every timing is cited or marked as an assumption.

## Must

<!--
Must Rules. Breaking one is a Critical Finding, which the Review Session fixes in the same pass,
so it costs tokens on every Issue that breaks it. Keep this list short: only rules worth that cost.
-->

- An Action's Tier is assigned only by the deterministic Action policy; model output can never set a Tier, approve an Action or bypass the Approval Queue (ADR 0002).
- No tool an agent can call places a Tier 2 Action (Reorder, Supplier message) directly; Tier 2 Actions run only after Approval or under the Auto-approval Limit.
- Upload contents are passed to models only as clearly separated data, never as instructions or inside the system prompt.
- The Audit Log is append-only: entries are never edited or deleted, and an undo is a new entry.
- Every Tier 1 Action is written to the Audit Log with what triggered it, who took it, its Tier and an undo recipe.
- A Tier 2 Action that already went out is never undone automatically; it is flagged for a human.
- Never commit or log secrets, API keys or tokens.
