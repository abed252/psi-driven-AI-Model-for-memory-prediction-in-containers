import pytest

from psi_memory.collector.parsers import parse_keyed_counters, parse_psi

REAL_PSI = """some avg10=1.50 avg60=0.75 avg300=0.10 total=123456
full avg10=0.30 avg60=0.10 avg300=0.00 total=6789
"""


def test_parse_real_psi_content():
    sample = parse_psi(REAL_PSI)
    assert sample.some.avg10 == 1.50
    assert sample.some.avg60 == 0.75
    assert sample.some.avg300 == 0.10
    assert sample.some.total_us == 123456
    assert sample.full is not None
    assert sample.full.avg10 == 0.30
    assert sample.full.total_us == 6789


def test_parse_psi_all_zero():
    sample = parse_psi(
        "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    )
    assert sample.some.avg10 == 0.0
    assert sample.some.total_us == 0


def test_parse_psi_without_full_line():
    # The CPU controller omits `full`; the parser must report None, not 0.
    sample = parse_psi("some avg10=0.05 avg60=0.02 avg300=0.00 total=42\n")
    assert sample.full is None
    assert sample.some.total_us == 42


def test_parse_psi_rejects_empty():
    with pytest.raises(ValueError):
        parse_psi("")


def test_parse_psi_rejects_malformed_token():
    with pytest.raises(ValueError):
        parse_psi("some avg10=0.00 avg60 avg300=0.00 total=0")


def test_parse_psi_rejects_missing_field():
    with pytest.raises(ValueError):
        parse_psi("some avg10=0.00 avg60=0.00 total=0")


def test_parse_memory_events():
    counters = parse_keyed_counters(
        "low 0\nhigh 3\nmax 7\noom 1\noom_kill 1\noom_group_kill 0\n"
    )
    assert counters == {"low": 0, "high": 3, "max": 7, "oom": 1,
                        "oom_kill": 1, "oom_group_kill": 0}


def test_parse_keyed_counters_rejects_garbage():
    with pytest.raises(ValueError):
        parse_keyed_counters("oom one\n")
