#!/usr/bin/env python3
"""Print a released-feature bulletin from a strictly validated catalog."""

import json
import sys
from pathlib import Path


def reject_constant(_value):
    raise ValueError("non-JSON constant")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def build_bulletin(raw):
    """Validate exact UTF-8 source bytes before selecting released entries."""
    catalog = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(catalog, dict) or set(catalog) != {"schema", "features"}:
        raise ValueError("invalid catalog fields")
    if type(catalog["schema"]) is not int or catalog["schema"] != 1:
        raise ValueError("invalid schema")
    if not isinstance(catalog["features"], list):
        raise ValueError("invalid features")

    ids = set()
    released = []
    for feature in catalog["features"]:
        if not isinstance(feature, dict) or set(feature) != {
            "id", "version", "title", "state"
        }:
            raise ValueError("invalid feature fields")
        if not isinstance(feature["id"], str) or not feature["id"]:
            raise ValueError("invalid id")
        if not isinstance(feature["title"], str) or not feature["title"]:
            raise ValueError("invalid title")
        if type(feature["version"]) is not int or feature["version"] <= 0:
            raise ValueError("invalid version")
        if feature["state"] not in ("planned", "released"):
            raise ValueError("invalid state")
        if feature["id"] in ids:
            raise ValueError("duplicate id")
        ids.add(feature["id"])
        if feature["state"] == "released":
            released.append({key: feature[key] for key in ("id", "version", "title")})
    return {"features": sorted(released, key=lambda feature: feature["id"])}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: build_bulletin.py CATALOG_JSON", file=sys.stderr)
        return 2
    try:
        bulletin = build_bulletin(Path(args[0]).read_bytes())
    except (OSError, ValueError, UnicodeError, RecursionError):
        # Do not echo paths, source values, parser details or tracebacks.
        print("error: cannot read or validate catalog", file=sys.stderr)
        return 1
    print(json.dumps(bulletin, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
