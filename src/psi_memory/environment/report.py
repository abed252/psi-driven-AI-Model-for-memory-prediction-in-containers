"""Environment-validation report structure and rendering (text + JSON)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "warn" | "fail" | "skip"
    details: str
    data: dict = field(default_factory=dict)


@dataclass
class EnvReport:
    created_at: str
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, name: str, status: str, details: str, **data) -> None:
        assert status in ("pass", "warn", "fail", "skip")
        self.checks.append(CheckResult(name, status, details, data))

    @property
    def ok(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    @property
    def validation_id(self) -> str:
        """Stable ID for runs to reference which environment they ran under."""
        body = json.dumps([asdict(c) for c in self.checks], sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:12]

    def to_json(self) -> str:
        return json.dumps(
            {
                "validation_id": self.validation_id,
                "created_at": self.created_at,
                "overall": "pass" if self.ok else "fail",
                "checks": [asdict(c) for c in self.checks],
            },
            indent=2,
        )

    def save(self, reports_dir: Path) -> Path:
        reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = reports_dir / f"env_validation_{stamp}_{self.validation_id}.json"
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def render_text(self) -> str:
        icons = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}
        width = max(len(c.name) for c in self.checks) if self.checks else 0
        lines = [f"Environment validation — {self.created_at}", ""]
        for c in self.checks:
            lines.append(f"[{icons[c.status]:4}] {c.name:<{width}}  {c.details}")
        lines.append("")
        lines.append(f"Overall: {'PASS' if self.ok else 'FAIL'}   id={self.validation_id}")
        return "\n".join(lines)


def new_report() -> EnvReport:
    return EnvReport(created_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
