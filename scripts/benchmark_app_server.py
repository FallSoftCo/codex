#!/usr/bin/env python3
"""Managed app-server startup for benchmark runners."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from replay_hollywood_operator import DEFAULT_CURRENT_APP_SERVER
from replay_hollywood_operator import load_app_server_url


@dataclass
class BenchmarkAppServer:
    url: str
    managed: bool
    codex_home: Path | None = None
    log_path: Path | None = None
    pid: int | None = None
    source: str = "explicit"

    def metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "url": self.url,
            "managed": self.managed,
            "source": self.source,
        }
        if self.codex_home is not None:
            data["codexHome"] = str(self.codex_home)
        if self.log_path is not None:
            data["logPath"] = str(self.log_path)
        if self.pid is not None:
            data["pid"] = self.pid
        return data


class AppServerStartupError(RuntimeError):
    pass


def add_benchmark_app_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-server-url")
    parser.add_argument(
        "--current-app-server", type=Path, default=DEFAULT_CURRENT_APP_SERVER
    )
    parser.add_argument(
        "--reuse-current-app-server",
        action="store_true",
        help="Use --current-app-server instead of starting an isolated benchmark app-server.",
    )
    parser.add_argument(
        "--benchmark-codex-home",
        type=Path,
        help="CODEX_HOME for a managed benchmark app-server. Defaults under the campaign output.",
    )
    parser.add_argument(
        "--codex-home-source",
        type=Path,
        default=Path.home() / ".codex",
        help="Source for auth.json and installation_id copied into benchmark CODEX_HOME.",
    )
    parser.add_argument("--app-server-start-timeout-seconds", type=int, default=30)


@contextmanager
def benchmark_app_server(
    *,
    required: bool,
    app_server_url: str | None,
    reuse_current_app_server: bool,
    current_app_server: Path,
    codex: Path,
    output_dir: Path,
    benchmark_codex_home: Path | None,
    codex_home_source: Path,
    start_timeout_seconds: int,
):
    if not required:
        yield None
        return
    if app_server_url:
        yield BenchmarkAppServer(url=app_server_url, managed=False, source="explicit")
        return
    if reuse_current_app_server:
        yield BenchmarkAppServer(
            url=load_app_server_url(current_app_server),
            managed=False,
            source="current-app-server",
        )
        return

    output_dir = output_dir.resolve()
    codex_home = (benchmark_codex_home or output_dir / "codex-home").resolve()
    log_path = output_dir / "app-server.log"
    prepare_minimal_codex_home(
        codex_home=codex_home,
        source_home=codex_home_source,
        output_dir=output_dir,
    )
    url = f"ws://127.0.0.1:{free_loopback_port()}"
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [str(codex.resolve()), "app-server", "--listen", url],
        cwd=str(output_dir),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_ready(url, start_timeout_seconds)
    except Exception as exc:
        terminate_process(process)
        log_handle.close()
        raise AppServerStartupError(
            f"managed app-server failed to start: {exc}\n{log_tail(log_path)}"
        ) from exc

    try:
        yield BenchmarkAppServer(
            url=url,
            managed=True,
            codex_home=codex_home,
            log_path=log_path,
            pid=process.pid,
            source="managed",
        )
    finally:
        terminate_process(process)
        log_handle.close()


def prepare_minimal_codex_home(
    *,
    codex_home: Path,
    source_home: Path,
    output_dir: Path,
) -> None:
    output_root = output_dir.resolve()
    target = codex_home.resolve()
    if codex_home.exists():
        if not target.is_relative_to(output_root):
            raise AppServerStartupError(
                f"refusing to replace benchmark CODEX_HOME outside output dir: {codex_home}"
            )
        shutil.rmtree(codex_home)
    codex_home.mkdir(parents=True)

    copied_files = []
    for name in ("auth.json", "installation_id", "version.json"):
        source = source_home / name
        if source.exists():
            shutil.copy2(source, codex_home / name)
            copied_files.append(name)
    if "auth.json" not in copied_files:
        raise AppServerStartupError(
            f"missing benchmark auth source: {source_home / 'auth.json'}"
        )
    (codex_home / "benchmark-codex-home.json").write_text(
        json.dumps(
            {
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sourceHome": str(source_home),
                "copiedFiles": copied_files,
                "purpose": "isolated Losangelex benchmark app-server",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_ready(websocket_url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    ready_url = websocket_url.replace("ws://", "http://", 1).rstrip("/") + "/readyz"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(ready_url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"{ready_url} was not ready after {timeout_seconds}s")


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def log_tail(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    )
