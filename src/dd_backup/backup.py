"""Dashboard backup orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import Config
from .storage import BackupBundle, StorageBackend


def powerpack_ids(dashboard: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def visit(widgets: list[dict[str, Any]]) -> None:
        for widget in widgets:
            definition = widget.get("definition") or {}
            powerpack_id = definition.get("powerpack_id")
            if powerpack_id:
                found.add(str(powerpack_id))
            children = definition.get("widgets")
            if isinstance(children, list):
                visit(children)

    visit(dashboard.get("widgets") or [])
    return found


@dataclass
class BackupReport:
    listed: int = 0
    selected: int = 0
    created: int = 0
    unchanged: int = 0
    pruned: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def run_backup(client: Any, storage: StorageBackend, config: Config, *, dry_run: bool = False) -> BackupReport:
    summaries = client.list_dashboards(config.page_size)
    report = BackupReport(listed=len(summaries))
    powerpack_cache: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        dashboard_id = str(summary["id"])
        if summary.get("deleted_at"):
            continue
        try:
            dashboard = client.get_dashboard(dashboard_id)
            if not config.selection.matches(dashboard):
                continue
            report.selected += 1
            if dry_run:
                print(f"SELECT {dashboard_id} {dashboard.get('title', '')}")
                continue
            powerpacks = {}
            if config.include_powerpacks:
                for powerpack_id in sorted(powerpack_ids(dashboard)):
                    if powerpack_id not in powerpack_cache:
                        powerpack_cache[powerpack_id] = client.get_powerpack(powerpack_id)
                    powerpacks[powerpack_id] = powerpack_cache[powerpack_id]
            result = storage.save(
                BackupBundle(dashboard, powerpacks),
                config.keep_versions,
                datetime.now(timezone.utc),
            )
            report.created += int(result.created)
            report.unchanged += int(not result.created)
            report.pruned += result.pruned
            print(f"{'SAVED' if result.created else 'UNCHANGED'} {dashboard_id} {result.path}")
        except Exception as error:
            report.failures.append((dashboard_id, str(error)))
            print(f"ERROR {dashboard_id} {error}")
    return report
