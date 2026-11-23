# Deployment Playbook

> How to take this prototype from Cobalt Home, the fictional Client, to a real retailer in the first
> week of an engagement. Terms are as in [`GLOSSARY.md`](../GLOSSARY.md).

The prototype touches the Client's systems at three seams: the **Data Source** (how Uploads
arrive), the **ERP** (reached only through the ERP MCP server, ADR 0006) and the **Notifier** (how
Uploaders and planners hear about things). Everything else (validation, Safe Fixes, Anomaly
detection, the Action policy, the Audit Log, Hours Saved) sits behind the Ops Day boundary
(`retail_ops_agent.ops_day.OpsDay`) and does not change when the seams do. Week one replaces the
three seams, calibrates the numbers that were guessed for Cobalt Home, and rebuilds the baseline
from real timings.

`OpsDay` is built with every dependency passed in, so each swap below is one constructor argument:

```python
OpsDay(
    models=Models(intake=..., analyst=..., ops=...),
    erp=...,  # ErpClient: McpErpClient pointed at the Client's ERP MCP server
    notifier=...,  # Notifier: Slack, Teams or email instead of LogNotifier
    data_source=...,  # DataSource: their upload folder, SFTP drop, POS or Shopify feed
    clock=...,
    database="ops.duckdb",  # a file, not ":memory:", so the BI store survives restarts
    auto_approval_limit=...,  # agreed with the inventory planner (below)
    baseline=...,  # their measured baseline (below)
)
```

## The week at a glance

| Day | Goal | Done when |
| --- | --- | --- |
| 1 | Discovery: shadow the people in each persona, collect a week of real Uploads, get read access to the ERP | Sample Uploads and an ERP sandbox account in hand; the manual processes written down and timed |
| 2 | Replace the Data Source; run the real Uploads through Intake in shadow mode (no Actions, no messages) | Every sample Upload is accepted, Safe-Fixed or Quarantined, and the BI analyst agrees with each verdict |
| 3 | Replace the ERP MCP server, read-only first; the contract suite passes against it | `tests/test_erp_contract.py` passes against the Client's server, with placing and cancelling Reorders pointed at the ERP's sandbox |
| 4 | Replace the Notifier; calibrate Anomaly thresholds on the Client's history | Messages land in the Uploaders' real chat; a backtest flags what the planners would have wanted flagged, and nothing they would not |
| 5 | Agree the Auto-approval Limit; rebuild the baseline from the timings taken on day 1; first scheduled Ops Day | n8n triggers the Ops Day, the Approval Queue is in front of the inventory planner, and Hours Saved shows measured minutes |

Shadow mode throughout: until day 5, run with `auto_approval_limit=0` so every Reorder waits for a
person, and point the Notifier at the engagement team rather than the Uploaders.

## 1. Replace the Data Source

**Seam:** `retail_ops_agent.data_source.DataSource`, a two-method protocol:

```python
class DataSource(Protocol):
    def put(self, upload: Upload) -> None: ...
    def uploads_for(self, day: date) -> list[Upload]: ...  # oldest first
```

`CsvDataSource` (a folder per day) is the only real implementation. At a real retailer, Uploads
arrive one of three ways:

- **They already upload CSVs** (a shared drive, SFTP, an email inbox). Write a `DataSource` that
  reads that location and fills in each `Upload`'s Sales Channel, day, kind, Uploader and submission
  time from the folder layout, filename or sender. Keep their files exactly as they are; validating
  them as they arrive is the point.
- **A POS or e-commerce platform has an API** (Shopify, Square, Lightspeed). Write a `DataSource`
  that pulls the day's orders and stock and renders them as an Upload in one of the four formats in
  `retail_ops_agent.upload_formats`. Shopify's orders map onto the Online Shop's Order Line format
  (paid, cancelled, refunded) and its inventory levels onto the Stock Snapshot. An API feed has
  fewer Defects than a hand-made CSV, but Intake still checks it.
- **A format the prototype does not know.** Add a parser to `upload_formats.py` that normalises it
  to daily sales and on-hand per SKU and Sales Channel, the same way Order Lines are totalled today.
  Nothing downstream of the BI store needs to change.

Order matters for Supersede (ADR 0009): `uploads_for` must return Uploads oldest first, because
the latest one for a Sales Channel, day and kind replaces every earlier one.

**Check:** run a week of the Client's real Uploads through `submit` and `run`. The BI analyst
should agree with every status. A clean Upload that ends Quarantined is a bug, not a calibration
issue: fix the parser or the check before going on.

## 2. Replace the ERP MCP server

**Seam:** the `retail_ops_agent.erp.ErpClient` protocol, reached over MCP by `McpErpClient`. The
agents and the Action policy only ever see this interface (ADR 0006).

The mock server (`retail_ops_agent.erp_server`) exposes eight tools: `list_sales_channels`,
`list_skus`, `list_suppliers`, `stock_levels`, `place_reorder`, `get_reorder`, `list_reorders` and
`cancel_reorder`. Replace it with a server that wraps the Client's ERP and exposes the same tools
with the same result shapes:

| Tool | NetSuite | Odoo |
| --- | --- | --- |
| `list_skus` (code, Supplier, unit cost, retail price, case pack, Lead Time) | Inventory items, with the preferred vendor's purchase price and lead time | `product.product` with `product.supplierinfo` (`price`, `delay`, `min_qty`) |
| `list_suppliers` | Vendors | `res.partner` records that are suppliers |
| `stock_levels` | Inventory balance per location | `stock.quant` per warehouse location |
| `place_reorder` | Create a Purchase Order (pending approval in NetSuite too, if they use its approval routing) | Create a `purchase.order` as a draft RFQ, or confirm it |
| `cancel_reorder` | Close or cancel the Purchase Order | `button_cancel` on the `purchase.order` |

Map each Sales Channel to the ERP's location or warehouse once, in the server, not in the agents.

Things to settle with the ERP vendor or the Client's ERP admin:

- **A service account** with read access to items, vendors and stock, and write access only to
  creating and cancelling purchase orders. Nothing else.
- **A sandbox** for days 3 and 4. Point the contract suite at it before production.
- **Where approval lives.** The Approval Queue is the human gate here, by rule (ADR 0002). If the
  ERP has its own approval routing, `place_reorder` can create the order as pending in the ERP as
  well; the prototype's rule still holds.
- **Rate limits and timeouts** on the ERP's API. `McpErpClient` waits `TIMEOUT_SECONDS` for each
  call; raise it if the ERP is slow.

**Check:** add the new server as a third parameter of the `erp` fixture in
`tests/test_erp_contract.py` and run the suite against the ERP sandbox. The contract covers reading
SKUs, stock and Suppliers, and placing, reading and cancelling Reorders. When it passes, the agents
cannot tell the difference. The same server then also works from Claude Desktop for the planners.

## 3. Replace the Notifier

**Seam:** `retail_ops_agent.notifier.Notifier`, one method:

```python
class Notifier(Protocol):
    def send(self, notification: Notification) -> None: ...  # sent_at, recipient, subject, body
```

`LogNotifier` keeps messages for the dashboard. Two ways to reach people for real:

- **Through n8n** (no code). The n8n workflow already forwards every notification an Ops Day sends
  to `NOTIFY_WEBHOOK_URL` as `{"text": ...}`, which Slack and Teams incoming webhooks accept. Use
  this for the first week.
- **A `Notifier` implementation** that posts to Slack's or Teams' API directly, or sends email.
  Use this when messages must reach individual Uploaders rather than one channel.

Either way, map each `recipient` to a real person or channel. Uploader messages go to the Uploader
named on the Upload. Alerts go to the recipients in `action_policy.ALERT_RECIPIENTS` (the inventory
planner for stockout risks and Slow Movers, the regional manager for Sales Drops, merchandising for
Sales Spikes); replace the `@cobalthome.example` addresses with the Client's people or channels.

**Check:** a Quarantined sample Upload produces exactly one message, in the Uploader's own chat,
that they can act on without asking the BI analyst.

## 4. Calibrate the Anomaly thresholds

The thresholds are module-level constants in `retail_ops_agent/anomalies.py`, chosen so Cobalt
Home's generated data flags what was planted and nothing else. A real retailer's sales are
noisier, so calibrate them against the Client's own history.

| Anomaly | Constants | Cobalt Home value | What to ask |
| --- | --- | --- | --- |
| Stockout risk | `SALES_WINDOW_DAYS`, `MIN_SALES_DAYS`, `MIN_AVERAGE_DAILY_UNITS`; the SKU's Lead Time from the ERP | 14 days, 7 days, 1 unit a day | Are Lead Times in the ERP right? Most false stockout risks are wrong Lead Times, not wrong thresholds. |
| Sales Drop | `DROP_WINDOW_DAYS`, `DROP_SHARE`, `DROP_SHARE_OF_OTHERS`, `MIN_OTHER_SALES_CHANNELS` | 3 days below 60% of usual, while the others hold above 60% of theirs; at least 2 others | How big a drop would the regional manager want to hear about the same evening? |
| Sales Spike | `SPIKE_WINDOW_DAYS`, `SPIKE_RATIO`, `SPIKE_MIN_DAILY_UNITS`, `SPIKE_MAX_OTHERS_RATIO` | 3 days at 2.5× usual and at least 8 a day, while others stay under 1.5× | Which promotions run at one Store only? Those are real spikes the merchandiser already knows about. |
| Slow Mover | `SLOW_WINDOW_DAYS`, `SLOW_SHARE`, `SLOW_MIN_USUAL_DAILY_UNITS`, `SLOW_MIN_ON_HAND`, `SLOW_MIN_DAYS_OF_COVER` | 7 days under 10% of a usual rate of at least 2.5 a day, with 20+ on hand and 60+ days of cover | Which SKUs are seasonal? A Slow Mover in January may be a Christmas line. |

How to calibrate:

1. **Backtest.** Load 8 to 12 weeks of the Client's history through the new Data Source with the
   offline scripted model (no model cost), and list every Anomaly detection flags each day.
   Detection is plain statistics (ADR 0003), so the same history always gives the same flags.
2. **Review with the people who would act.** Show the inventory planner the stockout risks and the
   regional manager the Sales Drops. Mark each flag as useful, already known, or noise, and ask
   what they wish had been flagged.
3. **Tune one constant at a time** until noise is rare and nothing useful is missed. Prefer
   missing a small Anomaly over flooding the Analyst: every flag costs a model call and someone's
   attention.
4. **Lock it in.** Turn the marked-up backtest into Golden Scenarios on real (anonymised) data, so
   evals catch a change that breaks it.

Keep Sales Drops and Sales Spikes judged against the other Sales Channels (ADR 0010). If the Client
has fewer than three Sales Channels, that rule turns both kinds off; decide with them whether
comparing against the same weeks last year is an acceptable substitute.

## 5. Agree the Auto-approval Limit

The Auto-approval Limit is the spending threshold under which a Reorder is approved by rule
without a person. It is `DEFAULT_AUTO_APPROVAL_LIMIT` in `retail_ops_agent/action_policy.py`
($150 at Cobalt Home) and the `auto_approval_limit` argument of `OpsDay`.

- **Start at 0.** For the first week every Reorder waits in the Approval Queue, so the inventory
  planner sees every recommendation and its cost.
- **Then set it from what they approve.** After a week or two, look at the Approval Queue: the
  Reorders the planner approved without changes and the ones they rejected. A limit just below the
  cost of the cheapest rejected Reorder, and no higher than the planner is comfortable with, is a
  good first value. It is the planner's decision, not the engineer's.
- **Revisit it monthly**, with the rejected and Expired Reorders in front of them.

The rules around it stay fixed whatever the limit is: Tiers are set by the rule table and never by
the model (ADR 0002); at most one pending Reorder per SKU and Sales Channel; a pending Reorder
Expires after 48 simulated hours (`approval_queue.EXPIRY`). If the planner works on a weekly cycle,
lengthen the Expiry to match it rather than letting Reorders Expire over a weekend.

## 6. Rebuild the baseline from real timings

Hours Saved is the count of each kind of Audit Log entry that still stands, times the baseline's
minutes for that task. Cobalt Home's baseline
([`docs/discovery/baseline.md`](discovery/baseline.md),
[`baseline.json`](../src/retail_ops_agent/baseline.json)) is all assumptions, labelled as such. At
a real Client, replace it with measurements.

1. **Time the tasks on day 1.** Shadow the BI analyst fixing a small Defect and chasing an
   unfixable Upload, an analyst investigating an Anomaly, and the inventory planner keying in a
   Reorder. Time at least three of each, ideally five, and note what made the slow ones slow.
2. **Ask how often.** From the analyst's chat history or the ERP's purchase orders, count how
   often each task happens in a normal week.
3. **Write `baseline.json`.** One task per Audit Log Action (`safe_fix`, `quarantine`, `alert`,
   `reorder`). Use the median minutes, set `basis` to `source` and name in `source` who was timed,
   when and how many times (keep `assumption` for any task you could not time, and say why in
   `reasoning`). The loader refuses a `source` timing that does not name its source, and a second
   task for the same Action. Set `simulated` to false and rewrite `label`.
4. **Pass it to `OpsDay`** as `baseline=load_baseline(path)`. The dashboard shows each task's
   minutes, basis and source next to Hours Saved, so leadership can question the figure.
5. **Re-time after a month.** Some of the work does not disappear: the planner still spends a
   minute or two on each Approval. Subtract it, as Cobalt Home's `key-in-reorder` already does.

Leave out work the Audit Log cannot count (see "What is left out" in the baseline). An Hours Saved
figure that is smaller and can be defended is worth more than a large one that cannot.

## 7. Before going live

- [ ] Golden Scenarios built from the Client's real (anonymised) Uploads, with their real Defects,
      pass with the model they will run on. `make evals` reports the hard rule as held.
- [ ] The prompt-injection Scenarios pass. Every free-text column in the Client's formats (product
      descriptions, order notes) is listed in `upload_formats.FREE_TEXT_COLUMNS`, so it only ever
      reaches a model as quoted data and is never loaded into the BI data.
- [ ] Model choice agreed: free-tier models are fine for a pilot; a Client running this every day
      will want a paid or self-hosted model under its own data agreement. Compare them with
      `make evals ARGS="--model ..."`.
- [ ] The BI store is a DuckDB file that is backed up, not `:memory:`.
- [ ] n8n's schedule matches when the last Upload of the day usually arrives.
- [ ] Every person who receives messages knows what they are and who to ask about them.
