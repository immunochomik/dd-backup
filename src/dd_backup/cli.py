"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from .backup import run_backup
from .client import DatadogClient
from .config import load_config
from .storage import make_storage


def read_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid environment-file line in {path}")
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[name.strip()] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up Datadog dashboards with version retention")
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--env-file", type=Path, help="Optional file with DD_API_KEY and DD_APP_KEY")
    parser.add_argument("--dry-run", action="store_true", help="List selected dashboards without writing backups")
    args = parser.parse_args(argv)
    try:
        config_path = args.config.resolve()
        config = load_config(config_path)
        env_path = args.env_file.resolve() if args.env_file else config_path.parent / ".env"
        values = dict(os.environ)
        if env_path.exists():
            values.update(read_env_file(env_path))
        api_key = values.get("DD_API_KEY")
        app_key = values.get("DD_APP_KEY")
        if not api_key or not app_key:
            raise ValueError("DD_API_KEY and DD_APP_KEY are required in the environment or --env-file")
        client = DatadogClient(config.site, api_key, app_key, config.timeout_seconds)
        storage = make_storage(config.storage_backend, config.storage_options, config_path.parent)
        report = run_backup(client, storage, config, dry_run=args.dry_run)
        print(
            f"SUMMARY listed={report.listed} selected={report.selected} "
            f"saved={report.created} unchanged={report.unchanged} "
            f"pruned={report.pruned} errors={len(report.failures)}"
        )
        return 1 if report.failures else 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
