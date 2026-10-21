#!/usr/bin/env python3
"""Print the released-feature bulletin: python3 build_bulletin.py CATALOG.json.

The input is read-only. All errors use fixed diagnostics without source content,
paths, or exception details. Success writes only the JSON projection to stdout.
"""

import json
from pathlib import Path
import sys


class InvalidCatalog(ValueError):
    """The input does not match the exact catalog schema."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCatalog()
        result[key] = value
    return result


def reject_constant(_value):
    raise InvalidCatalog()


def project_catalog(raw):
    catalog = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(catalog, dict) or set(catalog) != {"schema", "features"}:
        raise InvalidCatalog()
    if type(catalog["schema"]) is not int or catalog["schema"] != 1:
        raise InvalidCatalog()
    if not isinstance(catalog["features"], list):
        raise InvalidCatalog()

    seen = set()
    released = []
    for feature in catalog["features"]:
        if not isinstance(feature, dict) or set(feature) != {
            "id", "version", "title", "state"
        }:
            raise InvalidCatalog()
        identifier = feature["id"]
        title = feature["title"]
        version = feature["version"]
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise InvalidCatalog()
        seen.add(identifier)
        if not isinstance(title, str) or not title:
            raise InvalidCatalog()
        if type(version) is not int or version <= 0:
            raise InvalidCatalog()
        if feature["state"] not in ("planned", "released"):
            raise InvalidCatalog()
        if feature["state"] == "released":
            released.append({"id": identifier, "version": version, "title": title})

    released.sort(key=lambda feature: feature["id"])
    return {"features": released}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("error: expected one catalog JSON path\n")
        return 2
    try:
        raw = Path(args[0]).read_bytes()
    except (OSError, ValueError):
        sys.stderr.write("error: cannot read catalog\n")
        return 1
    try:
        bulletin = project_catalog(raw)
    except (ValueError, UnicodeError, RecursionError):
        sys.stderr.write("error: invalid catalog\n")
        return 1
    sys.stdout.write(json.dumps(bulletin, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
