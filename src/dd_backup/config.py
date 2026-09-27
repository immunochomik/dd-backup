"""Configuration and dashboard selection rules."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
import tomllib
from typing import Any


def _patterns(values: Any, name: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
        raise ValueError(f"{name} must be a list of nonempty strings")
    return tuple(values)


def _matches(value: str, patterns: tuple[str, ...]) -> bool:
    folded = value.casefold()
    return any(fnmatchcase(folded, pattern.casefold()) for pattern in patterns)


@dataclass(frozen=True)
class Selection:
    include_ids: tuple[str, ...] = ()
    include_titles: tuple[str, ...] = ()
    include_tags: tuple[str, ...] = ()
    exclude_ids: tuple[str, ...] = ()
    exclude_titles: tuple[str, ...] = ()
    exclude_tags: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> Selection:
        return cls(**{name: _patterns(data.get(name, []), name) for name in cls.__dataclass_fields__})

    def matches(self, dashboard: dict[str, Any]) -> bool:
        dashboard_id = str(dashboard.get("id", ""))
        title = str(dashboard.get("title", ""))
        tags = dashboard.get("tags") or []
        if not isinstance(tags, list):
            tags = []

        if (
            _matches(dashboard_id, self.exclude_ids)
            or _matches(title, self.exclude_titles)
            or any(_matches(str(tag), self.exclude_tags) for tag in tags)
        ):
            return False

        has_include_rules = bool(self.include_ids or self.include_titles or self.include_tags)
        if not has_include_rules:
            return True
        return (
            _matches(dashboard_id, self.include_ids)
            or _matches(title, self.include_titles)
            or any(_matches(str(tag), self.include_tags) for tag in tags)
        )


@dataclass(frozen=True)
class Config:
    site: str
    page_size: int
    timeout_seconds: float
    include_powerpacks: bool
    selection: Selection
    storage_backend: str
    storage_options: dict[str, Any]
    keep_versions: int
    directory: Path


def load_config(path: Path) -> Config:
    path = path.resolve()
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    datadog = raw.get("datadog", {})
    storage = raw.get("storage", {})
    if not isinstance(datadog, dict) or not isinstance(storage, dict):
        raise ValueError("[datadog] and [storage] must be TOML tables")
    site = datadog.get("site", "datadoghq.com")
    if not isinstance(site, str) or not site or "/" in site or ":" in site:
        raise ValueError("datadog.site must be a Datadog site hostname")
    if not (site == "datadoghq.eu" or site.endswith(".datadoghq.com") or site == "datadoghq.com" or site.endswith(".ddog-gov.com")):
        raise ValueError("datadog.site must be a Datadog site hostname")
    page_size = datadog.get("page_size", 100)
    timeout = datadog.get("timeout_seconds", 20)
    include_powerpacks = datadog.get("include_powerpacks", True)
    keep_versions = storage.get("keep_versions", 10)
    backend = storage.get("backend", "local")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 1000:
        raise ValueError("datadog.page_size must be between 1 and 1000")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("datadog.timeout_seconds must be positive")
    if not isinstance(include_powerpacks, bool):
        raise ValueError("datadog.include_powerpacks must be true or false")
    if not isinstance(keep_versions, int) or isinstance(keep_versions, bool) or keep_versions < 1:
        raise ValueError("storage.keep_versions must be at least 1")
    if not isinstance(backend, str) or not backend:
        raise ValueError("storage.backend must be a nonempty string")
    directory_value = storage.get("directory", "backups")
    if not isinstance(directory_value, str) or not directory_value:
        raise ValueError("storage.directory must be a nonempty path")
    directory = Path(directory_value)
    if not directory.is_absolute():
        directory = path.parent / directory
    selection_data = raw.get("selection", {})
    if not isinstance(selection_data, dict):
        raise ValueError("[selection] must be a TOML table")
    return Config(
        site=site,
        page_size=page_size,
        timeout_seconds=float(timeout),
        include_powerpacks=include_powerpacks,
        selection=Selection.from_mapping(selection_data),
        storage_backend=backend,
        storage_options=dict(storage),
        keep_versions=keep_versions,
        directory=directory.resolve(),
    )
