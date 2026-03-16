from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CONFIG_PATH = "config.json"
_MISSING = object()


def resolve_config_path(explicit_path: str | None = None) -> str | None:
    """Resolve config path from CLI or local file discovery."""
    if explicit_path:
        return explicit_path

    default_path = Path(DEFAULT_CONFIG_PATH)
    if default_path.exists():
        return str(default_path)

    return None


def load_json_config(explicit_path: str | None = None) -> tuple[str | None, dict[str, Any]]:
    """Load optional JSON config and return the resolved path and data."""
    config_path = resolve_config_path(explicit_path)
    if config_path is None:
        return None, {}

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a JSON object at the top level: {path}")

    return str(path), data


def get_config_value(config: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """Read a nested config value using a key path."""
    current: Any = config
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def get_first_config_value(config: Mapping[str, Any], *paths: tuple[str, ...], default: Any = None) -> Any:
    """Return the first value found across several alternative config paths."""
    for path in paths:
        value = get_config_value(config, *path, default=_MISSING)
        if value is not _MISSING:
            return value
    return default