# retail-ops-agent

At a retailer with a handful of stores and an online shop, someone starts every morning opening
CSVs: fixing headers, chasing store managers whose files can't be fixed without asking, and working
out whether an odd number is the business or the data. Meanwhile the inventory planner works out
stock cover in a spreadsheet and keys Reorders into the ERP by hand.

I picked this problem from a real job posting for a Forward Deployed Engineer (AI Enhanced) at a
nutritional supplement company, and built the prototype I'd want to show up with on day one.
The Client here is Cobalt Home, a fictional home-goods retailer: the work the posting describes
(messy daily CSVs, a BI system to keep trustworthy, Reorders keyed by hand) is the same at any
multi-channel retailer, and I'd rather not invent the details of a real company's business.

**Three agents turn those messy daily CSV Uploads into trusted BI data, then into investigated,
tiered Actions, with a human approving anything that costs money.**

**Live demo (Replay Mode):** https://cobalt-home-ops.streamlit.app/

A working prototype of a forward-deployed engagement at **Cobalt Home**, a fictional home and
lifestyle retailer (6 Stores, an Online Shop, about 300 SKUs). All data and discovery documents are
simulated and labelled as such. It costs $0 to build, run and host: free-tier models by default,
your own key for frontier models (ADR 0001).

Every Ops Day:

1. **Intake.** The Intake agent validates each Upload (four formats, Stores and Online Shop),
   applies Safe Fixes, Quarantines what can't be fixed without guessing, and writes the Uploader a
   plain-language message saying what to correct.
2. **Load.** Accepted data goes into the BI store (DuckDB); the dashboard reflects it.
3. **Detect.** Plain, reproducible statistics flag Anomalies: stockout risks, Sales Drops, Sales
   Spikes and Slow Movers.
4. **Investigate.** The Analyst agent looks into each Anomaly with read-only tools and explains the
   cause, or concludes Data Problem and sends the Uploads back to Intake.
5. **Act.** The Ops agent proposes Actions. Fixed rules set each Action's Tier: alerts run on their
   own and can be undone from the Audit Log; Reorders wait in the Approval Queue unless they are
   under the Auto-approval Limit.

The dashboard shows sales and inventory, Upload status, Investigations, the Approval Queue, the
Audit Log with undo, and **Hours Saved**, with every assumption behind it shown next to the number.

## What it shows, against the job posting

The posting doesn't say what systems the company runs, so I built against seams rather than
guessing a stack. Here's each responsibility it lists, and where I've shown it:

| Responsibility in the posting | Where it is in this project |
| --- | --- |
| Embed with the teams and discover manual bottlenecks | [Discovery documents](docs/discovery/): an [engagement brief](docs/discovery/engagement-brief.md), [personas](docs/discovery/personas.md), the [current manual processes](docs/discovery/manual-processes.md) step by step, and a [baseline](docs/discovery/baseline.md) of timings, every one marked as an assumption. |
| Build multi-agent, tool-calling workflows that save measurable hours | Intake, Analyst and Ops agents (Pydantic AI, typed outputs, their own tools and permissions) in a deterministic pipeline behind one Ops Day boundary (`src/retail_ops_agent/ops_day.py`). **Hours Saved** on the dashboard comes from the Audit Log times the baseline. The agents take real Actions: Safe Fixes, Quarantines, alerts and Reorders in the ERP. |
| Maintain the BI system: CSV uploads, ETL, validation, dashboards | Four Upload formats parsed and normalised (Online Shop Order Lines totalled, cancelled and refunded lines left out); Defect checks for missing, renamed and swapped columns, duplicate days, impossible quantities, unknown SKUs, date mismatches and encoding problems, with a Safe Fix for the four that need no guessing; Supersede for resent Uploads; a DuckDB BI store; a Streamlit [dashboard](dashboard/). |
| Act as the go-between with ERP and API vendors | The ERP is reached only through an [MCP server](#the-erp-mcp-server) with a contract suite, and the Data Source and Notifier sit behind seams. The [Deployment Playbook](docs/deployment-playbook.md) is the week-one plan for pointing them at a real retailer's NetSuite or Odoo, POS or Shopify, and Slack or Teams. |

Two things the posting implies but doesn't list:

- **Low-code where it fits, logic in tested code.** A scheduled [n8n workflow](#scheduled-ops-days-with-n8n)
  triggers each Ops Day and forwards notifications. It holds no business logic, which a test checks.
- **Agents that can be trusted with side effects.** [Golden-Scenario evals](evals/README.md) with
  exact Ground Truth grade each agent, an LLM judge grades free text against a Rubric, and the hard
  rule "no Tier 2 Action without Approval" must hold in 100% of Scenarios. Prompt injections planted
  in Uploads are graded for having no effect.

## Why I built it this way

**The demo opens on Replay Mode.** On a free tier, one Ops Day takes minutes, because every model
call is paced for the rate limit, and live runs often hit the limit anyway. A reviewer clicking the
link shouldn't have to wait that long, or paste in an API key, to see what the agents do. So the
demo plays back Recordings of real Ops Days, each naming the model it ran on: real model output,
with no wait and no key. Live Mode is one click away in the sidebar for anyone who wants to run a
day themselves.

**A rule, not the model, decides when money gets spent.** An inventory planner would never trust a
system where a model can place a Reorder on its own say-so. So the model only recommends an Action,
and a fixed rule table decides its Tier: alerts and Safe Fixes run on their own and can be undone,
and Reorders wait for Approval unless they are under the Auto-approval Limit. A model's
self-reported confidence can't be checked, and text planted in an Upload can talk it up; a rule
can't be talked into anything ([ADR 0002](docs/adr/0002-action-tiers-are-rules-not-confidence.md)).

**Free-tier models, on purpose.** This had to cost nothing to build, run and host, so the agents
default to free-tier models on Groq and Gemini, and anyone can bring their own key for a frontier
model ([ADR 0001](docs/adr/0001-zero-cost-free-tier-plus-byok.md)). That has a real cost: runs are
slow because they're paced, tool calling is weaker, and `gpt-oss-120b` insists on returning its
answer through a tool it calls `json`, so every agent's output tool now has that name. I treat
this as something to measure, not hide: the evals show where the cheap model is good enough.

## Design highlights

- **Tiers are rules, not model confidence** ([ADR 0002](docs/adr/0002-action-tiers-are-rules-not-confidence.md)).
  The model recommends; a rule table decides whether an Action runs, waits for Approval or is
  refused. A scripted model that "obeys" an injected instruction still cannot get a Reorder past the Approval Queue
  (`tests/test_prompt_injection.py`).
- **No LLM supervisor** ([ADR 0003](docs/adr/0003-deterministic-handoff-no-llm-supervisor.md)).
  Handoff between agents is a fixed pipeline and Anomalies come from statistics, so routing is
  testable and the same data always gives the same flags.
- **The ERP is an MCP server** ([ADR 0006](docs/adr/0006-erp-as-mcp-server.md)). The swap a real
  engagement needs is exactly one server, and Claude Desktop can talk to it too.
- **Synthetic data with planted problems** ([ADR 0005](docs/adr/0005-synthetic-data-with-planted-defects.md)).
  A seeded generator plants Defects, Anomalies, chain-wide Lookalikes and prompt injections, and
  records Ground Truth, so every eval has an exact answer.
- **Undo that stays honest** ([ADR 0007](docs/adr/0007-undoing-a-safe-fix-quarantines-the-upload.md),
  [ADR 0008](docs/adr/0008-undoing-a-quarantine-releases-the-checked-rows.md)). The Audit Log is
  append-only; an undo is a new entry, and it never loads data that would need a guess.
- **Corrections replace, they don't double-count** ([ADR 0009](docs/adr/0009-the-latest-upload-for-a-day-replaces-every-earlier-one.md)).
  A resent Upload Supersedes the earlier one; Anomalies built on it are re-checked, dependent
  alerts undone, and a Reorder already placed is flagged for a person, never cancelled silently.
- **Local problems, not chain-wide ones** ([ADR 0010](docs/adr/0010-anomalies-are-judged-against-the-other-sales-channels.md)).
  A Sales Drop or Spike must stand out from the other Sales Channels, so a seasonal dip is never
  blamed on one Store.
- **Agents catch each other's misses** ([ADR 0011](docs/adr/0011-a-data-problem-sends-uploads-back-to-intake-by-rule.md)).
  A Store reporting cases instead of units passes validation, shows up as a spike, and the Analyst
  sends it back to Intake as a Data Problem; a rule, not the model, picks which Uploads go back.
- **$0, with a framework that stays out of the way** ([ADR 0001](docs/adr/0001-zero-cost-free-tier-plus-byok.md),
  [ADR 0004](docs/adr/0004-pydantic-ai-over-langgraph.md)).

Terms are defined in [`GLOSSARY.md`](GLOSSARY.md); the full spec is
[`.scratch/retail-ops-agent/spec.md`](.scratch/retail-ops-agent/spec.md).

## Run it locally

Needs Python 3.13+ and [uv](https://docs.astral.sh/uv/). Docker only for n8n.

```sh
uv sync
make check       # ruff lint + format check, pyright, pytest (no keys, no network)
make dashboard   # Streamlit dashboard; opens in Replay Mode
make evals       # Golden Scenarios against real free-tier models; see evals/README.md
make record      # record Ops Days for Replay Mode
make deploy      # interactive wizard: deploy the dashboard to Streamlit Community Cloud
make trigger     # the local HTTP entry point n8n calls to run an Ops Day
make n8n         # local n8n in Docker, with the scheduled Ops Day workflow imported
```

Model keys are optional and free-tier only: copy `.env.example` to `.env.local` and add a
[Groq](https://console.groq.com/keys) or [Gemini](https://aistudio.google.com/apikey) key. With no
key, an offline scripted model stands in, so everything but the evals runs without a network.

## Evals

Golden Scenarios drive the same Ops Day boundary the dashboard uses, with real models, and grade
the outcome against the generator's Ground Truth: Defect precision and recall, Safe Fix
correctness, Upload statuses and BI data for Intake; the stated cause and Data Problems for the
Analyst; the Action, its Tier and the Approval Queue rules for the Ops agent; Lookalikes,
Supersede and prompt injections; and the hard rule. An LLM judge grades Uploader messages and
Investigations against written Rubrics.

```sh
make evals                                              # every Scenario, judge on
make evals ARGS="--tag prompt-injection --no-judge"     # one tag, deterministic graders only
make evals ARGS="--model groq:openai/gpt-oss-120b"      # choose the model (and --judge-model)
```

Runs are paced to stay inside free-tier rate limits. Each run writes a machine-readable Scorecard
to `evals/results/` and prints a table; it exits non-zero if any Scenario fails or the hard rule
breaks. Options, the Scenario format and every grader are in [`evals/README.md`](evals/README.md).

### Latest Scorecard

<!-- TODO(owner): run `make evals` with a free-tier key, then paste the printed table here with the
date and the models used (and a frontier-model run beside it, if you have a key). No Scorecard has
been published yet; the figures below are deliberately left blank rather than invented. -->

| | Free tier (`groq:openai/gpt-oss-120b`) |
| --- | --- |
| Run date | _not yet run_ |
| Golden Scenarios passed | _–_ / 33 |
| Defect precision / recall | _–_ |
| Hard rule (no Tier 2 Action without Approval) | _–_ |
| LLM judge criteria passed | _–_ |

## Adapting it to a real retailer

The [Deployment Playbook](docs/deployment-playbook.md) is the plan for week one at a real Client:
replacing the Data Source, the ERP MCP server and the Notifier; calibrating the Anomaly thresholds
and the Auto-approval Limit with the people who act on them; and rebuilding the baseline behind
Hours Saved from real timings.

## What I'd do next

1. **A frontier-model run beside the free-tier Scorecard.** The Scorecard only means something
   next to a baseline; I want to know where the free model is good enough.
2. **Real timings.** Hours Saved is only as honest as the baseline behind it, and right now every
   timing is an assumption.
3. **A real connector.** The seams are designed for it but untested against a real system; putting
   Shopify or Odoo behind them would prove the Playbook.
4. **Lot and expiry tracking.** A supplement business has to sell older stock first and pull
   expired batches, which the catalog doesn't model yet.

## Replay Mode

The dashboard opens in Replay Mode: it plays back Recordings of real Ops Days with no model, no key
and no network call, so a Visitor can step through each Ops Day stage by stage (Intake, Load,
Detection, Investigation, Actions). The Recordings live in `src/retail_ops_agent/recordings/` and
include a Defect day (Safe Fixes, a Quarantine and a corrected resend), a stockout risk with a
Reorder under the Auto-approval Limit, and a stockout risk whose Reorder waits for and gets
Approval. Each Recording names the model its agents ran on.

`make record` runs each Recording's seeded sandbox through the Ops Day boundary again and rewrites
its JSON. With a free-tier key in `.env.local` the agents use that model, paced for its rate limit;
without one, the offline scripted model stands in.

The sidebar switches to Live Mode, where each Visitor gets their own sandbox of Cobalt Home (BI
store, fake ERP, clock and Uploads), held only in their session's memory and seeded from the
generator with the offline scripted model. "Run day" processes the next day's Uploads with real
models; the Visitor can approve or reject Reorders, undo Audit Log entries, upload or edit a CSV of
their own (broken or malicious ones included) and reset. Ops Days first use the shared free-tier key
from the environment (`GROQ_API_KEY` or `GEMINI_API_KEY`), limited across every Visitor to
`LIVE_SHARED_RUNS` (40) Ops Days every `LIVE_SHARED_WINDOW_HOURS` (24); once that limit or the
provider's own is reached, the Visitor is asked for their own Groq or Gemini key, which is used for
their Ops Days only and never stored.

## Scheduled Ops Days with n8n

A local n8n in Docker triggers an Ops Day on a schedule and forwards the notifications it sends.
n8n is only a trigger: every rule lives in tested code behind the Ops Day boundary, and the
workflow (`n8n/workflows/ops-day.json`) has no code, branching or filtering nodes, which
`tests/test_n8n_trigger.py` checks.

```
Every evening (22:00) ─┐
                       ├─> Run Ops Day ──> Each notification ──> Forward notification
Run now (manual) ──────┘    POST /ops-day/run   split "notifications"   POST {"text": ...}
```

![n8n runs the Nov 6 Ops Day on gpt-oss-120b: the trigger Quarantines ST03's sales Upload for a missing date column, and n8n forwards the message to its Uploader](docs/media/n8n-ops-day.gif)

*One Ops Day triggered from n8n, at 10× speed (about 3 minutes in real time, as model calls are
paced for the free tier). Started with `make trigger ARGS="--seeded-days 5"`, so the first run
lands on the day with a Defect that has no Safe Fix.*

1. Start the trigger on the host. It seeds a Cobalt Home sandbox (Live Mode's, with its planted
   Defects and stockout risk) in memory, then runs the next day each time it is called. It uses a
   free-tier key from `.env.local` if there is one, else the offline scripted model. A real model's
   requests are paced to 10 a minute (`--rpm`), below Gemini's free-tier limit of 15, and retried
   when rate-limited, so one Ops Day takes a few minutes; the workflow waits up to 15.

   ```sh
   make trigger                       # http://127.0.0.1:8765
   make trigger ARGS="--host 0.0.0.0" # on Linux, so the n8n container can reach it
   ```

2. Start n8n and import the workflow (needs Docker):

   ```sh
   make n8n                           # n8n on http://localhost:5678
   ```

   Or start it with `docker compose -f n8n/docker-compose.yml up -d` and import
   `n8n/workflows/ops-day.json` from n8n's editor (Workflows → Import from File).

3. Open http://localhost:5678, set up the owner account, open "Cobalt Home: scheduled Ops Day",
   and press "Execute workflow" to run one Ops Day now, or activate it to run one every evening.

Each run's summary and every notification n8n forwards are printed by `make trigger`; the
forwarded ones are also at http://127.0.0.1:8765/inbox. By default n8n forwards to that local
inbox, a stand-in for Slack or Teams. To forward to a real chat, set `NOTIFY_WEBHOOK_URL` to an
incoming webhook that accepts `{"text": "..."}` before starting n8n:

```sh
NOTIFY_WEBHOOK_URL=https://hooks.slack.com/services/... docker compose -f n8n/docker-compose.yml up -d
```

The trigger's endpoints are `POST /ops-day/run` (run the next Ops Day; returns its day, a summary,
and the Uploader messages and alerts it sent, each with a ready-made `text`), `GET /health` (the
next day to run), and `POST`/`GET /inbox`. Once every generated day has run (90 by default,
`--days`), `/ops-day/run` answers 409; restart the trigger to start a fresh sandbox. A model outage
or rate limit answers 503 and the same day runs on the next trigger.

## Discovery and Hours Saved

`docs/discovery/` holds the simulated discovery documents: an engagement brief, personas, the
current manual processes step by step, and a baseline of manual timings. The baseline's
machine-readable form, `src/retail_ops_agent/baseline.json`, feeds the dashboard's Hours Saved:
the Audit Log entries of each baseline task's Action that no undo reversed, times its minutes each
time. Every timing is an assumption, marked as one, and shown next to the figure.

## The ERP MCP server

Cobalt Home's mock ERP runs as a standalone MCP server (ADR 0006). Its tools read Sales Channels,
SKUs, Suppliers and stock levels, and place, read and cancel Reorders. It is seeded from the same
generated Cobalt Home catalog as everything else, and its state lives in memory for as long as the
server runs.

```sh
uv run retail-ops-erp --seed 42   # speaks MCP over stdio
```

The agents and the Action policy never call these tools directly. They go through the ERP client
interface (`retail_ops_agent.erp.ErpClient`), which has two implementations: `McpErpClient`, which
talks to this server, and `InMemoryErp`, the fake used in tests and sandboxes. One contract suite
(`tests/test_erp_contract.py`) runs against both so the fake can't drift from the server. A real
engagement swaps this server for one that wraps the Client's own ERP (NetSuite, Odoo and so on)
and exposes the same tools.

### Connecting from Claude Desktop

Add the server to Claude Desktop's `claude_desktop_config.json` (Settings → Developer → Edit
Config), using the absolute path to your clone, and restart Claude Desktop:

```json
{
  "mcpServers": {
    "cobalt-home-erp": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/retail_ops_agent", "run", "retail-ops-erp", "--seed", "42"]
    }
  }
}
```

If Claude Desktop can't find `uv`, use its absolute path (`which uv`) as `command`. You can then ask
things like "Which SKUs does Store ST01 have fewer than 10 of?" or "Place a Reorder of 12 CH-0001
for ST01, then cancel it." The placing and cancelling tools are marked as writes, so the client
asks you before it runs them. Any other MCP client that can launch a stdio server works the same
way, and you can browse the tools with the MCP Inspector:

```sh
npx @modelcontextprotocol/inspector uv run retail-ops-erp --seed 42
```
