"""Loads and validates YAML/JSON configuration."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .errors import ValidationError

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
REQUIRED_REGION_KEYS = ("id", "country", "name", "lat", "lon", "timezone", "stations", "providers")
WEIGHT_KEYS = ("temperature", "moisture", "wetness", "rain", "wind", "sun")


def _yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict:
    with open(config_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_regions(config_dir: Path = CONFIG_DIR) -> list[dict]:
    regions = _yaml("regions.yaml", config_dir)["regions"]
    ids = set()
    for r in regions:
        missing = [k for k in REQUIRED_REGION_KEYS if k not in r]
        if missing:
            raise ValidationError(f"region {r.get('id')}: missing keys {missing}")
        if not {"en", "fr"} <= set(r["name"]):
            raise ValidationError(f"region {r['id']}: name needs 'en' and 'fr'")
        if not (-90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180):
            raise ValidationError(f"region {r['id']}: invalid coordinates")
        if r["id"] in ids:
            raise ValidationError(f"duplicate region id {r['id']}")
        ids.add(r["id"])
        from zoneinfo import ZoneInfo
        ZoneInfo(r["timezone"])  # raises if unknown
    return regions


def load_scoring(config_dir: Path = CONFIG_DIR) -> dict:
    cfg = _yaml("scoring.yaml", config_dir)
    for mode, m in cfg["modes"].items():
        if set(m["weights"]) != set(WEIGHT_KEYS):
            raise ValidationError(f"mode {mode}: weights must be exactly {WEIGHT_KEYS}")
        lo, hi = m["temp_ideal_c"]
        if lo >= hi:
            raise ValidationError(f"mode {mode}: temp_ideal_c must be [low, high]")
    return cfg


def load_pipeline(config_dir: Path = CONFIG_DIR) -> dict:
    return _yaml("pipeline.yaml", config_dir)


def load_tips(config_dir: Path = CONFIG_DIR) -> dict:
    return _yaml("tips.yaml", config_dir)


def load_i18n(config_dir: Path = CONFIG_DIR) -> dict:
    out = {}
    for p in sorted((config_dir / "i18n").glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out
