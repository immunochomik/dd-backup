from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from dd_backup.backup import powerpack_ids, run_backup
from dd_backup.client import DatadogClient, DatadogError
from dd_backup.config import Config, Selection
from dd_backup.storage import BackupBundle, LocalStorage


class SelectionTests(unittest.TestCase):
    def test_include_rules_are_or_and_exclusions_win(self):
        rules = Selection(
            include_ids=("one",), include_titles=("RT *",), include_tags=("team:ops",),
            exclude_titles=("*sandbox*",), exclude_tags=("environment:test",),
        )
        self.assertTrue(rules.matches({"id": "one", "title": "Other", "tags": []}))
        self.assertTrue(rules.matches({"id": "two", "title": "RT Capacity", "tags": []}))
        self.assertTrue(rules.matches({"id": "three", "title": "Other", "tags": ["TEAM:OPS"]}))
        self.assertFalse(rules.matches({"id": "one", "title": "RT Sandbox", "tags": []}))
        self.assertFalse(rules.matches({"id": "one", "title": "Other", "tags": ["environment:test"]}))
        self.assertFalse(rules.matches({"id": "none", "title": "Other", "tags": []}))


class PaginationTests(unittest.TestCase):
    def test_fetches_all_pages(self):
        client = DatadogClient("datadoghq.eu", "x", "y")
        calls = []

        def fake_get(path, params):
            calls.append(params["start"])
            pages = {0: [{"id": "a"}, {"id": "b"}], 2: [{"id": "c"}]}
            return {"dashboards": pages[params["start"]]}

        client._get = fake_get
        self.assertEqual([d["id"] for d in client.list_dashboards(2)], ["a", "b", "c"])
        self.assertEqual(calls, [0, 2])

    def test_repeated_page_stops(self):
        client = DatadogClient("datadoghq.eu", "x", "y")
        client._get = lambda path, params: {"dashboards": [{"id": "a"}]}
        with self.assertRaises(DatadogError):
            client.list_dashboards(1)


class LocalStorageTests(unittest.TestCase):
    def test_deduplicates_and_retains_ten_distinct_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = LocalStorage(root)
            first_time = datetime(2026, 9, 27, tzinfo=timezone.utc)
            first_bundle = BackupBundle(
                {"id": "abc-def-123", "title": "Capacity", "widgets": []},
                {"pack-1": {"data": {"id": "pack-1"}}},
            )
            first = storage.save(first_bundle, 10, first_time)
            self.assertTrue(first.created)
            self.assertTrue((first.path / "dashboard.json").is_file())
            self.assertTrue((first.path / "powerpacks" / "pack-1.json").is_file())
            duplicate = storage.save(first_bundle, 10, first_time + timedelta(minutes=1))
            self.assertFalse(duplicate.created)
            self.assertEqual(duplicate.path, first.path)
            for revision in range(1, 12):
                bundle = BackupBundle(
                    {"id": "abc-def-123", "title": "Capacity", "revision": revision}, {}
                )
                storage.save(bundle, 10, first_time + timedelta(minutes=revision + 1))
            versions = storage._versions(root / "abc-def-123")
            self.assertEqual(len(versions), 10)
            self.assertFalse(first.path.exists())
            self.assertEqual(
                __import__("json").loads((versions[-1] / "dashboard.json").read_text())["revision"], 11
            )

    def test_pruning_ignores_unrecognized_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            storage = LocalStorage(root)
            unrelated = root / "abc" / "do-not-delete"
            unrelated.mkdir(parents=True)
            first_time = datetime(2026, 9, 27, tzinfo=timezone.utc)
            for revision in range(3):
                storage.save(BackupBundle({"id": "abc", "revision": revision}, {}), 1,
                             first_time + timedelta(seconds=revision))
            self.assertTrue(unrelated.is_dir())
            self.assertEqual(len(storage._versions(root / "abc")), 1)


class BackupRunTests(unittest.TestCase):
    def test_backups_include_referenced_powerpacks_and_skip_unchanged(self):
        class FakeClient:
            powerpack_reads = 0

            def list_dashboards(self, page_size):
                return [{"id": "one"}, {"id": "two"}, {"id": "excluded"}]

            def get_dashboard(self, dashboard_id):
                return {
                    "id": dashboard_id, "title": dashboard_id, "tags": ["team:ops"],
                    "widgets": [{"definition": {"type": "powerpack", "powerpack_id": "pack-1"}}],
                }

            def get_powerpack(self, powerpack_id):
                self.powerpack_reads += 1
                return {"data": {"id": powerpack_id}}

        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient()
            storage = LocalStorage(Path(temporary))
            config = Config(
                site="datadoghq.eu", page_size=100, timeout_seconds=20,
                include_powerpacks=True,
                selection=Selection(exclude_ids=("excluded",)),
                storage_backend="local", storage_options={}, keep_versions=10,
                directory=Path(temporary),
            )
            first = run_backup(client, storage, config)
            second = run_backup(client, storage, config)
            self.assertEqual((first.listed, first.selected, first.created), (3, 2, 2))
            self.assertEqual((second.created, second.unchanged), (0, 2))
            self.assertEqual(client.powerpack_reads, 2)
            self.assertFalse((Path(temporary) / "excluded").exists())

    def test_nested_powerpack_detection(self):
        dashboard = {"widgets": [{"definition": {"type": "group", "widgets": [
            {"definition": {"type": "powerpack", "powerpack_id": "nested"}}
        ]}}]}
        self.assertEqual(powerpack_ids(dashboard), {"nested"})


if __name__ == "__main__":
    unittest.main()
