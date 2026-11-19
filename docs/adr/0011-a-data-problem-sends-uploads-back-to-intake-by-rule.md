# A Data Problem sends Uploads back to Intake by rule, and takes no Action

An Investigation can end in the structured conclusion Data Problem instead of a recommended Action. The Anomaly came from Uploads that are wrong, not from the business. The Analyst names the kind of Upload, the days, and what is wrong. The Ops Day then decides by rule which Uploads go back to Intake. They are the current, loaded Uploads of that kind and those days from the Anomaly's own Sales Channel, within the history the Analyst can see. The model never names an Upload directly, so it cannot send back another Sales Channel's data or a day after the Anomaly.

Intake Quarantines each Upload sent back. Its rows leave the BI data, a Tier 1 Quarantine entry in the Audit Log links it to the Investigation, and its Uploader gets a message saying what is wrong and what to do. The Upload is recorded with a `units_in_cases` Defect. That is the one Defect kind validation passes on purpose, because every quantity still looks plausible. The Defect sits on the SKU's row, in the quantity column, when the Anomaly is about one SKU. Undoing the Quarantine releases the Upload as it was.

No business Action (alert or Reorder) is taken for an Anomaly that concludes Data Problem, even if the model also recommends one. The Ops agent is never asked. After Uploads leave the BI data, the day's remaining Anomalies are investigated only if detection still flags them without those Uploads.

## Consequences

The generator plants `units_in_cases` in a Store's sales Uploads. One SKU's quantity sold is its case pack times the units really sold, while its net sales stay right. The SKU is chosen so that three days in a row show as a sales spike. Its price a unit falls to a fraction of the usual, which is the evidence an Investigation can find. A real local price cut lowers the price a unit only by a discount, so the two can be told apart. The `data_problems` grader scores both directions: a planted Data Problem must be caught with no Action taken, and a Data Problem concluded where none was planted is a false alarm.
