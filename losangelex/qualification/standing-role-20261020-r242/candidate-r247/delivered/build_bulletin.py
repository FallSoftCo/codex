#!/usr/bin/env python3
"""Validate a schema-1 catalog and print its released-feature bulletin."""

import json
from pathlib import Path
import sys


class InvalidCatalog(ValueError):
    """A catalog does not meet the complete schema."""


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCatalog()
        result[key] = value
    return result


def reject_constant(_value):
    raise InvalidCatalog()


def build_bulletin(raw):
    """Build from exact UTF-8 source bytes without modifying the source."""
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
        feature_id = feature["id"]
        if not isinstance(feature_id, str) or not feature_id or feature_id in seen:
            raise InvalidCatalog()
        seen.add(feature_id)
        if type(feature["version"]) is not int or feature["version"] <= 0:
            raise InvalidCatalog()
        if not isinstance(feature["title"], str) or not feature["title"]:
            raise InvalidCatalog()
        if feature["state"] not in ("planned", "released"):
            raise InvalidCatalog()
        if feature["state"] == "released":
            released.append({key: feature[key] for key in ("id", "version", "title")})
    return {"features": sorted(released, key=lambda feature: feature["id"])}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        sys.stderr.write("usage: build_bulletin.py CATALOG_JSON\n")
        return 2
    try:
        raw = Path(args[0]).read_bytes()
    except (OSError, ValueError):
        sys.stderr.write("error: cannot read catalog\n")
        return 1
    try:
        bulletin = build_bulletin(raw)
    except (ValueError, RecursionError):
        # Never echo a path, source value, parser detail, or traceback.
        sys.stderr.write("error: invalid catalog\n")
        return 1
    sys.stdout.write(json.dumps(bulletin, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
