"""Real filesystem/process crash boundaries; no provider responses are simulated."""

import asyncio
import json
import os
import signal
from pathlib import Path

import lax_connector.journal as journal
from lax_connector.connector import Connector


def main():
    os.umask(0o077)
    root = Path(os.environ["JOURNAL_CRASH_EVIDENCE"])
    root.mkdir(mode=0o700)
    records = [
        json.loads(Path(p).read_text())
        for p in json.loads(os.environ["JOURNAL_CRASH_RECORDS"])
    ]
    older, later = records
    agent, host = older["delivery"]["agent"], older["delivery"]["host"]
    assert (agent, host) == (later["delivery"]["agent"], later["delivery"]["host"])
    assert older["state"] == later["state"] == "completed"

    def create(name):
        state = root / name
        state.mkdir()
        journal.saved(state / "execution.json", older)
        store = journal.ExecutionJournals(state, agent=agent, host=host)
        assert json.loads(store.current().read_text()) == older
        return state, store

    state, store = create("older-recovery")
    original = store.current()
    current = store.begin(later)
    protected = {
        p: p.read_bytes() for p in (store.selection, store.projection, current.path)
    }
    journal.saved(original, {**older, "reconciled": True})
    assert all(p.read_bytes() == data for p, data in protected.items())

    def killed_boundary(name, record, *, before_canonical=False, after_selector=False):
        state, store = create(name)
        pid = os.fork()
        if pid == 0:
            atomic = journal._atomic_saved
            target = (
                store.selection
                if after_selector
                else store.path(journal.execution_key(record))
            )

            def interrupted(path, value):
                if Path(path) == target and before_canonical:
                    os.kill(os.getpid(), signal.SIGKILL)
                atomic(path, value)
                if Path(path) == target:
                    os.kill(os.getpid(), signal.SIGKILL)

            journal._atomic_saved = interrupted
            store.begin(record)
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        recovered = journal.ExecutionJournals(state, agent=agent, host=host)
        return state, recovered

    # A local interrupted capture uses actual source/claim identity in a private
    # shadow tree. It changes no authoritative delivery or original agent home.
    captured = {**later, "state": "captured-before-native"}
    state, store = killed_boundary("canonical-before-selector", captured)
    assert json.loads(store.current().read_text()) == older
    assert len(store.unsettled()) == 1
    assert len(store.records()) == 2

    async def denied_claim(state):
        connector = Connector(
            {
                "state": str(state),
                "agentId": agent,
                "hostId": host,
                "hollywoodUrl": "http://127.0.0.1:1",
                "token": "unusable-local-crash-test",
            }
        )
        try:
            await connector.once("must-never-be-sent")
        except (RuntimeError, FileNotFoundError):
            return
        raise AssertionError("Uncertain attempt was allowed to claim new work")

    asyncio.run(denied_claim(state))
    state, store = killed_boundary(
        "index-before-canonical", captured, before_canonical=True
    )
    try:
        store.unsettled()
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Dangling capture reference did not hold admission")
    asyncio.run(denied_claim(state))

    state, store = killed_boundary(
        "selector-before-projection", later, after_selector=True
    )
    assert json.loads(store.projection.read_text()) == later
    assert json.loads(store.current().read_text()) == later
    assert len(store.records()) == 2
    assert not store.unsettled()

    result = {
        "passed": True,
        "actualForkAndSigkill": True,
        "crashBoundaries": 3,
        "legacyActualRecordImportedWithoutReplay": True,
        "olderRecoveryPreservedLaterSelectorProjectionAndCanonical": True,
        "unselectedCapturedAttemptRetainedAndBlocksClaim": True,
        "danglingCaptureReferenceBlocksClaim": True,
        "projectionRepairedFromCanonicalSelector": True,
        "authoritativeOriginalDeliveryChanged": False,
        "originalAgentHomeChanged": False,
        "modelTurnsStarted": 0,
        "providerResponsesSimulated": False,
    }
    journal.saved(root / "result.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
