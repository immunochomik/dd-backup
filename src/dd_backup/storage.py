"""Pluggable storage with a versioned local backend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib.metadata import entry_points
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Protocol


VERSION_NAME = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{12}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class BackupBundle:
    dashboard: dict[str, Any]
    powerpacks: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class SaveResult:
    created: bool
    path: Path
    pruned: int


class StorageBackend(Protocol):
    def save(self, bundle: BackupBundle, keep_versions: int, captured_at: datetime) -> SaveResult:
        """Store a bundle and retain at most keep_versions versions for its dashboard."""


def _canonical_hash(bundle: BackupBundle) -> str:
    content = json.dumps(
        {"dashboard": bundle.dashboard, "powerpacks": bundle.powerpacks},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _versions(self, dashboard_dir: Path) -> list[Path]:
        if not dashboard_dir.exists():
            return []
        return sorted(
            entry for entry in dashboard_dir.iterdir()
            if entry.is_dir() and not entry.is_symlink() and VERSION_NAME.fullmatch(entry.name)
        )

    def _prune(self, dashboard_dir: Path, keep_versions: int) -> int:
        versions = self._versions(dashboard_dir)
        obsolete = versions[:-keep_versions]
        for version in obsolete:
            shutil.rmtree(version)
        return len(obsolete)

    def save(self, bundle: BackupBundle, keep_versions: int, captured_at: datetime) -> SaveResult:
        dashboard_id = str(bundle.dashboard.get("id", ""))
        if not SAFE_ID.fullmatch(dashboard_id):
            raise ValueError(f"Unsafe dashboard ID: {dashboard_id!r}")
        if keep_versions < 1:
            raise ValueError("keep_versions must be at least 1")
        if captured_at.tzinfo is None:
            raise ValueError("captured_at must have a timezone")
        dashboard_dir = self.root / dashboard_id
        if dashboard_dir.is_symlink():
            raise ValueError(f"Refusing symlinked dashboard directory: {dashboard_dir}")
        dashboard_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = _canonical_hash(bundle)
        versions = self._versions(dashboard_dir)
        if versions:
            latest_manifest = versions[-1] / "manifest.json"
            try:
                latest_digest = json.loads(latest_manifest.read_text())["sha256"]
            except (OSError, ValueError, KeyError):
                latest_digest = None
            if latest_digest == digest:
                return SaveResult(False, versions[-1], self._prune(dashboard_dir, keep_versions))

        timestamp = captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        version_dir = dashboard_dir / f"{timestamp}-{digest[:12]}"
        if version_dir.exists():
            raise FileExistsError(f"Backup version already exists: {version_dir}")
        temp_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=dashboard_dir))
        try:
            _write_json(temp_dir / "dashboard.json", bundle.dashboard)
            if bundle.powerpacks:
                powerpack_dir = temp_dir / "powerpacks"
                powerpack_dir.mkdir(mode=0o700)
                for powerpack_id, powerpack in sorted(bundle.powerpacks.items()):
                    if not SAFE_ID.fullmatch(powerpack_id):
                        raise ValueError(f"Unsafe powerpack ID: {powerpack_id!r}")
                    _write_json(powerpack_dir / f"{powerpack_id}.json", powerpack)
            _write_json(temp_dir / "manifest.json", {
                "schema_version": 1,
                "dashboard_id": dashboard_id,
                "title": bundle.dashboard.get("title", ""),
                "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
                "sha256": digest,
                "powerpack_ids": sorted(bundle.powerpacks),
            })
            os.replace(temp_dir, version_dir)
        except Exception:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise
        return SaveResult(True, version_dir, self._prune(dashboard_dir, keep_versions))


def make_storage(backend: str, options: dict[str, Any], config_dir: Path) -> StorageBackend:
    if backend == "local":
        directory = options.get("directory", "backups")
        path = Path(directory)
        if not path.is_absolute():
            path = config_dir / path
        return LocalStorage(path)
    matches = [entry for entry in entry_points(group="dd_backup.storage") if entry.name == backend]
    if len(matches) != 1:
        raise ValueError(f"Unknown or ambiguous storage backend: {backend}")
    return matches[0].load()(options, config_dir)
