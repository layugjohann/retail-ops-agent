# 07: Eval harness and Intake evals

**What to build:** Golden scenarios that drive the Ops Day boundary with real models and score the outcome against the generator's ground truth. This ticket builds the harness and the Intake graders. Same shape as fixline's evals: tag filtering, a model option, a judge option, and a scorecard file.

**Blocked by:** 04, 06

**Status:** done
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/6

- [ ] Scenario format: id, tags, seed, day range, planted items, expected outcomes
- [ ] Deterministic Intake graders: Defect precision and recall, Safe Fix correctness, no Quarantine of clean Uploads
- [ ] LLM judge grades Uploader messages against a written rubric, one pass/fail per criterion
- [ ] Runner options: filter by tag or scenario; choose model and judge model; skip the judge; output directory. It writes a machine-readable scorecard and prints a table
- [ ] Throttling keeps runs inside free-tier rate limits
- [ ] The harness itself is tested end to end with a scripted model (no keys needed)
- [ ] Starter scenarios cover every Defect kind from tickets 03–04 and a resubmission

## Comments

Usage: Implementer 72 input, 54,337 output, 133,195 cache creation, 3,732,752 cache read; Review Session 8 input, 3,388 output, 62,748 cache creation, 225,072 cache read.

**Review Session: Non-critical Findings**

- runner.run_scenario takes a `generated: GeneratedUploads` parameter it never uses; build_sandbox regenerates the Uploads itself. Remove the parameter (Preset: no unused parameters).
- ExpectedUpload.defect_kinds is never read by any grader. Graders use the generator's Ground Truth, and the field is only cross-checked in tests/test_evals.py. It is redundant data that can drift; either grade against it or drop it.
- ThrottledModel only overrides `request`. `request_stream` (and `count_tokens`) on the wrapped model would skip pacing and 429 retries. Intake and the judge don't stream today, but a future streaming agent would quietly lose throttling.
- build_sandbox's `sales_channels` filter silently ignores codes not in the catalog. A Scenario with a mistyped Sales Channel only fails later as 'never processed' findings instead of a clear validation error when the Scenario is loaded.
- Scorecard filenames have one-second resolution (`scorecard-%Y%m%dT%H%M%S.json`), so two runs started in the same second into the same output directory overwrite each other's Scorecard and Upload directory.
- Glossary _Avoid_ word 'file' is used in evals/README.md and code docstrings ('Scenario JSON files', 'One JSON file'). It describes Scenario definitions rather than Uploads, so it is arguably fine, but a reword would keep naming consistent.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-07-2026-11-18T17-19-14-641Z.log`).

Usage: Body writer 2 input, 1,418 output, 58,752 cache creation, 11,615 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/6
