# Retail Ops Automation

A prototype of a forward-deployed engagement: turning a retailer's daily data uploads into validated BI data, and turning that data into investigated, tiered actions that save the Client's teams measurable hours.

## Language

### Engagement

**Client**:
The fictional retailer this prototype is deployed at (currently Cobalt Home, a home and lifestyle goods retailer), modelled on the kind of retail and e-commerce business in the target job posting.
_Avoid_: Customer, company, user

**Deployment Playbook**:
The written plan for adapting this prototype to a real retailer's systems in the first week of an engagement.
_Avoid_: Setup guide, integration guide

**Visitor**:
Anyone trying the public demo; each Visitor gets their own sandboxed copy of the Client for one session.
_Avoid_: Guest, demo user, user

**Replay Mode**:
The default public demo, which steps through recorded Ops Days with no model and no key.
_Avoid_: Demo mode, playback, recording

**Live Mode**:
The public demo in which a Visitor runs Ops Days against real models in their own sandbox.
_Avoid_: Sandbox mode, interactive mode

### Data

**Sales Channel**:
Somewhere the Client sells, either a Store or the Online Shop; sales and inventory are always reported per Sales Channel.
_Avoid_: Location, outlet, channel (unqualified)

**Store**:
One physical shop of the Client.
_Avoid_: Branch, location, outlet

**Online Shop**:
The Client's e-commerce site, a Sales Channel whose Uploads come in a different format from the Stores'.
_Avoid_: Webstore, e-shop, website

**SKU**:
One sellable product variant in the Client's catalog.
_Avoid_: Product, item, article

**Upload**:
One CSV file a Client team submits for one Sales Channel and one day, either sales or inventory.
_Avoid_: File, import, data drop

**Order Line**:
One line of the Online Shop's sales Upload: one SKU within one order, with its quantity, line total and a status of paid, cancelled or refunded. Only paid Order Lines count as sales.
_Avoid_: Transaction, order row

**Stock Snapshot**:
The Online Shop's inventory Upload: units available per SKU at a snapshot time, under the Online Shop's own column headers.
_Avoid_: Stock export, stock dump

**Lead Time**:
The number of days between ordering a SKU from its Supplier and the stock arriving at the Sales Channel.
_Avoid_: Delivery time, turnaround

**Restock**:
Stock of one SKU arriving at one Sales Channel from its Supplier, one Lead Time after it was ordered; a Reorder becomes a Restock when it arrives.
_Avoid_: Delivery, replenishment

**Uploader**:
The Client staff member who submitted an Upload and is told about its Defects.
_Avoid_: User, submitter, sender

**Defect**:
Something wrong with an Upload itself (a missing column, a duplicate day, an impossible quantity, an unknown SKU), as opposed to something unusual in the business.
_Avoid_: Error, bad data, validation issue

**Safe Fix**:
A correction to a Defect that can be made without guessing at the Uploader's intent, and is recorded so it can be undone.
_Avoid_: Auto-fix, cleanup, repair

**Quarantine**:
The state of an Upload held back from the BI data because it has Defects that have no Safe Fix.
_Avoid_: Rejected, failed, blocked

**Superseded**:
The state of an Upload that a later Upload for the same Sales Channel, day and kind has replaced.
_Avoid_: Overwritten, replaced, stale

**Ground Truth**:
The generator's record of every Defect it planted in an Upload: which Upload, the Defect's kind, the row and column it is in, and the expected outcome. Tests and evals score Intake against it.
_Avoid_: Answer key, labels, expected results

### Operations

**Ops Day**:
One simulated business day processed end to end: that day's Uploads go through validation, loading, Anomaly detection, Investigation and Actions.
_Avoid_: Run, batch, job, daily run

**Anomaly**:
A statistically unusual pattern in valid data that may mean a business problem, such as a stockout risk or a sales drop at one Store.
_Avoid_: Alert, outlier, issue

**Investigation**:
The look into an Anomaly that ends in an explanation of its likely cause and a recommended Action.
_Avoid_: Analysis, diagnosis, report

**Data Problem**:
The conclusion of an Investigation that an Anomaly was caused by a Defect that validation missed, not by a business event.
_Avoid_: False alarm, false positive, bad data

**Action**:
Something done in response to a Defect or an Anomaly, such as posting an alert, opening a task, or placing a Reorder.
_Avoid_: Task, step, operation

**Action Tier**:
The level of an Action, set by fixed rules rather than by the model's confidence, that decides whether it runs on its own or needs Approval: Tier 0 reads, Tier 1 is internal and reversible, Tier 2 is external or costly.
_Avoid_: Risk level, permission level, autonomy level

**Approval**:
A human's yes or no on a Tier 2 Action before it runs.
_Avoid_: Sign-off, review, confirmation

**Approval Queue**:
The list of Tier 2 Actions waiting for Approval; at most one pending Reorder per SKU and Sales Channel, and a pending Action Expires if no one decides in time.
_Avoid_: Inbox, review queue, pending list

**Expired**:
The state of a Tier 2 Action that waited in the Approval Queue too long without a decision and will never run.
_Avoid_: Timed out, cancelled, lapsed

**Auto-approval Limit**:
The spending threshold under which a Reorder counts as approved without a human.
_Avoid_: Budget, cap, threshold

**Supplier**:
An outside company the Client buys SKUs from, and the recipient of Reorders.
_Avoid_: Vendor, distributor, seller

**Reorder**:
A purchase order sent to a supplier through the ERP to restock a SKU for one Sales Channel.
_Avoid_: Purchase order (in prose), restock request, PO

**Hours Saved**:
The estimated staff time the prototype saved, computed from the Audit Log and the documented manual time for each kind of task.
_Avoid_: Time saved, ROI, efficiency

**Audit Log**:
The permanent record of every Action taken, who or what took it, and how to undo it.
_Avoid_: History, activity log, trail

### Evals

**Golden Scenario**:
One seeded eval case: its tags, seed, day range, which Sales Channels send which Uploads, the Defects and resubmissions planted in them, and the outcome expected for each Upload. The eval harness drives it through the Ops Day boundary and grades the result against the Ground Truth.
_Avoid_: Test case, fixture, example

**Scorecard**:
The machine-readable record of one eval run: the models used, each Golden Scenario's grader results and judge verdicts, and the totals.
_Avoid_: Report, results file, leaderboard

**Rubric**:
The written criteria an LLM judge grades free text against, giving one pass or fail per criterion.
_Avoid_: Checklist, guidelines, score sheet
