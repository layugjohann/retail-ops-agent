# 14: Data Problem loop

**What to build:** An Upload reported in cases instead of units passes validation and produces a sales spike. The Analyst concludes Data Problem, the Upload goes back to Intake, which Quarantines it and messages the Uploader. Shows the agents catching each other's misses.

**Blocked by:** 04, 13

**Status:** ready-for-agent

- [ ] The generator can plant a cases-instead-of-units Upload that passes validation
- [ ] Data Problem is a structured conclusion an Investigation can reach
- [ ] A Data Problem conclusion Quarantines the Upload, removes its data from the BI data, and messages the Uploader
- [ ] No business Action (alert or Reorder) is taken for an Anomaly that turned out to be a Data Problem
- [ ] Eval scenarios with the `data-problem` tag are added

## Comments
