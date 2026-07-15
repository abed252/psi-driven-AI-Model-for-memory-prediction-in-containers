"""Dashboard rendering logic (pure functions, no Docker)."""

from psi_memory.dashboard.live import build_view, format_bytes, stall_delta_ms


def make_sample(total_some=50_000, total_full=10_000):
    return {
        "type": "sample", "mono": 10.0, "wall": 0.0,
        "current": 128 * 1024 * 1024, "max": 256 * 1024 * 1024, "high": "max",
        "swap_current": 0, "swap_max": 256 * 1024 * 1024,
        "pressure": {
            "some": {"avg10": 1.5, "avg60": 0.5, "avg300": 0.1, "total": total_some},
            "full": {"avg10": 0.2, "avg60": 0.1, "avg300": 0.0, "total": total_full},
        },
        "events": {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0},
        "missing": [],
    }


def test_format_bytes():
    assert format_bytes(256 * 1024 * 1024) == "256.0 MiB"
    assert format_bytes("max") == "max (unlimited)"
    assert format_bytes(None) == "—"


def test_stall_delta():
    previous = make_sample(total_some=50_000)
    current = make_sample(total_some=125_000)
    assert stall_delta_ms(current, previous, "some") == 75.0
    assert stall_delta_ms(current, None, "some") is None


def test_build_view_renders():
    from rich.console import Console

    view = build_view(make_sample(), make_sample(total_some=10_000),
                      container_state="running", elapsed_s=12.5)
    console = Console(record=True, width=100)
    console.print(view)
    text = console.export_text()
    assert "memory.current" in text and "128.0 MiB" in text
    assert "50.0%" in text          # usage ratio
    assert "avg10" in text and "oom_kill=0" in text
