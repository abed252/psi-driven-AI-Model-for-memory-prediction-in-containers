# Requirements Traceability

Maps every proposal / execution-spec requirement to implementation, tests, and outputs.
Status values: ✅ done · 🔶 partial · ⬜ planned (phase in parentheses).

| # | Requirement (proposal / spec) | Implementation | Tests | Outputs | Status |
|---|---|---|---|---|---|
| 1 | Data collection from container cgroup v2 files | Sampler sidecar `workloads/sampler.py` (monotonic scheduling, JSONL, tolerates target exit) + host stream `src/psi_memory/collector/stream.py` + batch runner `src/psi_memory/workloads/runner.py`; parsers `collector/parsers.py`, `cgroup_reader.py` | `test_sampler_script.py`, `test_psi_parser.py`, `test_cgroup_reader.py`, `tests/integration/test_workload_runs.py` | `data/raw/<run_id>/{samples.jsonl, meta.json, workload.log}` + batch manifest | ✅ |
| 2 | Per-container PSI and memory metrics | Verified inside-container + sidecar reads of `memory.current/max/high/pressure/events/stat/swap.*` | `test_container_sampling.py::test_exec_read_inside_container`, `::test_sidecar_sampling_reliable` | `artifacts/reports/env_validation_*.json` | ✅ |
| 3 | Environment validation and live monitoring | Validator: `src/psi_memory/environment/validate.py` (CLI `psi-validate-env`); live dashboard: `src/psi_memory/dashboard/live.py` (CLI `psi-dashboard`) | `test_validate_env_e2e.py`, `test_report.py`, `test_dashboard_view.py` | text + JSON reports, `validation_id`, live TUI | ✅ |
| 4 | Synthetic workloads (steady, leak, file-burst, bursty, trace-replay) | `workloads/{steady,leak,file_burst,bursty,trace_replay}.py` + `wl_common.py`, example trace, image `docker/Dockerfile.workloads`; YAML runner `src/psi_memory/workloads/{config,runner}.py` (CLI `psi-run`); PSI calibration `src/psi_memory/environment/calibration.py` (CLI `psi-calibrate`) | `test_batch_config.py`, `test_trace_replay.py`, `test_calibration_analysis.py`, `tests/integration/test_workload_runs.py` | calibration plots (`artifacts/plots/calibration/`) + report JSON | ✅ |
| 5 | Sliding-window dataset construction | `src/psi_memory/dataset/`: `loader.py`, `signals.py`, `windows.py`, `features.py` (tabular + sequences), `builder.py` (CLI `psi-build-dataset`), quality gates `quality.py` | `test_windows_labels.py`, `test_feature_parity.py`, `test_quality_gates.py`, `tests/integration/test_pipeline_e2e.py` | `data/processed/<name>/` with tabular.csv, sequences.npz, dataset.json, data_quality.json | ✅ |
| 6 | Future-peak labels, configurable 30–60 s horizon, no current-sample leakage | `windows.py`: strictly-after target, complete-horizon + gap + NaN discards, configurable H/horizon/interval/stride | `test_windows_labels.py` (hand-calculated series, off-by-one test) | dataset.json target definition | ✅ |
| 7 | Persistence baseline | `models/baselines.py::persistence_predict` | `test_baselines_and_metrics.py` | ablation reports | ✅ |
| 8 | Autopilot-style percentile heuristic | `models/baselines.py::heuristic_predict` (p95/max, named per spec) | `test_baselines_and_metrics.py` | ablation reports | ✅ |
| 9 | Random Forest + XGBoost | `models/training.py` (config-driven, saved artifacts + importances; CLI `psi-train`) | `test_training_discipline.py`, `test_pipeline_e2e.py` | `artifacts/models/`, `artifacts/metrics/` | ✅ |
| 10 | LSTM | `models/lstm.py`: sequences.npz + same splits/target, train-only normalizer, reproducible init, early stopping + checkpointing + loss history, CPU, configurable arch (CLI `psi-train --model lstm`) | `test_lstm_components.py`, `tests/integration/test_lstm_e2e.py` | `artifacts/models/*__lstm__*.pt` | ✅ |
| 11 | With/without-PSI ablation at every rung | `models/ablation.py` (CLI `psi-ablate [--with-lstm]`): identical rows/splits/params, PSI columns only difference — all rungs incl. LSTM | `test_feature_parity.py`, `test_lstm_components.py::test_variant_selection_*`, `test_pipeline_e2e.py::test_ablation_end_to_end` | `artifacts/metrics/ablation_*.json` | ✅ |
| 12 | Run-level train/val/test splits, split manifests | `dataset/splits.py`: stratified by workload, deterministic, leakage validator, saved manifests | `test_splits_leakage.py`, `test_pipeline_e2e.py::test_windows_respect_split_assignment` | `splits.json` per dataset | ✅ |
| 13 | Generalization experiments (held-out runs, param shift, LOWO, trace replay) | `evaluation/experiments.py` (CLI `psi-experiment heldout/param-shift/lowo`); held-out = run-level test split, 3 seeds + bootstrap CIs; shift batch `configs/collection_shift.yaml`; LOWO folds with structural no-overlap assert; trace-replay results reported per workload in every experiment | `test_evaluation.py` (fold integrity, CI, leakage rejection) | `artifacts/metrics/final/{heldout,param_shift,lowo}_*.json` | ✅ |
| 14 | Closed-loop controller + safety rules | `src/psi_memory/controller/`: `safety.py` (floor, malformed rejection, min/max, step caps, hysteresis, write-interval rate limit, reasons), `loop.py` (per-decision JSONL with all spec fields, dry-run default, restore-on-exit, safe stop on container exit, failures recorded), `window.py` (online signals with tested offline parity); CLI `psi-control` | `test_controller_safety.py`, `test_controller_policies.py`, `tests/integration/test_controller_loop.py` (fake cgroup), `test_controller_live.py` (docker: dry-run untouched, live write+restore) | `artifacts/controller/<session>/{decisions.jsonl, meta.json}` | ✅ |
| 15 | Controller modes: fixed / percentile / Senpai-style / learned | `controller/policies.py`: FixedPolicy, PercentilePolicy (Autopilot-style), SenpaiPolicy (memory.high, named per spec), LearnedPolicy (.joblib and .pt artifacts) | `test_controller_policies.py`, `test_controller_loop.py`, `test_controller_live.py` | decision logs per mode | ✅ |
| 16 | MAE, RMSE, wasted headroom, OOM rate, trade-off curves, error CDF | MAE/RMSE/underprediction/normalized: `models/metrics.py` + `evaluation/stats.py`; closed-loop outcomes (OOM events, demand-above-limit, avg/p95 headroom, rewrites, time under pressure, stability): `evaluation/closed_loop.py`; trade-off curves across margins + error CDFs: `evaluation/figures.py` (CLI `psi-experiment closed-loop/figures`) | `test_evaluation.py`, `test_baselines_and_metrics.py`, `tests/integration/test_figures.py` | `artifacts/metrics/final/closed_loop_*.json`, `artifacts/plots/final/` | ✅ |
| 17 | Reproducible commands + documentation | README: setup, all commands, architecture diagram, data schema, cgroup explanation, Docker Desktop caveats, safety notes, offline-vs-online distinction, reproducibility checklist, GenAI declaration; final report `docs/final_report.md`; pinned `requirements/lock.txt`; seeds `common/seed.py` | `test_seed.py`; full suite | README, final report | ✅ |

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
