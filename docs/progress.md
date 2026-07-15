# Progress

Current phase: **Phase 0 — COMPLETE** (2026-07-15). Next: Phase 1.

## Phase 0 report

### Files created or changed

- `pyproject.toml` — package `psi-memory`, src layout, console scripts, pytest config
- `requirements/{base,dev,lock}.txt` — pinned dependencies (Python 3.11.9 venv in `.venv/`)
- `src/psi_memory/common/` — `logging.py` (console+JSONL), `seed.py` (derive_seed, seed_everything), `units.py` (cgroup scalar / "max" / byte-MiB handling)
- `src/psi_memory/collector/` — `parsers.py` (PSI, keyed counters), `cgroup_reader.py` (snapshot reader, fake-fs testable)
- `src/psi_memory/environment/` — `docker_cli.py`, `probe.py` (temp containers, exec reads, sidecar sampling, limit updates), `report.py`, `validate.py`
- `src/psi_memory/cli.py` — `psi-validate-env`, `psi-version-report`, `psi-smoke`
- placeholder subpackages: workloads, dataset, features, models, controller, evaluation, dashboard
- `configs/validate_env.example.yaml`, `scripts/run_tests.ps1`
- `tests/unit/` (6 files, 29 tests), `tests/integration/` (2 files + conftest, 7 tests)
- `README.md`, `docs/requirements_traceability.md`, `docs/decisions.md` (D1–D8), this file
- directory skeleton: `data/{raw,processed,splits}`, `artifacts/{models,metrics,plots,reports}`, `logs/`, `workloads/`, `docker/`

### Commands executed (key ones)

- Environment probes: `docker info`, temp alpine containers, sidecar cgroup reads, `docker update --memory`, `memory.high` write/restore
- `py -3.11 -m venv .venv`; `pip install -e .` + deps; `pip freeze > requirements/lock.txt`
- `pytest -m "not docker"` → **29 passed**
- `pytest -m docker` → **7 passed**
- `psi-validate-env` → **15/15 checks PASS**, report `artifacts/reports/env_validation_20260715-222315_4167fbed30ae.json`
- `psi-smoke` → PASS (3 sidecar samples); `psi-version-report` → OK

### Tests

36/36 passing (29 unit, 7 docker integration). Integration tests auto-skip
when the Docker daemon is down.

### Phase 0 completion criteria check

- Repo structure per spec ✔ · Python 3.11 package + venv + pins ✔
- logging / seeds / version-report / run-tests / smoke commands ✔
- `validate_env` with all required checks, text + JSON ✔
- **Gate: temp container started and `memory.current` + `memory.pressure`
  sampled reliably ✔** (5/5 sidecar samples, monotonic timestamps, gaps in
  tolerance — integration test + validator check)

### Remaining risks

1. PSI has only been observed at ~0 (idle containers); no workload has yet
   driven it up. Phase 1 calibration must demonstrate rising PSI under a
   tight-limit leak with swap — if not, diagnose per the spec's checklist.
2. Sidecar sampling validated at 5 samples / 1 Hz on one container; Phase 1
   needs a long-running multi-container collector with atomic writes and
   drift-free scheduling (helper `probe.wait_monotonic` exists, unused yet).
3. VM is 7.4 GiB RAM / 2 GiB swap — workload limits must be sized so pressure
   happens inside container limits, not VM-wide.
4. OneDrive + non-ASCII path: venv and data live under a synced folder; if
   sync interferes with data collection, move `data/` output elsewhere (D4).

### Exact next step (Phase 1)

Implement the containerized workloads (steady, leak, file-burst, bursty,
trace-replay skeleton) + the sidecar collector writing per-run CSVs with
metadata (run ID, seed, params, validation_id), then the Rich dashboard, then
calibration runs demonstrating the expected PSI signatures.
