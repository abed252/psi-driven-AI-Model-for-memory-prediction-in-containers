"""The control loop: samples -> policy -> safety gate -> actuator -> log.

`run_session` is source/actuator-agnostic so the whole loop is testable with
fake components (spec: test with a fake cgroup filesystem before live use).
`run_live` wires it to a real container: sampler-sidecar metrics, dry-run by
default, original limits restored afterwards.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from psi_memory.common.units import MIB
from psi_memory.controller.policies import make_policy
from psi_memory.controller.safety import SafetyConfig, SafetyGate
from psi_memory.controller.window import SignalWindow

log = logging.getLogger(__name__)


def run_session(
    samples,                    # iterable of sampler records (dicts)
    policy,
    gate: SafetyGate,
    actuator,
    out_dir: Path,
    session_meta: dict,
    dry_run: bool = True,
    history_samples: int = 30,
    max_steps: int | None = None,
) -> dict:
    """Drive the control loop over a sample stream; returns a summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    window = SignalWindow(history_samples)
    previous_limit_mib: float | None = None
    initial_limits: dict = {}
    steps = writes = failed_writes = 0
    end_reason = "stream_end"

    with open(out_dir / "decisions.jsonl", "w", encoding="utf-8") as decisions:
        for record in samples:
            if record.get("type") == "end":
                end_reason = f"target:{record.get('reason', 'unknown')}"
                break
            if record.get("type") != "sample":
                continue
            if not initial_limits:
                initial_limits = {
                    "memory.max": str(record.get("max")),
                    "memory.high": str(record.get("high")),
                    "memory.swap.max": str(record.get("swap_max")),
                }
            window.push(record)
            if not window.ready:
                continue
            steps += 1

            usage_mib = record["current"] / MIB
            proposal = policy.propose(window)
            if previous_limit_mib is None:
                observed = record.get("max") if proposal.target == "memory.max" \
                    else record.get("high")
                previous_limit_mib = (observed / MIB if isinstance(observed, int)
                                      else proposal.value_mib)

            verdict = gate.evaluate(proposal.value_mib, usage_mib,
                                    previous_limit_mib, record["mono"])
            write_result = None
            if verdict.applied_mib is not None:
                write_result = actuator.apply(proposal.target, verdict.applied_mib)
                writes += 1
                if write_result.ok:
                    previous_limit_mib = verdict.applied_mib
                else:
                    failed_writes += 1

            psi = record.get("pressure") or {}
            decision = {
                "ts_wall": record["wall"], "ts_mono": record["mono"],
                "step": steps, "mode": policy.name, "target": proposal.target,
                "observed": {
                    "current_mib": usage_mib,
                    "memory_max": record.get("max"),
                    "memory_high": record.get("high"),
                    "swap_current_mib": (record.get("swap_current") or 0) / MIB,
                    "psi_some_avg10": psi.get("some", {}).get("avg10"),
                    "events": record.get("events"),
                },
                "prediction_mib": proposal.raw_prediction_mib,
                "policy_detail": proposal.detail,
                "requested_mib": verdict.requested_mib,
                "applied_mib": verdict.applied_mib,
                "clip_reasons": verdict.clip_reasons,
                "rate_limited": verdict.rate_limited,
                "skipped": verdict.skipped,
                "prev_limit_mib": previous_limit_mib,
                "live_usage_mib": usage_mib,
                "safety": asdict(gate.config),
                "model": session_meta.get("model_artifact"),
                "dry_run": dry_run,
                "write": (asdict(write_result) if write_result else None),
            }
            decisions.write(json.dumps(decision) + "\n")
            decisions.flush()
            if max_steps and steps >= max_steps:
                end_reason = "max_steps"
                break

    summary = {
        **session_meta,
        "steps": steps, "writes": writes, "failed_writes": failed_writes,
        "end_reason": end_reason, "dry_run": dry_run,
        "initial_limits": initial_limits,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out_dir / "meta.json").write_text(json.dumps(summary, indent=2),
                                       encoding="utf-8")
    log.info("controller session %s: %d steps, %d writes (%d failed), %s",
             session_meta.get("session_id"), steps, writes, failed_writes,
             end_reason)
    return summary


def run_live(
    container: str,
    mode: str,
    config: dict,
    duration_s: float,
    live: bool = False,
    model_artifact: Path | None = None,
    out_root: Path = Path("artifacts/controller"),
) -> dict:
    """Run the controller against a live container (dry-run unless live)."""
    from psi_memory.collector.stream import stream_samples
    from psi_memory.controller.actuator import DockerActuator, DryRunActuator
    from psi_memory.environment.probe import container_id

    controller_cfg = config.get("controller", {})
    interval_s = float(controller_cfg.get("interval_s", 1.0))
    history = int(controller_cfg.get("history_samples", 30))
    safety = SafetyConfig(**config.get("safety", {}))
    if mode == "senpai":
        safety.enforce_usage_floor = False  # squeezing below usage is the point

    session_id = f"{mode}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    out_dir = out_root / session_id
    cid = container_id(container)
    policy = make_policy(mode, config, model_artifact)
    actuator = DockerActuator(container) if live else DryRunActuator()
    gate = SafetyGate(safety)
    max_steps = int(duration_s / interval_s) if duration_s else None

    session_meta = {
        "session_id": session_id, "container": container, "cid": cid,
        "mode": mode, "live": live, "config": config,
        "model_artifact": str(model_artifact) if model_artifact else None,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    samples = stream_samples(cid, interval_s,
                             max_samples=(max_steps + history + 2) if max_steps else 0,
                             sidecar_name=f"psi-ctl-{session_id}")
    summary = run_session(samples, policy, gate, actuator, out_dir,
                          session_meta, dry_run=not live,
                          history_samples=history, max_steps=max_steps)

    if live and summary["writes"] > summary["failed_writes"]:
        restored = {}
        initial = summary["initial_limits"]
        target = policy.target
        original = initial.get(target, "")
        if original and original != "None":
            result = actuator.restore(
                target, original, original_swap=initial.get("memory.swap.max"))
            restored[target] = {"ok": result.ok, "error": result.error}
            log.info("restored %s to %s: %s", target, original,
                     "ok" if result.ok else result.error)
        summary["restored"] = restored
        (out_dir / "meta.json").write_text(json.dumps(summary, indent=2),
                                           encoding="utf-8")
    return summary
