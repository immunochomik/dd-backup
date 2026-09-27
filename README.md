# dd-backup

A small Python tool that backs up every custom Datadog dashboard in an organization. It saves the full dashboard JSON and any referenced powerpacks, with versioned local storage and a configurable retention count. The first storage backend is local; entry points let another package provide a backend later.

## Install

Requires Python 3.11 or newer. From this directory:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e .
cp config.example.toml config.toml
```

Set `DD_API_KEY` and `DD_APP_KEY` in the environment, or pass `--env-file /path/to/.env`. The application key needs `dashboards_read`; `dashboards_write` is not needed. Set the Datadog site in `config.toml` (for example `datadoghq.eu`). Keep credentials out of Git.

## Run

```sh
.venv/bin/dd-backup --dry-run
.venv/bin/dd-backup
```

Or run without installation:

```sh
PYTHONPATH=src python3.11 -m dd_backup.cli --config config.toml --env-file /path/to/.env
```

The default config includes all dashboards, backs up referenced powerpacks, stores versions under `backups/<dashboard-id>/`, and keeps the latest **10 distinct versions per dashboard**. Each version has `dashboard.json`, `manifest.json`, and a `powerpacks/` directory when needed. An unchanged dashboard and powerpack set does not create another version. A successful backup prunes older versions beyond the configured count. Existing backup versions for excluded or deleted dashboards are left alone.

Datadog's dashboard list endpoint includes custom or cloned dashboards; preset dashboards are not returned. The tool paginates the list, fetches each dashboard's full definition, and continues with the next dashboard if one fails. It exits nonzero if any dashboard failed. A list failure stops the run before backups begin.

## Select dashboards

Edit the `[selection]` table in `config.toml`. IDs match exactly or by glob pattern; title and tag patterns are case-insensitive. Multiple include rules use OR: a dashboard is included if its ID, title, or a tag matches. With no include rules, all dashboards are included. Any exclusion wins over inclusion.

```toml
[selection]
include_titles = ["RT *", "*capacity*"]
include_tags = ["team:saas-features"]
exclude_ids = ["abc-def-123"]
exclude_titles = ["*sandbox*"]
```

## Storage plugins

Set `storage.backend` to an installed entry point name in the `dd_backup.storage` group. Its loaded factory must accept `(options: dict, config_dir: Path)` and return an object with:

```python
save(bundle: BackupBundle, keep_versions: int, captured_at: datetime) -> SaveResult
```

`bundle.dashboard` is the full API JSON and `bundle.powerpacks` maps powerpack IDs to full API JSON. `SaveResult` reports whether a new version was created, its location, and how many old versions were pruned. The backend handles its own retention policy.

The local backend writes files in a temporary directory and renames that directory after all JSON files are complete. Retention only removes version directories created by this tool under the configured backup root.

## Test

```sh
PYTHONPATH=src python3.11 -m unittest discover -s tests -v
```

See [Datadog's Dashboards API](https://docs.datadoghq.com/api/latest/dashboards/) and [Powerpack API](https://docs.datadoghq.com/api/latest/powerpack/) for the source data.
