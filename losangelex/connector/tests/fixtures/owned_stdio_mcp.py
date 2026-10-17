"""Owned stdio MCP discovery fixture; never executes a tool or accesses a network."""

import json
import os
import sys
from pathlib import Path


log = Path(sys.argv[1])


def record(value):
    with log.open("a") as stream:
        stream.write(json.dumps(value) + "\n")


record({"event": "started", "pid": os.getpid(), "uid": os.geteuid()})
try:
    for line in sys.stdin:
        request = json.loads(line)
        record(request)
        method = request["method"]
        if "id" not in request:
            continue
        if method == "initialize":
            result = {"protocolVersion": request["params"]["protocolVersion"],
                "serverInfo": {"name": "owned-stdio-fixture", "version": "1"},
                "capabilities": {"tools": {}, "extensions": {"owned-proof": {}}}}
        elif method == "tools/list":
            result = {"tools": [{"name": "owned_profile_probe",
                "description": "Owned discovery marker; invocation is forbidden in this proof.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}}]}
        elif method == "resources/list":
            result = {"resources": []}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "ping":
            result = {}
        else:
            raise AssertionError("Only MCP initialization and discovery are authorized")
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
finally:
    record({"event": "exited", "pid": os.getpid()})
