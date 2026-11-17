# 09: Stockout risk → Investigation → Tier 1 alert

**What to build:** The first Anomaly path through all three stages. Deterministic statistics flag stockout risk (days of cover below the Supplier's lead time). The Analyst agent investigates with read-only tools and returns a structured Investigation. The Ops agent proposes an Action, the Action policy (a fixed rule table) assigns its Tier, and a Tier 1 alert is posted. The dashboard gets an Investigations view.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] Stockout risk detection is deterministic and needs no model
- [ ] The generator can plant a stockout risk with a cause the data reveals; it is recorded in the ground truth
- [ ] The Analyst has read-only tools only; its Investigation has a cause, evidence and a recommended Action
- [ ] The Action policy assigns Tiers by rules; a model-claimed Tier is ignored (tested with a scripted model that claims a different Tier)
- [ ] The alert is a Tier 1 Action in the Audit Log
- [ ] Handoff is the deterministic pipeline (ADR 0003): no model decides routing
- [ ] The dashboard shows Investigations with their evidence

## Comments
