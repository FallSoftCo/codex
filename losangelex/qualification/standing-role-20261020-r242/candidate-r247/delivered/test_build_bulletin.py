"""Real-process CLI tests; all temporary fixtures stay in this workspace."""

import copy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest


BASE = Path(__file__).resolve().parent
CLI = BASE / "build_bulletin.py"
FEATURE = {"id": "sample", "version": 1, "title": "Sample", "state": "released"}


class BulletinTests(unittest.TestCase):
    def invoke(self, raw, expected=None):
        with tempfile.TemporaryDirectory(prefix="bulletin-test-", dir=BASE) as directory:
            path = Path(directory) / "private-\x1b[31m-input.json"
            path.write_bytes(raw)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            result = subprocess.run(
                [sys.executable, str(CLI), str(path)],
                capture_output=True, check=False, timeout=10,
            )
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            if expected is None:
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"error: invalid catalog\n")
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                self.assertEqual(json.loads(result.stdout), expected)
                self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_empty_and_planned(self):
        for features in ([], [dict(FEATURE, state="planned")]):
            with self.subTest(features=features):
                self.invoke(json.dumps({"schema": 1, "features": features}).encode(),
                            {"features": []})

    def test_sort_filter_and_preserve_values(self):
        rng = random.Random(42)
        features = [
            dict(FEATURE, id="z", version=8, title="Release\nwith controls\x1b"),
            dict(FEATURE, id="A", title="Uppercase"),
            dict(FEATURE, id="a", state="planned"),
            dict(FEATURE, id="é", title="Unicode ☃"),
            dict(FEATURE, id="aa", version=10**40),
            dict(FEATURE, id=" ", title=" "),
        ]
        expected = {"features": [
            {key: feature[key] for key in ("id", "version", "title")}
            for feature in sorted(features, key=lambda item: item["id"])
            if feature["state"] == "released"
        ]}
        for _ in range(10):
            rng.shuffle(features)
            self.invoke(json.dumps({"schema": 1, "features": features},
                                   ensure_ascii=False).encode(), expected)

    def test_invalid_catalogs(self):
        valid = {"schema": 1, "features": [FEATURE]}
        invalid = [None, [], 1, "catalog", True, {}, {"schema": 1},
                   {"features": []}, dict(valid, extra="private\x1b"),
                   dict(valid, features={}), dict(valid, features=None),
                   dict(valid, features=[None]), dict(valid, features=[[]])]
        for schema in (0, 2, True, False, 1.0, "1", None, [], {}):
            invalid.append(dict(valid, schema=schema))
        for key in FEATURE:
            feature = dict(FEATURE)
            del feature[key]
            invalid.append(dict(valid, features=[feature]))
        invalid.append(dict(valid, features=[dict(FEATURE, extra=1)]))
        bad_values = {
            "id": ["", None, False, 1, [], {}],
            "version": [0, -1, True, False, 1.0, "1", None, [], {}],
            "title": ["", None, True, 1, [], {}],
            "state": ["", "Released", "retired", None, True, 1, [], {}],
        }
        for key, values in bad_values.items():
            for value in values:
                invalid.append(dict(valid, features=[dict(FEATURE, **{key: value})]))
        invalid.extend([
            dict(valid, features=[FEATURE, copy.deepcopy(FEATURE)]),
            dict(valid, features=[FEATURE, dict(FEATURE, state="planned")]),
            dict(valid, features=[dict(FEATURE, state="planned", version=False)]),
        ])
        for number, catalog in enumerate(invalid):
            with self.subTest(case=number):
                self.invoke(json.dumps(catalog).encode())

    def test_invalid_json_and_encodings(self):
        invalid = [
            b"", b"{private-secret", b"{\"schema\":1,}",
            b'{"schema":1,"features":[]} trailing-private-secret',
            b'{"schema":1,"schema":1,"features":[]}',
            b'{"schema":1,"features":[],"features":[]}',
            b'{"schema":1,"features":[{"id":"x","id":"y",'
            b'"version":1,"title":"Y","state":"released"}]}',
            b'{"schema":NaN,"features":[]}',
            b'{"schema":Infinity,"features":[]}',
            b'{"schema":-Infinity,"features":[]}',
            b'{"schema":1,"features":[],"private":"\xff"}',
            b'\xef\xbb\xbf{"schema":1,"features":[]}',
            '{"schema":1,"features":[]}'.encode("utf-16"),
            b"[" * 2000 + b"]" * 2000,
        ]
        for number, raw in enumerate(invalid):
            with self.subTest(case=number):
                self.invoke(raw)

    def test_argument_and_read_errors(self):
        for args in ([], ["private-one", "private-two"]):
            result = subprocess.run([sys.executable, str(CLI), *args],
                                    capture_output=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr, b"usage: build_bulletin.py CATALOG_JSON\n")
        with tempfile.TemporaryDirectory(prefix="bulletin-test-", dir=BASE) as directory:
            for path in (Path(directory), Path(directory) / "private-\x1b-missing.json"):
                result = subprocess.run([sys.executable, str(CLI), str(path)],
                                        capture_output=True, check=False, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"error: cannot read catalog\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
