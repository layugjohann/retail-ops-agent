# 07: Eval harness and Intake evals

**What to build:** Golden scenarios that drive the Ops Day boundary with real models and score the outcome against the generator's ground truth. This ticket builds the harness and the Intake graders. Same shape as fixline's evals: tag filtering, a model option, a judge option, and a scorecard file.

**Blocked by:** 04, 06

**Status:** ready-for-agent

- [ ] Scenario format: id, tags, seed, day range, planted items, expected outcomes
- [ ] Deterministic Intake graders: Defect precision and recall, Safe Fix correctness, no Quarantine of clean Uploads
- [ ] LLM judge grades Uploader messages against a written rubric, one pass/fail per criterion
- [ ] Runner options: filter by tag or scenario; choose model and judge model; skip the judge; output directory. It writes a machine-readable scorecard and prints a table
- [ ] Throttling keeps runs inside free-tier rate limits
- [ ] The harness itself is tested end to end with a scripted model (no keys needed)
- [ ] Starter scenarios cover every Defect kind from tickets 03–04 and a resubmission

## Comments
