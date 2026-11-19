# 13: More Anomaly kinds and lookalikes

**What to build:** Adds sales drops at one Sales Channel, spikes and slow movers, each with a planted cause, plus chain-wide lookalikes that must not be blamed on one Store.

**Blocked by:** 09, 12

**Status:** awaiting-merge
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/12

- [ ] Deterministic detection for a sales drop at one Sales Channel (compared with its own history and with other Sales Channels), spikes and slow movers
- [ ] The generator can plant each kind with a cause the data reveals, plus chain-wide lookalikes
- [ ] A chain-wide drop is not flagged as a problem at one Sales Channel
- [ ] Eval scenarios for each kind and lookalike are added

## Comments

Usage: Implementer unknown; Review Session 36 input, 11,184 output, 100,270 cache creation, 1,767,815 cache read.

**Review Session: Non-critical Findings**

- Dead code: `SKU_KINDS` in src/retail_ops_agent/anomalies.py is defined but never used.
- Naming: action_policy.py keeps the inventory planner's address as the generic `ALERT_RECIPIENT` next to the new `REGIONAL_MANAGER` and `MERCHANDISING`. A name such as `INVENTORY_PLANNER` would say what it is now that alerts go to several people.
- Duplicated logic and a magic number: generator/history.py `_usual` hard-codes a 14-day window (`range(1, 15)`) instead of reusing a constant, and it repeats the usual-rate idea from anomalies.py `USUAL_WINDOW_DAYS`.
- Weak typing: `_FootfallDrop.__init__` and `_PriceCut.__init__` take `*args: Any, **kwargs: Any`, and `_plan_plants` builds `common: dict[str, Any]`, so pyright can't check the plant constructors' arguments.
- Misleading defaults: `AnomalyPlan.cause` defaults to `DEMAND_SURGE` and `LookalikePlan.cause` to `CHAIN_WIDE_DIP`, but the before-validator always replaces them with the kind's cause.
- `_plan_plants` sends every unmatched Anomaly kind to `_FadingDemand` through a bare `else`, and every unmatched lookalike kind to `_PriceCut`. A table keyed by kind, or an explicit check, would be safer if a new kind is added.
- The `OpsDay.run_ops_day` docstring has a broken line wrap ('A Reorder is Tier 2: it is always for the' followed by a short line).
- Glossary: the new planted causes (footfall drop, price cut, fading demand) and the lookalike causes are not in GLOSSARY.md. 'Dip', listed as an Avoid word for Sales Drop, is used in the Lookalike cause name `chain_wide_dip`.
- Probably not from this change (untested on main): the clean-data sweep at all 7 Sales Channels flags many stockout risks over 42-day windows (33 from January, 31 from June, 303 from November). That contradicts the generator's claim that clean data shows no Anomaly. This branch doesn't touch stockout-risk detection or the stock policy.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-13-2026-11-19T09-39-03-925Z.log`).

Usage: Body writer 2 input, 1,650 output, 82,393 cache creation, 11,842 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/12
