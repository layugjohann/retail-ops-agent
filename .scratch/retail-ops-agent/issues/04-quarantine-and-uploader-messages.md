# 04: Quarantine and Uploader messages

**What to build:** Defects without a Safe Fix put the Upload into Quarantine, keeping it out of the BI data entirely, and Intake writes the Uploader a plain-language message (through the Notifier) saying what is wrong, where, and what to do. The Upload status view shows Quarantine.

**Blocked by:** 03
**Stacked on:** issue/03-safe-fixes-and-audit-log

**Status:** awaiting-merge
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/4

- [ ] Planted unfixable Defects (missing column, ambiguous swapped columns, duplicate day in one file, impossible quantity, unknown SKU, date mismatch) each lead to Quarantine
- [ ] None of a Quarantined Upload's rows appear in the BI data
- [ ] A clean Upload is never Quarantined
- [ ] The Notifier interface exists with a log implementation; the Uploader message is part of the Ops Day outcome and visible on the dashboard
- [ ] The message names the Defect, its location, and the fix to make
- [ ] Quarantine is a Tier 1 Action in the Audit Log and can be undone

## Comments

Usage: Implementer 64 input, 49,799 output, 125,521 cache creation, 3,110,319 cache read; Review Session 16 input, 5,823 output, 58,385 cache creation, 470,384 cache read.

**Review Session: Non-critical Findings**

- ops_day.run_ops_day: `if result.uploader_message:` is always true for a Quarantined Upload now that quarantine_message always builds a message, so the branch is dead code.
- Releasing a Quarantine for a header Defect (missing or swapped column) sets the Upload to 'accepted' while loading no rows. ADR 0008 documents this, but the Upload status view may mislead a BI analyst.
- Not checked: whether new domain concepts (UploaderMessage, the Quarantine Audit action, the release undo) need GLOSSARY.md entries in the same change.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-04-2026-11-18T07-07-36-745Z.log`).

Usage: Body writer 2 input, 1,875 output, 48,195 cache creation, 11,615 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/4

Stacked on Base Issue 03: this Pull Request targets `issue/03-safe-fixes-and-audit-log`, the branch of https://github.com/layugjohann/retail-ops-agent/pull/3. Merge that Pull Request first.
