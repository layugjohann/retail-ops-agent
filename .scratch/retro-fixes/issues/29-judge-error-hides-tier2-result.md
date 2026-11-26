# 29: A judge error hides the Tier 2 hard-rule result

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 12 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/evals/runner.py:273-291`; `src/retail_ops_agent/evals/scorecard.py:86-88`, `:163-164`

The deterministic graders and the LLM judges run in one `try`. If a judge call raises, the Scenario is recorded as an error with no grader results, so its `tier2_approval` result is lost and the summary can show `tier2_breaches=0` / `hard_rule_held=true` even when a breach happened. The run still fails, since passed ≠ scenarios.

- [ ] Run the graders before and outside the judges' `try`, and keep their results when a judge fails.
