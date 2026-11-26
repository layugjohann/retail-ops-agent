# 09: `make dashboard` does not load `.env.local`

Status: needs-triage
Blocked by: None
Source: retail-ops-agent Issue 01 (Review Session Non-critical Finding), triaged in Issue 07

**Where it is now (on `main` at `cfaa54f`):** `Makefile:25`; `dashboard/app.py:95`, `:124`

The `evals`, `record` and `trigger` targets pass `--env-file .env.local`, but `dashboard` does not. `dashboard/app.py` reads keys from `os.environ`, and the README tells users to put keys in `.env.local`, so a key there has no effect on Live Mode run locally.

- [ ] Add `--env-file .env.local` to the `dashboard` target (it must not fail when the file is missing), or say in the README that the keys must be exported.
