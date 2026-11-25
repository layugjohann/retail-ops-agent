# 06: Coding standards: a Must rule for correctness, and a decision on the GLOSSARY rule

Status: ready-for-human
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
   - [ ] Delete it, and add glossary entries by hand with `/domain-modeling` when a term matters.

- [ ] Both edits made, and this Issue's comments record which option was chosen.
