# 24: Deployment Playbook and README

**What to build:** The Deployment Playbook (how to adapt this to a real retailer in week one) and the portfolio README, which maps each responsibility in the job posting to the part of the project that shows it and includes the eval scorecard.

**Blocked by:** 17, 21, 23

**Status:** ready-for-agent

- [x] Playbook: replacing the Data Source, ERP MCP server and Notifier; calibrating Anomaly thresholds and the Auto-approval Limit; rebuilding the baseline from real timings
- [x] README: tagline, demo link, each posting responsibility mapped to a feature, design highlights linking the ADRs, how to run locally, how to run evals, and the latest scorecard
- [ ] **The user has reviewed and rewritten the README in their own voice** before this ticket is done

## Comments

- Implementer: the Deployment Playbook is `docs/deployment-playbook.md`. The README now opens with a tagline, the demo link, the five Ops Day stages, a table mapping each of the four responsibilities from the posting (taken from the engagement brief) to the project, design highlights linking ADRs 0001–0011, how to run it locally, how to run evals, and a link to the Playbook. The existing Replay, n8n, discovery and ERP sections are kept below that.
- **Still open: the Scorecard.** No eval run has been published, and the worktree has no model keys, so the "Latest Scorecard" table in the README is left blank with a TODO comment rather than filled with made-up figures. Run `make evals` with a free-tier key and paste the results in.
- **Still open: the third checkbox.** The owner needs to review the README and rewrite it in their own voice. That's a human step.

