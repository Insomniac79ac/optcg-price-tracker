"""One JSON health line per run (plan §2.4): pages, header totals vs ids seen, parse failures,
identity outcomes, bytes fetched and stored."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class RunReport:
    source: str
    parser_version: str
    started_at: datetime
    pages_planned: int = 0
    pages_fetched: int = 0
    pages_failed: int = 0
    requests: int = 0
    bytes_fetched: int = 0
    raw_rows: int = 0
    raw_bytes_stored: int = 0
    header_total: int = 0
    rows_parsed: int = 0
    parse_failures: int = 0
    products_new: int = 0
    variants_written: int = 0
    observations_written: int = 0
    outcomes: Counter = field(default_factory=Counter)
    stopped: str | None = None
    finished_at: datetime | None = None

    def to_log(self) -> str:
        payload = asdict(self)
        payload["event"] = "source_collector_run"
        payload["outcomes"] = dict(sorted(self.outcomes.items()))
        return json.dumps(payload, default=lambda v: v.isoformat(), ensure_ascii=False, sort_keys=True)
