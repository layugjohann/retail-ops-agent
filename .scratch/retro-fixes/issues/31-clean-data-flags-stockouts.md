# 31: Clean generated data flags stockout risks

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 13 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `src/retail_ops_agent/generator/history.py:7-8` (claim), `:582-595` (restock rule); `src/retail_ops_agent/anomalies.py:299-331` (detection)

The generator says clean data shows no Anomaly, but detection over clean history at all 7 Sales Channels flags stockout risks: 33 for 42 days from 2026-01-05, 31 from 2026-06-01, 110 from 2026-11-02 (rechecked on `main` during this triage). The likely cause: the restock rule compares on hand plus on order with the reorder point, while detection compares on hand alone with the Lead Time. `tests/test_stockout_risk.py:153` covers only 12 days in March.

- [ ] Make the generator and detection agree, and widen the clean-data test to several windows.
