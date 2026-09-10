#!/usr/bin/env python3
"""Check an installed app-server in disposable state, without submitting model work.

Requires websocket-client, also used by the legacy Losangelex team launcher.
"""

import argparse
import itertools
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request

import websocket


REQUEST_IDS = itertools.count(1)


def request(connection, method, params):
    request_id = next(REQUEST_IDS)
    connection.send(json.dumps({"id": request_id, "method": method, "params": params}))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        message = json.loads(connection.recv())
        if message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error']}")
            return message["result"]
    raise TimeoutError(method)


def connect(url):
    connection = websocket.create_connection(url, timeout=20, suppress_origin=True)
    try:
        request(
            connection,
            "initialize",
            {
                "clientInfo": {"name": "losangelex-runtime-smoke", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        connection.send(json.dumps({"method": "initialized"}))
        return connection
    except BaseException:
        connection.close()
        raise


def smoke(binary: Path):
    binary = binary.resolve()
    with tempfile.TemporaryDirectory(prefix="losangelex-runtime-smoke-") as directory:
        root = Path(directory)
        (root / "config.toml").write_text(
            'cli_auth_credentials_store = "ephemeral"\ncheck_for_update_on_startup = false\n'
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("HOLLYWOOD_", "LOSANGELEX_"))
            and key
            not in {
                "CODEX_HOME",
                "CODEX_THREAD_ID",
                "CODEX_EXEC_SERVER_URL",
                "CODEX_API_KEY",
                "OPENAI_API_KEY",
            }
        }
        environment.update(CODEX_HOME=directory, HOLLYWOOD_AUTO_ATTACH="0")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        with (root / "server.log").open("w") as log:
            process = subprocess.Popen(
                [str(binary), "app-server", "--listen", url],
                env=environment,
                cwd=root,
                stdout=log,
                stderr=log,
            )
            try:
                deadline = time.monotonic() + 20
                while True:
                    if process.poll() is not None:
                        raise RuntimeError((root / "server.log").read_text()[-4000:])
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/readyz", timeout=1
                        ) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    if time.monotonic() > deadline:
                        raise TimeoutError("app-server readiness")
                    time.sleep(0.1)
                connection = connect(url)
                try:
                    started = request(connection, "thread/start", {"cwd": directory})
                    thread_id = started["thread"]["id"]
                    request(
                        connection,
                        "thread/name/set",
                        {"threadId": thread_id, "name": "isolation-smoke"},
                    )
                finally:
                    connection.close()
                connection = connect(url)
                try:
                    result = request(connection, "thread/read", {"threadId": thread_id})
                    if (
                        result["thread"]["id"] != thread_id
                        or process.poll() is not None
                    ):
                        raise RuntimeError(
                            "Thread or server changed across client reconnect"
                        )
                finally:
                    connection.close()
                return {
                    "readiness": "passed",
                    "client_reconnect": "passed",
                    "model_turns_submitted": 0,
                }
            finally:
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke(args.binary), indent=2))
