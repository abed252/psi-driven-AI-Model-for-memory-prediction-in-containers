"""Data-quality gates on synthetic raw runs."""

import json

import pytest

from psi_memory.dataset.loader import RawDataError, load_run
from psi_memory.dataset.quality import check_runs


def load_all(factory):
    from psi_memory.dataset.loader import discover_runs

    return [load_run(d) for d in discover_runs(factory.dir)]


def test_healthy_collection_passes(synth_raw):
    synth_raw.add("steady-01", workload="steady")
    synth_raw.add("leak-01", workload="leak",
                  psi_avg10_fn=lambda i: min(i * 0.2, 20.0), oom=True)
    report = check_runs(load_all(synth_raw), interval_s=1.0, max_gap_factor=2.5)
    assert report.ok


def test_zero_psi_in_pressure_workloads_is_critical(synth_raw):
    synth_raw.add("steady-01", workload="steady")
    synth_raw.add("leak-01", workload="leak", psi_avg10_fn=lambda i: 0.0)
    report = check_runs(load_all(synth_raw), 1.0, 2.5)
    assert not report.ok
    failed = {c["name"] for c in report.checks
              if c["level"] == "critical" and not c["passed"]}
    assert "pressure_workloads_show_psi" in failed


def test_no_quiet_runs_is_critical(synth_raw):
    synth_raw.add("leak-01", workload="leak", psi_avg10_fn=lambda i: 10.0)
    report = check_runs(load_all(synth_raw), 1.0, 2.5)
    assert not report.ok  # dataset must contain non-pressured situations too


def test_non_monotonic_timestamps_rejected_at_load(synth_raw, tmp_path):
    run_dir = synth_raw.add("steady-01", workload="steady")
    # Corrupt: swap two samples' order.
    lines = (run_dir / "samples.jsonl").read_text().splitlines()
    lines[3], lines[4] = lines[4], lines[3]
    (run_dir / "samples.jsonl").write_text("\n".join(lines))
    with pytest.raises(RawDataError, match="non-monotonic"):
        load_run(run_dir)


def test_run_id_mismatch_rejected(synth_raw):
    run_dir = synth_raw.add("steady-01", workload="steady")
    meta = json.loads((run_dir / "meta.json").read_text())
    meta["run_id"] = "some-other-run"
    (run_dir / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(RawDataError, match="mixed runs"):
        load_run(run_dir)


def test_oom_exitcode_inconsistency_warns(synth_raw):
    run_dir = synth_raw.add("leak-01", workload="leak",
                            psi_avg10_fn=lambda i: 10.0, oom=True)
    meta = json.loads((run_dir / "meta.json").read_text())
    meta["exit_code"] = 0
    (run_dir / "meta.json").write_text(json.dumps(meta))
    synth_raw.add("steady-01", workload="steady")
    report = check_runs(load_all(synth_raw), 1.0, 2.5)
    warnings = [c for c in report.checks
                if c["name"].startswith("oom_consistency") and not c["passed"]]
    assert warnings and report.ok  # warning, not fatal
