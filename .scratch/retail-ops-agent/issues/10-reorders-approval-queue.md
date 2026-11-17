# 10: Reorders through the Approval Queue

**What to build:** Investigations can recommend Reorders, which are Tier 2. They wait in the Approval Queue unless under the Auto-approval Limit. Approving one places it in the ERP through the ERP client; rejecting records the decision. The dashboard gets an Approval Queue view showing the Investigation, quantity, Supplier and cost.

**Blocked by:** 08, 09

**Status:** ready-for-agent

- [ ] A Reorder never reaches the ERP without Approval or the Auto-approval Limit (tested, including with a scripted model that tries to bypass it)
- [ ] No agent tool can place a Reorder directly
- [ ] The Auto-approval Limit is configurable, and Reorders under it are approved automatically with an Audit Log entry
- [ ] Approve and reject are Ops Day operations; approving places the Reorder in the ERP (fake in tests), rejecting is recorded
- [ ] The Approval Queue view shows the Investigation, quantity, Supplier, cost, and approve/reject controls

## Comments
