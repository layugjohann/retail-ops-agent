# 03: CI runs the Gate on every push and Pull Request

Status: ready-for-agent
Blocked by: 02

**What to build:** A GitHub Actions workflow that runs the same checks as the Sandcastle Gate (`uv sync`,
`make check`) on every push to `main` and every Pull Request. Today, work committed outside a Run (Issue 23's pacing
and 503 retries, `d67a5b9`, the README PRs, merges of stacked PRs) never passes the Gate.

- [ ] `.github/workflows/check.yml` installs uv (`astral-sh/setup-uv`) and Python 3.13, then runs `uv sync` and
      `make check`.
- [ ] No model key or secret is needed. Evals stay out of CI, as they're already out of `make check`.
- [ ] The workflow passes on a Pull Request.
- [ ] Blocked by 02 so CI doesn't take about 6.5 min per push.
