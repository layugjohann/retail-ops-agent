# 15: Supersede effects further down the pipeline

**What to build:** When an Upload is Superseded, Anomalies built on it are re-checked, Tier 1 Actions that depended on them are undone, and Tier 2 Actions already sent are flagged for a human, never undone automatically.

**Blocked by:** 05, 10, 12

**Status:** ready-for-agent

- [ ] Anomalies that no longer hold after a resubmission are cleared
- [ ] Dependent Tier 1 Actions are undone through the Audit Log (recorded as new entries)
- [ ] Dependent Tier 2 Actions already sent are flagged on the dashboard and not undone automatically
- [ ] Pending Tier 2 Actions that depended on the Superseded Upload are withdrawn from the Approval Queue
- [ ] Eval scenarios with the `supersede` tag are added

## Comments
