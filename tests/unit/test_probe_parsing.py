"""Sidecar probe output parsing, without Docker."""

import pytest

from psi_memory.environment.probe import _parse_probe_output

GOOD_OUTPUT = """SAMPLE 100.25
3588096
some avg10=0.00 avg60=0.00 avg300=0.00 total=0
full avg10=0.00 avg60=0.00 avg300=0.00 total=0
END
SAMPLE 101.25
3600000
some avg10=0.10 avg60=0.02 avg300=0.00 total=1500
full avg10=0.00 avg60=0.00 avg300=0.00 total=0
END
"""


def test_parses_two_samples():
    samples = _parse_probe_output(GOOD_OUTPUT)
    assert len(samples) == 2
    assert samples[0].uptime_s == 100.25
    assert samples[0].current_bytes == 3588096
    assert samples[1].pressure.some.avg10 == 0.10
    assert samples[1].pressure.some.total_us == 1500


def test_timestamps_monotonic_in_fixture():
    samples = _parse_probe_output(GOOD_OUTPUT)
    assert samples[1].uptime_s > samples[0].uptime_s


def test_rejects_truncated_block():
    with pytest.raises(ValueError):
        _parse_probe_output("SAMPLE 100.0\n3588096\nEND\n")
