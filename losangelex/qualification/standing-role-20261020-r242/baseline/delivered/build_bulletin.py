#!/usr/bin/env python3
"""Print a release bulletin from one strictly validated catalog (stdlib only)."""

import json
from pathlib import Path
import sys


class InvalidCatalog(ValueError):
    """Invalid input; never include source-controlled text in diagnostics."""


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
    """Validate the exact source bytes before selecting any released entries."""
    catalog = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if type(catalog) is not dict or set(catalog) != {"schema", "features"}:
        raise InvalidCatalog()
    if type(catalog["schema"]) is not int or catalog["schema"] != 1:
        raise InvalidCatalog()
    if type(catalog["features"]) is not list:
        raise InvalidCatalog()

    seen = set()
    released = []
    for feature in catalog["features"]:
        if type(feature) is not dict or set(feature) != {
            "id", "version", "title", "state"
        }:
            raise InvalidCatalog()
        if type(feature["id"]) is not str or not feature["id"]:
            raise InvalidCatalog()
        if feature["id"] in seen:
            raise InvalidCatalog()
        seen.add(feature["id"])
        if type(feature["version"]) is not int or feature["version"] <= 0:
            raise InvalidCatalog()
        if type(feature["title"]) is not str or not feature["title"]:
            raise InvalidCatalog()
        if type(feature["state"]) is not str or feature["state"] not in (
            "planned", "released"
        ):
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
        sys.stderr.write("error: unable to read catalog\n")
        return 1
    try:
        bulletin = build_bulletin(raw)
    except (ValueError, UnicodeError, RecursionError):
        sys.stderr.write("error: invalid catalog\n")
        return 1
    sys.stdout.write(json.dumps(bulletin, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
