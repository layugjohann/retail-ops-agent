# 09: Stockout risk → Investigation → Tier 1 alert

**What to build:** The first Anomaly path through all three stages. Deterministic statistics flag stockout risk (days of cover below the Supplier's lead time). The Analyst agent investigates with read-only tools and returns a structured Investigation. The Ops agent proposes an Action, the Action policy (a fixed rule table) assigns its Tier, and a Tier 1 alert is posted. The dashboard gets an Investigations view.

**Blocked by:** 02, 03
**Stacked on:** issue/08-erp-mcp-server

**Status:** done
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/8

- [ ] Stockout risk detection is deterministic and needs no model
- [ ] The generator can plant a stockout risk with a cause the data reveals; it is recorded in the ground truth
- [ ] The Analyst has read-only tools only; its Investigation has a cause, evidence and a recommended Action
- [ ] The Action policy assigns Tiers by rules; a model-claimed Tier is ignored (tested with a scripted model that claims a different Tier)
- [ ] The alert is a Tier 1 Action in the Audit Log
- [ ] Handoff is the deterministic pipeline (ADR 0003): no model decides routing
- [ ] The dashboard shows Investigations with their evidence

## Comments

Usage: Implementer 84 input, 66,760 output, 158,921 cache creation, 4,915,333 cache read; Review Session 20 input, 7,535 output, 71,636 cache creation, 700,216 cache read.

**Review Session: Non-critical Findings**

- evals/runner.py passes the parameter named intake_model as the analyst and ops models too. The runner's model option should be renamed (e.g. model) or each agent should get its own model.
- bi_store._LOADED writes the loaded Upload statuses as a SQL string literal ("'accepted', 'safe_fixed'") instead of building it from UploadStatus, so the two can drift apart.
- Anomaly.summary always says 'Stockout risk' and talks about days of cover, whatever the kind. It is right only while AnomalyKind has a single member and will be wrong once Issue 13 adds more kinds.
- Undoing an alert (WITHDRAW_ALERT) only writes the undo entry. The planner who received the alert is not told it was withdrawn, so the 'how to undo' wording overstates what happens.
- Detection runs only for the day passed to run_ops_day. A resubmission for an earlier day changes that day's data but does not trigger detection for it (presumably covered by Issue 15's Supersede work).

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-09-2026-11-18T17-55-22-863Z.log`).

Usage: Body writer 2 input, 1,852 output, 58,850 cache creation, 11,615 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/8

Stacked on Base Issue 08: this Pull Request targets `issue/08-erp-mcp-server`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/7. Merge that Pull Request first.
