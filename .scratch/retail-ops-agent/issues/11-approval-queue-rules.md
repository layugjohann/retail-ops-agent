# 11: Approval Queue rules: one pending, replacement, Expiry

**What to build:** Makes double-ordering impossible and stops stale recommendations from running late. Covers advancing simulated time.

**Blocked by:** 10
**Stacked on:** issue/10-reorders-approval-queue

**Status:** done
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/10

- [ ] At most one pending Reorder per SKU and Sales Channel
- [ ] A newer Investigation of the same SKU and Sales Channel replaces the pending Reorder (recorded in the Audit Log)
- [ ] Advancing simulated time is an Ops Day operation
- [ ] A pending Action Expires 48 simulated hours after being queued and can no longer be approved

## Comments

Usage: Implementer unknown; Review Session 14 input, 4,004 output, 48,298 cache creation, 343,101 cache read.

**Review Session: Non-critical Findings**

- REPLACE_REORDER is recorded as Tier 1 (ActionTier.INTERNAL) but its undo recipe is NOT_UNDOABLE, and undo() refuses it. GLOSSARY defines Tier 1 as 'internal and reversible'. The recipe says how to work around it (reject the newer Reorder), but the entry itself is not reversible. Either make undo actually reverse it (reject the newer Reorder and restore the earlier one) or document the exception.
- The new ApprovalStatus value 'replaced' (with replaced_by and REPLACE_REORDER) uses a word GLOSSARY.md lists under _Avoid_ (for Superseded). The new Replaced and Expired Approval statuses are not added to GLOSSARY.md in the same change.
- dashboard/app.py: after 'Advance simulated time 24 hours', st.warning('Expired: ...') is followed immediately by st.rerun(), so the warning is never visible to the user.
- Expiry is a decision taken by the Action policy (QUEUE_RULES), but unlike replacement it leaves no Audit Log entry; it only shows as a status in the Approval Queue.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-11-2026-11-18T20-14-18-198Z.log`).

Usage: Body writer 2 input, 1,423 output, 36,158 cache creation, 11,615 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/10

Stacked on Base Issue 10: this Pull Request targets `issue/10-reorders-approval-queue`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/9. Merge that Pull Request first.
