"""Real CLI regression tests; temporary fixtures stay in this workspace."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
CLI = HERE / "build_bulletin.py"


def feature(id="a", version=1, title="Title", state="released"):
    return {"id": id, "version": version, "title": title, "state": state}


def catalog(features=None):
    return {"schema": 1, "features": [feature()] if features is None else features}


class BulletinTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".bulletin-tests-", dir=HERE)
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "source-PRIVATE.json"

    def run_cli(self, args):
        return subprocess.run(
            [sys.executable, str(CLI), *args], capture_output=True, timeout=10
        )

    def invoke(self, raw):
        self.source.write_bytes(raw)
        result = self.run_cli([str(self.source)])
        self.assertEqual(self.source.read_bytes(), raw, "CLI modified source")
        return result

    def assert_invalid(self, raw):
        result = self.invoke(raw)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"error: invalid catalog\n")

    def test_valid_catalogs(self):
        cases = [
            (catalog([]), {"features": []}),
            (catalog([feature(state="planned")]), {"features": []}),
            (catalog(), {"features": [{"id": "a", "version": 1, "title": "Title"}]}),
            (catalog([
                feature("z", 9, "Last"), feature("planned", state="planned"),
                feature("a", 2, "First"), feature("A", 3, "Capital"),
                feature("é", 4, "Café ☃"),
            ]), {"features": [
                {"id": "A", "version": 3, "title": "Capital"},
                {"id": "a", "version": 2, "title": "First"},
                {"id": "z", "version": 9, "title": "Last"},
                {"id": "é", "version": 4, "title": "Café ☃"},
            ]}),
            (catalog([feature(" ", 10**100, " ")]), {"features": [
                {"id": " ", "version": 10**100, "title": " "}
            ]}),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                raw = json.dumps(source, ensure_ascii=False).encode("utf-8")
                result = self.invoke(raw)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(json.loads(result.stdout), expected)
                self.assertEqual(
                    result.stdout,
                    (json.dumps(expected, ensure_ascii=True, separators=(",", ":")) + "\n").encode(),
                )

    def test_invalid_root_and_schema(self):
        cases = [None, [], True, 1, "PRIVATE", {}, {"schema": 1}, {"features": []}]
        cases.append({"schema": 1, "features": [], "extra": "PRIVATE"})
        for schema in [True, False, 0, -1, 2, 1.0, "1", None, [], {}]:
            cases.append({"schema": schema, "features": []})
        for features in [None, {}, "PRIVATE", True, 1, 1.0]:
            cases.append({"schema": 1, "features": features})
        for source in cases:
            with self.subTest(source=source):
                self.assert_invalid(json.dumps(source).encode())

    def test_invalid_feature_shapes(self):
        cases = [None, [], True, "PRIVATE", 1]
        for key in feature():
            row = feature()
            del row[key]
            cases.append(row)
        cases.append(dict(feature(), extra="PRIVATE"))
        for row in cases:
            with self.subTest(row=row):
                self.assert_invalid(json.dumps(catalog([row])).encode())

    def test_invalid_feature_fields(self):
        invalid = {
            "id": ["", None, True, 1, 1.0, [], {}],
            "title": ["", None, False, 1, 1.0, [], {}],
            "version": [0, -1, True, False, 1.0, "1", None, [], {}],
            "state": ["", "Released", "PRIVATE", None, True, 1, [], {}],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    row = feature()
                    row[field] = value
                    self.assert_invalid(json.dumps(catalog([row])).encode())

    def test_duplicate_ids_even_when_planned(self):
        for state in ["released", "planned"]:
            with self.subTest(state=state):
                self.assert_invalid(json.dumps(catalog([
                    feature("same"), feature("same", state=state)
                ])).encode())

    def test_planned_entries_are_validated(self):
        row = feature(state="planned")
        row["version"] = False
        self.assert_invalid(json.dumps(catalog([feature("other"), row])).encode())

    def test_malformed_json_and_duplicate_keys(self):
        cases = [
            b"", b"{", b"{PRIVATE}", b"\xff", b"{} {}",
            b'{"schema":1,"features":[],}',
            b'{"schema":1,"schema":1,"features":[]}',
            b'{"schema":1,"features":[],"features":[]}',
            b'{"schema":1,"features":[{"id":"a","id":"b","version":1,"title":"T","state":"released"}]}',
            b'{"schema":NaN,"features":[]}',
            b'{"schema":Infinity,"features":[]}',
            b'{"schema":-Infinity,"features":[]}',
            b'[' * 2000 + b']' * 2000,
        ]
        for raw in cases:
            with self.subTest(raw=raw[:80]):
                self.assert_invalid(raw)

    def test_no_partial_output_after_invalid_later_row(self):
        bad = copy.deepcopy(feature("PRIVATE"))
        bad["version"] = False
        self.assert_invalid(json.dumps(catalog([feature(), bad])).encode())

    def test_usage_and_io_errors_are_sanitized(self):
        for args in [[], ["PRIVATE", "SECOND-PRIVATE"]]:
            result = self.run_cli(args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"usage: build_bulletin.py CATALOG_JSON\n")
        for path in [self.source, Path(self.directory.name)]:
            result = self.run_cli([str(path)])
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"error: unable to read catalog\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
