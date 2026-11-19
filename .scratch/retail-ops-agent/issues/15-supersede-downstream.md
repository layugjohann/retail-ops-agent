# 15: Supersede effects further down the pipeline

**What to build:** When an Upload is Superseded, Anomalies built on it are re-checked, Tier 1 Actions that depended on them are undone, and Tier 2 Actions already sent are flagged for a human, never undone automatically.

**Blocked by:** 05, 10, 12
**Stacked on:** issue/14-data-problem-loop

**Status:** done
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/14

- [ ] Anomalies that no longer hold after a resubmission are cleared
- [ ] Dependent Tier 1 Actions are undone through the Audit Log (recorded as new entries)
- [ ] Dependent Tier 2 Actions already sent are flagged on the dashboard and not undone automatically
- [ ] Pending Tier 2 Actions that depended on the Superseded Upload are withdrawn from the Approval Queue
- [ ] Eval scenarios with the `supersede` tag are added

## Comments

Usage: Implementer 58 input, 11,807 output, 76,238 cache creation, 1,796,892 cache read; Review Session 22 input, 6,655 output, 68,474 cache creation, 743,710 cache read.

**Review Session: Non-critical Findings**

- New domain concepts (the 'withdrawn' Approval status, a cleared Anomaly, a flagged Reorder, and the restock_counted resubmission) are not added to GLOSSARY.md in the same change.
- generator/resubmissions._count_restock unpacks `[index] = [...]` and `next(...)` without a message. If the planted SKU has no row in the inventory Upload, it raises a bare ValueError/StopIteration instead of an error naming the problem.
- The branch history includes a 'WIP: Implementer failed' commit (783bed8) that holds most of the change. Consider squashing it before merging.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-15-2026-11-19T14-53-33-523Z.log`).

Usage: Body writer 2 input, 1,885 output, 51,447 cache creation, 11,842 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/14

Stacked on Base Issue 14: this Pull Request targets `issue/14-data-problem-loop`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/13. Merge that Pull Request first.
