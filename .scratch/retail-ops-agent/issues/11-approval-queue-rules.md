# 11: Approval Queue rules: one pending, replacement, Expiry

**What to build:** Makes double-ordering impossible and stops stale recommendations from running late. Covers advancing simulated time.

**Blocked by:** 10

**Status:** ready-for-agent

- [ ] At most one pending Reorder per SKU and Sales Channel
- [ ] A newer Investigation of the same SKU and Sales Channel replaces the pending Reorder (recorded in the Audit Log)
- [ ] Advancing simulated time is an Ops Day operation
- [ ] A pending Action Expires 48 simulated hours after being queued and can no longer be approved

## Comments
