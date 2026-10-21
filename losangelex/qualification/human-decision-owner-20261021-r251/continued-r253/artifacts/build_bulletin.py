#!/usr/bin/env python3
"""Validate one read-only catalog and emit its released-feature bulletin."""

import json
from pathlib import Path
import sys


class InvalidCatalog(ValueError):
    """The catalog does not satisfy the exact schema."""


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
        state = feature["state"]
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise InvalidCatalog()
        if not isinstance(title, str) or not title:
            raise InvalidCatalog()
        if type(version) is not int or version <= 0:
            raise InvalidCatalog()
        if not isinstance(state, str) or state not in ("planned", "released"):
            raise InvalidCatalog()
        seen.add(identifier)
        if state == "released":
            released.append({"id": identifier, "version": version, "title": title})

    return {"features": sorted(released, key=lambda feature: feature["id"])}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("error: expected one catalog JSON path", file=sys.stderr)
        return 2
    try:
        result = build_bulletin(Path(args[0]).read_bytes())
    except (OSError, ValueError, RecursionError, OverflowError):
        # No paths, untrusted values, exception messages, or tracebacks leak.
        print("error: invalid or unreadable catalog", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
