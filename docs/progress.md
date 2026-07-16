# Progress

Current phase: **Phase 3 — COMPLETE** (2026-07-16). Next: Phase 4 (controller).

## Phase 3 report (LSTM)

### Headline result — the complete model ladder on the mini dataset

Test-split MAE (MiB), `artifacts/metrics/ablation_mini_20260716-032530.json`:

| model | no-PSI | with-PSI |
|---|---|---|
| persistence | 33.82 | (PSI-independent) |
| heuristic p95 | 15.25 | (PSI-independent) |
| RF | 1.90 | 2.79 |
| XGBoost | **0.48** | 1.17 |
| LSTM | 0.83 | 0.77 |

Honest reading: XGBoost (no-PSI) still leads; the LSTM lands between the
trees, and it is the first rung where with-PSI edges out no-PSI (0.77 vs
0.83) — but on this parameter-homogeneous mini data that margin is
noise-level, not evidence. Per the spec, the LSTM is reported as-is, not
promoted. The decisive comparison happens on the Phase 5 varied-parameter
collection.

### Files created or changed

- `src/psi_memory/models/lstm.py` — sequence loading aligned to stored
  splits/schema, variant column selection, train-only Normalizer (inputs +
  target, zero-variance guard), LSTM regressor (configurable hidden size /
  layers / dropout), Adam + MSE, early stopping with best-weights restore,
  .pt checkpoints with loss history
- `psi-train --model lstm`; `psi-ablate --with-lstm`; `configs/models.yaml`
  lstm section
- torch 2.13 (CPU wheel) added; requirements + lock refreshed
- tests: `tests/unit/test_lstm_components.py` (7),
  `tests/integration/test_lstm_e2e.py` (5)
- docs: README, decisions D20, traceability rows 10-11, this file

### Commands executed (key ones)

- `pip install torch --index-url https://download.pytorch.org/whl/cpu`
- `pytest -m "not docker"` → **105 passed**; full suite → see below
- `psi-ablate --dataset data/processed/mini --include-test --with-lstm`

### Phase 3 completion criteria check

- Same run splits + same target as classical models (loads splits.json /
  dataset.json; alignment tested) ✔
- with/without-PSI variants (signal-column selection, tested) ✔
- Sequence normalization fitted only on training data (tested) ✔
- Reproducible initialization (derived seeds; identical-params test) ✔
- Train/val loss logging (per-epoch log + history in checkpoint) ✔
- Early stopping + checkpointing (patience, best-weights restore) ✔
- CPU-compatible training (CPU-only wheel; seconds on mini data) ✔
- Configurable depth/hidden/lr/batch/epochs (configs/models.yaml) ✔
- Test evaluation only after model selection (early stop selects on val;
  test behind --include-test) ✔
- Honest reporting even though the LSTM does not beat XGBoost ✔

### Remaining risks

1. On near-deterministic mini data all learned models are within ~2 MiB of
   perfect; ranking differences are not meaningful. Architecture/tuning work
   is deliberately deferred until the Phase 5 dataset exists.
2. LSTM determinism verified on CPU; if a GPU is ever used, torch would need
   deterministic-algorithms flags (out of scope while device=cpu).

### Exact next step (Phase 4)

Closed-loop controller with dry-run mode and a fake-cgroup test harness:
fixed / Autopilot-style / Senpai-style (memory.high) / learned-model modes,
mandatory safety rules, full per-decision logging.

---


## Phase 2 report (dataset pipeline + classical baselines + mini ablation)

### Headline results

1. **The full pipeline runs end to end on real data**: 23 collected runs →
   949 leakage-safe windows (train/val/test 517/215/217, quality gates PASS)
   → persistence / heuristic / RF / XGBoost, each tree twice (with/without
   PSI) → ablation report `artifacts/metrics/ablation_mini_*.json`.

2. **Mini-ablation numbers (test split; MiB MAE)**: persistence 33.8,
   heuristic(p95) 15.3, RF 1.90 (no-PSI) / 2.79 (with-PSI), XGB 0.48
   (no-PSI) / 1.17 (with-PSI). **PSI did not help on this mini dataset — 
   reported honestly.** Diagnosis (per-workload breakdown): with fixed
   per-workload parameters the trajectories are near-deterministic (leak
   test MAE 0.1-0.3 MiB for BOTH variants), so usage features alone almost
   fully determine the future peak and PSI can only add variance. The claim
   the project tests lives in the harder settings — varied parameters,
   parameter shift, leave-one-workload-out — which is the Phase 5 collection
   design. The mini dataset's job was to validate the machinery, and it did.

3. **Actionable finding (D19)**: fast leaks OOM so quickly that the
   complete-horizon rule discards nearly all their windows (0-8 per run);
   slow leaks (3 MiB/s) yield 66-78. Collection configs updated; rule of
   thumb recorded: time-to-OOM ≥ 2x (history + horizon).

### Files created or changed

- `src/psi_memory/dataset/`: `loader.py` (validated JSONL→frames),
  `signals.py` (no-PSI vs PSI signal groups — the ablation contract),
  `windows.py` (windows + strictly-after future-peak labels + discard rules),
  `features.py` (6 aggregates/signal + baseline columns), `splits.py`
  (stratified run-level splits + leakage validator + manifests), `quality.py`
  (gates), `builder.py` (CLI orchestration, full provenance metadata)
- `src/psi_memory/models/`: `baselines.py`, `metrics.py` (MAE/RMSE/
  underprediction, per workload), `training.py` (config-driven RF/XGB,
  train-only scaler, artifacts), `ablation.py`
- CLIs: `psi-build-dataset`, `psi-train`, `psi-ablate` (test split behind
  `--include-test`)
- configs: `dataset.yaml`, `models.yaml`, `mini_collection.yaml`,
  `mini_leak_extra.yaml`; `collection_full.example.yaml` leaks slowed (D19)
- deps: numpy, pandas, scikit-learn, xgboost, joblib (lock.txt refreshed)
- tests: `test_windows_labels.py`, `test_splits_leakage.py`,
  `test_feature_parity.py`, `test_baselines_and_metrics.py`,
  `test_training_discipline.py`, `test_quality_gates.py` (unit) +
  `test_pipeline_e2e.py` (integration, synthetic raw, no Docker);
  shared synthetic-run factory in `tests/conftest.py`
- docs: README, decisions D15-D19, traceability rows 5-12, this file

### Commands executed (key ones)

- `psi-run --config configs/mini_collection.yaml` (15 runs) +
  `configs/mini_leak_extra.yaml` (3 slow leaks)
- `psi-build-dataset --out data/processed/mini` → 949 windows, gates PASS
- `psi-ablate --dataset data/processed/mini --include-test`
- `pytest` → **103 passed** (92 non-docker + 11 docker)

### Phase 2 completion criteria check

- Reproducible dataset builder, raw immutable, full provenance recorded ✔
- Sequence features (`sequences.npz`) + tabular summaries ✔
- Without-PSI features per spec list; with-PSI identical rows + PSI columns
  only (tested) ✔
- Persistence, Autopilot-style percentile heuristic (named per spec), RF,
  XGBoost — config-driven ✔
- Artifacts saved: models, scalers, schema, metadata, config, split IDs,
  validation metrics, importances ✔
- Minimal ablation on small generated data before large-scale collection ✔
- Leakage rules implemented AND tested (run-level splits, train-only scaler,
  strictly-after labels, horizon discards, manifest storage) ✔
- Data-quality gates with machine-readable report; pipeline fails on
  critical gate failures ✔

### Remaining risks

1. Mini-ablation cannot demonstrate the PSI benefit (trajectories too
   regular); the full collection needs deliberate parameter variety within
   each workload — designed into `collection_full.example.yaml`.
2. XGB test MAE of 0.5 MiB signals near-memorization of same-parameter
   sibling runs; parameter-shift and LOWO experiments (Phase 5) are the
   honest generalization measures.
3. `heuristic` currently supports p95/p100 only (columns precomputed at
   build time); other percentiles need a dataset rebuild or sequence-side
   computation.

### Exact next step (Phase 3)

LSTM on `sequences.npz`: same splits, same target, with/without-PSI variants
(signal-column selection), train-only normalization, early stopping,
checkpointing, CPU training, honest comparison against the tree models.

---


## Phase 1 report (workloads, collector, dashboard, calibration)

### Headline result

**PSI behaves exactly as the proposal predicts on this machine.** Calibration
(5 live runs, `artifacts/reports/calibration_20260716-014102.json`): overall
**PASS**:

| Workload | peak some.avg10 | cumulative stall | OOM | verdict |
|---|---|---|---|---|
| steady | 0.00 % | 0 s | no | PSI near zero ✔ |
| file_burst | 0.00 % (usage 85 % of limit) | 0 s | no | high usage, PSI low ✔ — the §1 ambiguity, live |
| leak | **5.47 %** | **1.28 s** | **yes** (exit 137, flag+events) | PSI rises then OOM ✔ |
| bursty | 3.58 % | 2.47 s | no | 10 usage swings, oscillating PSI ✔ |
| trace_replay | 0.00 % | 0 s | no | tracks trace, correlation 1.000 ✔ |

steady/file_burst vs leak is precisely the raw-usage-is-ambiguous story the
project is built on, now demonstrated with our own pipeline end to end.

### Files created or changed

- `workloads/` — container-side stdlib scripts: `wl_common.py`, `steady.py`,
  `leak.py`, `file_burst.py`, `bursty.py`, `trace_replay.py`,
  `sampler.py` (JSONL sampler sidecar), `traces/example_trace.csv`
- `docker/Dockerfile.workloads` — single image for workloads + sampler
- `src/psi_memory/collector/stream.py` — host-side sidecar launch + JSONL streaming
- `src/psi_memory/workloads/config.py`, `runner.py` — YAML batch config,
  run-matrix expansion with derived seeds, full run lifecycle + metadata
- `src/psi_memory/dashboard/live.py` — Rich live dashboard (`psi-dashboard`)
- `src/psi_memory/environment/calibration.py` — signature checks, plots, report
- `src/psi_memory/cli.py`, `pyproject.toml` — new commands: `psi-run`,
  `psi-dashboard`, `psi-calibrate`; new dep: matplotlib (lock.txt updated)
- `configs/calibration.yaml`, `configs/collection_full.example.yaml`
- tests: `test_batch_config.py`, `test_sampler_script.py`,
  `test_trace_replay.py`, `test_calibration_analysis.py`,
  `test_dashboard_view.py` (unit) + `tests/integration/test_workload_runs.py`
- docs: README (commands, workloads, repo map), decisions (D9–D14),
  traceability rows 1/3/4 → done, this file

### Commands executed (key ones)

- `docker build -f docker/Dockerfile.workloads -t psi-workloads:latest .`
- `pytest -m "not docker"` → **53 passed**; `pytest -m docker` → **11 passed**
- `psi-run --config configs/calibration.yaml` → 5/5 runs, batch manifest
- `psi-calibrate` → overall PASS, 5 plots + JSON report

### Tests

64/64 passing (53 unit, 11 docker integration — including: steady run end to
end with complete metadata; collector surviving early target exit
(`end_reason=target_exited`); leak run recording growth **and** OOM
(exit 137, `OOMKilled` flag); `memory.high` applied via sidecar).

### Phase 1 completion criteria check

- 5 required workloads with configurable params, seeds, timeouts, clean
  SIGTERM shutdown ✔ (trace-replay engine + synthetic example trace;
  external trace download deliberately separate, documented)
- YAML batch runner recording every spec-required metadata field incl.
  image digest and `env_validation_id` ✔
- Collector: configurable interval, monotonic drift-free scheduling,
  per-line flush, tolerates container exit, malformed-record detection,
  raw fields preserved (JSONL), one metadata record per run, runs never
  merged ✔
- Rich live dashboard with all required fields ✔
- Calibration configs (fast) + full-collection example configs ✔
- PSI validation: expected signatures confirmed, OOM + `memory.events`
  detected, swap recorded, plots + machine-readable report stored ✔

### Remaining risks

1. Leak PSI peaked at 5.47 % — above the ≥5 % gate but not by much. For the
   Phase 2 full collection, consider higher `retouch_fraction` / tighter
   limits to get richer pressure variation (thresholds recorded in D14).
2. `some` ≈ `full` in single-process containers; multi-process workloads
   would decouple them. Not required by the proposal, noted for honesty.
3. Calibration numbers come from one run per workload; the full collection
   uses repeats with varied parameters (already configured in the example).
4. VM clock vs host clock skew is unmeasured; run correlation currently
   relies on the VM-monotonic timeline only, which is self-consistent.

### Exact next step (Phase 2)

Dataset builder: JSONL → windowed feature tables with future-peak labels
(strictly after window end), run-level splits with manifests, leakage tests;
then persistence + percentile heuristic + RF/XGBoost with the with/without-PSI
ablation on a small collected batch.

---

## Phase 0 report (2026-07-15) — foundation

Phase 0 delivered the repo structure, Python 3.11 package, environment
validator (15/15 PASS, report `env_validation_..._4167fbed30ae.json`), the
verified sidecar collection path, and 36 tests. Details: git history and
`docs/decisions.md` D1–D8.
