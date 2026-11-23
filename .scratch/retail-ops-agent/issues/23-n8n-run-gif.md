# 23: Run n8n locally and record the GIF (human)

**What to build:** A human step: run the n8n workflow locally, confirm it works, and record a GIF for the README.

**Blocked by:** 22

**Status:** ready-for-human
**Pull Request:** https://github.com/layugjohann/retail-ops-agent/pull/21

- [x] Workflow imported and running locally in Docker
- [ ] A scheduled Ops Day runs and forwards notifications
- [x] GIF recorded and added to the README

## Comments

**Session 2026-11-21: paused before recording**

- Groq's free tier hit its daily token limit (TPD 150,000), so the trigger was switched to Gemini by unsetting `GROQ_API_KEY`.
- Gemini then answered 429 on its per-minute limit (15 requests a minute): the trigger did not pace model calls. Fixed on branch `issue/23-n8n-run-gif` (uncommitted): `paced_models_from_environment` in `models.py`, shared with `make record`; trigger `--rpm` (default 10). Also: `make n8n` waits for n8n before importing; n8n pinned to 2.48.7; README notes the pacing. `make check` passed (392 tests).
- Verified end to end on port 8766 with `n8n execute`: with `--seeded-days 5` the first run is 2026-11-06 (ST03 sales Quarantined, one Uploader message forwarded to /inbox), about 2m50s, status success.
- The user's own run in the n8n editor then failed with Gemini's 503 "high demand", an overload on Google's side rather than our rate limit. `ThrottledModel` retries only 429s, so a 503 fails the Ops Day at once. Retry first. If 503s keep happening, consider having `ThrottledModel` also retry 503s with backoff.
- Still open: the scheduled run (Active, Every evening hour), the GIF, the README image, committing and opening the Pull Request.

**Session 2026-11-23: GIF recorded**

- Gemini still answered 503 "high demand", so `ThrottledModel` now retries 503s as well as 429s (`evals/throttle.py`, with a test). Back on Groq (gpt-oss-120b), whose daily limit had reset; an end-to-end run through `n8n execute` succeeded in about 2m50s.
- The GIF is `docs/media/n8n-ops-day.gif` (534 KB, 10× speed), cropped to leave out the shell prompt, browser profile and tab titles. It is in the README under "Scheduled Ops Days with n8n".
- Not yet verified: a run started by the schedule itself (the workflow Active, the "Every evening" node firing at its hour).
