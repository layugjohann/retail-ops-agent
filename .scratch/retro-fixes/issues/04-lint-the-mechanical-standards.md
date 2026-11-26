# 04: Lint the mechanical coding standards

Status: done
Pull Request: https://github.com/layugjohann/retail-ops-agent/pull/29
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

## Comments

Usage: Implementer 62 input, 13,002 output, 48,622 cache creation, 1,375,732 cache read; Review Session 12 input, 3,863 output, 22,858 cache creation, 168,422 cache read.

**Review Session: Non-critical Findings**

- The per-file ignores for `clock.py` and `evals/runner.py` turn off the whole TID251 code, so those files are also exempt from the LangGraph and `erp_server` bans, not just the clock ban. An inline `# noqa: TID251` with a reason on the single `datetime.now` call in each file would keep the other bans in force there.
- `tests/ruff.toml` has to repeat the time and LangGraph ban entries, because a nested config replaces the banned-api table rather than merging with it. A new ban added to `pyproject.toml` won't apply to the tests unless someone copies it here too. The comment in `pyproject.toml` mentions this, but it's an easy step to miss.
- No test currently imports `retail_ops_agent.erp_server` (the contract suite reaches it through the separate process `McpErpClient` launches), so dropping that ban for the tests isn't used yet. It matches the Issue's 'itself and tests' wording, so it's harmless.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-04-2026-11-25T15-40-17-604Z.log`).

Usage: Body writer 2 input, 1,134 output, 16,692 cache creation, 11,837 cache read.

**Pull Request opened**: https://github.com/layugjohann/retail-ops-agent/pull/29
