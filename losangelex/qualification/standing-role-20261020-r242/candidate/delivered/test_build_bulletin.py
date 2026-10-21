"""Real-process CLI tests; temporary fixtures stay inside this workspace."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
CLI = ROOT / "build_bulletin.py"
SENTINEL = "PRIVATE_PATH_OR_CONTENT_7319"


def feature(identifier="a", version=1, title="Title", state="released"):
    return {"id": identifier, "version": version, "title": title, "state": state}


class BulletinTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".bulletin-test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def invoke(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), *map(str, args)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    def check_input(self, raw, expected=None):
        path = self.directory / (SENTINEL + ".json")
        path.write_bytes(raw)
        result = self.invoke(path)
        self.assertEqual(path.read_bytes(), raw, "CLI mutated its source")
        if expected is None:
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"error: invalid catalog\n")
            self.assertNotIn(SENTINEL.encode(), result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(json.loads(result.stdout), expected)
        return result

    def check_catalog(self, catalog, expected=None):
        return self.check_input(json.dumps(catalog).encode("utf-8"), expected)

    def test_mixed_sorted_projection(self):
        catalog = {"schema": 1, "features": [
            feature("z", 8, "Last"),
            feature("planned", state="planned"),
            feature("a", 2, "First"),
            feature("A", 3, "Uppercase"),
        ]}
        expected = {"features": [
            {"id": "A", "version": 3, "title": "Uppercase"},
            {"id": "a", "version": 2, "title": "First"},
            {"id": "z", "version": 8, "title": "Last"},
        ]}
        first = self.check_catalog(catalog, expected)
        second = self.check_catalog(catalog, expected)
        self.assertEqual(first.stdout, second.stdout)

    def test_empty_and_all_planned(self):
        for entries in ([], [feature(state="planned")]):
            with self.subTest(entries=entries):
                self.check_catalog({"schema": 1, "features": entries}, {"features": []})

    def test_unicode_and_nonempty_whitespace(self):
        entries = [feature("é", 99999999999999999999, "雪\n\""),
                   feature(" ", 2, " "), feature("Z", 1, "ASCII")]
        expected = {"features": [
            {key: entry[key] for key in ("id", "version", "title")}
            for entry in sorted(entries, key=lambda entry: entry["id"])
        ]}
        self.check_input(json.dumps({"schema": 1, "features": entries},
                                   ensure_ascii=False).encode("utf-8"), expected)

    def test_invalid_root_schema_and_features(self):
        invalid = [None, True, 1, "catalog", [], {},
                   {"features": []}, {"schema": 1},
                   {"schema": 1, "features": [], "extra": SENTINEL}]
        invalid.extend({"schema": value, "features": []}
                       for value in [True, False, 0, 2, 1.0, "1", None, [], {}])
        invalid.extend({"schema": 1, "features": value}
                       for value in [None, {}, "features", 1, True])
        for index, catalog in enumerate(invalid):
            with self.subTest(case=index):
                self.check_catalog(catalog)

    def test_invalid_feature_fields(self):
        invalid = [None, True, 1, "feature", []]
        for key in feature():
            entry = feature()
            del entry[key]
            invalid.append(entry)
        invalid.append(dict(feature(), extra=SENTINEL))
        for key, values in {
            "id": ["", None, 1, True, [], {}],
            "title": ["", None, 1, True, [], {}],
            "version": [True, False, 0, -1, 1.0, "1", None, [], {}],
            "state": ["", "Released", "other", None, 1, True, [], {}],
        }.items():
            for value in values:
                entry = feature()
                entry[key] = value
                invalid.append(entry)
        for index, entry in enumerate(invalid):
            with self.subTest(case=index):
                self.check_catalog({"schema": 1, "features": [entry]})

    def test_duplicates_and_invalid_planned_entries(self):
        for entries in [
            [feature(), feature()],
            [feature(), feature(state="planned")],
            [feature(state="planned"), feature(state="planned")],
            [feature(), feature("later", version=True, state="planned")],
        ]:
            with self.subTest(entries=entries):
                self.check_catalog({"schema": 1, "features": entries})

    def test_malformed_json_and_duplicate_keys(self):
        invalid = [b"", b"{", b"not json " + SENTINEL.encode(),
                   b'{"schema":1,"features":[],}',
                   b'{"schema":1,"features":[]} trailing', b"\xff\xfe\x00",
                   b'{"schema":1,"schema":1,"features":[]}',
                   b'{"schema":1,"features":[],"features":[]}',
                   b'{"schema":NaN,"features":[]}',
                   b'{"schema":Infinity,"features":[]}',
                   b'{"schema":-Infinity,"features":[]}',
                   b'[' * 2000 + b']' * 2000,
                   b'{"schema":1,"features":[{"id":"a","id":"b",'
                   b'"version":1,"title":"Title","state":"released"}]}']
        for index, raw in enumerate(invalid):
            with self.subTest(case=index):
                self.check_input(raw)

    def test_argument_count_and_io_errors(self):
        for args in [(), (SENTINEL, SENTINEL)]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"error: expected one catalog JSON path\n")
        for path in [self.directory / SENTINEL, self.directory]:
            with self.subTest(path=path):
                result = self.invoke(path)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"error: cannot read catalog\n")

    def test_read_only_source(self):
        path = self.directory / "read-only.json"
        raw = b'{"schema":1,"features":[]}'
        path.write_bytes(raw)
        path.chmod(0o400)
        self.addCleanup(path.chmod, 0o600)
        result = self.invoke(path)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout), {"features": []})
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(path.stat().st_mode & 0o777, 0o400)


if __name__ == "__main__":
    unittest.main()
