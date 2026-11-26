# 07: Triage the remaining Review Findings

Status: awaiting-merge
Pull Request: https://github.com/layugjohann/retail-ops-agent/pull/32
Blocked by: 01

**What to build:** Sweep every Non-critical Finding in the `## Comments` of
`.scratch/retail-ops-agent/issues/*.md` (about 100, across 22 Issues) and decide what happens to each.
Issue 01 already covers the confirmed bugs, so skip those.

For each Finding, check `main` and put it in exactly one of these groups:
- **Gone**: already fixed, or the code it names no longer exists.
- **Bug or gap still present**: write a new Issue file in `.scratch/retro-fixes/issues/` (next free number,
  `Status: needs-triage`), naming the source Issue and the file and line where the bug is now.
- **Style or naming only**: list it in this Issue's comment. Don't file it.

- [x] Every Finding in Issues 01 to 25 is in one of the three groups. The comment on this Issue lists each Finding
      under its group, with the source Issue number.
- [x] No code changes in this Issue: it only files Issues.

## Comments

**Implementer:** All 103 Review Session Non-critical Findings in Issues 01 to 25 were checked against `main` at
`cfaa54f`. Issues 06, 19, 21, 23 and 25 had no Review Session Findings. 26 Findings are Gone (5 of them fixed by
retro-fix 01), 35 are still present and filed as Issues 08 to 41 (two Findings share Issue 08), and 42 are Style or
naming only. Each line gives the source Issue number.

Not a Review Session Finding, so not filed: Issue 25's "Open finding" (a per-minute 429 on the shared key calls
`limiter.exhaust()` for every Visitor, `src/retail_ops_agent/live.py:267-268`) is still on `main`. Issue 25 left it as
a separate decision.

### Gone

- 01: A Quarantined Upload with no model `uploader_message` gets no Audit Log entry or message. `_record_quarantine`
  always runs, and `quarantine_message` always builds a message.
- 01: The dead `store.kind` check in `generate_store_sales`. The function no longer exists.
- 02: `build_sandbox` makes 196 Intake model calls for the dashboard. The dashboard plays Recordings, and Live Mode
  seeds with the offline model and runs one paced day at a time.
- 03: The Safe Fix table only checked by an `assert`. Fixed by retro-fix 01.
- 03: The "reading the Upload again" comment hides an assumption. The comment now says the reload gives "the rows
  they passed", which is true.
- 07: `run_scenario` takes an unused `generated` parameter. It is now used.
- 08: The MCP client imports its result wrappers from `erp_server`. They now live in `erp.py`.
- 09: The runner passes `intake_model` to every agent. The runner now has `--model`, a `--{agent}-model` option
  for each agent, and `--judge-model`.
- 09: `Anomaly.summary` always says "Stockout risk". Each Anomaly kind now has its own summary.
- 10: Undoing a Reorder leaves it `approved`. Fixed by retro-fix 01 (`cancelled`).
- 10: The dashboard decides which Reorders count as decided. It now calls `OpsDay.decided_reorders()`.
- 10: `propose_action`'s `sku is None` branch is dead. It is now reachable: some Anomaly kinds have no SKU.
- 11: The Expired warning is wiped by `st.rerun()`. Fixed by retro-fix 01.
- 13: `SKU_KINDS` is dead code. Deleted in retro-fix 01.
- 14: A released Data Problem Quarantine keeps its Defect. Fixed by retro-fix 01.
- 15: The `WIP: Implementer failed` commit should be squashed. It is now part of `main`'s history.
- 17: The "user approved documents and timings" box is still open. Issue 17 is done.
- 18: Recordings were made with the offline model ("Not investigated"). They were re-recorded on
  `groq:openai/gpt-oss-120b` in Issue 26.
- 20: The dashboard only catches `ModelAPIError`. It now catches `AgentRunError`.
- 20: A failed shared-key day keeps its limiter slot. `SharedKeyLimiter.release()` was added in Issue 25.
- 22: `make n8n` imports the workflow before n8n is ready. It now polls `/healthz` (Issue 23).
- 22: n8n's image defaults to `latest`. It is pinned to 2.48.7.
- 24: The Deployment Playbook says `submit` and `run`. It now says `submit_upload` and `run_ops_day`.
- 24: The playbook implies `FREE_TEXT_COLUMNS` can list several columns per format. It now says the table must be
  widened first.
- 24: The README's Scorecard is placeholders but its box is ticked. The README says no Scorecard is published yet,
  and the Issue's closing comment records that choice.
- 24: The "owner rewrites the README" box is open. It is ticked.

### Bug or gap still present (filed)

- 01, 16: Model-reported Defects are not confirmed, and the free-text filter is narrow. Filed as **08**.
- 01: Nothing loads `.env.local` for `make dashboard`. **09**
- 02: An Upload for an unknown Sales Channel raises `KeyError` and aborts the Ops Day. **10**
- 02: Online Shop daily totals per SKU are not checked against `MAX_PLAUSIBLE_DAILY_UNITS`. **11**
- 03: Undoing a Safe Fix Quarantines the Upload, but no Uploader message is sent. **12**
- 03: The undo entry is logged before settling, with no transaction. **13**
- 03: Nothing tests that `_RENAMES` and `COLUMN_ALIASES` agree. **14**
- 04: A released header-Defect Upload shows `accepted` with no rows loaded. **15**
- 05: A late Upload for a day with nothing processed is never picked up. **16**
- 05: `_revise` recomputes money as quantity × retail price and drops discounts. **17**
- 07: `ThrottledModel` doesn't wrap `request_stream` or `count_tokens`. **18**
- 07: A mistyped Sales Channel in a Golden Scenario is silently dropped. **19**
- 07: Scorecard and Upload directory names have one-second resolution. **20**
- 08: Every MCP tool error becomes `ErpRefusal`. **21**
- 08: `_shut_down_loop` closes the loop even if the thread is still running. **22**
- 09: Undoing an alert doesn't tell the planner. **23**
- 09: Detection runs only for the `day` passed in. **24**
- 10: An ERP refusal during auto-approval leaves the item pending and stops the Ops Day. **25**
- 10: `_required` raises `"missing value"` without naming the value. **26**
- 11: `REPLACE_REORDER` (and `WITHDRAW_REORDER`) are Tier 1 but cannot be undone. **27**
- 11: Expiry writes no Audit Log entry. **28**
- 12: A judge error discards the Scenario's `tier2_approval` result. **29**
- 12: The `demand_surge` `CAUSE_PATTERNS` are too broad. **30**
- 13: Clean data flags stockout risks. Rechecked: 33, 31 and 110 risks for 42-day windows from January, June and
  November. **31**
- 14: Anomalies that still show after a Data Problem are investigated with their first detection's figures. **32**
- 16: The whitespace Safe Fix runs on free-text columns. **33**
- 16: A lowercase `description` header in the Stock Snapshot is silently ignored. **34**
- 17: Hours Saved counts Safe Fixes per Defect, not per Upload. **35**
- 18: `ReplayStep.withdrawn_reorders` is never rendered. **36**
- 18: The deploy wizard returns 0 and records nothing when `git push` fails. **37**
- 20: A Visitor's CSV is decoded with `errors="replace"`, which hides encoding Defects. **38**
- 22: Notifications from a failed Ops Day are never forwarded by the trigger. **39**
- 22: `Handler._run` returns no JSON 500 for unexpected errors. **40**
- 22: `/inbox` is unbounded, nothing is authenticated, and the README suggests `0.0.0.0` without a warning. **41**

### Style or naming only (not filed)

- 02: The _Avoid_ word "run" in `generator/history.py`.
- 02: The "store code ..." Defect detail wording. Only Store formats call it, so it is accurate.
- 02: `inventory_by_sku` silently falls back for a SKU missing from the ERP. Unknown SKUs are Quarantined at Intake.
- 03: `AuditLog.append` and `_settle_upload` rebuild the whole log. This is efficiency only, with no impact at
  demo scale.
- 03: No glossary entries for the undo recipe or "reinstate". Action Tier has since been added.
- 04: The `if result.uploader_message:` branch is always true.
- 04: No glossary entries for `UploaderMessage`, the Quarantine Action or release.
- 05: No glossary entry for "resubmission".
- 05: The _Avoid_ word "file" in ADR 0009 and `dashboard/app.py`.
- 05: `run_ops_day` does three jobs.
- 07: `ExpectedUpload.defect_kinds` is not read by any grader. A test cross-checks it.
- 07: The _Avoid_ word "file" in `evals/README.md` and the Scenario docstrings.
- 08: The _Avoid_ word `item` for a SKU in `erp.py`.
- 08: No glossary entry for `ReorderStatus`.
- 09: `bi_store._LOADED` is a hard-coded SQL literal, not built from `UploadStatus`.
- 10: `_cost` treats a `None` quantity as 0. It is unreachable, because `ActionProposal` requires a quantity.
- 10: No glossary entries for `auto_approved` or Route.
- 11: The "replaced" status uses an _Avoid_ word and has no glossary entry. Expired has since been added.
- 12: The scripted test models parse the prompt's JSON, and tests assert prompt text.
- 12: `AGENTS` is declared mid-module, `AfterRunStepKind` has no docstring, and the `after_run` loop walks the queue
  for `advance_time`.
- 13: `ALERT_RECIPIENT` should be named `INVENTORY_PLANNER`.
- 13: `_usual` hard-codes `range(1, 15)` instead of using `USUAL_WINDOW_DAYS`.
- 13: Weak typing: `*args: Any, **kwargs: Any` on the plant constructors and `common: dict[str, Any]`.
- 13: The misleading `cause` defaults on `AnomalyPlan` and `LookalikePlan`.
- 13: The bare `else` in `_plan_plants`. Every kind is handled today.
- 13: The broken line wrap in the `run_ops_day` docstring.
- 13: The planted causes are not in the glossary, and the _Avoid_ word "dip" appears in `chain_wide_dip`. Lookalike
  has since been added.
- 14: The aliases `_SKU_COLUMN` and `_QUANTITY_COLUMN` in `generator/defects.py`.
- 15: No glossary entries for withdrawn, cleared Anomaly, flagged Reorder or `restock_counted`.
- 15: `_count_restock`'s bare `ValueError` and `StopIteration`. They are unreachable today, so only the message is at
  stake.
- 16: `grade_injections` is about 100 lines doing several jobs.
- 16: `tests/test_prompt_injection.py` imports private test helpers behind pyright ignores.
- 17: The investigate-anomaly timing cites different sources in `baseline.json` and `baseline.md`.
- 17: `replay_step` re-reads `baseline.json` on every call. This is efficiency only.
- 17: The undo exclusion is worded differently in `baseline.md` and the dashboard/README.
- 18: `replay.py` depends on `evals.throttle`. It now goes through `models.py`, but `models.py` imports
  `evals.throttle`, so the core still depends on the eval package.
- 18: `test_each_stage_shows_only_what_that_stage_did` selects its Recording by index.
- 18: `sandbox._ran` is an unclear name.
- 18: `Decision.REJECT` and its `_decide` branch are unused and untested.
- 20: The _Avoid_ words `LiveRun`, `LAST_RUN`, `runs`, `DEFAULT_SHARED_RUNS`, `LIVE_SHARED_RUNS` and "CSV file", and
  the wording "broken or malicious ones".
- 20: The recording-only re-run of the last day in `build_sandbox` has no comment.
- 22: No glossary entry for the trigger or the local inbox.

Usage: Implementer unknown; Review Session 14 input, 4,816 output, 50,464 cache creation, 319,242 cache read.

**Review Session: Non-critical Findings**

- Inconsistent grouping: Issue 15's `_count_restock` bare ValueError/StopIteration with no message is listed as Style or naming only, while the same kind of Finding from Issue 10 (`_required` raising 'missing value') was filed as Issue 26.
- Several Findings under 'Style or naming only' are dismissed because the code is unreachable, not because they are naming: Issue 02 `inventory_by_sku` fallback, Issue 10 `_cost` None, Issue 04 always-true `if result.uploader_message:`, Issue 18 unused `Decision.REJECT`. The last two are dead code under the project's no-dead-code rule and could be filed.
- Issue 18's Finding that the core depends on the eval package (`models.py` imports `evals.throttle`) is structural, not style or naming, yet it is listed as Style or naming only.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-07-2026-11-26T13-59-11-341Z.log`).

Usage: Body writer 2 input, 896 output, 29,904 cache creation, 11,837 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/32
