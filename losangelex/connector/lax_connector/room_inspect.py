"""Canonical communication reads for native tools and existing running agents.

The CLI uses its owner's protected connector configuration. It never prints a
credential, accepts an owner token argument, mutates state or starts a model.
"""
import argparse
import json
import os
import stat
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import UUID

READ_NAMES = {"hollywood_rooms", "hollywood_agents", "hollywood_room_info", "hollywood_agent_info"}


def read_path(name, args):
    if name == "hollywood_rooms":
        return "rooms"
    if name == "hollywood_room_info":
        return "rooms/" + str(UUID(args["roomId"]))
    if name == "hollywood_agent_info":
        return "agents/" + str(UUID(args["agentId"])) + "/role"
    if name == "hollywood_agents":
        limit = args.get("limit", 100)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Agent page limit must be between 1 and 100")
        query = {"limit": limit}
        if args.get("after") is not None:
            query["after"] = str(UUID(args["after"]))
        return "agents?" + urlencode(query)
    raise ValueError("Unsupported communication read")


async def inspect_metadata(request, name, arguments):
    return await request("GET", read_path(name, arguments))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("The configured Hollywood endpoint redirected; credential not forwarded")


def inspect_local(config_path, name, arguments):
    info = config_path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError("Use your own private connector configuration")
    config = json.loads(config_path.read_text())
    authority = str(UUID(config["authorityId"]))
    agent = str(UUID(config["agentId"]))
    endpoint = urlsplit(config["hollywoodUrl"])
    local = endpoint.hostname in ("127.0.0.1", "localhost", "::1")
    if (endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or endpoint.path not in ("", "/")
            or not (endpoint.scheme == "https" or endpoint.scheme == "http" and local)):
        raise ValueError("Use the configured authenticated HTTPS or loopback Hollywood endpoint")
    path = read_path(name, arguments)
    request = Request(config["hollywoodUrl"].rstrip("/") + "/hollywood/v3/" + path,
                      method="GET", headers={"Authorization": "Bearer " + config["token"],
                      "X-Hollywood-Authority": authority, "X-Hollywood-Agent": agent})
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
    except HTTPError as error:
        raise RuntimeError("Canonical communication read rejected: HTTP " + str(error.code)) from None
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("Canonical read exceeded response bound; use the original pagination cursor")
    return json.loads(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rooms")
    agents = commands.add_parser("agents")
    agents.add_argument("--after")
    agents.add_argument("--limit", type=int, default=100)
    commands.add_parser("room-info").add_argument("roomId")
    commands.add_parser("agent-info").add_argument("agentId")
    args = parser.parse_args()
    name = {"rooms": "hollywood_rooms", "agents": "hollywood_agents",
            "room-info": "hollywood_room_info", "agent-info": "hollywood_agent_info"}[args.command]
    values = {key: value for key, value in vars(args).items() if key not in ("command", "config")}
    print(json.dumps(inspect_local(args.config, name, values), default=str))


if __name__ == "__main__":
    main()
