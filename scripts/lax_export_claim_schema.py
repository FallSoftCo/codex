#!/usr/bin/env python3
# Export the model-owned intent portion of Hollywood's native claim contract.
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hollywood-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.hollywood_source.resolve(strict=True)))
    from hollywood_backbone.collaboration_models import CollaborationCall

    canonical = CollaborationCall.model_json_schema()
    result = {
        "type": "object",
        "properties": {"command": canonical["properties"]["command"]},
        "required": ["command"],
        "additionalProperties": False,
        "$defs": canonical["$defs"],
    }
    acquire = result["$defs"]["Acquire"]["properties"]
    # The native bridge currently attests exact file bytes only.
    acquire["kind"] = {
        "type": "string",
        "enum": ["file"],
        "description": "This native physical-observation port supports file claims only. Directory observation is not implemented.",
    }
    acquire["leaseSeconds"]["description"] = (
        "Requested lease lifetime in whole seconds, from 1 through 3600 inclusive. Expiry does not release uncertain effects."
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
