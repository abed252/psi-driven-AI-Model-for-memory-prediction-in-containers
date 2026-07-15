# Technical Decisions

This file records important architectural and implementation decisions.

## D1 — Metric collection path on Docker Desktop (Phase 0, 2026-07-15)

**Problem.** Containers run inside Docker Desktop's WSL2 utility VM; their
cgroup directories are not visible from Windows or from the Ubuntu WSL distro.

**Alternatives tested (in the order required by the execution spec):**

1. **Read from inside the target container** — works: with cgroup namespaces
   the container's own cgroup appears at `/sys/fs/cgroup/`, and
   `memory.current/max/high/pressure/events/stat/swap.*` are all readable.
   Cost: each `docker exec` sample spawns a Windows process (~100–300 ms) —
   too heavy for 1 Hz multi-container sampling. Kept as validation fallback.
2. **Privileged sidecar (CHOSEN)** — `docker run --privileged --cgroupns=host
   -v /sys/fs/cgroup:/host/cgroup:ro` exposes the VM's full cgroup tree; a
   target's directory is `/host/cgroup/docker/<full-container-id>/`. The
   sampling loop runs inside the VM (native file reads, no per-sample process
   spawn), timestamps from the VM's monotonic `/proc/uptime`.
3. **`docker inspect`** — used to resolve container name → full ID for the
   sidecar path.
4. **Collector inside the docker-desktop distro** — not needed given (2).
5. **Native Docker CE in WSL** — not needed; explicitly avoided (would be a
   second daemon / permanent system change).

**Consequences.** The Phase 1 collector will be a containerized sidecar; data
leaves it via stdout or `docker cp` (see D4).

## D2 — Actuation paths for the Phase 4 controller (verified in Phase 0)

- `memory.max`: **`docker update --memory`** changes a running container's
  limit without restart (verified 256M→512M live). No direct cgroup write
  needed, and Docker's bookkeeping stays consistent.
- `memory.high`: not exposed by the Docker CLI; written directly through a
  **read-write privileged sidecar** (verified write 128M and restore to
  `max`). Required for the Senpai-style reactive mode.

## D3 — Project runs from Windows Python 3.11, not WSL

Ubuntu WSL has no docker CLI integration (enabling it would change Docker
Desktop settings — a persistent change we avoid). Windows has Python 3.11
(`py -3.11`), and all Docker interaction goes through the CLI, which works
identically from Windows. The venv lives in `.venv/` at the repo root.

## D4 — Data transfer avoids Windows bind mounts

The project path contains non-ASCII (Hebrew) characters and lives under
OneDrive; Windows bind mounts into the VM are slow (gRPC-FUSE) and
path-fragile. Probe/collector output therefore leaves containers via
**stdout** (Phase 0 probes) or **`docker cp` / volumes** (Phase 1 collector —
final choice recorded then). Also, Git Bash mangles `/sys/fs/cgroup` arguments
(`MSYS_NO_PATHCONV=1` needed); Python `subprocess` does not — one more reason
all Docker calls go through the Python wrapper (`environment/docker_cli.py`).

## D5 — Docker via CLI subprocess, not docker-py

The `docker` CLI is wrapped in `environment/docker_cli.py` instead of using
the docker-py SDK: no extra dependency pin, no SDK/daemon API version
coupling, and every action in logs/README is reproducible by hand.

## D6 — Missing/unlimited cgroup values are never zero

`memory.max` etc. containing the literal `max` parse to `None` and are listed
as `unlimited_fields`; absent files are listed in `missing_fields`. Malformed
content raises. This enforces the spec rule that missing data must be explicit,
not silently zeroed (tests: `test_units.py`, `test_cgroup_reader.py`).

## D7 — Kernel PSI averages are preserved as-is, plus cumulative total

`memory.pressure` parsing keeps the kernel's `avg10/avg60/avg300` (they are
windowed averages, not instantaneous values) **and** the cumulative `total`
microseconds, from which per-interval stall deltas will be derived in feature
engineering (spec requirement).

## D8 — Environment reports carry a stable `validation_id`

Each `psi-validate-env` run saves JSON with a content-hash ID; Phase 1 run
metadata references it (`env_validation_id`) so every dataset row is
traceable to the validated environment it was collected under.

## D9 — Raw run data is JSON Lines streamed over stdout (Phase 1, 2026-07-16)

The sampler sidecar emits one JSON object per sample on stdout; the host
streams it into `data/raw/<run_id>/samples.jsonl` with per-line flushes.
Rationale: (a) implements D4 — no Windows bind mounts; (b) preserves *all*
raw fields (`memory.stat` has ~50 keys that vary by kernel; a fixed CSV
schema would drop or zero them, violating the no-silent-zero rule); (c) a
crash loses at most one line. The Phase 2 dataset builder converts JSONL to
feature tables; raw files stay immutable.

## D10 — One image serves workloads, sampler, and sidecar writes

`psi-workloads:latest` (python:3.11-alpine + stdlib-only scripts) is used for
workload containers, the sampler sidecar, and the dashboard's stream. One
image digest in run metadata pins everything that ran; no version skew
between workload and collector.

## D11 — Workload scripts are standalone stdlib files, not package modules

`workloads/*.py` import only the stdlib and their sibling `wl_common.py`, so
the container needs no pip install and the image builds in seconds. Host-side
unit tests load them via importlib with the directory on sys.path — the same
layout they see inside the image at /app.

## D12 — Pressure needs allocation + re-touching, and swap-backed limits

Simply allocating past `memory.max` gets a container OOM-killed with PSI
still ~0. The leak/bursty workloads therefore (a) run with
`--memory-swap` > `--memory` so the kernel swaps instead of killing
immediately, and (b) re-touch previously allocated chunks every tick, forcing
refaults of swapped-out pages — the stalls PSI actually measures. Python's
`bytearray(n)` gets uncommitted zero-pages, so every page is written on
allocation and on touch (see `wl_common.py`).

## D13 — OOM detection uses docker's flag OR memory.events

`docker inspect .State.OOMKilled` misses OOM kills of child processes and
`memory.events` counters miss nothing but require the collector to have
sampled in time. Run metadata records both (`oom_killed_flag`,
`final_memory_events`) and derives `oom_observed` as their OR.

## D14 — Calibration thresholds

"Near zero" PSI = some.avg10 < 1% and < 0.2 s cumulative stall; "low" < 5%;
"genuine pressure" ≥ 5% avg10 or ≥ 1 s cumulative stall. These are recorded
in `environment/calibration.py` and in the calibration report so later phases
can revisit them; they are calibration gates, not scientific claims.

