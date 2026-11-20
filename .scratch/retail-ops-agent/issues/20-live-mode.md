# 20: Live Mode

**What to build:** Each Visitor gets their own in-memory sandbox of Cobalt Home (BI store, fake ERP, clock) where they can run Ops Days with real models, approve or reject, undo, upload their own CSV, and reset. A shared free-tier key with a rate limit is used first, then the Visitor is asked for their own key.

**Blocked by:** 18

**Status:** awaiting-merge
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/18

- [x] Each Visitor's sandbox is isolated and seeded from the generator; nothing is stored on the server
- [x] "Run day", approve/reject, undo, uploading their own CSV and reset all work through the Ops Day boundary
- [x] The shared key is rate-limited; once the limit is reached the Visitor is asked for their own key, which is never stored
- [x] A dashboard smoke test passes in Live Mode against a seeded sandbox (scripted model)

## Comments

### Implementer (2026-11-20)

- `retail_ops_agent.live` builds each Visitor's sandbox: `new_live_sandbox()` seeds Cobalt Home from the generator into an in-memory Data Source (new `InMemoryDataSource`), in-memory DuckDB, fake ERP and simulated clock, running the first 13 of 21 generated days with the offline scripted model so seeding costs no model calls. The dashboard keeps it in `st.session_state`, so each Visitor's sandbox is their own and nothing is written to disk (a test refuses every disk write while building and running one).
- `sandbox.Sandbox` is the steppable sandbox `build_sandbox` now runs on: `run_day()` submits the next day's generated Uploads and runs its Ops Day; `submit_own_upload()` takes a Visitor's CSV, replacing the generated Upload for the next day, or acting as a resubmission (Supersede) for a day already run. A failed run (model outage) keeps the day next without resubmitting its Uploads.
- `OpsDay.run_ops_day(day, models=...)` lets one Ops Day run with other models, so Live Mode can switch from the shared key to the Visitor's key without rebuilding the sandbox.
- Shared key: `SharedKeyLimiter`, one per server via `st.cache_resource`, a sliding window over every Visitor's Run days (`LIVE_SHARED_RUNS`, default 40, per `LIVE_SHARED_WINDOW_HOURS`, default 24). When it is used up, or the provider returns a rate-limit/quota error, the dashboard asks for the Visitor's own Groq or Gemini key (password field). The key is only used to build that Ops Day's models; it is not cached, logged or recorded, and `VisitorKey`'s repr hides it. The limiter counts shared Ops Days even when no key is set and the offline model stands in, which keeps the path testable offline.
- Dashboard Live Mode gains a "Your sandbox" section: Run day, Reset sandbox, and "Upload a CSV of your own" (file uploader or an editable text area prefilled with the generated Upload). Approve/reject, advance time and undo are unchanged.
- `BiStore` now loads rows with multi-row INSERTs instead of DuckDB's slow `executemany`, which cut seeding a sandbox from ~11s to ~3s.
- `make` could not run in the build sandbox (Xcode shim), so the gate commands were run directly: `uv sync`, ruff check, ruff format --check, pyright, pytest (380 passed).
- **For ticket 21:** with the shared key set as a Streamlit secret (top-level `GROQ_API_KEY`), consider setting `LIVE_SHARED_RUNS` to suit the free tier's daily limit; each Run day makes about 14 Intake calls plus two per Anomaly.

Usage: Implementer 76 input, 40,855 output, 116,920 cache creation, 3,540,763 cache read; Review Session 12 input, 4,667 output, 54,441 cache creation, 316,124 cache read.

**Review Session: Non-critical Findings**

- dashboard/app.py `_sandbox_controls` only catches `ModelAPIError` around `run_live_day`. Any other `AgentRunError` crashes the page with a traceback instead of the 'run the day again' message. One example is `UnexpectedModelBehavior` from a weak Visitor-chosen model exceeding output retries. The day itself is kept, so no data is lost.
- `run_live_day` takes a slot from the shared-key limiter before the Ops Day runs and keeps it if the day fails for a reason other than a rate limit (server error, network). Shared-key outages therefore use up the limit for every Visitor.
- Naming uses some GLOSSARY Avoid words. For Ops Day: `LiveRun`, `LAST_RUN`, `SharedKeyLimit.runs`, `DEFAULT_SHARED_RUNS` and the `LIVE_SHARED_RUNS` variable. For Upload: the UI label 'CSV file'. The text 'broken or malicious ones' fits better as 'with Defects or Prompt injections'.
- A Visitor's own CSV is decoded with `errors='replace'` before submission. Invalid bytes become U+FFFD instead of reaching Intake raw, so an encoding Defect the Visitor plants this way is silently changed rather than flagged.
- `Sandbox` and `build_sandbox` together mix two jobs: one is a reusable steppable sandbox, the other is recording-only behaviour (re-running the last day for its resubmissions). The `if any(plan.day == days_run[-1] ...)` re-run outside the class is easy to miss; a short comment saying why it exists would help.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-20-2026-11-19T20-42-26-634Z.log`).

Usage: Body writer 2 input, 1,669 output, 44,778 cache creation, 11,842 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/18
