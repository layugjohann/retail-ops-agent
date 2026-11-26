# 06: Coding standards: a Must rule for correctness, and a decision on the GLOSSARY rule

Status: awaiting-merge
Pull Request: https://github.com/layugjohann/retail-ops-agent/pull/31
Blocked by: None

**What to build:** Two edits to `.sandcastle/CODING_STANDARDS.md`. This Issue is `ready-for-human` because the second
edit is the owner's decision.

1. **Add a Must rule** so the Review Session fixes correctness bugs in the same pass, instead of logging them as
   Non-critical Findings that nobody acts on (see Issue 01):
   > Behaviour the change adds matches its own docstrings, comments, the Spec and the ADRs it touches.

   Under this rule, a Review Session would have fixed the `assert`-gated Safe Fix table, the hidden "Expired" warning,
   and the undo/status mismatches in Issues 10 and 14.

2. **Decide the GLOSSARY rule.** "A new domain concept is added to GLOSSARY.md in the same change that introduces it"
   was flagged in 10 of 22 reviews (Issues 03, 04, 05, 08, 10, 11, 13, 15, 20, 22). `GLOSSARY.md` hasn't changed
   since Issue 18. As things stand, the rule costs review tokens on every Run and changes nothing. Pick one:
   - [ ] Move it under `## Must`, so the Review Session adds the entry itself (costs tokens on most Issues).
   - [x] Delete it, and add glossary entries by hand with `/domain-modeling` when a term matters.

- [x] Both edits made, and this Issue's comments record which option was chosen.

## Comments

**Decision (2026-11-26): delete the GLOSSARY rule.** Flagged in 10 of 22 reviews and never acted on, so it only cost
review tokens. Naming a domain term is a judgement call, so glossary entries are now added by hand with
`/domain-modeling` when a term matters. The correctness rule is added as the last item under `## Must`.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/31
