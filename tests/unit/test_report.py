import json

from psi_memory.environment.report import new_report


def make_report():
    report = new_report()
    report.add("a.check", "pass", "fine", value=1)
    report.add("b.check", "warn", "meh")
    return report


def test_json_round_trip(tmp_path):
    report = make_report()
    parsed = json.loads(report.to_json())
    assert parsed["overall"] == "pass"
    assert parsed["checks"][0]["name"] == "a.check"
    assert parsed["checks"][0]["data"] == {"value": 1}
    saved = report.save(tmp_path)
    assert json.loads(saved.read_text())["validation_id"] == report.validation_id


def test_fail_check_fails_overall():
    report = make_report()
    report.add("c.check", "fail", "broken")
    assert not report.ok
    assert json.loads(report.to_json())["overall"] == "fail"


def test_validation_id_stable_for_same_checks():
    assert make_report().validation_id == make_report().validation_id


def test_render_text_contains_statuses():
    text = make_report().render_text()
    assert "PASS" in text and "WARN" in text and "a.check" in text
