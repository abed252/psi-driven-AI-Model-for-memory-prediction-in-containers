# PSI-Driven Prediction of Container Memory Demand

Predicting container peak memory demand from Linux **PSI (Pressure Stall
Information)** signals, for proactive cgroup sizing.

Course 236502 — Project in Artificial Intelligence, Technion.
Proposal: [`docs/proposal/PROPOSAL_document_v2.pdf`](docs/proposal/PROPOSAL_document_v2.pdf)
· Execution contract: [`docs/PROJECT_EXECUTION_SPEC.md`](docs/PROJECT_EXECUTION_SPEC.md)

**Status: Phase 0 complete** — repository foundation, environment validation,
and a verified per-container PSI/memory collection path on Docker Desktop.
Later phases (workloads, collector, dataset, models, controller, evaluation)
are described in the execution spec and not yet implemented.

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

## Commands (Phase 0)

| Command | What it does |
|---|---|
| `psi-validate-env` | Full environment validation (starts/removes a temp container). Text to stdout + JSON report saved under `artifacts\reports\`. Exit code 0 = pass. |
| `psi-validate-env --skip-docker` | Host-only checks, no containers. |
| `psi-validate-env --json` | JSON to stdout instead of text. |
| `psi-smoke` | Minimal end-to-end smoke test: start container → 3 sidecar samples → clean up. |
| `psi-version-report` | Versions of Python, dependencies, and Docker. |
| `pytest` | All tests (unit + docker integration). |
| `pytest -m "not docker"` | Unit tests only (no Docker needed). |
| `.\scripts\run_tests.ps1 [-UnitOnly]` | Same, as a script. |

Docker Desktop must be running for `psi-validate-env` (without
`--skip-docker`), `psi-smoke`, and the integration tests; docker-marked tests
auto-skip when the daemon is down.

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
src/psi_memory/
  common/              logging, deterministic seeds, byte-unit parsing
  collector/           cgroup v2 parsers + snapshot reader (Phase 1: full collector)
  environment/         docker CLI wrapper, container probes, validate_env
  workloads|dataset|features|models|controller|evaluation|dashboard/   later phases
configs/               example configurations
requirements/          base.txt, dev.txt, lock.txt (pinned)
tests/unit/            no Docker required
tests/integration/     marked `docker`; auto-skip when daemon is down
data/                  raw/processed/splits datasets (gitignored)
artifacts/             models, metrics, plots, reports (env-validation JSONs live here)
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
