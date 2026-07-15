# Progress

Current phase: **Phase 1 — COMPLETE** (2026-07-16). Next: Phase 2.

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
