"""Captured native launch ownership and independent pre-inference attestation."""

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid5

from .errors import HttpFailure
from .host import machine_identity
from .journal import saved
from .service_observer import boot_id, process, properties


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ExecutionLifecycle:
    def __init__(self, execution, *, config, transport, journal_directory):
        from .tool_execution import capture
        # The executor is owned by an actual accepted delivery, independently
        # of the scheduler or communication context that invokes this core.
        self.owner = capture(execution, thread=execution.get("nativeThread"),
            turn=execution.get("nativeTurn"), agent=config["agentId"], host=config["hostId"])
        self.config = {key: config[key] for key in ("agentId", "hostId", "binary")}
        self.transport = transport
        delivery = self.owner["delivery"]
        self.id = str(uuid5(UUID(delivery["id"]), "native-executor:"
            + str(delivery["generation"]) + ":" + delivery["claim_id"]))
        self.root = Path(journal_directory)
        self.row = None
        self.native = None

    def validate(self, value):
        row = value["executor"]
        d = self.owner["delivery"]
        if (
            row["id"],
            row["delivery"],
            row["agent"],
            row["host"],
            row["generation"],
            row["claim_id"],
        ) != (
            self.id,
            d["id"],
            self.config["agentId"],
            self.config["hostId"],
            d["generation"],
            d["claim_id"],
        ):
            raise RuntimeError("Native executor belongs to another captured attempt")
        return row

    async def original_post(self, path, payload, name):
        saved(self.root / (name + "-intent.json"), payload)
        try:
            result = await self.transport("POST", path, payload)
        except Exception as error:
            if isinstance(error, HttpFailure) and error.status in (400, 403, 409):
                raise
            # Inspect the original executor identity; never repeat a process
            # birth, attachment or model submission after an uncertain reply.
            result = await self.transport("GET", "executors/" + self.id)
        self.row = self.validate(result)
        saved(self.root / (name + "-receipt.json"), result)
        return self.row

    async def prepare(self):
        own = process(os.getpid())
        if not own or own["uid"] != os.geteuid() or not own["controlGroup"]:
            raise RuntimeError("Actual managed guardian identity unavailable")
        unit = own["controlGroup"].rsplit("/", 1)[-1]
        if not unit.startswith("lax-") or not unit.endswith(".service"):
            raise RuntimeError(
                "Native execution requires an enrolled LAX service guardian"
            )
        info = properties(unit)
        if (
            int(info["MainPID"]) != own["pid"]
            or info["ActiveState"] != "active"
            or info["ControlGroup"] != own["controlGroup"]
        ):
            raise RuntimeError("Native guardian is not this active service incarnation")
        self.descriptor = {
            "machineIdentity": machine_identity(),
            "bootId": boot_id(),
            "serviceUnit": unit,
            "serviceInvocation": UUID(info["InvocationID"]).hex,
            "controlGroup": own["controlGroup"],
            "guardianPid": own["pid"],
            "guardianStart": own["start"],
            "nativePid": None,
            "nativeStart": None,
        }
        d = self.owner["delivery"]
        payload = {
            "operationId": "native-reserve:" + self.id,
            "id": self.id,
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "hostId": self.config["hostId"],
            **{
                k: v
                for k, v in self.descriptor.items()
                if k not in ("nativePid", "nativeStart")
            },
        }
        row = await self.original_post(
            "connector/deliveries/" + d["id"] + "/executor/reserve",
            payload,
            "launch-reservation",
        )
        if (
            row["reservation_digest"] != digest(self.descriptor)
            or row["reservation_descriptor"] != self.descriptor
            or row["launch_phase"] != "reserved"
            or row["state"] == "stopped"
        ):
            raise RuntimeError(
                "Original launch reservation cannot admit another process"
            )
        await self.require_registered()

    async def current_controller(self, row):
        policy = await self.transport(
            "GET", "hosts/" + self.config["hostId"] + "/admission"
        )
        value = policy.get("policy")
        return bool(
            value
            and row["controller"] == value["controller"]
            and value["machine_identity"] == self.descriptor["machineIdentity"]
        )

    async def require_registered(self):
        deadline = time.monotonic() + 45
        while True:
            result = await self.transport("GET", "executors/" + self.id)
            row = self.validate(result)
            if result["deliveryState"] != "claimed" or row["state"] == "stopped":
                raise RuntimeError("Original launch no longer admits process birth")
            evidence = row["evidence"] or {}
            if (
                evidence.get("reason") == "registered-launch-pending"
                and row["controller"]
                and await self.current_controller(row)
            ):
                saved(self.root / "guardian-registration-attestation.json", result)
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Independent guardian registration unconfirmed; no native process created"
                )
            await asyncio.sleep(0.5)

    async def attach(self, rpc):
        self.native = rpc.process
        child = process(rpc.process.pid)
        if (
            not child
            or child["uid"] != os.geteuid()
            or child["controlGroup"] != self.descriptor["controlGroup"]
        ):
            raise RuntimeError("Actual native child ownership unavailable")
        if child["executable"] != str(
            Path(self.config["binary"]).resolve(strict=True)
        ):
            raise RuntimeError("Native child executable differs from pinned runtime")
        saved(self.root / "native-process.json", child)
        d = self.owner["delivery"]
        payload = {
            "operationId": "native-attach:" + self.id,
            "claimId": d["claim_id"],
            "generation": d["generation"],
            "hostId": self.config["hostId"],
            "reservationDigest": digest(self.descriptor),
            "nativePid": child["pid"],
            "nativeStart": child["start"],
        }
        row = await self.original_post(
            "executors/" + self.id + "/native", payload, "native-attachment"
        )
        expected = {
            **self.descriptor,
            "nativePid": child["pid"],
            "nativeStart": child["start"],
        }
        if row["launch_phase"] != "attached" or row["descriptor"] != expected:
            raise RuntimeError("Original native attachment is unconfirmed")
        self.descriptor = expected
        await self.require_live(wait=True)

    async def require_live(self, *, wait=False):
        deadline = time.monotonic() + (45 if wait else 0)
        while True:
            result = await self.transport("GET", "executors/" + self.id)
            row = self.validate(result)
            if (
                row["descriptor"] != self.descriptor
                or row["launch_phase"] != "attached"
            ):
                raise RuntimeError("Original attached executor changed")
            if self.native is None or self.native.returncode is not None:
                raise RuntimeError("Original native process is no longer live")
            if result["deliveryState"] != "claimed":
                raise RuntimeError(
                    "Captured delivery no longer admits native inference"
                )
            if (
                row["state"] == "live"
                and row["controller"]
                and (row["evidence"] or {}).get("reason") == "matched-live-incarnation"
                and await self.current_controller(row)
            ):
                saved(self.root / "native-admission-attestation.json", result)
                return result
            if row["state"] == "stopped" or time.monotonic() >= deadline:
                raise RuntimeError(
                    "Independent native execution attestation is unconfirmed; no inference admitted"
                )
            await asyncio.sleep(0.5)

    async def observe_close(self):
        if self.row is None:
            return
        # A client cannot attest its own stop. Retain explicit uncertainty if the
        # independent controller cannot yet prove that this group is drained.
        deadline = time.monotonic() + 15
        while True:
            try:
                result = await self.transport("GET", "executors/" + self.id)
                row = self.validate(result)
                saved(self.root / "native-close-observation.json", result)
                if row["state"] == "stopped":
                    return
            except Exception as error:
                saved(
                    self.root / "native-close-gap.json",
                    {
                        "error": type(error).__name__,
                        "executorId": self.id,
                        "selfStopAttested": False,
                    },
                )
            if time.monotonic() >= deadline:
                return
            await asyncio.sleep(0.5)
