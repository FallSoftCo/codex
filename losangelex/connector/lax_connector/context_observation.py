"""Observe original native turns without confusing missing notifications with execution failure."""
import asyncio
import time

TERMINAL = {"completed", "interrupted", "failed"}


async def original_turn(runner, identity):
    """Bounded, metadata-only native read; never infer or submit another turn."""
    cursor = None
    for _ in range(4):
        page = await runner.rpc.call("thread/turns/list", {
            "threadId": runner.thread, "limit": 20, "itemsView": "summary",
            **({"cursor": cursor} if cursor else {})}, timeout=15)
        for turn in page["data"]:
            if turn["id"] == identity:
                return turn
        cursor = page.get("nextCursor")
        if not cursor:
            break
    raise RuntimeError("Original native turn unavailable; execution remains held")


async def wait_terminal(runner):
    interval = runner.config.get("turnObservationSeconds",
                                runner.config.get("turnTimeoutSeconds", 900))
    deadline = runner.config.get("executionTimeoutSeconds")
    started = time.monotonic()
    while True:
        try:
            return await asyncio.wait_for(asyncio.shield(runner.finished), interval)
        except TimeoutError:
            observed = await original_turn(runner, runner.turn)
            runner.trace("native_turn_observed", {"nativeTurn": runner.turn,
                                                "status": observed["status"]})
            if observed["status"] in TERMINAL:
                if not runner.finished.done():
                    runner.finished.set_result(observed)
                return observed
            if deadline and time.monotonic() - started >= deadline:
                await runner.cancel()
                return await asyncio.wait_for(asyncio.shield(runner.finished),
                                               runner.config.get("interruptTimeoutSeconds", 15))
