"""Exercise real model -> Hollywood -> Firebase -> an explicitly selected Android emulator."""

import argparse
import json
import subprocess
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.serial.startswith("emulator-"):
        parser.error("This script changes Doze state; select a disposable emulator")
    if args.output.exists():
        parser.error("Choose a new report path to preserve previous evidence")
    adb = [args.adb, "-s", args.serial]
    headers = {
        "Authorization": "Bearer " + args.token_file.read_text().strip(),
        "Content-Type": "application/json",
    }

    def device(*command):
        return subprocess.check_output([*adb, *command], text=True).strip()

    def request(path, body=None):
        req = urllib.request.Request(
            args.url.rstrip("/") + "/hollywood/v2/" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    def receipt():
        xml = device(
            "shell", "run-as", "co.fallsoft.losangelex", "cat", "shared_prefs/push.xml"
        )
        return {n.get("name"): n.text or n.get("value") for n in ET.fromstring(xml)}

    overview = request("overview")
    if not overview["runtimeReady"] or not overview["pushConfigured"]:
        parser.error(
            "Configure the real model, Firebase sender and installed Android app first"
        )
    marker = "PUSH-" + uuid.uuid4().hex[:8]
    question = (
        f"Should Android notification previews remain generic? Reference: {marker}."
    )
    report = {"fixture": question, "checks": {}, "serial": args.serial}
    attention = None
    try:
        device("shell", "input", "keyevent", "KEYCODE_HOME")
        device("shell", "dumpsys", "battery", "unplug")
        device("shell", "input", "keyevent", "KEYCODE_SLEEP")
        device("shell", "dumpsys", "deviceidle", "force-idle")
        print("Letting Doze settle for 30 seconds", flush=True)
        time.sleep(30)
        report["idleBefore"] = device("shell", "dumpsys", "deviceidle", "get", "deep")
        command = request(
            "messages",
            {
                "commandId": str(uuid.uuid4()),
                "targets": ["theo"],
                "visibility": "direct",
                "body": "Theo, this is the Android notification acceptance test. "
                f"Use hollywood_ask to ask exactly: {question} "
                "Then wait for my answer. Do not inspect host files or write code.",
            },
        )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if attention is None:
                events = request(f"messages?after={command['id']}")["data"]
                attention = next(
                    (
                        e
                        for e in events
                        if e["kind"] == "attention" and marker in e["body"]
                    ),
                    None,
                )
            received = receipt()
            if attention and received.get("lastAttentionId") == str(attention["id"]):
                report.update(
                    attentionId=attention["id"],
                    attentionCreatedAt=attention["created_at"],
                    receivedAt=int(received["lastReceivedAt"]) / 1000,
                    originalPriority=received.get("lastOriginalPriority"),
                    deliveredPriority=received.get("lastPriority"),
                    idleAfterReceipt=device(
                        "shell", "dumpsys", "deviceidle", "get", "deep"
                    ),
                )
                break
            time.sleep(1)
        report["checks"]["actualModelQuestion"] = attention is not None
        report["checks"]["receivedDuringDoze"] = (
            report.get("idleAfterReceipt") == "IDLE"
        )
        if report["checks"]["receivedDuringDoze"]:
            raw = device("shell", "dumpsys", "notification", "--noredact")
            report["checks"]["genericNotification"] = (
                "A task needs your attention" in raw
            )
            report["checks"]["privateQuestionAbsentFromNotification"] = (
                marker not in raw
            )
    finally:
        device("shell", "dumpsys", "deviceidle", "unforce")
        device("shell", "dumpsys", "battery", "reset")
        device("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    if report["checks"].get("receivedDuringDoze"):
        connection = ET.fromstring(
            device(
                "shell",
                "run-as",
                "co.fallsoft.losangelex",
                "cat",
                "shared_prefs/connection.xml",
            )
        )
        android_url = next(n.text for n in connection if n.get("name") == "url")
        subprocess.run(
            [
                *adb,
                "shell",
                "run-as",
                "co.fallsoft.losangelex",
                "sh",
                "-c",
                '"umask 077; cat > files/proof-token"',
            ],
            input=args.token_file.read_bytes(),
            check=True,
            stdout=subprocess.DEVNULL,
        )
        output = device(
            "shell",
            "am",
            "instrument",
            "-w",
            "-e",
            "class",
            "co.fallsoft.losangelex.RoomUiTest,co.fallsoft.losangelex.NotificationUiTest",
            "-e",
            "roomServerUrl",
            android_url,
            "-e",
            "roomTokenFile",
            "proof-token",
            "-e",
            "notificationId",
            str(attention["id"]),
            "co.fallsoft.losangelex.test/androidx.test.runner.AndroidJUnitRunner",
        )
        report["checks"]["nativeApiReplyAndNotificationTests"] = (
            "OK (3 tests)" in output
        )
        report["instrumentation"] = output
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(
        "The test question remains open; answer it from the room after inspecting the evidence."
    )
    if not all(report["checks"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
