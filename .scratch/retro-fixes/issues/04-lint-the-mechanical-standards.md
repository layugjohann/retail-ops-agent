# 04: Lint the mechanical coding standards

Status: ready-for-agent
Blocked by: None

**What to build:** Turn the coding standards that are fixed patterns into checks in `make check`, so only a Review
Session's judgement calls are left to the Review Session.

- [ ] **Banned calls and imports** with ruff `flake8-tidy-imports` (`"TID"` in `select`, rules under
      `[tool.ruff.lint.flake8-tidy-imports.banned-api]`):
  - `datetime.datetime.now`, `datetime.date.today` and `time.time` behind the Ops Day boundary ("Times come from the
    injected clock"). `clock.py` is allowed. Any other existing legitimate call site gets a per-file ignore with a
    comment saying why.
  - `langgraph` anywhere (ADR 0004).
  - `retail_ops_agent.erp_server` imported anywhere but itself and tests (ADR 0006). `erp_mcp.py` imports the
    result-wrapper models from it today (Issue 08 Finding): move those models into `erp.py` or a shared module first.
- [ ] **Dead code**: `vulture` as a dev dependency, run from a new `deadcode` target in `make check`, with a small
      whitelist file for false positives (Pydantic fields, Streamlit callbacks, pytest fixtures). Delete any dead code
      it finds on `main`.
- [ ] The ruff `banned-api` messages name the standard or ADR, so an Implementer who hits one knows the reason.
- [ ] `.sandcastle/CODING_STANDARDS.md`: each rule now enforced by a check ends with "(enforced by ruff TID)" or
      similar, so a Review Session doesn't spend tokens on it.
