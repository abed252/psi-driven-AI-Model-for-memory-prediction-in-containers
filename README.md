# PSI-Driven Prediction of Container Memory Demand

Predicting container peak memory demand from Linux **PSI (Pressure Stall
Information)** signals, for proactive cgroup sizing.

Course 236502 — Project in Artificial Intelligence, Technion.
Proposal: [`docs/proposal/PROPOSAL_document_v2.pdf`](docs/proposal/PROPOSAL_document_v2.pdf)
· Execution contract: [`docs/PROJECT_EXECUTION_SPEC.md`](docs/PROJECT_EXECUTION_SPEC.md)

**Status: Phase 1 complete** — workloads, collector, dashboard, and PSI
calibration, on top of the Phase 0 foundation (environment validation and the
verified collection path). Later phases (dataset, models, controller,
evaluation) are described in the execution spec and not yet implemented.

## What this project does

Container memory limits are usually set from raw usage, which is ambiguous:
90% usage may be freely-reclaimable page cache (healthy) or a leaking heap
seconds from an OOM kill. PSI directly disambiguates the two. We predict each
container's **peak memory over the next control horizon (30–60 s)** from a
sliding window of PSI + memory metrics, ablate the PSI features at every model
rung (persistence → RF/XGBoost → LSTM), and evaluate a closed-loop controller
against fixed-limit, percentile-heuristic, and Senpai-style baselines.

## Environment

| Requirement | This machine (validated) |
|---|---|
| Windows + Docker Desktop (WSL2 backend) | Docker Desktop 29.5.2, WSL2 kernel 6.6.87 |
| cgroup v2 in the Docker VM | ✔ (cgroupfs driver) |
| Per-container PSI (`memory.pressure`) | ✔ readable inside container and via sidecar |
| Swap in the VM (needed for pressure workloads) | ✔ 2 GiB |
| Python 3.11 (Windows) | ✔ 3.11.9 via `py -3.11` |

Run everything from **Windows** (PowerShell); Docker commands go to Docker
Desktop's `desktop-linux` context. WSL-integration and native Docker CE are
**not** required.

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements\dev.txt
pip install -e .
```

Pinned versions used for the validated setup: `requirements\lock.txt`.

## Commands

| Command | What it does |
|---|---|
| `psi-validate-env` | Full environment validation (starts/removes a temp container). Text to stdout + JSON report saved under `artifacts\reports\`. Exit code 0 = pass. Flags: `--skip-docker`, `--json`. |
| `psi-smoke` | Minimal end-to-end smoke test: start container → 3 sidecar samples → clean up. |
| `psi-version-report` | Versions of Python, dependencies, and Docker. |
| `docker build -f docker\Dockerfile.workloads -t psi-workloads:latest .` | Build the workload + sampler image (required before running workloads). |
| `psi-run --config configs\calibration.yaml` | Run a batch of workload runs; writes `data\raw\<run_id>\{samples.jsonl, meta.json, workload.log}` + a batch manifest. |
| `psi-calibrate` | Analyze the newest batch: check expected PSI signatures, write plots to `artifacts\plots\calibration\` and a JSON report to `artifacts\reports\`. |
| `psi-dashboard <container>` | Live Rich dashboard (usage, limit, ratio, PSI, stall deltas, swap, events) for any running container. |
| `pytest` | All tests (unit + docker integration). |
| `pytest -m "not docker"` | Unit tests only (no Docker needed). |
| `.\scripts\run_tests.ps1 [-UnitOnly]` | Same, as a script. |

Docker Desktop must be running for everything except unit tests and
`psi-validate-env --skip-docker`; docker-marked tests auto-skip when the
daemon is down.

## Workloads

Five containerized workloads (stdlib-only Python, in `workloads/`), each with
configurable parameters, a deterministic seed, a duration, and clean SIGTERM
shutdown. Batches are driven by YAML configs (`configs/`):

| Workload | Behavior | Expected signal |
|---|---|---|
| `steady` | allocate and hold a fixed working set (+optional churn) | flat usage, PSI ≈ 0 |
| `leak` | allocate anonymous memory forever, re-touch old chunks | rising PSI under a tight limit + swap, then OOM kill |
| `file_burst` | repeatedly read a large file through the page cache | high usage, PSI low (reclaimable) |
| `bursty` | allocate/touch/free cycles with idle gaps | oscillating usage and PSI |
| `trace_replay` | track a memory-demand curve from a trace file (`workloads/traces/`) | follows the trace shape |

Each run records full metadata (`meta.json`): run ID, workload, params, seed,
image digest, limits, timings, exit code, OOM status (docker flag **and**
`memory.events` counters), collector config, and the environment
`validation_id` it ran under. Raw samples are immutable JSONL — one line per
second with all scalar files, PSI, `memory.events`, and `memory.stat`.

Calibration (`psi-run --config configs\calibration.yaml` then `psi-calibrate`)
verifies the expected-signal column above actually holds on this machine
before any model training — the spec's guard against training on dead PSI.
Latest calibration: **overall PASS** — steady/file_burst at 0 % PSI (with
file cache at 85 % of the limit), leak rising to 5.5 % `some.avg10` ending in
a detected OOM kill, bursty oscillating, trace replay tracking with
correlation 1.0 (plots in `artifacts\plots\calibration\`, report in
`artifacts\reports\`).

## How per-container metrics are collected (Docker Desktop)

Containers run inside Docker Desktop's WSL2 utility VM, so container cgroups
are not visible from the Windows host or the Ubuntu distro. Two validated
access paths (details: `docs/decisions.md`):

1. **Inside the container** — cgroup namespaces make the container's own
   cgroup appear at `/sys/fs/cgroup/`; `docker exec <c> cat
   /sys/fs/cgroup/memory.pressure` works. Used for validation only (each
   sample costs a Windows process spawn).
2. **Privileged sidecar (primary)** — a helper container started with
   `--privileged --cgroupns=host -v /sys/fs/cgroup:/host/cgroup:ro` sees the
   VM's full cgroup tree; a target's directory is
   `/host/cgroup/docker/<container-id>/`. Sampling loops run inside the VM at
   native speed.

Also validated: dynamic `memory.max` updates via `docker update` (no restart),
and `memory.high` writes via a read-write sidecar (needed for the Senpai-style
controller mode in Phase 4).

### cgroup v2 files used

| File | Meaning |
|---|---|
| `memory.current` | current memory usage (bytes) |
| `memory.max` | hard limit; literal `max` = unlimited (parsed as `None`, never 0) |
| `memory.high` | soft throttle limit (Senpai-style control knob) |
| `memory.pressure` | PSI: `some`/`full` lines, `avg10/avg60/avg300` (%) + cumulative `total` (µs) |
| `memory.events` | `oom`, `oom_kill`, `max`, `high`, `low` counters |
| `memory.stat` | detailed breakdown (anon, file, …) |
| `memory.swap.current` / `.max` | swap usage / limit |

## Repository map

```
docs/                  proposal PDF, execution spec, traceability, progress, decisions
workloads/             container-side scripts: 5 workloads + sampler.py + traces/
docker/                Dockerfile.workloads (workload + sampler image)
src/psi_memory/
  common/              logging, deterministic seeds, byte-unit parsing
  collector/           cgroup v2 parsers, snapshot reader, sampler stream (host side)
  environment/         docker CLI wrapper, probes, validate_env, calibration
  workloads/           YAML batch config + runner (host-side orchestration)
  dashboard/           live Rich dashboard
  dataset|features|models|controller|evaluation/           later phases
configs/               calibration.yaml, collection_full.example.yaml, examples
requirements/          base.txt, dev.txt, lock.txt (pinned)
tests/unit/            no Docker required
tests/integration/     marked `docker`; auto-skip when daemon is down
data/raw/<run_id>/     samples.jsonl + meta.json + workload.log per run (gitignored)
artifacts/             models, metrics, plots, reports (validation + calibration)
scripts/               run_tests.ps1
```

## Safety and caveats

- The validator and tests only start **project-owned temporary containers**
  (`psi-probe-*`, `psi-itest-*`) and remove them; nothing else is touched.
- `docker update` / `memory.high` writes are applied only to those temporary
  containers, and `memory.high` is restored to `max` afterwards.
- Docker Desktop limitations (VM-level PSI, VM RAM/swap caps, slow Windows
  bind mounts, non-ASCII project path) are recorded automatically in every
  validation report.

## Reproducibility

- Split-by-run discipline, seed derivation (`psi_memory.common.seed`), and
  pinned dependencies are in place from Phase 0.
- Every environment validation produces a JSON report with a stable
  `validation_id`; later data-collection runs will reference it.

## Generative AI declaration

Generative-AI tools are used to assist with code writing per course policy;
methodology, experiments, and analysis are the authors' own. A full
declaration will be included in the final report (placeholder, per proposal §6).
