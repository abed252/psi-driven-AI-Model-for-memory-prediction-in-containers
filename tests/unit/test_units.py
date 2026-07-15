import pytest

from psi_memory.common.units import bytes_to_mib, mib_to_bytes, parse_cgroup_scalar


def test_parse_scalar_plain_number():
    assert parse_cgroup_scalar("268435456\n") == 268435456


def test_parse_scalar_max_means_none_not_zero():
    # memory.max == "max" means unlimited; it must never become 0.
    assert parse_cgroup_scalar("max\n") is None


def test_parse_scalar_rejects_garbage():
    with pytest.raises(ValueError):
        parse_cgroup_scalar("banana")


def test_parse_scalar_rejects_negative():
    with pytest.raises(ValueError):
        parse_cgroup_scalar("-5")


def test_bytes_to_mib_exact_for_mib_multiples():
    assert bytes_to_mib(268435456) == 256.0
    assert bytes_to_mib(1048576) == 1.0


def test_bytes_to_mib_no_silent_truncation():
    # 1 MiB + 1 byte must not round to exactly 1.0.
    assert bytes_to_mib(1048577) > 1.0


def test_mib_to_bytes_round_trip():
    assert mib_to_bytes(256) == 268435456
    assert mib_to_bytes(0.5) == 524288


def test_mib_to_bytes_rejects_fractional_bytes():
    with pytest.raises(ValueError):
        mib_to_bytes(1e-9)
