# 02: Make the test suite fast again

Status: ready-for-agent
Blocked by: None

**What to build:** Cut the wall time of `uv run pytest`. It grew from 22 s (Gate at Issue 01) to about 6.5 min
(Issue 17), and Implementers and Review Sessions run it many times per Issue.

Measured on `main` (`pytest --durations=25`):
- Each `tests/test_dashboard.py` test spends about 4.5 s seeding a sandbox. Each `tests/test_live_mode.py` fixture
  spends about 4.3 s in setup.
- `test_evals.py::test_every_starter_scenario_passes_...` takes 24 s, and
  `test_action_evals.py::test_every_action_scenario_passes_...` takes 18 s.

- [ ] `pytest-xdist` is a dev dependency (`uv add --dev`), and `-n auto` is in `[tool.pytest.ini_options] addopts`.
      Any test that breaks when run in parallel (shared files, ports, global state) is fixed, not excluded.
- [ ] The seeded sandbox the dashboard and Live Mode tests need is built once per session (or per xdist worker) and
      each test gets an independent copy, so no test sees another test's changes.
- [ ] Record the full-suite wall time before and after in a comment on this Issue. Target: under 90 s on this Mac.
- [ ] `make check` still passes, and the test count is unchanged.
