"""Deterministic human-review control lane; no model input or new scheduler."""
import asyncio
import hashlib

from .automatic_refill_data import require
from .journal import saved


class ReviewedContextControl:
    def __init__(self, runner):
        self.runner = runner
        self.task = None
        self.key = None
        self.error = None

    def tick(self, summary=None):
        if self.task is not None and self.task.done():
            try:
                self.task.result()
            except BaseException as error:
                self.error = str(error)[:1000]
                self.runner.trace("manual_review_waiting", {"error": self.error})
            self.task = None
        if summary is None:
            return self.task is not None
        key = (summary["draftId"], summary["control"]["state"], summary["control"]["revision"])
        if self.task is None and key != self.key:
            self.key, self.error = key, None
            self.task = asyncio.create_task(self.advance(summary))
        saved(self.runner.state / "manual-review-status.json", {
            "draftId": summary["draftId"], "state": summary["control"]["state"],
            "error": self.error, "inferenceStarted": False})

    async def close(self):
        if self.task is not None:
            # Never turn timeout into a replacement retry; the original SDK
            # journal will retain any uncertain dispatched operation.
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 20)
            except (TimeoutError, asyncio.CancelledError):
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def advance(self, summary):
        try:
            return await self.perform(summary)
        except Exception:
            r = self.runner
            idle = r.automatic.idle
            operation = idle.pending
            if operation is not None and operation.get("reviewMode") == "manual":
                from .idle_context_review import undispatched
                try:
                    undispatched(idle, operation)
                    status = await r.request("pending")
                    current = status["contextRebuild"]["manualReview"]
                    if current and current["draftId"] == summary["draftId"] and current["control"]["state"] not in ("cancel_requested", "revise_requested", "refused"):
                        from .automatic_refill_history import capture
                        observed = (await r.rpc.call("thread/read", {"threadId": r.thread, "includeTurns": False}))["thread"]
                        history = capture(observed, r.thread)
                        cut = (await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
                        hashed = hashlib.sha256(idle.path(operation["operationId"]).read_bytes()).hexdigest()
                        await r.request("seed_refused", {"draftId": summary["draftId"],
                            "nativeState": cut, "historySha256": history["beforeSha256"],
                            "journalSha256": hashed, "noDispatch": True},
                            operation="seed-refused:"+hashlib.sha256(operation["operationId"].encode()).hexdigest(),
                            turn="context-maintenance")
                except Exception as proof_error:
                    r.trace("manual_review_refusal_unconfirmed", {"error": str(proof_error)[:500]})
            raise

    async def perform(self, summary):
        r, control = self.runner, summary["control"]
        require(r.purpose == "writer" and r.config.get("manualSeedControl", 0) == 1,
                "Explicit paired manual Writer control required")
        require(not r.active and not r.accepting and not r.failed,
                "Original idle review owner is not available")
        idle = r.automatic.idle
        operation = idle.pending
        state, draft = control["state"], summary["draftId"]
        key = hashlib.sha256(control["requestOperationId"].encode()).hexdigest()

        async def report(action, value):
            return await r.request(action, value, operation="seed-control:" + action + ":" + key,
                                   turn="context-maintenance")

        if state == "requested":
            if operation is None:
                pending = [{"id": value, "cancelled": False} for value in summary["nextMaterialIds"]]
                operation = await idle.prepare_for_review(control["requestOperationId"], pending)
            require(operation["requestOperationId"] == control["requestOperationId"],
                    "Another native preparation owns this context")
            from .idle_context_review import approve
            approve(idle, operation, operation["approvalDigest"])
            require((await r.rpc.call("thread/contextWindow/read", {"threadId": r.thread}))["state"]
                    == operation["preflight"]["state"],
                    "Cold prepared cut requires explicit new review")
            return await report("seed_prepared", {
                "draftId": draft, "approvalDigest": operation["approvalDigest"],
                "preflight": operation["preflight"], "snapshotSha256": operation["snapshot"]["sha256"],
                "runtime": operation["preparedRuntime"],
                "historySha256": operation["originalHistory"]["beforeSha256"]})
        if state == "approved":
            require(operation is not None and operation.get("approvalDigest") == control["approvalDigest"],
                    "Approved original local preparation unavailable; reconcile first")

            async def admit():
                receipt = await report("seed_apply", {"draftId": draft,
                    "approvalDigest": operation["approvalDigest"], "preflight": operation["preflight"]})
                require(receipt["control"]["state"] == "applying"
                        and receipt["control"]["approvalDigest"] == operation["approvalDigest"],
                        "Original human dispatch admission differs")

            return await idle.apply_prepared(operation, approved_digest=control["approvalDigest"],
                                             before_dispatch=admit)
        if state in ("cancel_requested", "revise_requested"):
            if operation is not None:
                require(operation["requestOperationId"] == control["requestOperationId"],
                        "Cancellation belongs to another native review")
                await idle.cancel_prepared(operation)
            else:
                path = idle.path(control["nativeOperationId"])
                if path.exists():
                    import json
                    from .idle_context_review import cancelled
                    original = json.loads(path.read_text())
                    require(original["agentId"] == r.config["agentId"]
                            and original["requestOperationId"] == control["requestOperationId"],
                            "Original cancelled review identity differs")
                    cancelled(original)
            if state == "revise_requested":
                return await report("seed_revised", {"draftId": draft,
                    "replacementDraftId": control["replacement"]["draftId"],
                    "nativeOperationId": control["nativeOperationId"], "nativeWindowChanged": False})
            return await report("seed_cancelled", {"draftId": draft,
                "nativeOperationId": control["nativeOperationId"], "nativeWindowChanged": False})
        # Prepared waits without inference. Applying after a lost response must
        # resolve the original journal/receipts, not automatically invoke apply.
        return None
