# 17: A changed resubmission drops the row's discount

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 05 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/generator/resubmissions.py:134-138` (`_revise`)

`_revise` recomputes a changed row's money column as quantity × retail price instead of scaling the original `net_sales` / `line_total`. Discounted rows now exist (price cuts and promotions, `generator/anomalies.py:58`), so a changed sales resubmission on a discounted day would silently lose the discount. No current Golden Scenario does this.

- [ ] Scale the original figure by the new quantity, with a test on a discounted row.
