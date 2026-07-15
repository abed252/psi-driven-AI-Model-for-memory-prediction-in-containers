Your assessment is mostly correct. Proceed with the project, but follow the execution contract below strictly.

You are responsible for building the complete project from scratch in this repository, not merely producing a prototype or isolated scripts. The final result must be reproducible, tested, documented, and aligned with every requirement in the proposal PDF.

Before making changes, reread the proposal and create a requirement-to-implementation checklist covering:

1. Data collection from container cgroup v2 files.
2. Per-container PSI and memory metrics.
3. Environment validation and live monitoring.
4. All required synthetic workloads.
5. Sliding-window dataset construction.
6. Future peak-memory labels for a configurable 30–60 second horizon.
7. Persistence baseline.
8. Percentile/Autopilot-style heuristic baseline.
9. Random Forest and XGBoost models.
10. LSTM model.
11. With-PSI versus without-PSI ablation for every applicable model.
12. Run-level train, validation, and test splits.
13. Generalization experiments.
14. Closed-loop controller.
15. Fixed-limit, percentile, reactive-PSI/Senpai-style, and learned-model controller modes.
16. MAE, RMSE, wasted-headroom, OOM-rate, trade-off-curve, and error-CDF evaluation.
17. Reproducible commands and complete documentation.

The proposal defines the central prediction target as the maximum memory usage over the upcoming control horizon, rather than the next sample. It also requires splitting data by complete runs to prevent leakage. Treat both as hard correctness requirements.

## General working rules

Work autonomously, but do not silently make risky system changes.

You may freely:

- Inspect files.
- Create and edit project files.
- Run tests.
- Install Python dependencies inside a project virtual environment.
- Build Docker images.
- Start and stop project-owned test containers.
- Generate temporary datasets and experiment outputs.
- Add scripts, tests, configuration files, documentation, and CI-style checks.

Do not do any of the following without first explaining why and obtaining my approval:

- Uninstall or replace Docker Desktop.
- Install a second Docker daemon.
- Change global WSL configuration.
- Edit `.wslconfig`.
- Modify kernel parameters globally.
- Remove unrelated Docker images, containers, volumes, or networks.
- Use `sudo` for permanent system changes.
- Delete existing repository content.
- Change the project’s intended scientific methodology merely because another approach is easier.

Prefer the currently installed Docker setup when it can satisfy the project. Do not assume native Docker CE is required until you have tested the available access paths.

If Docker Desktop prevents direct host access to the container cgroup pseudo-files, investigate these alternatives in order:

1. Reading the cgroup metrics from inside the target container.
2. Mounting the relevant cgroup v2 path read-only into a privileged metrics sidecar or collector.
3. Using Docker inspection to identify the correct cgroup.
4. Running the collector in the Docker Desktop Linux environment.
5. Only then propose native Docker inside WSL as an optional environment change.

Document exactly which approach works and why.

## Scientific correctness requirements

The main scientific question is not “Can memory usage be predicted?” It is:

Does memory PSI provide useful predictive information beyond ordinary memory-usage features for forecasting future peak container memory demand and for making safer memory-limit decisions?

Every design decision must preserve the ability to answer that question fairly.

### No data leakage

Implement and test strict leakage prevention:

- Split by complete run ID, never by randomly shuffling individual windows.
- Fit scalers only on the training split.
- Perform hyperparameter selection using only training and validation data.
- Keep the final test split untouched until final evaluation.
- Ensure future target samples are never included in the input window.
- Ensure windows near the end of a run are discarded when a complete future horizon is unavailable.
- Do not let windows from the same run appear in multiple splits.
- Store split manifests so experiments can be reproduced exactly.

Create automated tests specifically for these rules.

### Target definition

For an input window ending at timestamp `t`, define the target as:

`max(memory.current)` strictly after `t`, over the configured prediction horizon.

The current sample at `t` must not be included in the future target.

The label implementation must handle:

- Irregular or missing samples.
- Run boundaries.
- Configurable sampling interval.
- Configurable history-window length.
- Configurable prediction horizon.
- Byte-to-MiB conversion without silent precision loss.

Write unit tests using tiny hand-calculated time series that make off-by-one errors obvious.

### PSI parsing

Linux `memory.pressure` contains `some` and `full` lines with values such as:

- `avg10`
- `avg60`
- `avg300`
- `total`

Parse these robustly.

Collect at least:

- `memory.current`
- `memory.max`
- `memory.high`
- `memory.events`
- `memory.stat`
- `memory.pressure`
- swap usage or swap events where available
- timestamps using a monotonic clock and wall-clock time
- container ID
- workload type
- run ID
- parameter configuration
- random seed

Do not treat `memory.pressure` averages as instantaneous measurements. Preserve both the kernel-provided averages and useful deltas of the cumulative `total` field.

Record missing or unsupported fields explicitly rather than silently replacing them with zero.

### PSI validation

Do not claim PSI is useful merely because the file exists.

Build a calibration procedure that confirms:

- PSI remains near zero for the steady-state workload.
- PSI remains low for reclaimable file-cache activity when the machine is not actually constrained.
- PSI rises or oscillates under genuinely constrained anonymous-memory workloads.
- The collector detects OOM and `memory.events` changes.
- Swap availability and behavior are recorded.

If PSI remains zero, diagnose the cause rather than manufacturing values or immediately moving on to model training.

Possible causes to inspect include:

- No real memory pressure.
- No swap.
- Container limit behavior.
- Host-level versus cgroup-level PSI.
- Too-slow sampling.
- Workload allocations being freed or optimized away.
- File cache being reclaimed normally.
- The Docker/WSL execution layer.

Store calibration plots and a short machine-readable validation report.

## Development phases

Work phase by phase. At the end of each phase:

1. Run the relevant automated tests.
2. Run a small end-to-end smoke test.
3. Update the README.
4. Write a short progress report containing:
   - Files created or changed.
   - Commands executed.
   - Tests passed or failed.
   - Remaining risks.
   - Exact next step.

Continue automatically when the phase succeeds. Stop only when:

- A permanent system modification needs approval.
- A requirement is genuinely ambiguous.
- The environment makes progress impossible.
- A test repeatedly fails and continuing would hide a correctness problem.

Do not stop simply to ask whether you should continue after ordinary successful phases.

## Phase 0 — Repository and environment foundation

First inspect the repository and preserve any useful existing content.

Create a clean structure similar to:

project-root/
  README.md
  pyproject.toml
  requirements/
  configs/
  src/
    psi_memory/
      common/
      environment/
      workloads/
      collector/
      dataset/
      features/
      models/
      controller/
      evaluation/
      dashboard/
  workloads/
  docker/
  scripts/
  tests/
    unit/
    integration/
  data/
    raw/
    processed/
    splits/
  artifacts/
    models/
    metrics/
    plots/
    reports/
  logs/

Use a proper Python package rather than relying on imports from arbitrary script directories.

Use Python 3.11.

Create a local virtual environment and dependency lock or pinned requirements.

Add:

- `.gitignore`
- configuration examples
- structured logging
- deterministic random-seed utilities
- version-report script
- a command to run all tests
- a minimal smoke-test command

Implement `validate_env` that reports, without mutating the system:

- OS and kernel.
- Python version.
- Docker client/server versions.
- Active Docker context.
- cgroup version.
- memory controller availability.
- PSI availability globally.
- per-container PSI visibility.
- readable cgroup paths.
- swap status.
- writable controller fields needed by the project.
- whether dynamic `memory.max` and `memory.high` updates are supported.
- expected limitations of Docker Desktop under WSL.

Output both human-readable text and JSON.

Do not declare Phase 0 complete until a temporary container can be started and its `memory.current` and `memory.pressure` can be sampled reliably.

## Phase 1 — Workloads, collector, and dashboard

Implement containerized workloads with configurable parameters and deterministic seeds.

Required workloads:

1. Steady state
   - Allocate and hold a stable working set.
   - Optional low-level background activity.
   - Expected low PSI.

2. Anonymous memory leak
   - Gradually allocate anonymous memory and retain it.
   - Configurable allocation step and interval.
   - Expected rising pressure under a sufficiently tight environment.

3. File-read burst
   - Repeatedly read a configurable large file.
   - Represent reclaimable page-cache activity.
   - Do not accidentally implement it as anonymous-memory retention.
   - Expected low PSI unless the whole environment is genuinely pressured.

4. Bursty batch
   - Alternate between allocation/compute phases and idle/free phases.
   - Configurable duty cycle, burst size, and period.
   - Expected oscillating behavior under constraint.

5. Trace replay
   - Implement the replay engine and input format even if a real external trace is not yet downloaded.
   - Include a small synthetic example trace for testing.
   - Keep external trace downloading separate and documented.

Avoid unnecessarily dangerous allocations. Workloads must be constrained to project containers and must support timeouts and clean shutdown.

Build a batch runner driven by YAML configuration. Each run must record:

- unique run ID
- workload
- parameters
- seed
- container image digest
- memory limit
- memory.high
- swap limit
- start/end times
- exit status
- OOM status
- environment validation ID
- collector configuration

The collector must:

- sample at a configurable interval, initially around one second
- use monotonic scheduling to reduce drift
- write atomically or flush safely
- tolerate a container exiting during collection
- detect malformed cgroup records
- preserve raw fields
- create one metadata record per run
- never merge different runs implicitly

Create a live Rich dashboard showing:

- current usage
- configured limit
- usage ratio
- PSI some/full values
- deltas of PSI total
- swap when available
- memory event counters
- container state
- elapsed run time

Add calibration configurations that complete quickly and longer data-collection configurations for later experiments.

## Phase 2 — Dataset and classical baselines

Implement a reproducible dataset builder.

Raw data must remain immutable. Processed datasets must record:

- source run IDs
- feature schema
- target definition
- history length
- horizon
- sampling assumptions
- code/config version
- split manifest

Create sequence features and tabular window summaries.

Without-PSI features should include conventional information such as:

- memory.current
- memory.max
- usage ratio
- memory growth
- slopes
- recent deltas
- mean
- max
- variance
- relevant memory.stat features
- swap information where consistently available

With-PSI variants must use the identical data rows, splits, model settings, and non-PSI features, with only PSI-derived columns added.

Implement:

1. Persistence predictor.
2. Rolling maximum or high-percentile heuristic inspired by production memory sizing.
3. Random Forest regressor.
4. XGBoost regressor.

Do not describe the heuristic as an exact reproduction of Google Autopilot unless the implementation truly matches the published system. Name it clearly as an “Autopilot-style percentile heuristic.”

Provide configuration-driven training and evaluation.

Save:

- fitted models
- scalers
- feature schema
- model metadata
- training configuration
- split IDs
- validation metrics
- feature importances

Run a minimal ablation experiment on small generated data before large-scale collection.

## Phase 3 — LSTM

Implement the LSTM only after the classical pipeline works.

Requirements:

- same run splits as the classical models
- same target definition
- with-PSI and without-PSI variants
- sequence normalization fitted only on training data
- reproducible initialization
- training and validation loss logging
- early stopping
- checkpointing
- CPU-compatible training
- configurable network depth, hidden size, learning rate, batch size, and epochs
- test-set evaluation only after final model selection

The LSTM is not automatically the preferred result. Report it honestly even if it does not outperform the tree models.

## Phase 4 — Closed-loop controller

Implement the controller with a dry-run mode first.

Controller modes:

1. Fixed limit.
2. Autopilot-style percentile heuristic.
3. Senpai-style reactive PSI control using `memory.high`.
4. Learned predictor with configurable model artifact.

Because this is an academic implementation, label the third mode “Senpai-style” unless it faithfully reproduces the original system.

Each control decision must log:

- timestamp
- observed metrics
- prediction or heuristic value
- requested limit
- applied limit
- reason for clipping
- previous limit
- live usage
- safety margin
- rewrite rate limiting
- model/version
- OOM and memory event state

Mandatory safety rules:

- never set `memory.max` below current live usage plus a configurable floor
- never apply nonpositive or malformed values
- enforce minimum and maximum allowed limits
- rate-limit increases and decreases
- apply optional smoothing or hysteresis
- avoid excessive cgroup writes
- use dry-run by default
- restore original limits after experiments when possible
- stop safely if the container exits
- record failed writes rather than hiding them

Test controller logic with a fake cgroup filesystem before using live containers.

## Phase 5 — Full evaluation

Implement experiment commands for:

1. PSI ablation at every model rung.
2. Held-out-run evaluation.
3. Parameter-shift evaluation.
4. Leave-one-workload-out evaluation.
5. Trace-replay evaluation.
6. Closed-loop comparison.
7. Error-distribution CDF.

Metrics:

- MAE
- RMSE
- optional normalized errors for cross-scale comparison
- underprediction frequency
- OOM events or demand-above-limit events
- average wasted headroom
- percentile wasted headroom
- limit rewrite count
- time spent under pressure
- controller stability

For closed-loop results, report OOM rate and wasted headroom jointly across several safety margins as a trade-off curve. Do not present one arbitrary margin as the sole conclusion.

Report results:

- overall
- per workload
- with confidence intervals where practical
- across multiple independent seeds
- with exact sample and run counts

Figures should include:

- representative time-series plots
- predicted versus actual future peak
- PSI versus usage examples
- with-PSI versus without-PSI model comparison
- feature importance for tree models
- OOM/headroom trade-off curves
- error CDFs
- per-workload results
- generalization results

Plots must be generated by scripts from stored results, not manually edited.

## Testing requirements

Use `pytest`.

At minimum, include tests for:

- PSI parser.
- `memory.max` handling when its value is `max`.
- Byte-unit conversion.
- Future-peak label indexing.
- Run-boundary handling.
- Missing-sample handling.
- Split leakage.
- Training-only scaler fitting.
- With/without-PSI feature parity.
- Baseline correctness.
- Controller clipping and rate limits.
- Fake-cgroup writes.
- Collector behavior when a container exits.
- Metadata serialization.
- Reproducibility with fixed seeds.

Add integration tests for:

- temporary container metric collection
- a short workload run
- raw-to-processed dataset generation
- model training on a tiny dataset
- dry-run controller execution
- plot generation

Keep slow live-container tests marked separately.

## Data-quality gates

Do not train final models merely because CSV files exist.

Before accepting a data-collection batch, verify:

- timestamps are monotonic
- sampling gaps are within tolerance
- required fields are present
- no mixed run IDs
- units are consistent
- enough future horizon remains for labels
- OOM/event counters are interpreted correctly
- target distributions are nontrivial
- PSI is not universally missing
- PSI is not universally zero in workloads expected to induce pressure
- the dataset contains both pressured and nonpressured situations
- each split contains complete independent runs

Produce a data-quality report and fail the pipeline when critical checks fail.

## Documentation

The final README must provide exact commands for:

- environment validation
- setting up the Python environment
- building workload images
- running a calibration workload
- collecting a small dataset
- collecting a full batch
- monitoring live metrics
- building the processed dataset
- training every model
- running ablations
- running the controller in dry-run mode
- running live-controller experiments
- producing all figures
- running tests
- reproducing the final results

Also include:

- architecture diagram
- data schema
- repository map
- explanation of cgroup v2 files
- Docker Desktop/WSL caveats
- safety notes
- known limitations
- exact distinction between offline prediction and online control
- a reproducibility checklist
- a Generative AI usage declaration placeholder consistent with the proposal

## Final completion criteria

Do not call the project complete until all of the following are true:

- Environment validation passes or limitations are documented precisely.
- Per-container memory and PSI collection works.
- All required workloads exist.
- Calibration demonstrates meaningful expected signal behavior, or failed expectations are documented honestly.
- Dataset generation is tested and leakage-safe.
- All baseline models run.
- Both PSI and no-PSI variants run.
- LSTM runs.
- Closed-loop dry-run and live modes work.
- All required evaluation metrics and figures are produced.
- Tests pass.
- README commands work from a fresh setup as far as the environment allows.
- A final report summarizes what was implemented, what was measured, what remains uncertain, and whether the evidence supports the PSI hypothesis.

## Start now

Begin with these actions:

1. Inspect the repository.
2. Re-read the proposal PDF.
3. Create `docs/requirements_traceability.md`, mapping each proposal requirement to planned code, tests, and outputs.
4. Run non-destructive environment inspection.
5. Design the initial repository structure.
6. Implement Phase 0.
7. Continue through the later phases automatically when tests pass.

In your first response, show:

- the requirement traceability summary
- the environment findings
- the exact Docker/cgroup collection approach you selected
- repository structure
- Phase 0 implementation plan
- risks or assumptions that still need validation

Then begin implementing it. Do not stop at another high-level plan.