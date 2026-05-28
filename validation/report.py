"""ValidationReport dataclass + JSON serializer."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ValidationReport:
    vol: int
    passed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    row_count: int = 0
    law_count: int = 0
    timestamp: Optional[str] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    @property
    def status(self) -> str:
        if self.failed:
            return "failed"
        if self.warnings:
            return "warning"
        return "passed"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def to_file(self, path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json())
