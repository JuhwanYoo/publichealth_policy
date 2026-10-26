"""이미 처리한 항목 기록 (data/seen.json). 재요약을 막는다."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

RETENTION_DAYS = 60


class SeenState:
    def __init__(self, path: Path):
        self.path = path
        self._seen: dict[str, str] = {}   # item id -> ISO 날짜(처음 본 시각)
        if path.exists():
            try:
                self._seen = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._seen = {}

    def __contains__(self, item_id: str) -> bool:
        return item_id in self._seen

    def mark(self, item_ids: list[str], now: datetime) -> None:
        stamp = now.astimezone(timezone.utc).isoformat()
        for item_id in item_ids:
            self._seen.setdefault(item_id, stamp)

    def prune(self, now: datetime) -> None:
        cutoff = now.astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS)
        self._seen = {
            k: v for k, v in self._seen.items()
            if datetime.fromisoformat(v) >= cutoff
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._seen, indent=0, sort_keys=True), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._seen)
