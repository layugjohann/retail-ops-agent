# 10: Reorders through the Approval Queue

**What to build:** Investigations can recommend Reorders, which are Tier 2. They wait in the Approval Queue unless under the Auto-approval Limit. Approving one places it in the ERP through the ERP client; rejecting records the decision. The dashboard gets an Approval Queue view showing the Investigation, quantity, Supplier and cost.

**Blocked by:** 08, 09

**Status:** in-progress

- [ ] A Reorder never reaches the ERP without Approval or the Auto-approval Limit (tested, including with a scripted model that tries to bypass it)
- [ ] No agent tool can place a Reorder directly
- [ ] The Auto-approval Limit is configurable, and Reorders under it are approved automatically with an Audit Log entry
- [ ] Approve and reject are Ops Day operations; approving places the Reorder in the ERP (fake in tests), rejecting is recorded
- [ ] The Approval Queue view shows the Investigation, quantity, Supplier, cost, and approve/reject controls

## Comments

Usage: Implementer 68 input, 35,943 output, 109,918 cache creation, 3,135,943 cache read; Review Session 10 input, 4,427 output, 51,294 cache creation, 246,162 cache read.

**Review Session: Non-critical Findings**

- Undoing a Reorder's Audit Log entry cancels it in the ERP, but its Approval Queue item keeps status 'approved' or 'auto_approved'. So the dashboard's 'Decided Reorders' table and OpsDay.reorders() still show a Reorder that has been cancelled in the ERP.
- If the ERP refuses an auto-approved placement, the Reorder stays pending in the Approval Queue and the exception stops the Ops Day. The queue item is added before _place_reorder runs. A person can still approve it, but auto-approval is not atomic, and once Issue 11's one-pending rule lands this path needs handling.
- The dashboard decides which Reorders count as decided itself, with `r.status.value != "pending"`. That filter is a little business logic in Streamlit; a 'decided Reorders' view on the Ops Day boundary would keep it out of the dashboard.
- propose_action takes `sku: Sku | None` and handles None ('unknown'), but its only caller always passes a Sku from `skus[anomaly.sku]`. The None branch is dead code.
- _required raises ValueError('missing value') without saying which value is missing, which goes against the rule that errors name the problem.
- _cost accepts `quantity: int | None` and quietly treats None as 0. Callers only use it for Reorders, which always have a quantity, so the None case would hide a bug instead of raising.
- New domain terms added in this change (the auto_approved status, the policy Route) are not checked against or added to GLOSSARY.md in the same change.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-10-2026-11-18T19-40-08-206Z.log`).

Usage: Body writer 2 input, 1,765 output, 43,906 cache creation, 11,615 cache read.
