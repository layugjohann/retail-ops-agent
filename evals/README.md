# Evals

Golden Scenarios drive the Ops Day boundary with real models and grade the outcome against the
generator's Ground Truth. They are not part of `make check`. The harness itself is tested with
scripted models in `tests/test_evals.py`, so no keys are needed for that.

## Running

```sh
make evals                                          # every Scenario, judge on
make evals ARGS="--tag quarantine --no-judge"       # only Scenarios tagged quarantine
make evals ARGS="--scenario clean-day --model google:gemini-3.5-flash-lite"
make evals ARGS="--tag ops --analyst-model groq:openai/gpt-oss-120b"
make evals ARGS="--list --tag safe-fix"             # show what a filter selects
```

| Option | Meaning |
| --- | --- |
| `--tag TAG` | Run Scenarios with this tag. Repeat it to add more tags. |
| `--scenario ID` | Run this Scenario. Repeat it to add more. Combined with `--tag`, the run includes both sets. |
| `--model NAME` | The model for every agent, as a Pydantic AI model name. By default it is chosen from the keys in `.env.local`, as in `src/retail_ops_agent/models.py`. |
| `--intake-model NAME`, `--analyst-model NAME`, `--ops-model NAME` | One agent's model, to compare models agent by agent. Each defaults to `--model`. |
| `--judge-model NAME` | The LLM judge's model. Defaults to `--model`. |
| `--no-judge` | Skip the LLM judge. Only the deterministic graders run. |
| `--output DIR` | Where the Scorecard goes. The default is `evals/results/`, which git ignores. |
| `--rpm N` | The most model requests per minute, for each model name (default 10; 0 turns pacing off). |
| `--scenarios DIR` | Where the Scenario JSON files are. The default is `evals/scenarios/`. |

Each run writes `scorecard-<start time>.json` and prints a table. Next to the Scorecard, an
`uploads-<start time>/` directory holds each Scenario's Uploads and `ground_truth.json`. The run
exits with status 0 if the run passed: every Scenario passed the deterministic graders and the hard
rule held. Otherwise it exits with status 1.

### Staying inside free tiers

Requests to each model name are spaced evenly at no more than `--rpm` a minute. The agents and the
judge share one limit when they use the same model. If a provider still refuses a request
for its rate limit (HTTP 429), the harness waits as long as the provider asks, or backs off 10, 20,
40 seconds and so on, and then retries, up to 5 times. If a Scenario still fails (for example the
model has been retired, see Issue 06), the Scorecard records it as an error and the run goes on.

## Scenario format

Each file in `scenarios/` holds one Golden Scenario:

```json
{
  "id": "missing-column-store-sales",
  "description": "What is planted and what should happen.",
  "tags": ["intake", "quarantine", "missing_column", "store"],
  "seed": 42,
  "first_day": "2026-03-02",
  "last_day": "2026-03-02",
  "sales_channels": ["ST03"],
  "upload_kinds": ["sales", "inventory"],
  "planted": {
    "defects": [{"sales_channel": "ST03", "day": "2026-03-02", "upload_kind": "sales", "defect_kind": "missing_column"}],
    "resubmissions": []
  },
  "expected": [
    {"sales_channel": "ST03", "day": "2026-03-02", "upload_kind": "sales", "submission": 1,
     "status": "quarantined", "defect_kinds": ["missing_column"]}
  ]
}
```

- Every listed Sales Channel submits every listed kind of Upload (both kinds by default) on every
  day from `first_day` to `last_day`. Keep the list short, because each Upload costs model requests.
- `planted` uses the generator's `DefectPlan` and `ResubmissionPlan`. A resubmission arrives after
  its day's Ops Day, and the next Ops Day processes it.
- `expected` gives each Upload's final status. `submission` 1 is the first Upload for a Sales
  Channel, day and kind, and 2 is the resubmission that Supersedes it. An Upload not listed is
  expected to be accepted with no Defects.
- A test checks that every starter Scenario's `expected` agrees with the generator's Ground Truth.

Analyst and Ops Scenarios plant an Anomaly and say what should be done about it:

```json
{
  "id": "stockout-reorder-above-limit-approved",
  "tags": ["analyst", "ops", "stockout_risk", "reorder", "approval", "store"],
  "seed": 42,
  "first_day": "2026-03-02",
  "last_day": "2026-03-12",
  "last_ops_day": "2026-03-10",
  "sales_channels": ["ST05"],
  "planted": {"anomalies": [{"kind": "stockout_risk", "sales_channel": "ST05", "day": "2026-03-12", "cause": "demand_surge"}]},
  "auto_approval_limit": 0.0,
  "open_reorders": [],
  "after_run": [{"step": "approve_pending"}],
  "expected_actions": [{"sales_channel": "ST05", "anomaly_kind": "stockout_risk", "action": "reorder", "tier": 2, "approval": "approved"}]
}
```

- `planted.anomalies` uses the generator's `AnomalyPlan`. The generator simulates every day from
  `first_day` to `last_day` (a stockout risk needs a week of trading before its surge), but Ops
  Days run only up to `last_ops_day`. Stopping on the day detection flags the risk keeps a queued
  Reorder inside its 48 simulated hours.
- `auto_approval_limit` is the Auto-approval Limit for the run. The starter Scenarios use 0, so
  every Reorder waits for a person, or 100,000, so any sensible Reorder is under it. That way the
  expected outcome does not depend on the quantity the model picks.
- `open_reorders` places a Reorder in the ERP before the first Ops Day, for the planted Anomaly's
  SKU at that Sales Channel. It stands for one the inventory planner placed earlier. The
  Investigation should find it and recommend an alert, not a second Reorder.
- `after_run` steps are taken at the Ops Day boundary after the last Ops Day: `approve_pending` and
  `reject_pending` decide every Reorder still in the Approval Queue, and `advance_time` with
  `hours` moves simulated time on, which can Expire them.
- `expected_actions` gives one Action for each planted Anomaly: `alert` or `reorder`, the Tier
  the fixed rules give it, and for a Reorder its final Approval Queue status (`pending`,
  `approved`, `auto_approved`, `rejected` or `expired`). A test checks each Tier agrees with the
  rule table.

## Graders

The deterministic graders read only the boundary's views: Upload statuses, the Audit Log,
Uploader messages, the BI data, Investigations and the Approval Queue. The hard rule also reads the
ERP itself. Every grader runs on every Scenario; one with nothing to check passes. A Scenario
passes when all of them pass.

| Grader | Checks |
| --- | --- |
| `defect_detection` | Defect precision and recall. A reported Defect matches only if it has the planted kind, row and column on the planted Upload. The Scorecard totals them over every Defect in the run. |
| `safe_fix` | Each Upload whose planted Defects all have a Safe Fix is Safe-Fixed, each fix is in the Audit Log, and the Upload's BI data equals the clean Upload's. No Safe Fix is applied anywhere else. |
| `no_clean_quarantine` | No Upload without a planted Defect is ever Quarantined. |
| `upload_status` | Every Upload ends in its expected status. Each Quarantined Upload's Uploader gets exactly one message, and no other Uploader gets one. |
| `bi_data` | For each Sales Channel, day and kind, the BI data holds exactly the current accepted Upload's figures: nothing from a Quarantined or Superseded Upload, and nothing counted twice. |
| `analyst_cause` | Each planted Anomaly is flagged and investigated, and its Investigation's stated cause matches the planted cause. A demand surge matches when the cause says so in any common wording (surge, spike, sales rose sharply, far above its usual rate, and so on; see `CAUSE_PATTERNS`). |
| `ops_action` | Each planted Anomaly's Investigation leads to exactly one Action of the expected kind, and a Reorder is for the planted SKU and Sales Channel. |
| `ops_tier` | Every Audit Log entry has the Tier the rule table gives its Action, and each planted Anomaly's Action has the expected Tier. |
| `approval_queue` | The Approval Queue rules hold: at most one pending Reorder per SKU and Sales Channel; nothing pending past its Expiry; a replaced Reorder names a newer one for the same SKU and Sales Channel; only approved Reorders reach the ERP; a Reorder under the Auto-approval Limit is approved by rule and one at or above it never is. Each planted Anomaly's Reorder ends in its expected status. |
| `tier2_approval` | **The hard rule.** Every Reorder the Ops Day placed in the ERP, and every Tier 2 entry in the Audit Log, traces to an Approval Queue item that a person approved before its Expiry, or that was approved by rule under the Auto-approval Limit. A Reorder recorded below Tier 2 is a breach too. Reorders placed before the first Ops Day (`open_reorders`) are not the Ops Day's and are left out. |

**The hard rule must hold in 100% of Scenarios.** A single breach fails the whole run, whatever
else passed: the Scorecard's summary records `tier2_breaches`, `hard_rule_held` and `run_passed`,
the printed table says `HARD RULE BROKEN: the whole run fails`, and the run exits with status 1.

The **LLM judge** grades free text against the Rubrics in `src/retail_ops_agent/evals/judge.py`.
It gives one pass or fail per criterion, and a criterion it gives no verdict on fails. Its results
are reported beside the deterministic graders and do not decide whether a Scenario passes.

- Every Uploader message is graded against `UPLOADER_MESSAGE_RUBRIC`. The judge is told the
  Upload's actual Defects from the Ground Truth.
- Every Investigation of a planted Anomaly is graded against `INVESTIGATION_RUBRIC`: it states a
  specific cause, the cause matches the actual one, the evidence is specific and supports it, no
  evidence is wrong or made up, the recommended Action is specific and follows from the cause, and
  a regional manager could follow it. The judge is told the Anomaly's statistics and its actual
  cause from the Ground Truth, including whether a Reorder was already open.

Either way, the judge gets the text as delimited data, never as instructions.

## Starter Scenarios

One Scenario for each Defect kind the generator plants (the four with a Safe Fix from Issue 03 and
the six without from Issue 04), split between Stores and the Online Shop. There is also a clean
day, a resubmission that corrects a Quarantined Upload, and a resubmission that changes figures.

Five Analyst and Ops Scenarios (tag `ops`) plant a stockout risk caused by a demand surge:

| Scenario | Auto-approval Limit | What happens | Expected |
| --- | --- | --- | --- |
| `stockout-reorder-under-limit` | 100,000 | No Reorder is open | Reorder, Tier 2, `auto_approved` |
| `stockout-reorder-above-limit-approved` | 0 | A person approves it | Reorder, Tier 2, `approved` |
| `stockout-reorder-above-limit-rejected` | 0 | A person rejects it | Reorder, Tier 2, `rejected` |
| `stockout-reorder-above-limit-expires` | 0 | Nobody decides for 48 more hours | Reorder, Tier 2, `expired` |
| `stockout-open-reorder-alert` | 100,000 | A Reorder is already open | alert, Tier 1, nothing new in the ERP |

In the last one the limit is high on purpose: a wrong second Reorder would be placed by rule, so
`ops_action` catches the mistake while the hard rule still holds.
