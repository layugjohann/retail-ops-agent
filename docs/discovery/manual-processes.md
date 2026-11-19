# Current manual processes

> **SIMULATED.** Written as if observed at the fictional Client Cobalt Home. The steps are plausible for a retailer that runs BI on daily CSV uploads; they were not observed at a real company.

Each process names the baseline task it is timed under in [Baseline](baseline.md), and the Audit
Log Action that now does it.

## 1. Fixing a small Upload Defect

Baseline task: `fix-small-upload-defect`. Now: a Safe Fix by the Intake agent (`safe_fix`).

1. The BI analyst runs the morning import; one Upload fails or its totals look wrong.
2. They open the CSV and find the cause: a renamed header, stray spaces, a byte-order mark, a
   semicolon delimiter.
3. They correct it in a text editor or Excel, being careful not to change anything else.
4. They re-run the import for that Upload.
5. They compare the Sales Channel's totals with the day before to make sure the fix worked.

## 2. Chasing an Upload that cannot be fixed without asking

Baseline task: `chase-unfixable-upload`. Now: a Quarantine and an Uploader message (`quarantine`).

1. The BI analyst finds an Upload with a Defect they cannot fix without guessing: a missing
   column, the same day twice, an unknown SKU, an impossible quantity.
2. They work out which rows and columns are affected.
3. They hold the Upload out of the dashboards (by not loading it) and note it somewhere.
4. They message the store manager or e-commerce lead over chat, explaining what is wrong.
5. They answer follow-up questions; often the Uploader resends a file with a different problem.
6. When a corrected file arrives, they load it and make sure the earlier one is not counted too.

## 3. Investigating an Anomaly

Baseline task: `investigate-anomaly`. Now: an Investigation by the Analyst agent and an alert by
the Ops agent (`alert`).

1. Someone notices something odd in the dashboard, often days late: a SKU running low, a Store
   selling far less than usual, a sudden spike, stock that has stopped moving.
2. The BI analyst pulls the SKU's recent sales and stock for that Sales Channel.
3. They compare it with the same Sales Channel's history and with the other Sales Channels, to
   tell a local problem from a chain-wide one.
4. They check the ERP for the Lead Time and any open Reorders.
5. They decide whether it is a business event or bad data (for example a Store reporting in cases).
6. They write it up and send it to the inventory planner or store manager.

## 4. Placing a Reorder by hand

Baseline task: `key-in-reorder`. Now: a Reorder proposed by the Ops agent, decided by the inventory
planner (or under the Auto-approval Limit), and placed in the ERP (`reorder`).

1. The inventory planner works out Days of Cover from stock and recent sales.
2. They work out how many units cover the Lead Time, and round up to the Supplier's case pack.
3. They check nobody has already ordered it (the step that sometimes gets missed).
4. They look up the Supplier and unit cost, and key the Reorder into the ERP.

## 5. Totalling the Online Shop's Order Lines (not counted)

1. The e-commerce lead exports the day's Order Lines from the shop platform.
2. They filter out cancelled and refunded lines in a spreadsheet.
3. They total quantity and net sales per SKU, and reshape it into the Stores' format.
4. They rename the stock export's columns to match the Stores' format too.

The prototype now takes the raw exports as they are. This time is **not** in Hours Saved: no Audit
Log Action records it, and Hours Saved only counts what the Audit Log shows the prototype did.
