# Sales drops and spikes are judged against the other Sales Channels, and only a stockout risk can lead to a Reorder

A sales drop or a sales spike at one Sales Channel is flagged only when it stands out from the Sales Channel's own usual rate *and* from how the other Sales Channels moved over the same days. A dip or a promotion that the whole chain shares (a Lookalike) is never blamed on one Sales Channel. The cost is that a drop or spike cannot be flagged when fewer than two other Sales Channels sent sales for those days. A Sales Channel missing its Uploads therefore turns this detection off for the others, rather than making every Sales Channel look local.

A spike that already threatens stock is flagged as the stockout risk it causes, not also as a spike. Otherwise one demand surge would produce two Investigations and possibly two Actions.

The Action policy, not the model, decides which Anomaly kinds can lead to a Reorder. Only a stockout risk can. A sales drop is about a whole Sales Channel, not one SKU. A spike that leaves plenty of stock needs no Reorder, and one that does not is a stockout risk. Reordering a slow mover would only add to the stock that is not selling. A Reorder proposed for any other kind is posted as a Tier 1 alert instead. Alerts go to a recipient fixed by kind: the inventory planner for stockout risks and slow movers, the regional manager for sales drops, and the merchandiser for sales spikes.

## Consequences

The detection thresholds (`DROP_SHARE`, `SPIKE_RATIO`, `SLOW_SHARE` and so on in `anomalies.py`) are tuned so that seeded clean data flags none of the three new kinds across seasons. They are among the values the Deployment Playbook says to calibrate against a real retailer's data. The generator refuses to plant a local price cut when no SKU is stocked well enough for the spike to stay clear of a stockout risk. That happens in the December peak season, when stock runs low across the chain.
