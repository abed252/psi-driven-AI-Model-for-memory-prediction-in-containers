# Requirements Traceability

Maps every proposal / execution-spec requirement to implementation, tests, and outputs.
Status values: ✅ done · 🔶 partial · ⬜ planned (phase in parentheses).

| # | Requirement (proposal / spec) | Implementation | Tests | Outputs | Status |
|---|---|---|---|---|---|
| 1 | Data collection from container cgroup v2 files | Access paths validated; parsers + snapshot reader: `src/psi_memory/collector/parsers.py`, `cgroup_reader.py`; probe sampling: `src/psi_memory/environment/probe.py`. Full batch collector ⬜ (P1) | `tests/unit/test_psi_parser.py`, `test_cgroup_reader.py`, `tests/integration/test_container_sampling.py` | validation report JSON | 🔶 P0 part done |
| 2 | Per-container PSI and memory metrics | Verified inside-container + sidecar reads of `memory.current/max/high/pressure/events/stat/swap.*` | `test_container_sampling.py::test_exec_read_inside_container`, `::test_sidecar_sampling_reliable` | `artifacts/reports/env_validation_*.json` | ✅ |
| 3 | Environment validation and live monitoring | Validator: `src/psi_memory/environment/validate.py` (+`report.py`, CLI `psi-validate-env`). Live dashboard ⬜ (P1) | `tests/integration/test_validate_env_e2e.py`, `tests/unit/test_report.py` | text + JSON reports, `validation_id` | 🔶 validator ✅, dashboard ⬜ |
| 4 | Synthetic workloads (steady, leak, file-burst, bursty, trace-replay) | ⬜ (P1) `src/psi_memory/workloads/`, `workloads/`, `docker/` | ⬜ | ⬜ | ⬜ P1 |
| 5 | Sliding-window dataset construction | ⬜ (P2) `src/psi_memory/dataset/` | ⬜ | ⬜ | ⬜ P2 |
| 6 | Future-peak labels, configurable 30–60 s horizon, no current-sample leakage | ⬜ (P2); byte-unit exactness already in `common/units.py` | `test_units.py` now; label-indexing tests ⬜ | ⬜ | ⬜ P2 |
| 7 | Persistence baseline | ⬜ (P2) | ⬜ | ⬜ | ⬜ P2 |
| 8 | Autopilot-style percentile heuristic | ⬜ (P2) | ⬜ | ⬜ | ⬜ P2 |
| 9 | Random Forest + XGBoost | ⬜ (P2) | ⬜ | ⬜ | ⬜ P2 |
| 10 | LSTM | ⬜ (P3) | ⬜ | ⬜ | ⬜ P3 |
| 11 | With/without-PSI ablation at every rung | ⬜ (P2/P3); feature-schema parity requirement recorded | ⬜ | ⬜ | ⬜ |
| 12 | Run-level train/val/test splits, split manifests | ⬜ (P2) | ⬜ leakage tests | ⬜ | ⬜ P2 |
| 13 | Generalization experiments (held-out runs, param shift, LOWO, trace replay) | ⬜ (P5) | ⬜ | ⬜ | ⬜ P5 |
| 14 | Closed-loop controller + safety rules | ⬜ (P4). Enablers verified now: dynamic `memory.max` via `docker update`; `memory.high` write+restore via sidecar | `test_container_sampling.py::test_dynamic_memory_max_update`, `::test_memory_high_write_and_restore` | validation report | 🔶 actuation verified |
| 15 | Controller modes: fixed / percentile / Senpai-style / learned | ⬜ (P4) | ⬜ | ⬜ | ⬜ P4 |
| 16 | MAE, RMSE, wasted headroom, OOM rate, trade-off curves, error CDF | ⬜ (P5) `src/psi_memory/evaluation/` | ⬜ | ⬜ | ⬜ P5 |
| 17 | Reproducible commands + documentation | `README.md` (Phase 0 commands work); pinned `requirements/lock.txt`; seeds `common/seed.py` | `test_seed.py` | README | 🔶 grows per phase |

## Phase 0-specific spec requirements

| Spec requirement | Where satisfied |
|---|---|
| Repo structure per spec | directory tree matches `PROJECT_EXECUTION_SPEC.md` Phase 0 layout |
| Proper Python package, src layout, Python 3.11 | `pyproject.toml`, `.venv` (3.11.9) |
| Pinned requirements | `requirements/base.txt`, `dev.txt`, `lock.txt` |
| `.gitignore`, config examples | `.gitignore`, `configs/validate_env.example.yaml` |
| Structured logging | `src/psi_memory/common/logging.py` (console + JSONL) |
| Deterministic seed utilities | `src/psi_memory/common/seed.py` |
| Version-report script | `psi-version-report` |
| Run-all-tests command | `pytest` / `scripts/run_tests.ps1` |
| Minimal smoke-test command | `psi-smoke` |
| `validate_env`, text + JSON, all listed checks | `psi-validate-env`; 15 checks incl. OS/kernel, Python, Docker versions/context, cgroup version, memory controller files, global + per-container PSI, readable paths, swap, dynamic `memory.max`, `memory.high` writability, Docker Desktop limitations |
| PSI parser robustness (`some`/`full`, avg/total, missing≠0) | `collector/parsers.py` + `test_psi_parser.py` |
| `memory.max` = "max" handling | `common/units.py::parse_cgroup_scalar` + `test_units.py` |
| Byte conversion without silent precision loss | `common/units.py` + `test_units.py` |
| Phase 0 gate: temp container sampled reliably | `test_sidecar_sampling_reliable` (5 samples, monotonic, gap tolerance) + validator check `container.sidecar_sampling` |
