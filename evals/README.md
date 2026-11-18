# Evals

Golden Scenarios drive the Ops Day boundary with real models and grade the outcome against the
generator's Ground Truth. They are not part of `make check`. The harness itself is tested with
scripted models in `tests/test_evals.py`, so no keys are needed for that.

## Running

```sh
make evals                                          # every Scenario, judge on
make evals ARGS="--tag quarantine --no-judge"       # only Scenarios tagged quarantine
make evals ARGS="--scenario clean-day --model google:gemini-3.5-flash-lite"
make evals ARGS="--list --tag safe-fix"             # show what a filter selects
```

| Option | Meaning |
| --- | --- |
| `--tag TAG` | Run Scenarios with this tag. Repeat it to add more tags. |
| `--scenario ID` | Run this Scenario. Repeat it to add more. Combined with `--tag`, the run includes both sets. |
| `--model NAME` | The Intake model, as a Pydantic AI model name. By default it is chosen from the keys in `.env.local`, as in `src/retail_ops_agent/models.py`. |
| `--judge-model NAME` | The LLM judge's model. Defaults to the Intake model. |
| `--no-judge` | Skip the LLM judge. Only the deterministic graders run. |
| `--output DIR` | Where the Scorecard goes. The default is `evals/results/`, which git ignores. |
| `--rpm N` | The most model requests per minute, for each model name (default 10; 0 turns pacing off). |
| `--scenarios DIR` | Where the Scenario JSON files are. The default is `evals/scenarios/`. |

Each run writes `scorecard-<start time>.json` and prints a table. Next to the Scorecard, an
`uploads-<start time>/` directory holds each Scenario's Uploads and `ground_truth.json`. The run
exits with status 0 if every Scenario passed the deterministic graders, and 1 if any failed.

### Staying inside free tiers

Requests to each model name are spaced evenly at no more than `--rpm` a minute. The Intake model
and the judge share one limit when they use the same model. If a provider still refuses a request
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

## Graders

The deterministic graders read only the boundary's views: Upload statuses, the Audit Log,
Uploader messages and the BI data. A Scenario passes when all of them pass.

| Grader | Checks |
| --- | --- |
| `defect_detection` | Defect precision and recall. A reported Defect matches only if it has the planted kind, row and column on the planted Upload. The Scorecard totals them over every Defect in the run. |
| `safe_fix` | Each Upload whose planted Defects all have a Safe Fix is Safe-Fixed, each fix is in the Audit Log, and the Upload's BI data equals the clean Upload's. No Safe Fix is applied anywhere else. |
| `no_clean_quarantine` | No Upload without a planted Defect is ever Quarantined. |
| `upload_status` | Every Upload ends in its expected status. Each Quarantined Upload's Uploader gets exactly one message, and no other Uploader gets one. |
| `bi_data` | For each Sales Channel, day and kind, the BI data holds exactly the current accepted Upload's figures: nothing from a Quarantined or Superseded Upload, and nothing counted twice. |

The **LLM judge** grades every Uploader message against the Rubric in
`src/retail_ops_agent/evals/judge.py` (`UPLOADER_MESSAGE_RUBRIC`). It gives one pass or fail per
criterion, and a criterion it gives no verdict on fails. The judge is told the Upload's actual
Defects from the Ground Truth, and it gets the message as delimited data. Its results are reported
beside the deterministic graders and do not decide whether a Scenario passes.

## Starter Scenarios

One Scenario for each Defect kind the generator plants (the four with a Safe Fix from Issue 03 and
the six without from Issue 04), split between Stores and the Online Shop. There is also a clean
day, a resubmission that corrects a Quarantined Upload, and a resubmission that changes figures.
