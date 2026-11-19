# Personas

> **SIMULATED.** Composite people invented for the fictional Client Cobalt Home. They are not based on interviews with real staff.

## Store manager (Uploader)

- **Who:** runs one of the 6 Stores. Exports the till's daily sales and the stock count from the
  back office every evening and uploads both CSVs.
- **Today:** uploads at closing time, often in a hurry. Sometimes renames a column in Excel, saves
  with semicolons, or reports a delivery in cases instead of units. Hears about a problem a day
  later, over chat, from the BI analyst, and has to dig the file out again.
- **Wants:** to upload in the format they already have, and if something is wrong, to be told once,
  plainly, what to change.
- **Does not want:** a new tool to learn or a form to fill in.

## Inventory planner

- **Who:** keeps every Sales Channel in stock. Owns Reorders to Suppliers in the ERP.
- **Today:** checks stock in the dashboard when there is time, works out Days of Cover in a
  spreadsheet, and keys Reorders into the ERP by hand. Has twice reordered the same SKU because a
  store manager raised it too.
- **Wants:** stockout risks raised before shelves are empty, with a suggested quantity, Supplier and
  cost, and the final yes or no on anything that costs money.
- **Does not want:** the system ordering on its own above an agreed limit.

## BI analyst

- **Who:** keeps the BI data and dashboards trustworthy. The first person to see every Upload.
- **Today:** spends the start of every day opening CSVs, fixing headers and delimiters, and chasing
  Uploaders whose files cannot be fixed without asking. When a number looks odd, spends most of an
  hour working out whether it is the business or the data.
- **Wants:** clean Uploads to load themselves, bad ones held back with a clear reason, and every
  automatic fix recorded so it can be reversed.
- **Does not want:** an automated fix that guesses.

## E-commerce lead (Uploader)

- **Who:** runs the Online Shop. Its sales export is Order Lines, including cancelled and refunded
  ones; its stock export has its own column headers.
- **Today:** totals the Order Lines into daily sales by SKU in a spreadsheet, leaving out cancelled
  and refunded lines, and renames the stock export's columns to match the Stores' format before
  uploading both.
- **Wants:** to upload the raw exports as they come out of the shop platform.
- **Does not want:** Online Shop sales overstated by cancelled or refunded orders.
