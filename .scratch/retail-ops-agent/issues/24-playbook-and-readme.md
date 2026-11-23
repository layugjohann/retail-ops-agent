# 24: Deployment Playbook and README

**What to build:** The Deployment Playbook (how to adapt this to a real retailer in week one) and the portfolio README, which maps each responsibility in the job posting to the part of the project that shows it and includes the eval scorecard.

**Blocked by:** 17, 21, 23

**Status:** in-progress

- [x] Playbook: replacing the Data Source, ERP MCP server and Notifier; calibrating Anomaly thresholds and the Auto-approval Limit; rebuilding the baseline from real timings
- [x] README: tagline, demo link, each posting responsibility mapped to a feature, design highlights linking the ADRs, how to run locally, how to run evals, and the latest scorecard
- [ ] **The user has reviewed and rewritten the README in their own voice** before this ticket is done

## Comments

- Implementer: the Deployment Playbook is `docs/deployment-playbook.md`. The README now opens with a tagline, the demo link, the five Ops Day stages, a table mapping each of the four responsibilities from the posting (taken from the engagement brief) to the project, design highlights linking ADRs 0001–0011, how to run it locally, how to run evals, and a link to the Playbook. The existing Replay, n8n, discovery and ERP sections are kept below that.
- **Still open: the Scorecard.** No eval run has been published, and the worktree has no model keys, so the "Latest Scorecard" table in the README is left blank with a TODO comment rather than filled with made-up figures. Run `make evals` with a free-tier key and paste the results in.
- **Still open: the third checkbox.** The owner needs to review the README and rewrite it in their own voice. That's a human step.

Usage: Implementer 42 input, 18,151 output, 77,578 cache creation, 1,373,933 cache read; Review Session 28 input, 5,336 output, 46,539 cache creation, 642,163 cache read.

**Review Session: Non-critical Findings**

- docs/deployment-playbook.md section 1 'Check' says to run Uploads through `submit` and `run`; the OpsDay methods are `submit_upload` and `run_ops_day`.
- docs/deployment-playbook.md go-live checklist says every free-text column in the Client's formats should be listed in `upload_formats.FREE_TEXT_COLUMNS`, but that table maps each format to a single column (dict[UploadFormat, str]); a Client format with several free-text columns can't be covered by listing alone. The line should say the table or code needs widening first.
- The Issue's README checkbox (which includes 'the latest scorecard') is ticked, but the README's 'Latest Scorecard' table is placeholders plus a TODO. Not inventing figures is correct and is disclosed in the Issue comments, but the box should stay unticked, or `make evals` should be run and the table filled, before the ticket closes.
- The Issue's third checkbox (the owner rewrites the README in their own voice) is still open; this is a human step that has to happen before the ticket is done.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-24-2026-11-23T16-03-30-220Z.log`).

Usage: Body writer 2 input, 953 output, 31,267 cache creation, 11,842 cache read.
