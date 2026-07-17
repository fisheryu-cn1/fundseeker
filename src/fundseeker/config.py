"""Configuration loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "institutions.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML configuration file."""
    if path is None:
        path = DEFAULT_CONFIG_PATH
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_institution_config(
    config: dict[str, Any], code: str
) -> dict[str, Any] | None:
    """Find configuration for a specific institution code."""
    for inst in config.get("institutions", []):
        if inst.get("code") == code:
            return inst
    return None
