# Project Walkthrough

Concise companion to the interactive page at
[`docs/project-walkthrough/index.html`](project-walkthrough/index.html) (open
it directly in a browser — it's self-contained, no server needed). Every
claim below was checked against the current source, tests, and generated
artifacts on 2026-07-21 (HEAD `2927c6c`), not copied from older docs without
verification.

**Evidence classification used throughout:** ✅ *Implemented and working*
(code + tests + real generated output) · 🟡 *Incomplete/unverified* · ⬜
*Planned, not implemented* · ⚪ *Obsolete/unused* · ❓ *Unclear*.

## 1. Big picture

**Problem.** A container's `memory.current` alone can't tell you whether
90% usage is a harmless page cache or a leak about to trigger an OOM kill.
**PSI** (`memory.pressure`) is the kernel's own signal for which is
happening — it measures time actually lost to memory stalls, not how much
memory is held.

**What's tested.** Whether adding PSI features improves (a) offline
prediction of a container's future peak memory, and (b) a live controller's
memory-limit decisions — versus an identical system using only usage
features. Every comparison is a paired with/without-PSI run on identical
rows, splits, and hyperparameters.

**The verdict is two-part and it's the whole point of the project:**

| | Result |
|---|---|
| **Offline prediction** | PSI does **not** measurably help. Gaps are ±6%, inconsistent in sign, inside seed noise for the best model. Structural reasons documented in `docs/final_report.md` §3 (label saturation under tight limits; peak usage is already largely predictable from the usage slope). |
| **Closed-loop control** | PSI is **decisive**. Identical architecture and margins: a learned controller *without* PSI caused 3,186 limit collisions + 1 OOM kill on a dynamic workload; the same controller *with* PSI caused zero, at equal or lower headroom cost. |

Status: ✅ both halves, numbers verified byte-exact against
`artifacts/metrics/final/*.json`.

## 2. Environment architecture

Everything runs from one Windows machine, but the containers being measured
run inside **Docker Desktop's WSL2 Linux VM** — their cgroup v2 files are
invisible from Windows or the Ubuntu WSL distro. That's the reason this
needs an architecture section at all (`docs/decisions.md` D1–D5).

```
Windows host (Python 3.11, all psi-* CLI commands)
      │  subprocess ["docker", ...]           — no docker-py SDK (D5)
      ▼
Docker Desktop (client ↔ daemon, 29.5.2)
      ▼
WSL2 utility VM (kernel 6.6.87, cgroup v2, cgroupfs driver)
  ├─ workload container — own cgroup at /sys/fs/cgroup/ (cgroup namespacing)
  └─ sampler sidecar — --privileged --cgroupns=host
        -v /sys/fs/cgroup:/host/cgroup:ro
        reads /host/cgroup/docker/<container-id>/*  ──► stdout, JSON Lines
      │
      ▼  (never a Windows bind mount — OneDrive path has Hebrew chars, D4)
data/raw/<run_id>/samples.jsonl
```

**cgroup v2 files used:** `memory.current` (usage, bytes) · `memory.max`
(hard limit; literal `"max"` → `None`, never 0, D6) · `memory.high` (soft
throttle, the Senpai-style control knob) · `memory.pressure` (PSI:
`some`/`full` × avg10/avg60/avg300 + cumulative `total`) · `memory.events`
(`oom`, `oom_kill`, `max`, …) · `memory.stat` (anon vs. file) ·
`memory.swap.current`/`.max`.

Status: ✅ — `psi-validate-env` passes 15/15 checks live
(`artifacts/reports/env_validation_*.json`), cross-referenced by every
run's `env_validation_id`.

## 3. End-to-end data flow

| # | Stage | In → Out | Source |
|---|---|---|---|
| 1 | Workload container generates real memory behavior | YAML config → live process memory state | `workloads/{steady,leak,file_burst,bursty,trace_replay,mixed}.py` |
| 2 | Sampler sidecar takes a reading every second | cgroup files → one JSON sample/stdout | `workloads/sampler.py` |
| 3 | Host stream writer persists the raw run | sidecar stdout → `data/raw/<run_id>/{samples.jsonl,meta.json,workload.log}` | `src/psi_memory/collector/stream.py` |
| 4 | Dataset builder: windows + future-peak labels + splits + quality gates | raw runs → `data/processed/<name>/{tabular.csv,sequences.npz,splits.json,dataset.json,data_quality.json}` | `src/psi_memory/dataset/{builder,windows,splits,quality}.py` · `psi-build-dataset` |
| 5 | Model training — 5 rungs, paired PSI ablation | processed dataset → `artifacts/models/*.{joblib,pt}`, `artifacts/metrics/*.json` | `src/psi_memory/models/{training,lstm,ablation}.py` · `psi-train`/`psi-ablate` |
| 6 | Evaluation — generalization & figures | models → `artifacts/metrics/final/*.json`, `artifacts/plots/final/*.png` | `src/psi_memory/evaluation/{experiments,stats,figures}.py` · `psi-experiment` |
| 7 | Closed-loop controller acts on a live container | live container (+ optional model) → `artifacts/controller/<session>/{decisions.jsonl,meta.json}` | `src/psi_memory/controller/{policies,safety,loop,actuator}.py` · `psi-control` |
| 8 | Closed-loop scoring — decision logs only, no second measurement channel (D26) | decision logs → `artifacts/metrics/final/closed_loop_*.json`, final report §4 | `src/psi_memory/evaluation/closed_loop.py` |

Status: ✅ every stage — real files exist at every arrow above.

## 4. Repository map

```
docs/                    proposal, execution spec, decisions (D1-D26), progress,
                          traceability, final_report.md, this walkthrough
workloads/                container-side scripts (stdlib only): 6 workloads +
                          sampler.py + wl_common.py + traces/*.csv
docker/Dockerfile.workloads   one image: workloads + sampler + sidecar writes (D10)
src/psi_memory/
  common/                byte-unit parsing, deterministic seeds, logging
  collector/             PSI/cgroup parsers, host-side JSONL streaming
  environment/           docker CLI wrapper, validator, calibration
  workloads/             YAML batch config + run orchestration (host side)
  dashboard/             live Rich TUI
  dataset/               loader, windows/labels, splits, quality gates, builder
  models/                baselines, RF/XGBoost, LSTM, ablation
  controller/            safety gate, policies, actuators, control loop
  evaluation/            stats, generalization experiments, closed-loop, figures
  cli.py                 every psi-* command
configs/                 12 YAML files — every batch run is config-driven
tests/unit/ (23 files, 156 tests) · tests/integration/ (8 files, 14 need Docker)
data/raw/ (65 run dirs) · data/processed/{full,shift,mini}/ · data/splits/
artifacts/models,metrics,plots,reports,controller/   every reported number traces here
requirements/ (pinned) · scripts/run_tests.ps1
```

Not shown: `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.egg-info/` — real,
uninteresting.

## 5. Phases & progress

| Phase | Status | Commit · tests | Key output |
|---|---|---|---|
| 0 — Foundation | ✅ | `730c8bf` · 36 | env validator 15/15, verified sidecar path |
| 1 — Workloads/collector/dashboard | ✅ | `3b96c17` · 64 | live calibration confirmed every expected PSI signature |
| 2 — Dataset + classical baselines | ✅ | `8e744a3` · 103 | leakage-safe pipeline; first (honest, negative) mini-ablation |
| 3 — LSTM | ✅ | `a4197ac` · 105+ | full model ladder, reported honestly |
| 4 — Closed-loop controller | ✅ | `1524e7b` · 149 | 4 modes, safety gate, live write+restore verified |
| 5 — Full evaluation | ✅ | `2927c6c` · 170 | 36-run dataset, generalization suite, 22-session closed-loop comparison, final report |

All 17 rows of `docs/requirements_traceability.md` are ✅.

**Two documentation inconsistencies found during verification** (not fixed
here — out of scope for this walkthrough, flagging only):

1. `docs/final_report.md` §1 says "262+ automated tests." The verified
   count is **170** (`pytest --collect-only`), matching the Phase 5 commit
   message. 262 doesn't match anywhere else in the repo.
2. `README.md`'s "Workloads" section still says "five" and omits `mixed`
   (added Phase 5, D25) — code, decisions, progress, and the final report
   all correctly say six.

## 6. Models & experiments

| Rung | Features | With/without-PSI pair? |
|---|---|---|
| Persistence | last known usage only | no — usage-only by construction |
| Percentile heuristic ("Autopilot-style") | p95 of recent usage | no — usage-only by construction |
| Random Forest | usage aggregates (+PSI variant) | yes |
| XGBoost | usage aggregates (+PSI variant) | yes |
| LSTM | raw window sequence (+PSI channels) | yes |

**Target:** `max(memory.current)` in MiB, strictly after the window's end,
within a configurable horizon (default 30s) — `dataset/windows.py`.
**Splits:** whole runs assigned to train/val/test, stratified by workload,
never individual windows — validator hard-errors on any run in two splits
(`dataset/splits.py`).

**Held-out test MAE, MiB** (3 seeds, bootstrap CIs — verified byte-exact
against `artifacts/metrics/final/heldout_*.json`):

| Model | no-PSI | with-PSI |
|---|---|---|
| Persistence | 35.21 | — |
| Heuristic (p95) | 30.24 | — |
| Random Forest | 8.24 | 8.23 |
| XGBoost | 11.10 | 10.43 |
| **LSTM** | **1.37** | 1.61 |

Parameter-shift: every learned model degrades to 20–24 MAE; the plain p95
heuristic (13.3) **beats all of them** — echoes Google Autopilot's own
production experience. LOWO: learned models beat persistence clearly on
*bursty* (RF-with-PSI 34.2 vs. persistence 89.3), not on stable workloads.

**Closed-loop headline** (22 live sessions, bursty scenario, 3 margins each,
identical architecture — only PSI columns differ):

| Controller | Demand-above-limit events (3 margins) | OOM kills |
|---|---|---|
| Learned, **no PSI** | 1,501 / 405 / 1,280 (= 3,186 total) | 1 |
| Learned, **with PSI** | 0 / 0 / 0 | 0 |

On the predictable *leak* scenario every controller was collision-free;
with-PSI held lower (cheaper) headroom at every margin (62.3<68.8,
88.2<107.6, 132.3<145.9 MiB). Source: `artifacts/controller/closed_loop/`
(22 sessions + index), scored by `evaluation/closed_loop.py`. Status: ✅ —
numbers reproduced independently from raw decision logs.

**Risks worth knowing:**
- Label saturates under tight limits with swap (D24) — a structural ceiling
  on what PSI could add to *this* label.
- `heldout_multi_seed()` reuses one model directory across seeds — the
  metrics aggregation is correct (computed before each overwrite), but the
  single `.joblib`/`.pt` file on disk reflects only the last seed run.
- Closed-loop numbers are one session per (mode, margin, scenario) cell —
  consistent patterns, not a distribution.
- `closed_loop.run_comparison()`'s resumability logic has no dedicated test
  (only `session_metrics()` is unit-tested); evidenced by a clean 22-entry
  session index, not a regression test.
- `some` ≈ `full` PSI in these workloads (all single-process; a
  multi-process workload would decouple them).

## 7. How to run it

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements\dev.txt
pip install -e .
```

1. `psi-validate-env` — confirms Docker/WSL2/cgroup v2/PSI access.
2. `docker build -f docker\Dockerfile.workloads -t psi-workloads:latest .`
3. `psi-run --config configs\calibration.yaml` then `psi-calibrate` → must PASS.
4. `psi-run --config configs\collection_full.yaml` (~2h) and `configs\collection_shift.yaml` (~20min).
5. `psi-build-dataset --out data\processed\full --batch-manifest <path>` (repeat for `shift`).
6–8. `psi-experiment heldout|param-shift|lowo --dataset ...`
9. `psi-experiment closed-loop --model-no-psi <artifact> --model-with-psi <artifact>`
10. `psi-experiment figures --dataset data\processed\full`
11. `pytest` (or `pytest -m "not docker"` for the no-daemon subset).

Everyday commands: `psi-dashboard <container>` (live TUI) ·
`psi-train --dataset ... --model {persistence|heuristic|rf|xgb|lstm}` ·
`psi-ablate --dataset ... [--with-lstm]` ·
`psi-control <container> --mode {fixed|percentile|senpai|learned}`
(**dry-run by default** — add `--live` to actually write limits).

**Common failures, from this project's real history:**
- Leak workload OOMs almost immediately → ~0 usable windows (horizon rule
  discards them). Fix: slow the leak; time-to-OOM should be ≥2× (history +
  horizon) (D19).
- `docker inspect` hangs mid-batch (real daemon stall happened once) → the
  runner now retries with backoff and isolates failures per-run
  (`workloads/runner.py`, `test_runner_resilience.py`).
- A long closed-loop batch gets killed (host sleep, etc.) → re-running the
  same command is safe, it skips sessions already in `session_index.jsonl`.
- Docker-marked tests fail/skip → check the daemon is actually running.

## 8. Glossary

**PSI** — Pressure Stall Information; time stalled waiting for memory, not
how much is held. **cgroup v2** — kernel resource-grouping mechanism; every
container is a cgroup. **memory.current** — usage in bytes. **memory.max**
— hard limit; crossing it → reclaim → OOM kill if reclaim fails.
**memory.high** — soft throttle below `memory.max`; the Senpai-style knob.
**Reclaim** — kernel freeing memory under pressure (cheap if page cache,
expensive if active data). **Swap** — disk-backed overflow, enabled here so
pressure builds gradually instead of an instant OOM. **OOM (kill)** —
kernel forcibly kills a process to free memory. **Prediction horizon** —
how far ahead a model predicts (default 30s). **MAE** — mean absolute
error, in MiB here; lower is better. **PSI ablation** — training the
identical model with vs. without PSI columns to isolate its effect.
**Run-level split** — whole runs, not time windows, assigned to
train/val/test. **Future-peak label** — highest usage strictly after a
window ends, within the horizon. **Safety gate** — clips/rejects any
proposed limit change, independent of which policy proposed it. **Dry-run**
— controller logs decisions without writing them. **Autopilot-style** — a
percentile-of-usage heuristic in the spirit of Google's Autopilot, not a
reproduction. **Senpai-style** — reactive policy squeezing `memory.high`
against a PSI budget. **Headroom** — gap between usage and the current
limit. **Demand-above-limit event** — a moment demand exceeded the limit,
from `memory.events`' `max` counter.

## 9. Read-the-code path

1. `docs/PROJECT_EXECUTION_SPEC.md` — what was this contracted to build?
2. `src/psi_memory/collector/parsers.py` — how does a raw PSI line become numbers?
3. `workloads/sampler.py` — how is one sample actually taken, once a second?
4. `src/psi_memory/dataset/windows.py` — how is a label computed without leaking the future?
5. `src/psi_memory/dataset/splits.py` — how is cross-split leakage made structurally impossible?
6. `src/psi_memory/models/training.py` + `ablation.py` — how is with/without-PSI isolated?
7. `src/psi_memory/models/lstm.py` — what does the sequence model see that trees don't?
8. `src/psi_memory/controller/safety.py` — what stops a learned policy from doing something dangerous?
9. `src/psi_memory/evaluation/closed_loop.py` — how does a session become the final numbers?
10. `docs/final_report.md` — what did it all add up to?

## 10. Remaining work & risks

**Genuinely missing:** real external memory-demand traces (engine is ready
and tested, download was always a separate step); repeats for closed-loop
cells (no CI the way offline metrics have one); a demand-oriented label
investigation (peak current+swap, or reclaim-cost-aware); a regression test
for `run_comparison()`'s resumability.

**Should improve:** the two documentation inconsistencies above; per-seed
model artifacts get overwritten in `heldout_multi_seed()`; remove or
repurpose the dead `collector/cgroup_reader.py`; multi-process workloads to
decouple `some`/`full` PSI.

**Conclusions the evidence currently supports:** PSI decisively improves
closed-loop control on a dynamic workload (reproduced from raw logs); the
offline regression gap is small and inconsistent across three separate
evaluation designs — a real negative result; the percentile heuristic is a
genuinely strong baseline under distribution shift.

**Not yet supported:** whether PSI would help offline prediction under a
different (demand-oriented) label; generalization beyond this one machine,
kernel (6.6), and synthetic workloads; whether the closed-loop result holds
under repeated sampling rather than one session per cell.

---
*Generated by direct repository inspection — every claim above cites a
file, test, or generated artifact. No project code or behavior was changed
to produce this document.*
