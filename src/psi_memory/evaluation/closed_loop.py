"""Closed-loop comparison (spec experiment 6).

Runs each controller mode on freshly started, identically seeded workload
containers and scores the outcomes from the decision logs:

- OOM events and demand-above-limit (memory.events `max`) growth
- average / p95 wasted headroom (enforced limit minus live usage)
- limit rewrite count and controller stability (distinct applied values)
- time under pressure (fraction of steps with PSI some avg10 > threshold)

Margin-sensitive modes (percentile, learned) run once per safety margin so
OOM-vs-headroom can be reported as a trade-off curve, not one arbitrary
point.
"""

from __future__ import annotations

import copy
import json
import logging
import time
import uuid
from pathlib import Path

import numpy as np

from psi_memory.controller.loop import run_live
from psi_memory.environment.docker_cli import run_docker
from psi_memory.workloads.config import WORKLOAD_SCRIPTS

log = logging.getLogger(__name__)

MIB = 1024 * 1024
PRESSURE_THRESHOLD_AVG10 = 5.0


def session_metrics(session_dir: Path) -> dict:
    """Outcome metrics computed from a controller session's decision log."""
    decisions = [json.loads(line) for line in
                 (session_dir / "decisions.jsonl").read_text(encoding="utf-8")
                 .splitlines()]
    meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    if not decisions:
        return {"session": session_dir.name, "steps": 0, "empty": True}

    target = decisions[0]["target"]
    headrooms, limits, psi_high_steps = [], [], 0
    max_events_first = max_events_last = None
    oom_kills = 0
    for decision in decisions:
        observed = decision["observed"]
        usage = observed["current_mib"]
        raw_limit = (observed["memory_max"] if target == "memory.max"
                     else observed["memory_high"])
        if isinstance(raw_limit, (int, float)) and not isinstance(raw_limit, bool):
            limit_mib = raw_limit / MIB
            headrooms.append(limit_mib - usage)
            limits.append(limit_mib)
        psi = observed.get("psi_some_avg10")
        if psi is not None and psi > PRESSURE_THRESHOLD_AVG10:
            psi_high_steps += 1
        events = observed.get("events") or {}
        if max_events_first is None:
            max_events_first = events.get("max", 0)
        max_events_last = events.get("max", max_events_last)
        oom_kills = max(oom_kills, events.get("oom_kill", 0))

    headrooms_arr = np.asarray(headrooms, dtype=float)
    limits_arr = np.asarray(limits, dtype=float)
    return {
        "session": session_dir.name,
        "mode": meta["mode"],
        "steps": len(decisions),
        "writes": meta.get("writes", 0),
        "failed_writes": meta.get("failed_writes", 0),
        "oom_kill_events": int(oom_kills),
        "demand_above_limit_events": int((max_events_last or 0)
                                         - (max_events_first or 0)),
        "avg_headroom_mib": float(headrooms_arr.mean()) if len(headrooms_arr) else None,
        "p95_headroom_mib": (float(np.percentile(headrooms_arr, 95))
                             if len(headrooms_arr) else None),
        "time_under_pressure_frac": psi_high_steps / len(decisions),
        "limit_changes": int((np.abs(np.diff(limits_arr)) > 0.5).sum())
                          if len(limits_arr) > 1 else 0,
        "limit_std_mib": float(limits_arr.std()) if len(limits_arr) else None,
        "end_reason": meta.get("end_reason"),
        "target": target,
    }


SCENARIOS = {
    "bursty": {"workload": "bursty", "duration_s": 150,
               "memory_limit": "512m", "memory_swap": "1g",
               "params": {"burst_mib": 220, "hold_s": 10, "idle_s": 10,
                          "duration_s": 170, "seed": 424242}},
    "leak": {"workload": "leak", "duration_s": 150,
             "memory_limit": "512m", "memory_swap": "1g",
             "params": {"step_mib": 2, "tick_s": 1.0, "retouch_fraction": 0.3,
                        "duration_s": 170, "seed": 424242}},
}


def _start_scenario_container(name: str, scenario: dict, image: str) -> None:
    args = []
    for key, value in sorted(scenario["params"].items()):
        args.extend([f"--{key.replace('_', '-')}", str(value)])
    run_docker("run", "-d", "--name", name,
               "--memory", scenario["memory_limit"],
               "--memory-swap", scenario["memory_swap"],
               image, "python", f"/app/{WORKLOAD_SCRIPTS[scenario['workload']]}",
               *args)


def run_comparison(
    controller_config: dict,
    model_artifacts: dict[str, Path],   # {"learned_no_psi": ..., "learned_with_psi": ...}
    margins: list[float],
    metrics_dir: Path,
    out_root: Path = Path("artifacts/controller/closed_loop"),
    scenarios: dict | None = None,
    image: str = "psi-workloads:latest",
) -> dict:
    """Run every mode (x margins where applicable) on identical scenarios."""
    scenarios = scenarios or SCENARIOS
    mode_specs = [("fixed", "fixed", None, None)]
    mode_specs += [("percentile", "percentile", m, None) for m in margins]
    mode_specs.append(("senpai", "senpai", None, None))
    for tag, artifact in model_artifacts.items():
        mode_specs += [(tag, "learned", m, Path(artifact)) for m in margins]

    # Resumability: every finished session is appended to an index file; a
    # re-run after a crash/sleep skips combos that are already recorded.
    out_root.mkdir(parents=True, exist_ok=True)
    index_path = out_root / "session_index.jsonl"
    done: set[tuple] = set()
    sessions = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            done.add((record["scenario"], record["label"], record["margin"]))
            sessions.append(record)
        log.info("resuming: %d sessions already recorded", len(sessions))

    for scenario_name, scenario in scenarios.items():
        for tag, mode, margin, artifact in mode_specs:
            if (scenario_name, tag, margin) in done:
                continue
            config = copy.deepcopy(controller_config)
            if margin is not None:
                config.setdefault("percentile", {})["margin_frac"] = margin
                config.setdefault("learned", {})["margin_frac"] = margin
            container = f"psi-cl-{uuid.uuid4().hex[:8]}"
            label = f"{scenario_name}/{tag}" + (f"@{margin}" if margin is not None else "")
            log.info("closed-loop session: %s", label)
            _start_scenario_container(container, scenario, image)
            try:
                summary = run_live(container, mode, config,
                                   duration_s=scenario["duration_s"],
                                   live=True, model_artifact=artifact,
                                   out_root=out_root)
                session_dir = out_root / summary["session_id"]
                outcome = session_metrics(session_dir)
                inspect = run_docker("inspect", "-f", "{{json .State}}",
                                     container, check=False)
                if inspect.returncode == 0:
                    state = json.loads(inspect.stdout)
                    outcome["oom_killed_flag"] = bool(state.get("OOMKilled"))
                    outcome["oom_kill_events"] = max(
                        outcome["oom_kill_events"],
                        int(bool(state.get("OOMKilled"))))
                record = {"scenario": scenario_name, "label": tag,
                          "mode": mode, "margin": margin,
                          "model": str(artifact) if artifact else None,
                          **outcome}
                sessions.append(record)
                with open(index_path, "a", encoding="utf-8") as index:
                    index.write(json.dumps(record) + "\n")
            finally:
                run_docker("rm", "-f", container, check=False)

    report = {"experiment": "closed_loop_comparison",
              "margins": margins,
              "scenarios": {k: v for k, v in scenarios.items()},
              "pressure_threshold_avg10": PRESSURE_THRESHOLD_AVG10,
              "sessions": sessions,
              "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / f"closed_loop_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("closed-loop report: %s (%d sessions)", path, len(sessions))
    return report
