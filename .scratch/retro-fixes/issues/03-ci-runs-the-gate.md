# 03: CI runs the Gate on every push and Pull Request

Status: in-progress
Blocked by: 02
Stacked on: issue/02-faster-test-suite

**What to build:** A GitHub Actions workflow that runs the same checks as the Sandcastle Gate (`uv sync`,
`make check`) on every push to `main` and every Pull Request. Today, work committed outside a Run (Issue 23's pacing
and 503 retries, `d67a5b9`, the README PRs, merges of stacked PRs) never passes the Gate.

- [ ] `.github/workflows/check.yml` installs uv (`astral-sh/setup-uv`) and Python 3.13, then runs `uv sync` and
      `make check`.
- [ ] No model key or secret is needed. Evals stay out of CI, as they're already out of `make check`.
- [ ] The workflow passes on a Pull Request.
- [ ] Blocked by 02 so CI doesn't take about 6.5 min per push.

## Comments

Usage: Implementer 14 input, 1,752 output, 15,683 cache creation, 164,067 cache read; Review Session 8 input, 2,364 output, 14,588 cache creation, 84,228 cache read.

**Review Session: Non-critical Findings**

- Unverified: the Issue requires the workflow to pass on a Pull Request, but it hasn't run on GitHub yet. Only the Gate commands were run locally: uv sync passed, and the four make check targets passed when run one by one (make itself is blocked by the macOS sandbox here). Open a PR to confirm it passes.
- `cancel-in-progress: true` applies to pushes to main as well as PRs, so two quick pushes to main cancel the first commit's run and it never gets a result. Suggest `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`.
- `uv sync` without `--locked` quietly updates uv.lock in CI when it's out of date with pyproject.toml, so CI can pass on a stale lock file. `uv sync --locked` would fail instead, though the plain command matches the Gate exactly.

**Gate passed**: every command exited 0 (log: `.sandcastle/logs/gate-03-2026-11-25T15-09-33-127Z.log`).

Usage: Body writer 2 input, 1,047 output, 10,466 cache creation, 11,837 cache read.
