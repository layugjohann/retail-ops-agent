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

## Comments

**Implementer:** Full-suite wall time (`/usr/bin/time -p uv run pytest`, 8 cores, 401 tests both times):

| | wall | CPU (user) |
|---|---|---|
| Before (`295d5b6`) | 355 s | 327 s |
| After (`-n auto`) | 61 s | 310 s |

Other Sandcastle sessions were running on this Mac at the same time; the load average went from 3 to 35 during
these runs. An earlier "before" run under heavy load took 412 s, and "after" runs under load took 100 to 115 s
before the insert fix below. Both runs in the table were taken back to back while the load was low (about 3).

xdist alone brought the suite to about 105 s. CPU is the limit, so it also took less work:

- The seeded Live Mode sandbox is built once per xdist worker (`seeded_live_sandbox`, session-scoped) and each test
  gets a `deepcopy` (`live_sandbox`). The dashboard tests patch `live.new_live_sandbox` to return a copy, so each
  Visitor, and each reset, gets its own. `Sandbox`, `BiStore` (copies every table into a new in-memory DuckDB) and
  `InMemoryErp` (new lock) define `__deepcopy__`. A copy takes about 0.2 s; seeding takes about 5 s.
  `test_each_visitors_sandbox_is_isolated` and `test_a_live_sandbox_writes_nothing_to_disk` still build their
  own sandboxes, since building one is what they test.
- `BiStore._insert` was the biggest hotspot across the suite (65 s of a serial profile): about 12 ms per Upload
  for the multi-row `INSERT ... VALUES`. It now inserts from a DataFrame (`from_df(...).insert_into`), at about
  1 ms. The stored values are the same.
- The eval runner passes its generated Uploads to `build_sandbox` (new `generated` parameter) instead of
  generating each Golden Scenario twice, and `_season_factor` is memoised. Alone, the two end-to-end eval tests
  dropped from 28 s and 22 s to 21 s and 15 s.

No test broke when run in parallel. Each test writes under `tmp_path`, and every port and cache is per process.
Six parallel runs all passed. `make` can't run inside the sandbox (the Xcode `make` shim is blocked), so I ran
its four commands (ruff check, ruff format --check, pyright, pytest) directly, and all passed.
