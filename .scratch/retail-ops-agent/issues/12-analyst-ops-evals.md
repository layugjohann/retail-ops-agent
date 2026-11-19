# 12: Analyst and Ops evals

**What to build:** Extends the eval harness to the Analyst and Ops agents, including the hard rule that no Tier 2 Action runs without Approval.

**Blocked by:** 07, 10
**Stacked on:** issue/11-approval-queue-rules

**Status:** awaiting-merge
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/11

- [ ] Analyst grader: stated cause matches the planted cause
- [ ] Ops graders: right Action, right Tier, Approval Queue rules respected
- [ ] Hard rule: any Tier 2 Action without Approval or the Auto-approval Limit fails the whole run
- [ ] LLM judge grades Investigation write-ups against a written rubric
- [ ] Scenarios cover stockout risk with and without Reorders, above and below the Auto-approval Limit

## Comments

Usage: Implementer 80 input, 60,200 output, 156,543 cache creation, 4,603,706 cache read; Review Session unknown.

**Review Session: Non-critical Findings**

- runner.run_evals runs the deterministic graders and the LLM judges in one try block; if a judge call raises, the Scenario's tier2_approval result is discarded and recorded as an error, so the summary can show tier2_breaches=0 / hard_rule_held=true even if a breach occurred (the run still fails via passed != scenarios).
- CAUSE_PATTERNS for demand_surge is very broad (e.g. 'faster than usual', 'far more than', 'above the usual'), so some wrong causes worded that way would pass analyst_cause.
- tests/eval_models.py scripted models parse the first JSON object out of the prompt, and the judge test asserts prompt text ('Stockout risk for', delimiters), coupling tests to prompt structure against the testing standard.
- Minor style: AGENTS constant declared mid-module in runner.py; AfterRunStepKind lacks a docstring; after_run loop iterates the Approval Queue for every step kind, including advance_time, which obscures intent.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-12-2026-11-18T20-39-16-440Z.log`).

Usage: Body writer 2 input, 1,317 output, 59,070 cache creation, 11,615 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/11

Stacked on Base Issue 11: this Pull Request targets `issue/11-approval-queue-rules`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/10. Merge that Pull Request first.
