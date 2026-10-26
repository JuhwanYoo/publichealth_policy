"""config/sources.yaml 로딩 (profile 기본값 병합)."""

from __future__ import annotations

from pathlib import Path

import yaml

from policybrief.models import Source

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
KEYWORDS_PATH = CONFIG_DIR / "keywords.yaml"


def load_sources(path: Path = SOURCES_PATH, include_disabled: bool = False) -> list[Source]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults: dict[str, dict] = data.get("defaults", {})
    sources: list[Source] = []
    for raw in data.get("sources", []):
        raw = dict(raw)
        profile = raw.pop("profile", None)
        merged = {**defaults.get(profile, {}), **raw}
        source = Source.model_validate(merged)
        if source.enabled or include_disabled:
            sources.append(source)
    return sources
